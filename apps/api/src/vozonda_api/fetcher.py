"""Hardened article fetching: polite, bounded, and SSRF-safe.

Design rules (see TODO DUE-033):
- browser-like headers so sites like wikipedia do not 403 us
- accept only text-ish content types; a pdf link fails loudly, not silently
- cap the download at FETCH_MAX_BYTES; huge pages get truncated, not OOMed
- one polite retry with backoff on transient errors
- never fetch loopback/private/link-local addresses (SSRF guard); the api
  runs on a machine with local services that must not be reachable through
  pasted URLs
- YouTube transcripts via yt-dlp (auto-subs, no cloud API keys)
"""

import asyncio
import ipaddress
import os
import re
import socket
import subprocess
import tempfile
from urllib.parse import urlparse

import httpx

from . import __version__
from .env import env

FETCH_HEADERS = {
    # A contact URL in the user agent, as Wikimedia's robot policy asks: without it Wikipedia answers 403 to the
    # Docker image (Python 3.12-slim TLS stack), so the quickstart example failed on a clean machine.
    "User-Agent": f"vozonda/{__version__} (+https://vozonda.com; self-hosted audio overviews)",
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    "Accept-Language": "en,de;q=0.8",
}

FETCH_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
FETCH_MAX_BYTES = 2_000_000
# PDFs are binary and often larger (the Attention paper is ~2.2 MB); a PDF cut
# at 2 MB is unreadable and failed as "scanned without text layer".
PDF_MAX_BYTES = 25_000_000
# Audio files have their own cap (300 MB default, overridable via VOZONDA_AUDIO_MAX_BYTES).
# Reads one byte past the cap to distinguish "exactly at cap" from "larger".
AUDIO_MAX_BYTES = int(env("AUDIO_MAX_BYTES", "300000000"))
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
TEXT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/ogg",
    "audio/opus",
)

YOUTUBE_REGEX = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|v/)|youtu\.be/)([a-zA-Z0-9_-]{11})"
)
NOSTR_SCHEME_REGEX = re.compile(r"^nostr:(n(?:event|addr|ote|pub)1[a-z0-9]+)", re.IGNORECASE)
NOSTR_GATEWAY_REGEX = re.compile(r"https?://(?:njump\.me|habla\.news/a|coracle\.social|snort\.social/e|primal\.net/e)/(n(?:event|addr|ote|pub)1[a-z0-9]+)", re.IGNORECASE)
YTDLP_TIMEOUT = 30.0


def resolve_nostr_url(url: str) -> str:
    """Resolve a nostr: URI or gateway link to a canonical gateway URL."""
    url = url.strip()
    m = NOSTR_SCHEME_REGEX.match(url)
    if m:
        return f"https://njump.me/{m.group(1)}"
    m2 = NOSTR_GATEWAY_REGEX.match(url)
    if m2:
        return f"https://njump.me/{m2.group(1)}"
    return url


class FetchError(Exception):
    """Raised with a user-presentable reason; maps to a failed job stage."""


def _host_is_private(host: str) -> bool:
    """True if host resolves only to non-public addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # unresolvable: treat as unsafe, fetch will fail anyway.
        # the message must say dns, not local: a dead subdomain is not ssrf
        raise FetchError(f"cannot resolve host '{host}' (dns)") from None
    addrs = {info[4][0] for info in infos}
    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if not ip.is_global:
            return True
    return not addrs


def guard_url(url: str) -> None:
    """Raise FetchError when the URL targets local or unroutable hosts."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise FetchError(f"unsupported scheme '{parsed.scheme}', use http(s)")
        host = parsed.hostname or ""
        if not host:
            raise FetchError("URL has no hostname")
        if _host_is_private(host):
            raise FetchError(f"refusing to fetch local address '{host}'")
    except ValueError as e:
        raise FetchError("malformed URL") from e


async def _guard_request(request: httpx.Request) -> None:
    """httpx request hook: runs for the first request and every redirect hop."""
    await asyncio.to_thread(guard_url, str(request.url))


def guarded_client(**kwargs) -> httpx.AsyncClient:
    """AsyncClient whose every request, redirects included, passes guard_url.

    guard_url() on the first URL alone let a public page redirect the fetch to
    loopback or the LAN (the local LLM on :30001, cloud metadata addresses).
    """
    hooks = dict(kwargs.pop("event_hooks", None) or {})
    hooks["request"] = [_guard_request, *hooks.get("request", [])]
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)


