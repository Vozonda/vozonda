"""Source objects for the source tray (VOZONDA-MULTI-SOURCE-TRAY, docs/plan-multisource-tray.md).

A source is read once, when it is added: the article fetched, the PDF turned into text,
the image read by the local vision model, the video's subtitles pulled, the audio
transcribed. The tray card then shows the real title, size and language, or a clear
error with a next step, before anyone presses start. A job references source ids and
copies their text into `job_sources`, so a variant can rebuild the tray from exactly
the text the episode used.

Privacy: an uploaded file is never written to disk by this module; only its extracted
text is kept (the PDF temp file of pdftotext is removed by the fetcher). Re-encoding an
image drops its EXIF data. Sources that no job uses are deleted after SOURCE_TTL_S.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import time
import uuid
from typing import Any

from . import jobs as jobs_mod
from .audio_source import detect_audio
from .fetcher import (
    AUDIO_MAX_BYTES,
    PDF_MAX_BYTES,
    FetchError,
    _extract_image_text,
    _extract_pdf_text,
    fetch_document,
    guard_url,
)

logger = logging.getLogger(__name__)

SOURCE_TTL_S = 24 * 3600
UPLOAD_MAX_BYTES = PDF_MAX_BYTES
READ_TIMEOUT_S = 180.0


def upload_limit(data: bytes) -> int:
    """Return the upload size limit for the given bytes.

    Audio uploads may be up to AUDIO_MAX_BYTES; every other file keeps
    UPLOAD_MAX_BYTES (25 MB).
    """
    if detect_audio(data):
        return max(UPLOAD_MAX_BYTES, AUDIO_MAX_BYTES)
    return UPLOAD_MAX_BYTES


MIN_TEXT_CHARS = 20
# a pasted note or text file larger than this is almost certainly a mistake (a whole
# book is ~1 MB); keeps a single request from filling the database
MAX_TEXT_CHARS = 2_000_000
# the backend digest limit; VOZONDA-MULTI-SOURCE-TRAY moves it into the settings
MAX_SOURCES = 10
IMAGE_MAX_SIDE = 2048
URL_KINDS = ("article", "pdf", "image", "youtube", "audio")
# Audio file extensions accepted for uploads and URLs.
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".ogg", ".opus")

ROLES = ("main", "context")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  origin_url TEXT,
  title TEXT NOT NULL DEFAULT '',
  text TEXT,
  words INTEGER NOT NULL DEFAULT 0,
  chars INTEGER NOT NULL DEFAULT 0,
  language TEXT,
  status TEXT NOT NULL DEFAULT 'reading',
  error_code TEXT,
  error_hint TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS job_sources (
  job_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  source_id TEXT,
  kind TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  origin_url TEXT,
  role TEXT NOT NULL DEFAULT 'main',
  text TEXT NOT NULL,
  PRIMARY KEY (job_id, position)
);
"""

# code -> (hint shown on the red card, worth a retry)
ERRORS: dict[str, tuple[str, bool]] = {
    "paywall": ("the site blocks reading (paywall or login). Paste the text as a note instead.", False),
    "unreachable": ("the page could not be reached. Check the link or try again.", True),
    "timeout": ("reading took too long. Try again.", True),
    "blocked_address": ("local and private addresses are not allowed.", False),
    "bad_url": ("this is not a valid http(s) link.", False),
    "pdf_no_text": ("this PDF has no text layer (a scan). Upload the pages as images instead.", False),
    "too_large": ("the file is too large for upload. Upload a smaller file or paste its text.", False),
    "no_subtitles": ("this video has no subtitles, so there is nothing to read. Paste a transcript as a note.", False),
    "image_unreadable": ("no readable text found in this image, or the vision model is not running.", True),
    "unsupported_type": ("this file type is not supported. Use PDF, JPG, PNG, WebP, TXT, MP3, M4A, WAV, OGG or OPUS.", False),
    "too_short": (f"too little readable text (at least {MIN_TEXT_CHARS} characters).", False),
    "too_long": (f"the text is longer than {MAX_TEXT_CHARS:,} characters.", False),
    "unreadable": ("could not read this source.", True),
}

_tasks: set[asyncio.Task] = set()