def _read_bytes_bounded(resp: httpx.Response, limit: int = FETCH_MAX_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return b"".join(chunks)[:limit]


def _read_audio_bounded(resp: httpx.Response, limit: int = AUDIO_MAX_BYTES) -> bytes:
    """Read audio with a hard cap: reads one byte past the limit to detect overflow.
    
    Raises FetchError if the content exceeds the limit (strictly greater than limit).
    Returns the full content if it is exactly at or under the limit.
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            mb = limit // 1_000_000
            raise FetchError(f"audio is larger than {mb} MB; provide a smaller file or a transcript")
    return b"".join(chunks)


def _read_bounded(resp: httpx.Response) -> str:
    raw = _read_bytes_bounded(resp)
    return raw.decode(resp.encoding or "utf-8", errors="replace")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract readable text from PDF bytes using pdftotext (Poppler)."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        temp_path = f.name
    try:
        res = subprocess.run(
            ["pdftotext", "-layout", temp_path, "-"],
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
        if res.returncode != 0 or not res.stdout.strip():
            if len(pdf_bytes) >= PDF_MAX_BYTES:
                raise FetchError(f"PDF is larger than {PDF_MAX_BYTES // 1_000_000} MB; upload a smaller file or paste its text")
            raise FetchError("could not extract text from PDF (empty or scanned without text layer)")
        return res.stdout.strip()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
# Audio file extensions used to detect audio type from the URL path.
_AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".ogg", ".opus")
IMAGE_MAX_SIDE = 2048

# a screenshot or scanned page is transcribed; a photo, painting or chart without much
# text is described, so it can still be talked about (a painting used to fail as 'no text')
VISION_PROMPT = (
    "This image is a source for a podcast discussion. If it contains readable text (an "
    "article, document, slide or screenshot), transcribe all of it faithfully. If it has "
    "little or no text (a photo, painting, chart or diagram), describe in detail what it "
    "shows: the subject, composition, visible details, any numbers or labels, and its style. "
    "Say only what is visible; do not guess names, dates or facts that the image does not "
    "show. Output only the transcription or the description."
)


def _shrink_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Downscale to IMAGE_MAX_SIDE and re-encode as JPEG (drops EXIF). The vision server
    rejects large images (a 7000 px photo came back as HTTP 400)."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as im:
        im.load()
        im.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=90)
    return out.getvalue(), "image/jpeg"


async def _extract_image_text(image_bytes: bytes, ctype: str) -> str:
    """Transcribe the text of an image, or describe it, with the local vision model."""
    import base64

    from .providers import LLM_BASE, LLM_MODEL

    try:
        image_bytes, ctype = await asyncio.to_thread(_shrink_image, image_bytes)
    except Exception as e:
        raise FetchError(f"image could not be decoded: {e}") from e
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{ctype};base64,{b64}"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": VISION_PROMPT,
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            resp = await client.post(f"{LLM_BASE.rstrip('/')}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            extracted = data["choices"][0]["message"]["content"].strip()
            if not extracted:
                raise FetchError("vision model extracted no readable text from image")
            return extracted
        except Exception as e:
            raise FetchError(f"image vision extraction failed: {e}") from e


def extract_youtube_id(url: str) -> str | None:
    """Extract 11-char YouTube video ID from various URL formats."""
    m = YOUTUBE_REGEX.search(url)
    return m.group(1) if m else None


def _fetch_youtube_transcript(video_id: str) -> tuple[str, str]:
    """Fetch transcript and title via yt-dlp (auto-subs, no API keys).
    Returns (title, transcript_text). Raises FetchError on failure.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    # Get title
    try:
        title_result = subprocess.run(
            ["yt-dlp", "--print", "title", url],
            capture_output=True,
            text=True,
            timeout=YTDLP_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise FetchError("YouTube title fetch timed out") from e
    except FileNotFoundError as e:
        raise FetchError("yt-dlp not installed") from e

    if title_result.returncode != 0 or not title_result.stdout.strip():
        raise FetchError("Could not fetch video title. The video may be unavailable, age-restricted, or not a video.")

    title = title_result.stdout.strip()

    # Get transcript via temp file (yt-dlp doesn't output subs to stdout)
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            vtt_result = subprocess.run(
                [
                    "yt-dlp",
                    "--write-auto-subs",
                    "--sub-format",
                    "vtt",
                    "--skip-download",
                    "-o",
                    os.path.join(tmpdir, "%(id)s.%(ext)s"),
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=YTDLP_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise FetchError("YouTube VTT fetch timed out") from e

        if vtt_result.returncode != 0:
            raise FetchError("Could not fetch subtitles. The video may not have auto-generated or uploaded captions.")

        # Find the VTT file (could be .en.vtt or .en-en.vtt etc.)
        vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
        if not vtt_files:
            raise FetchError("No subtitles available for this video")

        vtt_file = os.path.join(tmpdir, vtt_files[0])
        with open(vtt_file, "r", encoding="utf-8") as f:
            vtt_content = f.read()

    if not vtt_content.strip():
        raise FetchError("Subtitles empty")

    # Parse VTT to plain text
    transcript = _parse_vtt(vtt_content)
    if not transcript.strip():
        raise FetchError("Subtitles parsing failed")

    return title, transcript


def _parse_vtt(vtt_text: str) -> str:
    """Convert WebVTT to plain text (strip timestamps, cues, keep content)."""
    lines = vtt_text.split("\n")
    out = []
    in_cue = False
    for line in lines:
        line = line.strip()
        if not line or line == "WEBVTT":
            continue
        if "-->" in line:
            in_cue = True
            continue
        if in_cue and line:
            # Skip positioning/alignment tags
            cleaned = re.sub(r"<[^>]+>", "", line)
            cleaned = re.sub(r"\{\d+:\d+:\d+\.\d+\}", "", cleaned)
            if cleaned:
                out.append(cleaned)
        elif line == "":
            in_cue = False
    # Deduplicate consecutive identical lines (common in VTT)
    deduped = []
    for ln in out:
        if not deduped or deduped[-1] != ln:
            deduped.append(ln)
    return "\n".join(deduped)


async def fetch_article(url: str) -> str:
    """Fetch an article body, Nostr note, or YouTube transcript with retries, type checks and a size cap."""
    return (await fetch_document(url))[1]


async def fetch_document(url: str) -> tuple[str, str]:
    """Like fetch_article, but also say what was found: (kind, content).

    kind is article (HTML), pdf, image or youtube, decided by what the server sent,
    not by the URL; a source card shows it (VOZONDA-MULTI-SOURCE-TRAY).
    """
    url = resolve_nostr_url(url)
    guard_url(url)

    video_id = extract_youtube_id(url)
    if video_id:
        # YouTube: fetch transcript via yt-dlp (blocking call in thread pool)
        loop = asyncio.get_event_loop()
        title, transcript = await loop.run_in_executor(None, _fetch_youtube_transcript, video_id)
        # Combine title + transcript for the pipeline
        return "youtube", f"{title}\n\n{transcript}"

    async with guarded_client(
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        headers=FETCH_HEADERS,
    ) as client:
        attempts = 2
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = await client.get(url)
                if resp.status_code in RETRYABLE_STATUS and attempt < attempts - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and ctype not in TEXT_TYPES:
                    raise FetchError(f"source is '{ctype}', expected an article page, PDF, or image document")

                # what the server says wins; the path (never the #fragment: a Wikipedia page
                # ending in '#/media/File:x.jpg' is HTML) only decides when it says nothing
                path = urlparse(url).path.lower()
                untyped = not ctype
                is_pdf_hint = ctype == "application/pdf" or (untyped and path.endswith(".pdf"))
                is_image_hint = ctype.startswith("image/") or (untyped and path.endswith(_IMAGE_EXTS))
                is_audio_hint = ctype.startswith("audio/") or (untyped and path.endswith(_AUDIO_EXTS))
                # images and PDFs get the large cap; audio has its own cap (AUDIO_MAX_BYTES)
                big = is_pdf_hint or is_image_hint
                if is_audio_hint:
                    raw_bytes = await asyncio.to_thread(_read_audio_bounded, resp)
                else:
                    raw_bytes = _read_bytes_bounded(resp, PDF_MAX_BYTES if big else FETCH_MAX_BYTES)
                if is_pdf_hint or (untyped and raw_bytes.startswith(b"%PDF")):
                    loop = asyncio.get_event_loop()
                    return "pdf", await loop.run_in_executor(None, _extract_pdf_text, raw_bytes)
                if is_image_hint or (untyped and raw_bytes[:3] in (b"\xff\xd8\xff", b"\x89PN")):
                    if len(raw_bytes) >= PDF_MAX_BYTES:
                        raise FetchError(f"image is larger than {PDF_MAX_BYTES // 1_000_000} MB; use a smaller version of it")
                    return "image", await _extract_image_text(raw_bytes, ctype or "image/jpeg")
                if is_audio_hint:
                    return "audio", raw_bytes

                return "article", raw_bytes.decode(resp.encoding or "utf-8", errors="replace")
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < attempts - 1:
                    await asyncio.sleep(1.5)
                    continue
        status = getattr(last_error, "response", None)
        code = getattr(status, "status_code", None)
        if code is not None:
            raise FetchError(f"fetch failed: HTTP {code}") from last_error
        raise FetchError(f"fetch failed: {type(last_error).__name__}") from last_error