class TrayError(Exception):
    """A tray a job cannot start with; status is the HTTP status for the API."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class SourceError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code if code in ERRORS else "unreadable"
        self.detail = detail


def init_sources_db() -> None:
    with _db():
        pass


def _db():
    """A jobs-DB connection with the source tables in place (CREATE IF NOT EXISTS is
    cheap, and a job delete must not fail on a DB from before the tray)."""
    conn = jobs_mod._conn()
    conn.executescript(SCHEMA)
    return conn


def _now() -> float:
    return time.time()


def _row(row: Any, with_text: bool = False) -> dict[str, Any]:
    d = dict(row)
    text = d.pop("text", None)
    if with_text:
        d["text"] = text
    else:
        d["preview"] = (text or "")[:280]
    code = d.pop("error_code", None)
    hint = d.pop("error_hint", None)
    d["error"] = {"code": code, "hint": hint, "retryable": ERRORS.get(code, ("", False))[1]} if code else None
    return d


def get(source_id: str, with_text: bool = False) -> dict[str, Any] | None:
    with _db() as c:
        row = c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return _row(row, with_text) if row else None


def _insert(kind: str, origin_url: str | None, status: str = "reading") -> str:
    sid = f"src-{uuid.uuid4().hex[:12]}"
    now = _now()
    with _db() as c:
        c.execute(
            "INSERT INTO sources (id, kind, origin_url, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, kind, origin_url, status, now, now),
        )
    return sid


def _set_ready(source_id: str, kind: str, title: str, text: str) -> None:
    from .pipeline import detect_source_lang

    # pages often leave runs of blank or space-only lines behind (arXiv abstract pages)
    text = re.sub(r"\n[ \t]*(?:\n[ \t]*)+", "\n\n", text).strip()
    with _db() as c:
        c.execute(
            "UPDATE sources SET kind = ?, title = ?, text = ?, words = ?, chars = ?, language = ?, status = 'ready', "
            "error_code = NULL, error_hint = NULL, updated_at = ? WHERE id = ?",
            (kind, title[:200], text, len(text.split()), len(text), detect_source_lang(text), _now(), source_id),
        )


def _set_failed(source_id: str, code: str) -> None:
    with _db() as c:
        c.execute(
            "UPDATE sources SET status = 'failed', text = NULL, error_code = ?, error_hint = ?, updated_at = ? WHERE id = ?",
            (code, ERRORS[code][0], _now(), source_id),
        )


def set_title(source_id: str, title: str) -> dict[str, Any] | None:
    with _db() as c:
        c.execute("UPDATE sources SET title = ?, updated_at = ? WHERE id = ?", (title.strip()[:200], _now(), source_id))
    return get(source_id)


def delete(source_id: str) -> bool:
    with _db() as c:
        return c.execute("DELETE FROM sources WHERE id = ?", (source_id,)).rowcount > 0


def purge_stale(now: float | None = None) -> int:
    """Delete sources older than the TTL. A job keeps its own copy in job_sources."""
    cutoff = (now if now is not None else _now()) - SOURCE_TTL_S
    with _db() as c:
        return c.execute("DELETE FROM sources WHERE created_at < ?", (cutoff,)).rowcount


# --- reading ---------------------------------------------------------------


def classify(exc: Exception) -> str:
    """Map a fetch/extract failure to an error code with a hint the user can act on."""
    if isinstance(exc, SourceError):
        return exc.code
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    msg = str(exc).lower()
    if re.search(r"http (401|402|403|451)", msg):
        return "paywall"
    if "timed out" in msg or "timeout" in msg:
        return "timeout"
    if "local address" in msg:
        return "blocked_address"
    if "scheme" in msg or "malformed" in msg or "no hostname" in msg:
        return "bad_url"
    if "pdf is larger" in msg or "image is larger" in msg:
        return "too_large"
    if "pdf" in msg:
        return "pdf_no_text"
    if "subtitle" in msg or "captions" in msg:
        return "no_subtitles"
    if "vision" in msg or "image" in msg:
        return "image_unreadable"
    if "expected an article page" in msg:
        return "unsupported_type"
    if "too short" in msg or "script-only" in msg:
        return "too_short"
    if "http" in msg or "dns" in msg or "fetch failed" in msg or "unavailable" in msg:
        return "unreachable"
    return "unreadable"


def _first_line_title(text: str, fallback: str) -> str:
    for ln in text.strip().splitlines():
        ln = ln.strip()
        if ln:
            return ln[:120] if len(ln) <= 120 else ln[:117].rstrip() + "..."
    return fallback


def _text_title(text: str, fallback: str) -> str:
    from .pipeline import _guess_text_title

    return _guess_text_title(text) or fallback


def _check_text(text: str) -> str:
    text = text.strip()
    if len(text) < MIN_TEXT_CHARS:
        raise SourceError("too_short")
    if len(text) > MAX_TEXT_CHARS:
        raise SourceError("too_long")
    return text


async def read_url(url: str) -> tuple[str, str, str]:
    """(kind, title, text) for a link. The kind is what the server actually sent."""
    from urllib.parse import urlparse

    from .audio_source import extract_existing_transcript, transcribe_audio
    from .pipeline import _extract

    path = urlparse(url).path.lower()
    ext = os.path.splitext(path)[1] if "." in path else ""

    # If the URL looks like an audio file by extension, fetch and transcribe.
    if ext in AUDIO_EXTS:
        kind, content = await fetch_document(url)
        title, text, _, _ = await transcribe_audio(file_bytes=content)
        existing = extract_existing_transcript(text)
        if existing:
            text = existing
        text = _check_text(text)
        return "audio", title, text

    kind, content = await fetch_document(url)

    # fetch_document returns "audio" when the content-type is audio/.
    if kind == "audio":
        title, text, _, _ = await transcribe_audio(file_bytes=content)
        existing = extract_existing_transcript(text)
        if existing:
            text = existing
        text = _check_text(text)
        return "audio", title, text

    if kind == "article":
        title, body, _og = await _extract(url, html=content, max_chars=None)
        return kind, title or url, _check_text(body)
    text = _check_text(content)
    if kind == "youtube":
        return kind, _first_line_title(text, "YouTube video"), text
    return kind, _text_title(text, f"{kind} document"), text


def sniff(data: bytes) -> str | None:
    """The file type from its bytes, never from the name: pdf, png, jpeg, webp, text or None."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if b"\x00" in data[:8192]:
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text"


def _normalize_image(data: bytes) -> tuple[bytes, str]:
    """Downscale for the vision model and re-encode, which also drops EXIF metadata."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        im.load()
        im.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        out = io.BytesIO()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(out, format="JPEG", quality=90)
    return out.getvalue(), "image/jpeg"


async def read_upload(data: bytes) -> tuple[str, str, str]:
    """(kind, title, text) for an uploaded file. The bytes stay in memory only.

    Accepted file types: PDF, PNG, JPEG, WebP, plain text (UTF-8), and audio
    in MP3 (with ID3 tags or bare MPEG frames), M4A, WAV, OGG (Vorbis/Opus),
    and FLAC formats.
    """
    from .audio_source import extract_existing_transcript, transcribe_audio

    if len(data) > upload_limit(data):
        limit = upload_limit(data)
        kind_label = "audio" if detect_audio(data) else "file"
        mb = limit // 1_000_000
        raise SourceError("too_large", f"{kind_label} upload is limited to {mb} MB")
    ftype = sniff(data)
    # Check if it is an audio file (by magic bytes or sniff).
    if ftype is None and detect_audio(data):
        title, text, _, _ = await transcribe_audio(file_bytes=data)
        existing = extract_existing_transcript(text)
        if existing:
            text = existing
        text = _check_text(text)
        return "audio", title, text
    if ftype is None:
        raise SourceError("unsupported_type")
    if ftype == "pdf":
        text = _check_text(await asyncio.to_thread(_extract_pdf_text, data))
        return "pdf", _text_title(text, "uploaded PDF"), text
    if ftype in ("png", "jpeg", "webp"):
        try:
            img, ctype = await asyncio.to_thread(_normalize_image, data)
        except Exception as exc:
            raise SourceError("unsupported_type", str(exc)) from exc
        text = _check_text(await _extract_image_text(img, ctype))
        return "image", _text_title(text, "uploaded image"), text
    text = _check_text(data.decode("utf-8"))
    return "file-text", _first_line_title(text, "uploaded text"), text


async def _run_read(source_id: str, reader) -> None:
    try:
        kind, title, text = await asyncio.wait_for(reader, READ_TIMEOUT_S)
        _set_ready(source_id, kind, title, text)
    except Exception as exc:
        code = classify(exc)
        logger.info("source %s failed: %s (%s)", source_id, code, exc)
        _set_failed(source_id, code)


def _start(source_id: str, reader) -> None:
    task = asyncio.create_task(_run_read(source_id, reader))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def add_url(url: str) -> dict[str, Any]:
    """Validate now (bad links fail the request), read in the background."""
    url = url.strip()
    try:
        guard_url(url)
    except FetchError as exc:
        raise SourceError(classify(exc), str(exc)) from exc
    sid = _insert("article", url)
    _start(sid, read_url(url))
    return get(sid)  # type: ignore[return-value]


def add_note(text: str) -> dict[str, Any]:
    text = _check_text(text)
    sid = _insert("note", None)
    _set_ready(sid, "note", _first_line_title(text, "note"), text)
    return get(sid)  # type: ignore[return-value]


def add_upload(data: bytes) -> dict[str, Any]:
    if len(data) > upload_limit(data):
        limit = upload_limit(data)
        kind_label = "audio" if detect_audio(data) else "file"
        mb = limit // 1_000_000
        raise SourceError("too_large", f"{kind_label} upload is limited to {mb} MB")
    if sniff(data) is None and not detect_audio(data):
        raise SourceError("unsupported_type")
    sid = _insert("file", None)
    _start(sid, read_upload(data))
    return get(sid)  # type: ignore[return-value]


def retry(source_id: str) -> dict[str, Any] | None:
    """Read a failed link again. An upload cannot be retried: its bytes are gone."""
    src = get(source_id)
    if src is None:
        return None
    if not src.get("origin_url"):
        raise SourceError("unreadable", "an upload cannot be retried, upload the file again")
    with _db() as c:
        c.execute(
            "UPDATE sources SET status = 'reading', error_code = NULL, error_hint = NULL, updated_at = ? WHERE id = ?",
            (_now(), source_id),
        )
    _start(source_id, read_url(src["origin_url"]))
    return get(source_id)


# --- jobs ------------------------------------------------------------------


def resolve_for_job(refs: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Look up the tray a job is started with; TrayError says why it cannot start."""
    from .budget import max_sources

    limit = max_sources()
    if not refs:
        raise TrayError(422, "sources is empty")
    if len(refs) > limit:
        raise TrayError(422, f"at most {limit} sources per episode")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ref in refs:
        sid, role = ref["id"], ref.get("role") or "main"
        if role not in ROLES:
            raise TrayError(422, f"role must be one of {list(ROLES)}")
        if sid in seen:
            raise TrayError(422, f"source {sid} is listed twice")
        seen.add(sid)
        src = get(sid, with_text=True)
        if src is None:
            raise TrayError(404, f"no such source {sid} (sources expire after 24 h)")
        if src["status"] == "reading":
            raise TrayError(409, f"source {sid} is still being read")
        if src["status"] != "ready":
            raise TrayError(422, f"source {sid} could not be read; remove it from the tray")
        out.append({**src, "role": role})
    if not any(s["role"] == "main" for s in out):
        raise TrayError(422, "at least one source must be a main source")
    return out


def save_job_sources(job_id: str, tray: list[dict[str, Any]]) -> None:
    with _db() as c:
        c.execute("DELETE FROM job_sources WHERE job_id = ?", (job_id,))
        c.executemany(
            "INSERT INTO job_sources (job_id, position, source_id, kind, title, origin_url, role, text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (job_id, i, s.get("id"), s["kind"], s.get("title") or "", s.get("origin_url"), s.get("role") or "main", s["text"])
                for i, s in enumerate(tray)
            ],
        )


def delete_job_sources(job_id: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM job_sources WHERE job_id = ?", (job_id,))


def _legacy_sources(job: dict[str, Any]) -> list[dict[str, Any]]:
    """A job from before the tray: derive its sources from url / digest_sources."""
    raw = job.get("digest_sources") or [job.get("url") or ""]
    out = []
    for s in raw:
        s = (s or "").strip()
        if not s or s.startswith("digest:"):
            continue
        if re.match(r"^https?://", s, re.IGNORECASE):
            out.append({"kind": "article", "title": "", "origin_url": s, "role": "main", "text": None})
        else:
            text = s[5:].strip() if s.lower().startswith("text:") else s
            out.append({"kind": "note", "title": _first_line_title(text, "note"), "origin_url": None, "role": "main", "text": text})
    return out


def job_sources(job: dict[str, Any], with_text: bool = False) -> list[dict[str, Any]]:
    """The sources an episode was made from. Without with_text: what may be shown
    publicly (an upload is a title only, never its text)."""
    with _db() as c:
        rows = c.execute(
            "SELECT position, kind, title, origin_url, role, text FROM job_sources WHERE job_id = ? ORDER BY position",
            (job["id"],),
        ).fetchall()
    items = [dict(r) for r in rows] if rows else _legacy_sources(job)
    out = []
    for i, s in enumerate(items):
        text = s.get("text")
        item = {
            "position": i,
            "kind": s["kind"],
            "title": s.get("title") or "",
            "origin_url": s.get("origin_url") if s["kind"] in URL_KINDS else None,
            "role": s.get("role") or "main",
            "words": len(text.split()) if text else None,
        }
        if with_text:
            item["text"] = text
        out.append(item)
    return out


def clone_job_sources(job: dict[str, Any]) -> list[dict[str, Any]]:
    """New tray sources from an episode (create variant): the same text, no re-fetch.
    A legacy link without stored text is read again."""
    out = []
    for s in job_sources(job, with_text=True):
        if s.get("text"):
            sid = _insert(s["kind"], s.get("origin_url"))
            _set_ready(sid, s["kind"], s["title"] or _first_line_title(s["text"], "source"), s["text"])
            src = get(sid)
        elif s.get("origin_url"):
            src = add_url(s["origin_url"])
        else:
            continue
        out.append({**src, "role": s["role"]})  # type: ignore[dict-item]
    return out


async def purge_loop(interval_s: float = 3600.0) -> None:
    while True:
        try:
            n = purge_stale()
            if n:
                logger.info("sources: purged %d unused sources older than 24 h", n)
        except Exception:
            logger.warning("sources: purge failed", exc_info=True)
        await asyncio.sleep(interval_s)
