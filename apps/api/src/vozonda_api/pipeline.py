import asyncio
import json
import logging
import os
import re
import shutil
import signal
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

from . import budget
from . import condense as condense_mod
from .env import env
from .fetcher import FetchError, fetch_article
from .jobs import JobStore
from .length import (
    DEFAULT_MINUTES,
    OUTLINE_THRESHOLD_WORDS,
    budget_prompt_line,
    cap_target_minutes,
    correction_action,
    deviation_percent,
    outline_split,
    rolling_wpm,
    word_budget,
)
from .nostr_orchestrator import publish_job as _publish_job
from .providers import HF_HOME, LOCAL_ONLY, MEDIA_DIR, TTS_PY, llm_chain, tts_fallbacks
from .providers.script import script_call, with_thinking_off
from .rhythm import rhythm_problems_for
from .styles import (
    SCRIPT_PARAMS,
    SCRIPT_PROMPT,
    STYLE_TEMPLATES,
    get_setting_safe,
)
from .voices import default_cast_for

# asyncio keeps only a weak reference to a task: an unreferenced background task can be
# garbage-collected mid-run (Python docs, asyncio.create_task). Keep it until it is done.
_BACKGROUND_TASKS: set = set()


def _spawn_background(coro):
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


# Subprocess tracking for job cancellation (VOZONDA-CANCEL-KILLS-RENDERER).
# Every subprocess the pipeline spawns for a job (voice renderer, ffmpeg
# mastering, chapter embedding) is awaited through _communicate_tracked, which
# kills the renderer's process group when the job's task is cancelled: SIGTERM
# to the group, up to 10 s grace, then SIGKILL. Renderers run in their own
# process group (start_new_session=True) so children of the renderer die too.
_job_subprocesses: dict[str, list[asyncio.subprocess.Process]] = {}

_TERMINATE_GRACE_S = 10.0


def _register_subprocess(job_id: str, proc: asyncio.subprocess.Process) -> None:
    """Track a subprocess spawned for a job so cancellation can kill it."""
    _job_subprocesses.setdefault(job_id, []).append(proc)


def _forget_subprocess(job_id: str, proc: asyncio.subprocess.Process) -> None:
    """Stop tracking a subprocess that already exited."""
    procs = _job_subprocesses.get(job_id)
    if not procs:
        return
    try:
        procs.remove(proc)
    except ValueError:
        pass
    if not procs:
        _job_subprocesses.pop(job_id, None)


def _media_dir() -> Path:
    """Media dir, resolved late so tests can point it at a tmp dir via env."""
    try:
        return Path(env("MEDIA", "") or str(MEDIA_DIR))
    except Exception:
        return MEDIA_DIR


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM a subprocess's process group, wait, then SIGKILL survivors.

    Signals the whole process group (the renderer runs with
    start_new_session=True), so children of the renderer die too. Never raises.
    """
    if proc.returncode is not None:
        return
    pid = proc.pid
    try:
        if pid is not None:
            os.killpg(pid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_S)
    except TimeoutError:
        pass
    except Exception:
        logger.debug("subprocess wait after SIGTERM failed", exc_info=True)
    if proc.returncode is None:
        try:
            if pid is not None:
                os.killpg(pid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            pass
        except Exception:
            logger.debug("subprocess wait after SIGKILL failed", exc_info=True)


async def _communicate_tracked(
    job_id: str, proc: asyncio.subprocess.Process
) -> tuple[Any, Any]:
    """Await proc.communicate, killing the process group when cancelled.

    On CancelledError the process group gets SIGTERM (10 s grace, then
    SIGKILL), partial output files of the job are removed, and the error is
    re-raised so the job ends as cancelled/failed instead of orphaning a
    renderer that blocks the GPU for the next job.
    """
    _register_subprocess(job_id, proc)
    try:
        return await proc.communicate()
    except asyncio.CancelledError:
        await _terminate_process(proc)
        _cleanup_job_output_files(job_id)
        raise
    finally:
        if proc.returncode is not None:
            _forget_subprocess(job_id, proc)


async def _kill_job_subprocesses(job_id: str) -> None:
    """Terminate every tracked subprocess of a job. Never raises.

    Backup for cancellations that land outside a subprocess wait (LLM calls,
    ffmpeg setup); called from the DELETE /jobs cancellation path in main._run.
    The communicate wrapper above already kills on cancel.
    """
    procs = _job_subprocesses.pop(job_id, [])
    if not procs:
        return
    await asyncio.gather(*(_terminate_process(p) for p in procs), return_exceptions=True)


def _cleanup_job_output_files(job_id: str) -> None:
    """Remove partial output files of a cancelled job (.wav, turn caches)."""
    media = _media_dir()
    for pattern in (
        f"{job_id}.wav",
        f"{job_id}.timing.json",
        f".{job_id}_turns",
        f".{job_id}_cloud",
        f"{job_id}.mp3",
        f"{job_id}-og.png",
        f"{job_id}-cover.png",
        f"{job_id}.chapters.mp3",
    ):
        try:
            matches = list(media.glob(pattern))
        except Exception:
            continue
        for p in matches:
            try:
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
            except Exception:
                logger.debug("cleanup failed for %s", p, exc_info=True)

# Hallucination-Guard helpers (DUE-077 / #262)


async def _attach_insights(
    store: JobStore,
    job_id: str,
    body: str,
    style: str = "balanced",
    language: str = "auto",
) -> list[dict[str, Any]]:
    """Extract Blinkist-grade insights with source_quote attribution and persist.

    Warn-only: failures are recorded as stage meta, job continues.
    Returns the extracted takeaways list (may be empty on error).
    """
    try:
        from .insights import extract_insights
        from .script_lint import lint_insights

        exec_summary, exec_quote, tks = await extract_insights(body, style=style, language=language)
        lint_result = lint_insights(exec_summary, exec_quote, tks, body)
        factuality = float(lint_result.get("factuality_score", 0.0))
        store.update(
            job_id,
            executive_summary=exec_summary,
            executive_quote=exec_quote,
            key_takeaways=tks,
            factuality_score=factuality,
        )
        try:
            store.add_stage_meta(job_id, "script", insights_lint=lint_result, factuality_score=factuality)
        except Exception:
            logger.warning("insights lint meta write failed for job %s", job_id, exc_info=True)
        return tks
    except Exception as exc:
        try:
            store.add_stage_meta(job_id, "script", insights_error=str(exc)[:300])
        except Exception:
            logger.warning("insights error meta write failed for job %s", job_id, exc_info=True)
        return []


def _finalize_insights_timings(store: JobStore, job_id: str) -> None:
    """Map each takeaway's section_idx to the script's t0 → timestamp_ms/time_formatted."""
    try:
        job = store.get(job_id)
        tks = job.get("key_takeaways")
        script_lines = job.get("script")
        if not tks or not script_lines:
            return
        n = len(script_lines)
        updated: list[dict[str, Any]] = []
        for tk in tks:
            raw_idx = tk.get("section_idx", 0)
            try:
                sec = int(raw_idx)  # type: ignore[arg-type]
            except Exception:
                sec = 0
            # clip to script bounds: prefer direct index when valid, else proportional
            if 0 <= sec < n:
                line_idx = sec
            else:
                # proportional fallback
                line_idx = min(n - 1, max(0, (sec * n) // max(1, len(tks))))
            t0 = script_lines[line_idx].get("t0") if isinstance(script_lines[line_idx], dict) else None
            ts_ms: int | None = int(float(t0) * 1000) if isinstance(t0, (int, float)) else None
            tf: str | None = None
            if ts_ms is not None:
                s = ts_ms // 1000
                tf = f"{s // 60}:{str(s % 60).zfill(2)}"
            nt = dict(tk)
            nt["timestamp_ms"] = ts_ms
            nt["time_formatted"] = tf
            updated.append(nt)
        store.update(job_id, key_takeaways=updated)
    except Exception:
        logger.warning("finalize insights timings failed for job %s", job_id, exc_info=True)

# ---------------------------------------------------------------------------
# Research mode (#135): discover, triage, sub-fetch
# ---------------------------------------------------------------------------

_LINK_BLOCKLIST = re.compile(
    r"(/tag/|/category/|/author/|/page/\d|/search|\?p=|/feed|/rss"
    r"|\.pdf$|\.mp3$|\.jpg$|\.png$|\.svg$|\.css$|\.js$)"
    r"|#|javascript:|mailto:",
    re.IGNORECASE,
)

def _discover_links(html: str, seed_url: str) -> list[str]:
    """Extract outgoing reference links from seed HTML.

    Internal links first (same host), then external citations.
    Returns deduplicated list of candidate URLs.
    """
    from urllib.parse import urljoin, urlparse

    try:
        from lxml import html as lhtml
        from lxml_html_clean import Cleaner
    except ImportError:
        return []

    try:
        Cleaner()
        tree = lhtml.fromstring(html)
    except Exception:
        return []

    seed_parsed = urlparse(seed_url)
    seed_host = seed_parsed.hostname or ""

    seen: set[str] = set()
    candidates: list[str] = []

    # Internal links first (article/main scoped)
    for link in tree.xpath("//article//a/@href | //main//a/@href | //section//a/@href"):
        url = urljoin(seed_url, link)
        try:
            parsed = urlparse(url)
        except Exception:
            continue
        # Same host, not blocked
        if parsed.hostname == seed_host and parsed.scheme in ("http", "https"):
            if _LINK_BLOCKLIST.search(url):
                continue
            # Link text must be >= 3 words
            el = tree.xpath(f"//a[@href='{link}']")
            if el and len((el[0].text_content() or "").split()) < 3:
                continue
            # Defense-in-depth SSRF guard (F-11): _discover_links is only
            # called after fetch_article has validated the seed URL, so
            # same-host links are expected to be external. Guard here too.
            try:
                from .fetcher import guard_url
                guard_url(url)
            except Exception:
                continue
            if url not in seen:
                seen.add(url)
                candidates.append(url)


    # External citations (max 3)
    for link in tree.xpath("//a/@href"):
        url = urljoin(seed_url, link)
        try:
            parsed = urlparse(url)
        except Exception:
            continue
        if parsed.hostname and parsed.hostname != seed_host:
            if _LINK_BLOCKLIST.search(url):
                continue
            if len((tree.xpath(f"//a[@href='{link}']")[0].text_content() or "").split()) < 2:
                continue
            # SSRF guard
            try:
                from .fetcher import guard_url
                guard_url(url)
            except Exception:
                continue
            if url not in seen:
                seen.add(url)
                candidates.append(url)
                if len([c for c in candidates if urlparse(c).hostname != seed_host]) >= 3:
                    break

    return candidates


async def _triage_links(
    seed_url: str,
    candidates: list[str],
    llm_chain: list[dict],
    max_results: int = 3,
) -> list[str]:
    """LLM triage: which candidates deliver primary data, background, or controversy?

    Returns up to max_results URLs ranked by relevance.
    """
    if not candidates:
        return []

    prompt = (
        f"Given the seed URL: {seed_url}\n"
        f"These are linked URLs found on the page:\n"
        + "\n".join(f"  {i+1}. {u}" for i, u in enumerate(candidates))
        + f"\n\nWhich {max_results} of these are most relevant for deep research "
        f"(primary data, background context, or controversy)? Return a JSON array "
        f"of the selected URLs only, no explanation.\n"
        f"Example: [\"https://...\", \"https://...\"]"
    )

    for prov in llm_chain:
        try:
            result = await _chat_completion(
                prov, prompt, max_tokens=512
            )
            # Extract JSON array from result
            import json
            start = result.find("[")
            end = result.rfind("]") + 1
            if start >= 0 and end > start:
                selected = json.loads(result[start:end])
                if isinstance(selected, list):
                    return selected[:max_results]
        except Exception:
            continue

    # Fallback: return first N candidates
    return candidates[:max_results]


async def _sub_fetch(urls: list[str], max_bytes: int = 50000) -> list[dict]:
    """Async bounded fetch of sub-sources. Returns list of {url, body}."""
    import httpx

    results: list[dict] = []

    async def _fetch_one(session: httpx.AsyncClient, url: str) -> dict | None:
        try:
            r = await session.get(url, timeout=30, follow_redirects=True)
            if r.status_code != 200:
                return None
            from .fetcher import _read_bounded
            body = _read_bounded(r)
            if len(body) < 100:
                return None
            return {"url": url, "body": body[:max_bytes]}
        except Exception:
            return None

    from .fetcher import guarded_client

    async with guarded_client(timeout=30, follow_redirects=True) as session:
        tasks = [_fetch_one(session, u) for u in urls]
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                if result:
                    results.append(result)
            except Exception:
                continue

    return results



def _looks_like_text(raw: str) -> bool:
    """A pasted article, not a URL: has whitespace/newlines and no scheme."""
    stripped = raw.strip()
    if re.match(r"^[a-z][a-z0-9+.-]*://", stripped, re.IGNORECASE):
        return False
    # DUE-066: pasted text may be as short as 20 chars (API validates >=20)
    # Bare domains without whitespace are URLs, not text.
    # Only treat as text if it has whitespace/newlines OR is very short (<20)
    # and has no dots (bare domains have dots but are still URLs).
    if len(stripped) < 20:
        return True
    return ("\n" in raw or " " in raw.strip()) and len(raw.strip()) >= 20


_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "and", "of", "to", "in", "is", "that", "it", "for", "with"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "ein", "eine", "mit", "sich"},
    "es": {"el", "la", "los", "las", "que", "de", "y", "en", "una", "por"},
    "fr": {"le", "la", "les", "et", "est", "que", "une", "des", "pour", "dans"},
    "it": {"il", "la", "che", "di", "e", "un", "una", "per", "sono", "non"},
    "pt": {"o", "a", "que", "de", "e", "um", "uma", "para", "com", "nao"},
}


def detect_source_lang(text: str) -> str | None:
    """Best-effort language guess from stopwords; None when unclear."""
    words = re.findall(r"[a-zA-Z\u00c0-\u024f]+", text[:4000].lower())
    if len(words) < 40:
        return None
    counts = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOPWORDS.items()}
    best = max(counts.items(), key=lambda kv: kv[1])
    return best[0] if best[1] >= 10 else None


_TITLE_BOILERPLATE = re.compile(
    r"(copyright|license|licence|attribution|permission|grant|arxiv|doi|preprint|all rights|http|www\.|@)",
    re.IGNORECASE,
)


def _guess_text_title(text: str) -> str:
    """Title of plain text (a PDF's text layer): the first title-like line.

    The first line of a paper is often a licence notice ('Provided proper
    attribution is provided, Google hereby grants ...' for the Attention
    paper), so take the first short line without a closing period or
    boilerplate among the first lines; fall back to the first line.
    """
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()][:25]
    for ln in lines:
        words = ln.split()
        # a title starts with a capital (continuation lines of a notice do not)
        if (2 <= len(words) <= 12 and ln[0].isupper() and not ln.endswith((".", ",", ";", ":"))
                and not _TITLE_BOILERPLATE.search(ln)):
            return " ".join(words)[:120]
    first = lines[0] if lines else ""
    return first[:120] if len(first) > 3 and not re.match(r"^https?://", first) else ""


async def _extract(
    url: str,
    html: str | None = None,
    depth: str = "direct",
    max_chars: int | None = 25000,
) -> tuple[str, str, str | None]:
    """Extract title, body, and og:image URL from HTML, with optional research depth enrichment.

    max_chars=None keeps the whole body (a source object keeps all of it; the budget
    is applied when a job uses it)."""
    if html is None:
        html = await fetch_article(url)
    og_image: str | None = None
    og_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not og_m:
        og_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.IGNORECASE)
    if og_m:
        og_image = og_m.group(1).strip()

    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if title_m:
        title = title_m.group(1).strip()[:120]
    elif not html.strip().startswith("<") and html.strip().split("\n")[0].strip():
        guessed = _guess_text_title(html)
        if guessed:
            title = guessed
            body_lines = html.strip().split("\n", 1)
            body = body_lines[1] if len(body_lines) > 1 else ""
            body = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", body)).strip()
            return title, body if max_chars is None else body[:max_chars], og_image
        else:
            title = html.strip()[:120]
    else:
        title = html.strip()[:120]
    from lxml import html as lhtml
    from lxml_html_clean import Cleaner

    doc = lhtml.fromstring(html)
    cleaner = Cleaner(
        scripts=True,
        style=True,
        javascript=True,
        forms=True,
        annoying_tags=True,
        remove_unknown_tags=True,
    )
    for bad in doc.xpath("//nav|//header|//footer|//aside"):
        bad.getparent().remove(bad)
    cleaned = cleaner.clean_html(doc)
    text_el = cleaned.xpath("//article") or cleaned.xpath("//main") or [cleaned]
    body = text_el[0].text_content()
    body = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", body)).strip()
    if len(body) < 30:
        raise FetchError("could not extract readable article text from this page (content too short or script-only)")

    # Research Depth Enrichment (#DUE-016)
    if depth in ("deep-page", "fact-check", "contrast") and re.match(r"^https?://", url):
        parsed_origin = urlparse(url)
        found_links: list[str] = []
        for a in text_el[0].xpath(".//a[@href]"):
            href = str(a.get("href", "")).strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            full_link = urljoin(url, href)
            parsed_link = urlparse(full_link)
            if parsed_link.scheme not in ("http", "https"):
                continue

            is_deep = depth == "deep-page" and parsed_link.netloc == parsed_origin.netloc and full_link != url
            is_fact = (
                depth == "fact-check"
                and parsed_link.netloc != parsed_origin.netloc
                and not re.search(r"(twitter\.com|x\.com|facebook\.com|linkedin\.com|reddit\.com|t\.me|instagram\.com|youtube\.com)", parsed_link.netloc)
            )
            if (is_deep or is_fact) and full_link not in found_links:
                found_links.append(full_link)
            if len(found_links) >= 2:
                break

        if found_links:
            enrich_sections: list[str] = []
            for link in found_links:
                try:
                    sub_html = await fetch_article(link)
                    sub_doc = lhtml.fromstring(sub_html)
                    sub_cleaned = cleaner.clean_html(sub_doc)
                    sub_el = sub_cleaned.xpath("//article") or sub_cleaned.xpath("//main") or [sub_cleaned]
                    sub_text = re.sub(r"\s+", " ", sub_el[0].text_content()).strip()
                    if len(sub_text) >= 100:
                        tag = "Subpage Context" if depth == "deep-page" else "Cited Source Reference"
                        enrich_sections.append(f"--- {tag} ({link}) ---\n{sub_text[:3500]}")
                except Exception:
                    continue
            if enrich_sections:
                body = f"{body}\n\n" + "\n\n".join(enrich_sections)

        if depth == "contrast":
            body = (
                f"{body}\n\n"
                f"--- Contrasting Perspectives & Counter-Arguments ---\n"
                f"Identify and discuss counter-arguments, opposing viewpoints, and common criticisms regarding the subject above. "
                f"The hosts should debate these points with nuance."
            )

    return title, body if max_chars is None else body[:max_chars], og_image



async def extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    return (m.group(1).strip() if m else "")[:120]


FORMATS = ["dialog", "narration"]

TONES = ["neutral", "warm", "calm", "energetic", "dramatic"]

NARRATION_BASE = """You rewrite the source text as a spoken essay for a single narrator.
Rules:
- Do not read the source aloud. Retell it: hook first, then the arc, strong closing line.
- Keep every claim grounded in the source. No invented facts.
- Flowing prose paragraphs, each two to four sentences. No markdown, no headings, no lists.
- Write for the ear: short sentences, natural rhythm, contractions welcome.
"""

_NARRATION_TONE_LINES = {
    "neutral": "",
    "warm": "Tone: warm and inviting, like telling a friend about something you found.\n",
    "calm": "Tone: calm and measured, documentary style.\n",
    "energetic": "Tone: energetic, fast-paced, infectious enthusiasm.\n",
    "dramatic": "Tone: dramatic, weighty, tension through short sentences.\n",
}

NARRATION_PROMPT = NARRATION_BASE + """Output ONLY a JSON array of paragraph objects:
[{"speaker":"A","text":"paragraph one"},{"speaker":"A","text":"paragraph two"}]
Source text:
"""

LANGUAGES = {
    "auto": "Auto (source language)",
    "en": "English",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}


EMOTIONS = [
    {"id": "neutral", "help": "no extra coloring"},
    {"id": "warm", "help": "like sharing good news with friends"},
    {"id": "calm", "help": "documentary narration style"},
    {"id": "energetic", "help": "with infectious enthusiasm"},
    {"id": "dramatic", "help": "with weight and tension"},
    {"id": "cheerful", "help": "bright and lighthearted"},
    {"id": "serious", "help": "grave and grounded"},
]

from .styles import EMOTION_INSTRUCTS as _EMOTION_INSTRUCT


def _stored_line(ln: dict[str, Any], host_names: dict[str, str]) -> dict[str, Any]:
    out = {"speaker": ln["speaker"], "text": ln["text"]}
    custom = host_names.get(str(ln.get("speaker", "")).upper())
    if custom:
        # display name rides along; speaker letter stays the voice-mapping id
        out["name"] = custom
    return out


# DUE-078: per-job/per-feed voice profiles ride on the stored object and
# take precedence over the global panel defaults; letters stay technical.
_PROFILE_KEYS = {
    "voice.a.timbre": "a.timbre",
    "voice.b.timbre": "b.timbre",
    "voice.c.timbre": "c.timbre",
    "voice.solo.timbre": "solo.timbre",
    "voice.solo.name": "solo.name",
    "voice.a.name": "a.name",
    "voice.b.name": "b.name",
    "voice.c.name": "c.name",
    "voice.dialog.count": "count",
    "voice.emotion": "emotion",
    "voice.a.emotion": "a.emotion",
    "voice.b.emotion": "b.emotion",
    "voice.c.emotion": "c.emotion",
    "voice.solo.emotion": "solo.emotion",
    "voice.speed": "speed",
    "voice.gap_ms": "gap_ms",
    "tts.engine": "engine",
    "engine": "engine",
}


def _voice_profile(store, job_id: str) -> dict[str, Any]:
    try:
        vp = store.get(job_id).get("voice_profile") or {}
        return vp if isinstance(vp, dict) else {}
    except Exception:
        return {}


def _split_paragraphs(body: str) -> list[dict[str, str]]:
    """Split extracted body into paragraph lines for verbatim narration."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
    return [{"speaker": "Narrator", "text": p} for p in paragraphs]


async def _narration_script(
    body: str,
    output_lang: str,
    src_lang: str | None,
    store: JobStore,
    job_id: str,
    host_names: dict[str, str] | None = None,
    title: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Narration path: skip dialog generation.

    Same language (or auto=source): verbatim paragraph split, zero LLM calls.
    Different language: exactly one translation-only LLM call, plain text in/out.
    """
    # Resolve auto to source language
    if output_lang == "auto" and src_lang:
        output_lang = src_lang

    if output_lang == "auto":
        # Still auto after source detection failed - treat as same language
        output_lang = "en"  # fallback, will use verbatim path

    # Same language (or source lang unknown / auto): verbatim read, zero LLM calls
    if output_lang == src_lang or output_lang == "auto" or src_lang is None:
        lines = _split_paragraphs(body)
        # Count paragraphs for lint stats
        desc = f"{len(lines)} paragraphs, {len(body.split())} words"
        return lines, desc

    # Different language: one translation-only LLM call
    try:
        from .settings_store import get_setting

        custom_prompt = get_setting("script.narration")
    except Exception:
        custom_prompt = None

    lang_name = LANGUAGES.get(output_lang, output_lang)
    translation_prompt = (
        f"Translate the following text faithfully into {lang_name}. "
        "Keep paragraph structure exactly as-is. Do not add commentary, "
        "summaries, or introductions. Output ONLY the translated text.\n\n"
    )
    if custom_prompt:
        translation_prompt += (
            f"Additional instructions from user:\n{custom_prompt}\n\n"
        )
    # #111: solo narrator name intro
    if host_names and "NARRATOR" in host_names:
        translation_prompt = (
            f"The narrator is called {host_names['NARRATOR']}. "
            f"Begin with a brief self-introduction using this name. "
            f"\n\n{translation_prompt}"
        )
    # #112: outro with episode title
    if title:
        translation_prompt = (
            f"This episode is titled '{title}'. "
            f"End with a brief outro that names the episode. "
            f"\n\n{translation_prompt}"
        )
    translation_prompt += body

    errors: list[str] = []
    for prov in llm_chain():
        try:
            content = await _chat_completion(prov, translation_prompt, max_tokens=8192)
            content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
            # Split translated text into paragraphs
            lines = _split_paragraphs(content)
            desc = f"{len(lines)} paragraphs, {len(content.split())} words"
            return lines, desc
        except Exception as exc:
            errors.append(f"{prov['name']}: {exc}")
    raise RuntimeError("all translation writers failed | " + " ; ".join(errors))


# -- digest word-count targets by number of sources -------------------------
_DIGEST_TARGETS: dict[int, int] = {2: 800, 3: 1200, 4: 1500}
_DIGEST_WORDS_MAX = 1800
_DIGEST_SECTION_RE = re.compile(
    r"\[SECTION:(\d+):([^\]]*)\]([\s\S]*?)\[/SECTION\]", re.IGNORECASE
)
_DIGEST_CHAPTERS_RE = re.compile(r"CHAPTERS\s+JSON\s*:\s*(\[[\s\S]*?\])", re.IGNORECASE)
# the first sentence of length.budget_prompt_line, swapped per outline section
_BUDGET_SENTENCE_RE = re.compile(
    r"Write about \d+ words \(plus or minus 10 percent\) in about \d+ turns \(\d+ to \d+ turns\)\.[^\n]*"
)
_SECTION_TAG_RE = re.compile(r"\[/?SECTION(?::[^\]]*)?\]", re.IGNORECASE)
# an inline speaker change inside one text: 'A: "..." B: "..."'
# (a quote must follow, so prose like "Plan B: cheaper" is left alone)
_INLINE_TURN_RE = re.compile(r'(?:^|\s)([ABC])\s*:\s*(?=["\u201c\u201e])')


def _split_inline_turns(speaker: str, text: str) -> list[tuple[str, str]]:
    """Split a text that holds several 'A: ... B: ...' turns into separate turns."""
    marks = list(_INLINE_TURN_RE.finditer(text))
    if not marks:
        return [(speaker, text)]
    turns: list[tuple[str, str]] = []
    lead = text[: marks[0].start()].strip()
    if lead:
        turns.append((speaker, lead))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        chunk = text[m.end():end].strip().strip('"\u201c\u201d\u201e').strip()
        if chunk:
            turns.append((m.group(1), chunk))
    return turns


def _clean_src(raw: Any, n_sources: int | None) -> list[int] | None:
    """Per-line source citations (VOZONDA-TRAY-CITATIONS): the sorted unique
    source numbers a script line draws on, within 1..n_sources.

    Out-of-range and non-int values are dropped, an empty result is dropped,
    and the line itself always stays, so this returns None instead of raising.
    Without a source count (single-source runs) there is nothing to cite."""
    if not isinstance(raw, (list, tuple)) or n_sources is None:
        return None
    try:
        n = int(n_sources)
    except (TypeError, ValueError):
        return None
    kept = sorted({v for v in raw if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= n})
    return kept or None


def _normalize_turns(lines_raw: list | None, fmt: str, n_hosts: int, *, min_turns: int = 4,
                      n_sources: int | None = None) -> list[dict[str, Any]]:
    """Clean LLM script lines into playable turns, or raise ValueError to retry.

    2026-09-23: a digest came back as 4 objects, each holding a whole section
    ('[SECTION:0:Bitcoin] A: "..." B: "..."'), and played as ONE voice reading
    everything. Section tags are stripped, inline turns split, and a dialog for
    2+ hosts that still has a single speaker is rejected.
    """
    out: list[dict[str, Any]] = []
    for ln in lines_raw or []:
        spk = str(ln.get("speaker", "A")).upper()
        txt = _SECTION_TAG_RE.sub(" ", str(ln.get("text", ""))).strip()
        if not txt:
            continue
        section = ln.get("section")
        src = _clean_src(ln.get("src"), n_sources)
        for turn_spk, turn_txt in _split_inline_turns(spk, txt):
            turn_txt = " ".join(turn_txt.split())
            if not turn_txt:
                continue
            if fmt == "narration":
                item: dict[str, Any] = {"speaker": "A", "text": turn_txt}
            elif turn_spk in ("A", "B", "C"):
                item = {"speaker": turn_spk, "text": turn_txt}
            else:
                continue
            if isinstance(section, int):
                item["section"] = section
            if src is not None:
                item["src"] = list(src)
            out.append(item)
    if len(out) < (2 if fmt == "narration" else min_turns):
        raise ValueError("script too short")
    if fmt != "narration" and n_hosts >= 2 and len({t["speaker"] for t in out}) < 2:
        raise ValueError("dialog script has a single speaker")
    return out


def _digest_word_target(n: int) -> int:
    return _DIGEST_TARGETS.get(n, _DIGEST_WORDS_MAX)


def _focus_block(focus: str | None) -> str:
    """Listener focus as a prompt block: steers emphasis, never adds facts."""
    text = " ".join(str(focus or "").split())[:300]
    if not text:
        return ""
    return (
        "LISTENER FOCUS (the listener asked for this; give it priority): "
        f"{text}\n"
        "Cover it wherever the source supports it. If the source says little or "
        "nothing about it, say so in one sentence; never invent facts to satisfy it.\n"
    )


async def _script_digest(
    sections: list[dict[str, Any]],
    style: str = "balanced",
    language: str = "auto",
    n_hosts: int = 2,
    explicit: bool = False,
    fmt: str = "dialog",
    host_names: dict[str, str] | None = None,
    title: str = "",
    focus: str | None = None,
    budget_chars: int | None = None,
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Script a digest episode from N pre-extracted sections.

    Each section is {"index": int, "title": str, "url": str, "body": str}.
    Returns (lines, description, chapters).
    chapters = [{"index": int, "title": str, "url": str, "word_offset": int}]
    """
    n = len(sections)
    target_words = _digest_word_target(n)
    # Reserve ~10% for transitions + outro
    per_story_words = int(target_words * 0.9 / n)

    lang_line = ""
    if language and language != "auto":
        # LANGUAGES lives in this module (line ~131); the styles import
        # blew up at runtime with ImportError (digest-74608f)
        lang_name = LANGUAGES.get(language, language)
        lang_line = f"Write the entire output in {lang_name}.\n"
    elif language == "auto":
        lang_line = "Write the entire output in the same language as the source text.\n"

    adult_block = (
        "\nADULT REGISTER (explicit mode is ON): use raw, unfiltered language throughout.\n"
        if explicit
        else ""
    )

    # Build section blocks for the prompt
    section_blocks = []
    prompt_budget = budget_chars if budget_chars is not None else budget.source_budget_chars()
    _dg_lengths = [len(s["body"]) for s in sections]
    _dg_roles = [str(s.get("role") or "main") for s in sections]
    _dg_shares = budget.allocate(_dg_lengths, _dg_roles, prompt_budget)
    for s, share in zip(sections, _dg_shares):
        title_escaped = s["title"].replace("[", "(").replace("]", ")")
        body_truncated = s["body"][:share]
        # the bracket number is the citation index: a script line carries it in "src"
        num = s.get("position", s["index"]) + 1
        section_blocks.append(
            f"=== SOURCE [{num}]: {title_escaped} ===\n{body_truncated}"
        )
    sources_text = "\n\n".join(section_blocks)

    trio_line = ""
    if fmt != "narration" and n_hosts >= 3:
        trio_line = "Use exactly three named hosts: A is the host, B and C are experts with distinct viewpoints.\n"
    elif n_hosts == 1:
        trio_line = "Use a single narrator voice (A only).\n"

    # #111: host names for digest intro
    names_line = ""
    if host_names and fmt != "narration":
        name_pairs = ", ".join(f"{k} is called {v}" for k, v in sorted(host_names.items()) if k != "NARRATOR")
        if name_pairs:
            names_line = f"Hosts introduce themselves by name in the opening ({name_pairs}).\n"

    # #112: episode title for digest outro
    title_line = ""
    if title:
        title_line = f"This episode is titled '{title}'. Name the episode in the outro.\n"

    prompt = (
        f"{lang_line}{_focus_block(focus)}{trio_line}{names_line}{title_line}{adult_block}"
        f"You are scripting a DIGEST episode covering {n} distinct stories.\n"
        f"Total spoken length target: ~{target_words} words.\n"
        f"Per-story target: ~{per_story_words} words per section.\n\n"
        "FORMAT RULES (mandatory):\n"
        "1. Output ONE JSON array. Every turn is its own object: "
        "{\"speaker\":\"A\",\"text\":\"...\",\"section\":0}. Never put more than one "
        "speaker in one text, and never write 'A:' or 'B:' inside a text.\n"
        "   \"section\" is the 0-based index of the story the turn belongs to.\n"
        "   Each turn may carry \"src\" with the numbers of the sources above it draws on, "
        "for example {\"speaker\":\"A\",\"text\":\"...\",\"section\":0,\"src\":[1]}. "
        "A transition between stories or a short interjection carries no \"src\".\n"
        "2. Between sections, include ONE transition turn where a host names the next story.\n"
        "3. Every factual claim must stay within its section. Never mix facts across sections.\n"
        "4. Each section must open with the host introducing the source topic.\n"
        "5. After all sections, add a brief OUTRO (max 30 words, no new facts).\n"
        "6. After the closing JSON add:\n"
        "   DESCRIPTION: <one sentence max 24 words summarising all topics>\n"
        "   CHAPTERS JSON: [{\"index\":0,\"title\":\"...\"},{\"index\":1,\"title\":\"...\"}]\n\n"
        "Speakers: A and B (or A, B, C for three-host mode); every host speaks in every section.\n"
        "Wrap the JSON array in [ and ].\n\n"
        f"SOURCE MATERIAL:\n{sources_text}\n\n"
        "Now write the digest script following all rules above."
    )

    errors: list[str] = []
    for prov in llm_chain():
        try:
            lines_raw: list | None = None
            description = ""
            out: list[dict[str, Any]] = []
            for _attempt in range(2):
                try:
                    lines_raw, description = await script_call(
                        prompt=prompt,
                        model=prov.get("model", "qwen3.6-35b"),
                        base=prov["base"],
                        key=prov.get("key", ""),
                        max_tokens=16384,
                    )
                    out = _normalize_turns(lines_raw, fmt, n_hosts, n_sources=n)
                    break
                except ValueError:
                    if _attempt == 1:
                        raise

            # Extract chapters JSON from description tail (script_call strips DESCRIPTION:
            # but CHAPTERS JSON may remain in raw content - we parse from description field)
            chapters_data: list[dict[str, Any]] = []
            chapters_match = _DIGEST_CHAPTERS_RE.search(description)
            if chapters_match:
                try:
                    chapters_data = json.loads(chapters_match.group(1))
                    # Strip CHAPTERS JSON from description
                    description = _DIGEST_CHAPTERS_RE.sub("", description).strip()
                except (json.JSONDecodeError, ValueError):
                    chapters_data = []

            # Try to extract section structure from raw lines to compute word_offsets
            # script_call already parsed the JSON into lines, but SECTION markers
            # would have been stripped. We need them to assign chapters.
            # Fallback: divide lines evenly across sections.

            # Compute word offsets for chapters: exact from the turns' section
            # index when present, else an even split
            section_start: dict[int, int] = {}
            running = 0
            for ln in out:
                sec_idx = ln.pop("section", None)
                if isinstance(sec_idx, int) and sec_idx not in section_start:
                    section_start[sec_idx] = running
                running += len(ln["text"].split())
            total_words = running
            words_per_section = max(1, total_words // n)
            chapters_out: list[dict[str, Any]] = []
            cum_words = 0
            for i, sec in enumerate(sections):
                # Use extracted chapters data if available
                title = sec["title"]
                if chapters_data and i < len(chapters_data):
                    title = chapters_data[i].get("title", title)
                chapters_out.append({
                    "index": i,
                    "title": title,
                    "url": sec["url"],
                    "word_offset": section_start.get(i, cum_words),
                })
                cum_words += words_per_section

            return out, description, chapters_out

        except Exception as exc:
            errors.append(f"{prov['name']}: {exc}")

    raise RuntimeError("all digest script writers failed | " + " ; ".join(errors))



def _host_names(profile: dict[str, str] | None = None) -> dict[str, str]:
    """Custom display names per host letter (issue #76); letters stay the
    technical speaker ids for voice mapping, names ride along per line."""
    out: dict[str, str] = {}
    for letter in ("a", "b", "c"):
        name = profile.get(f"{letter}.name") if profile else None
        if not name:
            try:
                raw = str(get_setting_safe(f"voice.{letter}.name") or "").strip()
                if raw:
                    name = raw
            except Exception:
                logger.debug("host name lookup failed for letter %s", letter, exc_info=True)
        if name:
            out[letter.upper()] = name[:24]
    # solo narrator
    solo_name = profile.get("solo.name") if profile else None
    if not solo_name:
        try:
            raw = str(get_setting_safe("voice.solo.name") or "").strip()
            if raw:
                solo_name = raw
        except Exception:
            logger.debug("solo narrator name lookup failed", exc_info=True)
    if solo_name:
        out["NARRATOR"] = solo_name[:24]
    return out


async def _script_outline(
    prompt: str,
    prov: dict,
    planned_words: int,
    turn_words_max: int = 45,
    fmt: str = "dialog",
    n_hosts: int = 2,
    style: str = "",
    n_sources: int | None = None,
) -> tuple[list, str]:
    """Long episodes (VOZONDA-LEN-1): outline first, then section by section.

    The outline carries one word budget per section (summing to the planned
    total); each section is generated with the previous section's last turns
    as context so the arc stays continuous.

    Each section prompt REPLACES the episode budget sentence with the
    section's own: until 2026-09-24 it kept 'Write about 3200 words' and
    only appended 'about 1067 for this section', so every section wrote a
    whole episode (34,729 words for a 20-minute target).
    """
    budgets = outline_split(planned_words)
    titles: list[str] = []
    try:
        raw = await _chat_completion(
            prov,
            f"Plan a podcast episode of about {planned_words} words as "
            f"{len(budgets)} sections. Output ONLY a JSON array of short section titles.",
            max_tokens=1024,
        )
        m = re.search(r"\[[\s\S]*\]", raw)
        if m:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, list):
                titles = [str(t) for t in parsed]
    except Exception:
        titles = []
    while len(titles) < len(budgets):
        titles.append(f"Section {len(titles) + 1}")

    all_lines: list = []
    description = ""
    context = ""
    n = len(budgets)
    for i, words in enumerate(budgets):
        from .rhythm import profile_for

        has_contract = fmt != "narration" and profile_for(style, n_hosts) is not None
        section_budget = budget_prompt_line(words, turn_words_max, contract=has_contract)
        base_prompt, replaced = _BUDGET_SENTENCE_RE.subn(section_budget, prompt, count=1)
        if not replaced:
            base_prompt = f"{prompt}\n{section_budget}"
        role = (
            "Open the episode." if i == 0 else
            "Close the episode at the end of this section." if i == n - 1 else
            "Continue seamlessly: no new opening, no summary, no takeaways, no goodbye; the episode goes on after this section."
        )
        sec_prompt = (
            f"{base_prompt}\n\nOUTLINE MODE: this is section {i + 1} of {n} ({titles[i]}). "
            f"Write ONLY this section, about {words} words. {role}"
        )
        if context:
            sec_prompt += f"\nThe previous section ended with these turns (JSON, continue after them):\n{context}"
        # same 3 attempts + format reminder as a whole episode (VOZONDA-JSON-3):
        # bench round 3 s3 failed here, on a section, with 'no JSON array'
        sec_lines, description = await _script_direct(
            sec_prompt, prov, words, fmt, n_hosts, min_turns=2, n_sources=n_sources
        )
        filtered = _normalize_turns(sec_lines, fmt, n_hosts, min_turns=2, n_sources=n_sources)
        all_lines.extend(filtered)
        # JSON, not 'A: text' lines: the model copied that line format and
        # stopped writing JSON (bench s2, section 3, 2026-09-24)
        context = json.dumps([{"speaker": ln["speaker"], "text": ln["text"]} for ln in filtered[-2:]], ensure_ascii=False)
    return all_lines, description


SCRIPT_JSON_REMINDER = "Output ONLY the JSON array of turns. No prose before or after it, no code fence."


async def _script_direct(
    prompt: str,
    prov: dict[str, Any],
    planned_words: int | None = None,
    fmt: str = "dialog",
    n_hosts: int = 2,
    *,
    max_tokens: int = 16384,
    min_turns: int = 4,
    n_sources: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Script generation with up to 3 attempts on ValueError (whole episode or one outline section).

    Attempts 1 and 2 use the prompt as-is. Attempt 3 appends SCRIPT_JSON_REMINDER.
    Guards against runaway scripts (>2.2x planned_words).
    """
    prov = prov or {}
    for _attempt in range(3):
        try:
            call_prompt = (
                prompt
                if _attempt < 2
                else f"{prompt}\n{SCRIPT_JSON_REMINDER}"
            )
            lines, description = await script_call(
                prompt=call_prompt,
                model=prov.get("model", "qwen3.6-35b"),
                base=prov.get("base", ""),
                key=prov.get("key", ""),
                max_tokens=max_tokens,
            )
            checked = _normalize_turns(lines, fmt, n_hosts, min_turns=min_turns, n_sources=n_sources)
            # a model stuck in a loop wrote 9688 words for a 1280-word
            # budget (tuning run, 2026-09-24): retry instead of voicing it
            if planned_words and sum(len(t["text"].split()) for t in checked) > 2.2 * planned_words:
                raise ValueError("runaway script, far over the word budget")
            return lines, description
        except ValueError:
            if _attempt == 2:
                raise
    raise RuntimeError("all script attempts failed")


async def _role_and_rhythm(
    out: list[dict[str, Any]],
    profile: Any,
    prov: dict[str, Any],
    lang_line: str,
    language: str,
    body: str,
    length_meta: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Targeted role repair, then the deterministic rhythm layer (2026-10-02).

    Code picks the loud host's longest turns and fixes who speaks; the model only
    writes the two parts of each spot (live: host A 12/15/22 -> 28/28/29 percent).
    Every repair is checked (content kept, the quiet host gets a real part) and
    dropped otherwise; a failed call never fails the episode."""
    import hashlib

    from . import script_contract as sc
    from .rhythm_layer import apply_rhythm_layer

    meta = length_meta if length_meta is not None else {}
    meta["rhythm_problems"] = rhythm_problems_for(out, profile)
    qh = sc.quiet_host(out, profile)
    if qh is not None:
        quiet, loud = qh
        spots = sc.repair_targets(out, profile)

        async def one(i: int) -> tuple[int, list[dict[str, Any]] | None]:
            try:
                raw = await _chat_completion(prov, sc.repair_prompt(out, i, quiet, loud, lang_line), max_tokens=4096)
                return i, sc.accept_repair(out[i], sc.parse_parts(raw, quiet, loud), quiet, loud)
            except Exception:
                logger.warning("role repair of turn %s failed", i, exc_info=True)
                return i, None

        results = await asyncio.gather(*(one(i) for i in spots))
        repairs = {i: r for i, r in results if r}
        out = sc.splice(out, repairs)
        meta["role_repair"] = {"quiet": quiet, "spots": len(spots), "accepted": len(repairs)}
    lang = language if language and language != "auto" else (detect_source_lang(body) or "en")
    before = len(out)
    out = apply_rhythm_layer(out, profile, lang, seed=hashlib.sha1(body[:4000].encode()).hexdigest())
    meta["rhythm_layer_added"] = len(out) - before
    meta["rhythm_problems_after"] = rhythm_problems_for(out, profile)
    return out


async def _script(
    body: str,
    style: str = "balanced",
    fmt: str = "dialog",
    tone: str = "neutral",
    language: str = "auto",
    n_hosts: int = 2,
    explicit: bool = False,
    host_names: dict[str, str] | None = None,
    title: str = "",
    tts_engine: str = "",
    emotion: str = "",
    target_minutes: float | None = None,
    length_meta: dict[str, Any] | None = None,
    focus: str | None = None,
    n_sources: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    lang_line = ""
    if language and language != "auto":
        lang_name = LANGUAGES.get(language, language)
        lang_line = f"Write the entire output in {lang_name}.\n"
    elif language == "auto":
        lang_line = "Write the entire output in the same language as the source text.\n"
    try:
        from .settings_store import get_setting

        if not tts_engine:
            tts_engine = get_setting("tts.engine") or "qwen_tts"
        if not emotion:
            emotion = get_setting("voice.emotion") or "neutral"

        if fmt == "narration":
            key = "script.narration"
            fallback = NARRATION_BASE + _NARRATION_TONE_LINES.get(tone, "") + NARRATION_PROMPT[len(NARRATION_BASE):]
        else:
            if style == "default":  # legacy value from early episodes
                style = "balanced"
            elif style == "witty":  # legacy alias mapped to tech_roast
                style = "tech_roast"
            key = f"script.style.{style}" if style != "balanced" else "script.balanced"
            fallback = None
        template = get_setting(key)
    except Exception:
        template = None
        if not tts_engine:
            tts_engine = "qwen_tts"
        if not emotion:
            emotion = "neutral"
    if not template:  # unset or emptied in settings: that style's built-in, never balanced's
        template = fallback or STYLE_TEMPLATES.get(style, SCRIPT_PROMPT)
    custom_row: dict[str, Any] | None = None
    if fmt != "narration" and style.startswith("custom_"):
        # user styles render through the same code path as built-in styles: the
        # shared dialogue rules plus a role paragraph, with the rhythm type's
        # contract opening the prompt and its reminder closing it. A deleted
        # custom style renders with balanced and logs a warning.
        try:
            from .custom_styles import get_custom_style

            custom_row = get_custom_style(style)
        except KeyError:
            custom_row = None
        except Exception:
            logger.warning("custom style lookup failed for %s", style, exc_info=True)
            custom_row = None
        if custom_row is None:
            logger.warning("custom style %s was deleted, falling back to balanced", style)
            style = "balanced"
            template = None
            try:
                from .settings_store import get_setting as _get_balanced

                template = _get_balanced("script.balanced")
            except Exception:
                template = None
            template = template or SCRIPT_PROMPT
        elif template == SCRIPT_PROMPT:
            # no settings override for this custom style: use its own roles
            from .style_registry import custom_template_for

            template = custom_template_for(custom_row)
    prompt_text = template or SCRIPT_PROMPT

    # #111: inject host names into dialog prompt for intro self-introductions
    if fmt != "narration" and host_names:
        name_pairs = ", ".join(f"{k} is called {v}" for k, v in sorted(host_names.items()) if k != "NARRATOR")
        if name_pairs:
            names_line = f"Hosts introduce themselves by name in the first lines ({name_pairs}).\n"
            marker = "Output ONLY a JSON array"
            if marker in prompt_text:
                prompt_text = prompt_text.replace(marker, names_line + marker)
            else:
                prompt_text += "\n" + names_line

    # #112: inject episode title for outro wrap
    if title:
        outro_line = f'This episode is titled "{title}". Close with a brief outro that names the episode.\n'
        marker = "Output ONLY a JSON array"
        if marker in prompt_text:
            prompt_text = prompt_text.replace(marker, outro_line + marker)
        else:
            prompt_text += "\n" + outro_line

    if fmt != "narration" and n_hosts >= 3:
        hosts_line = (
            "Use exactly three named hosts: A is the host, B and C are "
            "experts with distinct viewpoints. All three must speak at "
            "least three times. Map speakers to letters A, B, C.\n"
        )
        marker = "Output ONLY a JSON array"
        if marker in prompt_text:
            prompt_text = prompt_text.replace(marker, hosts_line + marker)
            # keep the inline example consistent with the three-host order,
            # otherwise models copy the A/B-only example and drop speaker C
            if '","text":"..."}]' in prompt_text and '{"speaker":"C"' not in prompt_text:
                prompt_text = prompt_text.replace(
                    '{"speaker":"A","text":"..."},{"speaker":"B","text":"..."}]',
                    '{"speaker":"A","text":"..."},{"speaker":"B","text":"..."}]',
                    1,
                )
        else:
            prompt_text += "\n" + hosts_line

    # VOZONDA-LEN-1: a precise word budget replaces the fixed turn range;
    # SCRIPT_PARAMS keeps shaping turn size, not episode length.
    planned_words: int | None = None
    _sd = SCRIPT_PARAMS.get(style)
    twm = _sd.get("turn_words_max", SCRIPT_PARAMS["turn_words_max"]) if isinstance(_sd, dict) else SCRIPT_PARAMS["turn_words_max"]
    if fmt != "narration" and target_minutes is not None:
        eng = tts_engine or "qwen_tts"
        lang = language if language and language != "auto" else None
        wpm_settings: dict[str, float] = {}
        raw_engine = get_setting_safe(f"tts.wpm.{eng}")
        if raw_engine:
            try:
                wpm_settings[f"tts.wpm.{eng}"] = float(raw_engine)
            except (TypeError, ValueError):
                pass
        if lang:
            raw_lang = get_setting_safe(f"tts.wpm.{eng}.{lang}")
            if raw_lang:
                try:
                    wpm_settings[f"tts.wpm.{eng}.{lang}"] = float(raw_lang)
                except (TypeError, ValueError):
                    pass
        planned_words = word_budget(target_minutes, eng, wpm_settings, lang)

    # Output contract instead of a per-turn TURN PLAN (2026-10-02). The JSON plan
    # skeleton gave no JSON in 6 of 9 live runs on the 35B and the role split in
    # none; the style's roles in numbers up front, a reminder after the source, a
    # targeted role repair and the deterministic rhythm layer met the profile in
    # 9 of 9 (script_contract, rhythm_layer).
    from .rhythm import apply_profile_rules, profile_for

    profile = profile_for(style, n_hosts) if fmt != "narration" else None
    if profile is not None:
        prompt_text = apply_profile_rules(prompt_text, profile)
        if length_meta is not None:
            length_meta["rhythm_profile"] = style

    if planned_words is not None:
        budget_line = budget_prompt_line(planned_words, twm, contract=profile is not None)
        prompt_text, n_sub = re.subn(
            r"Aim for\s+\d+\s+to\s+\d+\s+turns total\.", budget_line, prompt_text
        )
        if n_sub == 0:
            prompt_text += "\n" + budget_line

    if fmt != "narration" and n_sources is not None and n_sources > 1:
        # multi-source runs (combine) cite per line: the sources above are
        # numbered [1]..[n], and each JSON turn may carry them in "src".
        # Into the existing output-format sentence, not a block at the end.
        _src_hint = (
            f"Each turn may carry \"src\" with the numbers [1]..[{n_sources}] of the sources above it draws on, "
            "for example {\"speaker\":\"A\",\"text\":\"...\",\"src\":[1,2]}. "
            "Transitions and short interjections carry no \"src\".\n"
        )
        _marker = "Output ONLY a JSON array"
        if _marker in prompt_text:
            prompt_text = prompt_text.replace(_marker, _src_hint + _marker, 1)
        else:
            prompt_text = prompt_text + "\n" + _src_hint

    try:
        from .styles import HOOK_BRIEFS

        brief = HOOK_BRIEFS.get(style)
    except Exception:
        brief = None
    brief_line = f" {brief}" if brief else ""
    hook_line = (
        "After the closing ] add one new line:\n"
        "DESCRIPTION: <one sentence, max 24 words, on why someone should "
        f"listen to this episode - concrete, no hype words.{brief_line} "
        "Write it in the same language as the dialogue.>\n"
    )
    trio_line = (
        "CAST REQUIREMENT: write exactly three speakers, A, B and C.\n"
        if fmt != "narration" and n_hosts >= 3
        else ""
    )
    adult_block = (
        "\nADULT REGISTER (explicit mode is ON for this episode): use raw, unfiltered "
        "language throughout. Swear freely, use crude expressions, and let the dialogue "
        "feel genuinely rough and real. Do NOT sanitize or soften the language. If the "
        "source text contains strong language, preserve and amplify it. Translate "
        "profanity into the output language the way locals actually curse - use the "
        "strongest natural words, not mild euphemisms. This is NOT casual conversation; "
        "it is unfiltered adult dialogue. The facts from the source stay untouched; "
        "only the register changes.\n"
    )
    try:
        from .settings_store import get_setting
        use_names_setting = get_setting("script.use_names")
        intro_hook_setting = get_setting("script.intro_hook")
        takeaways_setting = get_setting("script.takeaways")
    except Exception:
        use_names_setting = None
        intro_hook_setting = None
        takeaways_setting = None

    tuning_lines = []
    if use_names_setting == "0":
        tuning_lines.append("NAME DIRECTIVE: Do NOT mention or address each other by names (e.g. avoid 'Hey Alex', 'Good point, Sam'). Speak directly without using host names.")
    elif use_names_setting == "1":
        tuning_lines.append("NAME DIRECTIVE: Naturally mention each other's names in dialogue turns where appropriate to establish conversational rapport.")

    if intro_hook_setting == "1":
        tuning_lines.append("COLD OPEN HOOK: Start Turn 1 immediately with the most surprising, intriguing fact or question without generic podcast greetings.")

    if takeaways_setting == "1":
        tuning_lines.append("WRAP-UP DIRECTIVE: Ensure the final 2 turns provide clear, actionable takeaways and conclusions from the topic.")

    # Emotion register & capability-driven prose tuning via central seam resolver
    try:
        from .providers import resolve_emotion_delivery

        emo_delivery = resolve_emotion_delivery(tts_engine, emotion=emotion, style=style)
        tuning_lines.append(emo_delivery["prompt_directive"])
    except Exception:
        if emotion and emotion != "neutral":
            tuning_lines.append(f"OVERALL EMOTIONAL REGISTER: Shape the dialogue energy and host interaction to be {emotion}.")

    tuning_block = ("\n" + "\n".join(tuning_lines) + "\n") if tuning_lines else ""

    from .script_contract import contract_block, reminder_line

    # contract first and reminder last: the middle of a long prompt is followed worst
    contract = contract_block(profile) if profile is not None else ""
    prompt = contract + trio_line + lang_line + _focus_block(focus) + tuning_block + prompt_text + (adult_block if explicit else "") + body + "\n" + hook_line
    if fmt != "narration":
        from .styles import FORM_CHECK

        prompt += "\n" + FORM_CHECK
    if fmt != "narration" and n_hosts >= 3:
        prompt += (
            "\nFINAL CHECK before answering: the array must contain turns "
            "from exactly three speakers A, B and C, each speaking at least "
            "three times. Two-speaker output is a failure."
        )
    if profile is not None:  # last line: where the model's attention is high again
        prompt += "\n" + reminder_line(profile)

    errors: list[str] = []
    for prov in llm_chain():
        try:
            # three attempts per writer: a model can drift out of json on a
            # single sample; attempt 3 adds a format reminder (VOZONDA-JSON-3)
            lines: list | None = None
            description = ""
            if planned_words is not None and planned_words > OUTLINE_THRESHOLD_WORDS:
                lines, description = await _script_outline(
                    prompt, prov, planned_words, turn_words_max=twm, fmt=fmt, n_hosts=n_hosts, style=style,
                    n_sources=n_sources,
                )
            else:
                lines, description = await _script_direct(
                    prompt, prov, planned_words=planned_words, fmt=fmt, n_hosts=n_hosts, n_sources=n_sources
                )
            out = _normalize_turns(lines, fmt, n_hosts, n_sources=n_sources)
            # VOZONDA-LEN-1: one corrective pass when outside +-15% of budget
            if planned_words is not None:
                actual_words = sum(len(str(ln["text"]).split()) for ln in out)
                first_pass_words, first_pass_turns = actual_words, len(out)
                correction_kept = False
                action = correction_action(actual_words, planned_words)
                if action:
                    fix = (
                        "expand these sections with more depth from the source, no new facts"
                        if action == "expand"
                        else "condense, keep the arc and the hook"
                    )
                    fix_prompt = (
                        f"{prompt}\nLENGTH CORRECTION: the draft is "
                        f"{'too short' if action == 'expand' else 'too long'}; "
                        f"{fix}. Target about {planned_words} words."
                    )
                    try:
                        fixed_lines, fixed_desc = await script_call(
                            prompt=fix_prompt,
                            model=prov.get("model", "qwen3.6-35b"),
                            base=prov["base"],
                            key=prov.get("key", ""),
                            max_tokens=16384,
                        )
                        # The correction writes a fresh script (the draft is not sent),
                        # so keep it only if it lands closer to the budget without
                        # falling apart into fragments (bench s2: 152 turns of 10 words).
                        out2 = _normalize_turns(fixed_lines, fmt, n_hosts, n_sources=n_sources)
                        words2 = sum(len(str(ln["text"]).split()) for ln in out2)
                        if abs(words2 - planned_words) < abs(actual_words - planned_words) and words2 / len(out2) >= 8:
                            out = out2
                            description = fixed_desc or description
                            correction_kept = True
                            actual_words = words2
                    except Exception:
                        logger.warning("script length correction failed", exc_info=True)
                if length_meta is not None:
                    length_meta["planned_words"] = planned_words
                    length_meta["actual_words"] = actual_words
                    length_meta["first_pass_words"] = first_pass_words
                    length_meta["first_pass_turns"] = first_pass_turns
                    if action:
                        length_meta["correction"] = action
                        length_meta["correction_kept"] = correction_kept
            if profile is not None:
                out = await _role_and_rhythm(out, profile, prov, lang_line, language, body, length_meta)
            return out, description
        except Exception as exc:
            errors.append(f"{prov['name']}: {exc}")
    raise RuntimeError("all script writers failed | " + " ; ".join(errors))


# Transient failures of a (cloud) script writer: retried with backoff before
# the chain moves on. A read timeout is not retried; it already took 600 s.
LLM_RETRY_STATUS = {429, 500, 502, 503, 504}
LLM_RETRY_BACKOFF_S = (10, 30)
_llm_retry_sleep = asyncio.sleep


async def _chat_completion(prov: dict, prompt: str, max_tokens: int = 4096) -> str:
    for attempt, wait in enumerate((0, *LLM_RETRY_BACKOFF_S)):
        if wait:
            await _llm_retry_sleep(wait)
        try:
            return await _chat_completion_once(prov, prompt, max_tokens)
        except (httpx.HTTPStatusError, httpx.ConnectError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            transient = status is None or status in LLM_RETRY_STATUS
            if not transient or attempt == len(LLM_RETRY_BACKOFF_S):
                raise
    raise RuntimeError("unreachable")


async def _chat_completion_once(prov: dict, prompt: str, max_tokens: int) -> str:
    from .providers import OPENCODE_BASE
    from .providers.script import opencode_run

    if prov.get("base") == OPENCODE_BASE:
        return await opencode_run(prov["model"], prompt)
    base = prov["base"].rstrip("/")
    key = prov.get("key") or ""
    is_anthropic = "api.anthropic.com" in base
    if is_anthropic and base.endswith("/v1"):
        base = base[: -len("/v1")]  # the code appends /v1/messages itself
    async with httpx.AsyncClient(timeout=600) as c:
        if is_anthropic:
            payload = {
                "model": prov["model"],
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            url = f"{base}/v1/messages"
        else:
            payload = {
                "model": prov["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            }
            with_thinking_off(payload, base)
            headers = {}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            url = f"{base}/chat/completions"
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        if is_anthropic:
            return data["content"][0]["text"]
        return data["choices"][0]["message"]["content"]


async def _generate_episode_title(
    store: JobStore,
    job_id: str,
    lines: list[dict[str, Any]],
    source_title: str,
    llm_chain_func,
) -> str | None:
    """Generate a descriptive episode title from the script using an LLM call.

    Returns the new title if successful, None to keep the original title.
    """
    if not lines:
        return None

    script_text = " ".join(ln.get("text", "") for ln in lines)
    words = script_text.split()
    if len(words) > 1500:
        script_text = " ".join(words[:1500])

    prompt = (
        "You are naming a podcast episode. Write ONE title, max 70 characters, "
        "in the episode's language. Be concrete, no clickbait, no quotes, no emoji, "
        "no trailing period.\n\n"
        f"Source title(s): {source_title}\n\n"
        f"Script (first ~1500 words):\n{script_text}"
    )

    for prov in llm_chain_func():
        try:
            # a title is a nice-to-have: never let it hold the episode up
            result = await asyncio.wait_for(_chat_completion(prov, prompt, max_tokens=128), 60)
            result = result.strip().strip('"\'')
            result = result.split("\n")[0].strip()
            if 8 <= len(result) <= 90:
                return result
        except Exception:
            continue
    return None


async def _voice(
    store,
    job_id: str,
    lines: list[dict[str, Any]],
    workdir: Path,
    *,
    fmt: str = "dialog",
    language: str = "auto",
    style: str = "balanced",
) -> Path:
    try:
        return await _voice_local(
            store, job_id, lines, workdir, fmt=fmt, language=language, style=style
        )
    except Exception as local_err:
        fallbacks = tts_fallbacks()
        if not fallbacks:
            raise
        last: Exception = local_err
        for fb in fallbacks:
            try:
                return await _voice_cloud(job_id, lines, workdir, fb)
            except Exception as exc:
                last = exc
        raise last from local_err


# Speaker instructs for TTS neutral emotion - imported from style_registry
from .style_registry import _STYLE_SPEAKER_INSTRUCTS

# Calm styles keep their own slow pacing when the episode sets none, so a
# faster global default (maintainer 2026-09-23: ~1.12 / 260 ms, closer to NotebookLM)
# never rushes a meditation or an ASMR session. (speed, gap_ms)
CALM_STYLE_PACING: dict[str, tuple[float, int]] = {
    "meditation": (0.85, 600),
    "asmr": (0.9, 650),
}


def _pacing(store, job_id: str, style: str | None) -> tuple[float, int]:
    """Speed and turn gap: episode voice profile > calm style > global setting > default."""
    try:
        vp = _voice_profile(store, job_id)
    except Exception:
        vp = {}
    calm = CALM_STYLE_PACING.get(style or "")

    def pick(key: str, setting: str, default: float, calm_value: float | None) -> float:
        v = vp.get(key)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        if calm_value is not None:
            return float(calm_value)
        raw = get_setting_safe(setting)
        try:
            return float(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            return default

    speed = pick("speed", "voice.speed", 1.0, calm[0] if calm else None)
    gap = int(pick("gap_ms", "voice.gap_ms", 380, calm[1] if calm else None))
    return max(0.5, min(2.0, speed)), max(50, min(1200, gap))


def _detected_source_lang(store, job_id: str) -> str | None:
    """Source language the extract stage detected, if any."""
    try:
        for stage in store.get(job_id).get("stages") or []:
            if stage.get("name") == "extract":
                lang = (stage.get("meta") or {}).get("source_lang")
                return str(lang) if lang else None
    except Exception:
        logger.debug("detected source lang lookup failed for job %s", job_id, exc_info=True)
    return None


async def _voice_local(
    store,
    job_id: str,
    lines: list[dict[str, Any]],
    workdir: Path,
    *,
    fmt: str = "dialog",
    language: str = "auto",
    style: str = "balanced",
) -> Path:
    # "auto" means the source language. The script stage already follows the
    # detected language; without this the voices fell back to English, so a
    # German article got a German script read by English default voices.
    if not language or language == "auto":
        language = _detected_source_lang(store, job_id) or "auto"

    try:
        from .settings_store import get_setting

        voice = _voice_profile(store, job_id)

        def sv(key: str, default: str) -> str:
            """DUE-078 reader chain: job profile > global setting > default."""
            pkey = _PROFILE_KEYS.get(key)
            if pkey and pkey in voice and voice[pkey] is not None:
                return voice[pkey]
            try:
                v = get_setting(key)
                return default if v in (None, "") else v
            except Exception:
                return default
    except Exception:

        def sv(key: str, default: str) -> str:
            return default

    emotion = sv("voice.emotion", "neutral")
    tts_engine = sv("tts.engine", "qwen_tts")

    # Kokoro covers English and 7 more languages; anything else renders
    # with Piper when kokoro is the engine (logged once per job).
    try:
        from .providers import resolve_voice_engine

        _fb_lang = language if language != "auto" else "en"
        _fb_engine, _fb_msg = resolve_voice_engine(tts_engine, _fb_lang)
        if _fb_msg and _fb_engine != tts_engine:
            print(_fb_msg, flush=True)
            try:
                store.add_stage_meta(job_id, "voice", fallback=_fb_msg)
            except Exception:
                logger.warning("voice fallback meta write failed for job %s", job_id, exc_info=True)
            tts_engine = _fb_engine
    except Exception:
        logger.warning("voice engine resolve failed for job %s, kokoro language fallback skipped", job_id, exc_info=True)

    # Central emotion delivery resolver for TTS synthesis instructs
    try:
        from .providers import resolve_emotion_delivery

        emo_delivery = resolve_emotion_delivery(tts_engine, emotion=emotion, style=style)
        instruct = emo_delivery["instruct_text"]
    except Exception:
        instruct = None

    role_instructs = _STYLE_SPEAKER_INSTRUCTS.get(style) or {} if emotion == "neutral" else {}

    # Resolve language for default timbre selection (DUE-041)
    lang = language if language != "auto" else "en"
    cast = default_cast_for(tts_engine)
    role_defaults = cast.get(lang) or cast["en"]

    def _role_timbre(role: str, fallback: str = "ryan") -> str:
        if isinstance(role_defaults, dict):
            v = role_defaults.get(role)
            return v if isinstance(v, str) else fallback
        return role_defaults if isinstance(role_defaults, str) else fallback

    if fmt == "narration":
        solo = sv("voice.solo.timbre", _role_timbre("solo"))
        solo_instruct = (_EMOTION_INSTRUCT.get(sv("voice.solo.emotion", "")) or instruct) if instruct is not None else None
        voices = {ln["speaker"]: {"timbre": solo, "instruct": solo_instruct} for ln in lines}
    else:
        # per-job hosts (watchlist/DUE-062) overrides global setting
        try:
            job_hosts = store.get(job_id).get("hosts")
            if job_hosts is not None:
                count = int(job_hosts)
            else:
                count = int(sv("voice.dialog.count", "2"))
        except Exception:
            count = int(sv("voice.dialog.count", "2"))
        # Resolve language for default timbre selection
        pool = [sv(f"voice.{chr(97+idx)}.timbre", _role_timbre(chr(97 + idx))) for idx in range(3)]
        emo_pool = [sv("voice.a.emotion", ""), sv("voice.b.emotion", ""), sv("voice.c.emotion", "")]
        assigned: dict[str, dict[str, Any]] = {}
        idx = 0
        for ln in lines:
            spk = ln["speaker"]
            if spk not in assigned:
                slot = idx % len(pool)
                timbre = pool[idx] if idx < min(count, len(pool)) else pool[idx % len(pool)]
                spk_emo = emo_pool[slot] or emotion
                spk_instruct = (_EMOTION_INSTRUCT.get(spk_emo) or instruct) if instruct is not None else None
                assigned[spk] = {"timbre": timbre, "instruct": spk_instruct}
                idx += 1
        if emotion == "neutral" and role_instructs and instruct is not None:
            for spk, v in assigned.items():
                if spk in role_instructs:
                    v["instruct"] = role_instructs[spk]
        voices = assigned

    lang_map = {
        "en": "English", "de": "German", "es": "Spanish", "fr": "French",
        "it": "Italian", "pt": "Portuguese", "ru": "Russian",
        "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
    }

    workdir.mkdir(parents=True, exist_ok=True)
    cfg_path = workdir / f"{job_id}.voice.json"
    wav = workdir / f"{job_id}.wav"
    try:
        store.add_stage_meta(job_id, "script",
            voices=list(dict.fromkeys(v["timbre"] for v in voices.values())),
            voice_map={spk: v["timbre"] for spk, v in voices.items()},
        )
    except Exception:
        logger.warning("voice map meta write failed for job %s", job_id, exc_info=True)
    cfg = {
        "segments": lines,
        "voices": voices,
        "gap_ms": _pacing(store, job_id, style)[1],
        "language": lang_map.get(language, "English"),
        "out": str(wav),
    }
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False))

    try:
        from .settings_store import get_setting as _get_setting

        engine = sv("tts.engine", _get_setting("tts.engine") or "qwen_tts")
    except Exception:
        engine = sv("tts.engine", "qwen_tts")

    # same kokoro -> piper language rule for the renderer lookup (the
    # message is logged once above, at cast time)
    try:
        from .providers import resolve_voice_engine as _resolve_ve

        _rlang = language if language != "auto" else "en"
        engine, _ = _resolve_ve(engine, _rlang)
    except Exception:
        logger.debug("renderer voice engine resolve failed for job %s", job_id, exc_info=True)

    try:
        store.add_stage_meta(job_id, "voice", engine=engine)
    except Exception:
        logger.warning("voice engine meta write failed for job %s", job_id, exc_info=True)

    # Renderer and interpreter come from the engine's plugin META, so a new
    # engine is one provider module plus its renderer script.
    from .providers import tts_engines
    here = Path(__file__).resolve().parent
    meta = tts_engines().get(engine)
    renderer = here / (getattr(meta, "renderer", "") or "render_vozonda.py")
    if not renderer.exists():
        renderer = here / "render_vozonda.py"
    render_py = TTS_PY
    try:
        from .plugins import registry
        render_py = getattr(registry.get(engine), "RENDER_PY", TTS_PY) or TTS_PY
    except Exception:
        logger.debug("renderer interpreter lookup failed for engine %s", engine, exc_info=True)

    proc = await asyncio.create_subprocess_exec(
        render_py,
        str(renderer),
        "--config",
        str(cfg_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "HF_HOME": HF_HOME},
        start_new_session=True,
    )
    _, _ = await _communicate_tracked(job_id, proc)
    if proc.returncode != 0 or not wav.exists():
        raise RuntimeError("Text-to-speech generation failed. The voice engine returned an error.")
    return wav


async def _voice_cloud(
    job_id: str,
    lines: list[dict[str, Any]],
    workdir: Path,
    fb: dict,
) -> Path:

    key = fb.get("key") or ""
    if not key and fb.get("key_env"):
        raise RuntimeError(f"{fb['name']}: missing key ({fb['key_env']} unset)")
    seg_dir = workdir / f".{job_id}_cloud"
    seg_dir.mkdir(parents=True, exist_ok=True)
    mapping = fb.get("voices") or {}
    default_voice = next(iter(mapping.values()), "alloy")

    files: list[Path] = []
    async with httpx.AsyncClient(timeout=120) as c:
        for i, line in enumerate(lines):
            voice = mapping.get(line["speaker"], default_voice)
            mp3 = seg_dir / f"{i:04d}.mp3"
            if fb["name"] == "openai_tts":
                payload: dict[str, Any] = {
                    "model": fb.get("model", "gpt-4o-mini-tts"),
                    "voice": voice,
                    "input": line["text"],
                    "response_format": "mp3",
                }
                if line.get("instruct"):
                    payload["instructions"] = line["instruct"]
                headers = {"Authorization": f"Bearer {key}"}
                url = "https://api.openai.com/v1/audio/speech"
            elif fb["name"] == "elevenlabs":
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
                payload = {
                    "text": line["text"],
                    "model_id": fb.get("model", "eleven_multilingual_v2"),
                }
                headers = {"xi-api-key": key}
            else:
                raise RuntimeError(f"unknown cloud tts provider: {fb['name']}")
            r = await c.post(url, json=payload, headers=headers)
            if r.status_code != 200 or len(r.content) < 512:
                raise RuntimeError(f"{fb['name']} turn {i} failed: {r.status_code}")
            mp3.write_bytes(r.content)
            files.append(mp3)

    list_file = seg_dir / "list.txt"
    list_file.write_text("\n".join(f"file '{f}'" for f in files))
    wav = workdir / f"{job_id}.wav"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-ar", "24000", "-ac", "1", str(wav),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    _, _ = await _communicate_tracked(job_id, proc)
    if proc.returncode != 0 or not wav.exists():
        raise RuntimeError("Audio concatenation failed. The cloud service returned an error.")
    return wav


def _is_music_enabled(store: JobStore, job_id: str, job: dict[str, Any] | None = None) -> bool:
    """Check if music intro/outro beds are enabled for this job or environment (#113)."""
    if job:
        if job.get("music_bed") is not None:
            return bool(job["music_bed"])
        if job.get("music") is not None:
            return bool(job["music"] and job["music"] not in ("none", "false", "0"))
    vp = _voice_profile(store, job_id)
    if "music_bed" in vp:
        return bool(vp["music_bed"])
    if "music" in vp:
        return bool(vp["music"] and vp["music"] not in ("none", "false", "0"))
    setting = get_setting_safe("music.enabled")
    if setting is not None:
        return str(setting).lower() in ("true", "1", "yes", "on")
    # Auto-detect if music assets exist in MEDIA_DIR
    try:
        from .music import find_music_assets
        intro, outro = find_music_assets(MEDIA_DIR)
        return bool(intro or outro)
    except Exception:
        return False


def _build_master_ffmpeg_args(
    wav: Path,
    mp3: Path,
    speed: float = 1.0,
    filters: list[str] | None = None,
    metadata: dict[str, str] | None = None,
) -> list[str]:
    """Build ffmpeg argument list for mastering step. Pure function for testability."""
    if filters is None:
        filters = []
    else:
        filters = list(filters)
    if abs(speed - 1.0) > 0.01:
        filters.append(f"atempo={max(0.5, min(2.0, speed))}")
    filters.append("loudnorm=I=-16:LRA=11:TP=-1.5")
    args = [
        "ffmpeg",
        "-y",
        "-i",
        str(wav),
        "-af",
        ",".join(filters),
        "-b:a",
        "128k",
    ]
    if metadata:
        for k, v in metadata.items():
            args.extend(["-metadata", f"{k}={v}"])
    args.append(str(mp3))
    return args


async def _master(
    wav: Path,
    job_id: str,
    speed: float = 1.0,
    music_bed: bool | None = None,
    intro_music: Path | str | None = None,
    outro_music: Path | str | None = None,
    turn_durations: list[float] | None = None,
) -> Path:
    if music_bed:
        try:
            from .music import apply_music_beds_to_file, find_music_assets, style_to_jingle_preset

            if not intro_music or not outro_music:
                auto_intro, auto_outro = find_music_assets(MEDIA_DIR)
                intro_music = intro_music or auto_intro
                outro_music = outro_music or auto_outro

            custom_intro = get_setting_safe("music.intro")
            custom_outro = get_setting_safe("music.outro")
            custom_duck = float(get_setting_safe("music.duck_db") or -12.0)
            custom_style = get_setting_safe("music.style") or "auto"

            jingle_pal = style_to_jingle_preset(get_setting_safe("tone.default") or "balanced")
            if custom_style != "auto":
                jingle_pal = custom_style

            if custom_intro == "0":
                intro_music = None
            elif custom_intro and Path(custom_intro).exists():
                intro_music = Path(custom_intro)

            if custom_outro == "0":
                outro_music = None
            elif custom_outro and Path(custom_outro).exists():
                outro_music = Path(custom_outro)

            if turn_durations is None:
                timing_file = wav.parent / f"{wav.stem}.timing.json"
                if timing_file.exists():
                    try:
                        turn_durations = json.loads(timing_file.read_text())
                    except Exception:
                        turn_durations = None

            apply_music_beds_to_file(
                wav_path=wav,
                out_path=wav,
                intro_path=intro_music,
                outro_path=outro_music,
                duck_db=custom_duck,
                turn_durations=turn_durations,
                jingle_palette=jingle_pal,
            )
        except Exception:
            logger.warning("music beds failed for job %s, continuing without music", job_id, exc_info=True)

    # AI disclosure metadata for ID3
    metadata: dict[str, str] = {}
    try:
        from .settings_store import get_setting as _getDisclosure2

        if _getDisclosure2("disclosure.ai_label") == "1":
            try:
                from .jobs import JobStore as _JS

                _store2 = _JS()
                _job2 = _store2.get(job_id)
                _stages = {s["name"]: s for s in _job2.get("stages", [])} if isinstance(_job2.get("stages"), list) else _job2.get("stages", {})
                _script_meta = _stages.get("script", {}).get("meta", {}) if isinstance(_stages.get("script"), dict) else {}
                _voice_meta = _stages.get("voice", {}).get("meta", {}) if isinstance(_stages.get("voice"), dict) else {}
                _llm = _script_meta.get("llm_model") or _script_meta.get("llm_provider") or "AI"
                _tts = _voice_meta.get("engine") or "AI"
                metadata["comment"] = f"AI-generated (script: {_llm}, voices: {_tts})"
                metadata["AI_GENERATED"] = "true"
            except Exception:
                logger.debug("AI disclosure meta lookup failed for job %s", job_id, exc_info=True)
    except Exception:
        logger.warning("AI disclosure tag not written for job %s", job_id, exc_info=True)

    filters: list[str] = []
    mp3 = MEDIA_DIR / f"{job_id}.mp3"
    args = _build_master_ffmpeg_args(wav, mp3, speed=speed, filters=filters, metadata=metadata)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    _, _ = await _communicate_tracked(job_id, proc)
    if proc.returncode != 0 or not mp3.exists():
        raise RuntimeError("Audio processing failed. The audio engine returned an error.")
    return mp3


async def _embed_chapters(mp3: Path, chapters: list[dict], duration: float) -> None:
    """Embed ID3 chapter tags into an MP3 using ffmpeg ffmetadata."""
    if not chapters:
        return
    job_id = mp3.stem
    max_word_offset = max(c["word_offset"] for c in chapters) if chapters else 1
    if max_word_offset == 0:
        max_word_offset = 1

    meta_lines = [";FFMETADATA1"]
    for ch in sorted(chapters, key=lambda c: c["word_offset"]):
        t = (ch["word_offset"] / max_word_offset) * duration
        meta_lines.append("[CHAPTER]")
        meta_lines.append("TIMEBASE=1/1000")
        meta_lines.append(f"START={int(t * 1000)}")
        meta_lines.append(f"END={int(min(t + 1, duration)) * 1000}")
        meta_lines.append(f"title={ch['title']}")

    meta_file = mp3.parent / f"{mp3.stem}_chapters.meta"
    meta_file.write_text("\n".join(meta_lines))

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(mp3), "-i", str(meta_file),
            "-map_metadata", "1", "-codec", "copy",
            str(mp3.with_suffix(".chapters.mp3")),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        _, _ = await _communicate_tracked(job_id, proc)
        if proc.returncode == 0:
            chapters_mp3 = mp3.with_suffix(".chapters.mp3")
            if chapters_mp3.exists():
                mp3.unlink(missing_ok=True)
                chapters_mp3.rename(mp3)
    finally:
        meta_file.unlink(missing_ok=True)


async def _run_research_job(
    store: JobStore, job_id: str, job: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """Research pipeline: seed fetch -> discover -> triage -> sub-fetch -> multi-extract -> script -> voice -> master.

    Reuses the digest infrastructure (multi-source jobs, concurrent bounded fetch,
    per-source sections, chapters) but adds auto-discovery of linked sources.
    """
    seed_url = job["url"]

    # Stage: fetch (seed URL)
    store.set_stage_running(job_id, "fetch")
    yield store.get(job_id)

    fetched_html: str | None = None
    try:
        fetched_html = await fetch_article(seed_url)
    except FetchError as e:
        yield store.fail(job_id, "fetch", str(e))
        return
    store.set_stage_done(job_id, "fetch")

    # Stage: discover
    store.set_stage_running(job_id, "discover", detail="scanning seed page for linked sources")
    yield store.get(job_id)
    candidates: list[str] = []
    try:
        candidates = _discover_links(fetched_html, seed_url)[:5]
        store.add_stage_meta(job_id, "discover", discovered=len(candidates))
    except Exception:
        store.add_stage_meta(job_id, "discover", discovered=0)
    store.set_stage_done(job_id, "discover")
    yield store.get(job_id)

    # Stage: triage
    store.set_stage_running(job_id, "triage", detail=f"LLM scoring {len(candidates)} candidates")
    yield store.get(job_id)
    triaged_urls: list[str] = []
    if candidates:
        try:
            triaged_urls = await _triage_links(seed_url, candidates, llm_chain, max_results=3)
            store.add_stage_meta(job_id, "triage", triaged=len(triaged_urls))
        except Exception:
            triaged_urls = candidates[:1]
    else:
        store.add_stage_meta(job_id, "triage", triaged=0)
    store.set_stage_done(job_id, "triage")
    yield store.get(job_id)

    # Stage: sub-fetch
    store.set_stage_running(job_id, "sub-fetch", detail=f"fetching {len(triaged_urls)} sources")
    yield store.get(job_id)
    sub_sources: list[dict] = []
    if triaged_urls:
        try:
            sub_sources = await _sub_fetch(triaged_urls, max_bytes=50000)
            store.add_stage_meta(job_id, "sub-fetch", fetched=len(sub_sources))
        except Exception:
            store.add_stage_meta(job_id, "sub-fetch", fetched=0)
    store.set_stage_done(job_id, "sub-fetch")
    yield store.get(job_id)

    # Stage: extract (seed + sub-sources)
    store.set_stage_running(job_id, "extract", detail="extracting content from all sources")
    yield store.get(job_id)

    sections: list[dict[str, Any]] = []

    # Seed section
    from .fetcher import extract_title
    seed_title = job.get("title") or "Seed page"
    sections.append({"index": 0, "title": seed_title, "url": seed_url, "body": fetched_html[:50000]})

    # Sub-source sections
    for i, src in enumerate(sub_sources):
        try:
            src_title = (await extract_title(src["body"])) if src["body"] else src["url"]
        except Exception:
            src_title = src["url"]
        sections.append({"index": i + 1, "title": src_title, "url": src["url"], "body": src["body"][:50000]})

    # Store research sources for making-of
    all_urls = [seed_url] + [s["url"] for s in sub_sources]
    store.update(job_id, research_sources=all_urls)

    store.set_stage_done(job_id, "extract")
    yield store.get(job_id)

    # Stage: script (multi-source synthesis via _script_digest)
    store.set_stage_running(job_id, "script", detail="synthesizing research from all sources")
    yield store.get(job_id)

    job_hosts = job.get("hosts", 2)
    try:
        job_hosts = int(job_hosts)
    except Exception:
        job_hosts = 2

    fmt = job.get("format") or "dialog"
    output_lang = job.get("language") or "auto"
    host_names = _host_names(_voice_profile(store, job_id))
    title = job.get("title", "")

    lines, description, chapters = await _script_digest(
        sections,
        style=job.get("style") or "balanced",
        language=output_lang,
        n_hosts=job_hosts,
        explicit=bool(job.get("explicit")),
        fmt=fmt,
        host_names=host_names,
        title=title,
        focus=job.get("focus"),
    )

    if description:
        store.update(job_id, description=description)

    from .script_lint import lint_digest_script
    store.update(
        job_id,
        script=[_stored_line(ln, host_names) for ln in lines],
        chapters=chapters,
    )

    try:
        lint = lint_digest_script(lines, sections)
        if lint.get("warnings"):
            store.add_stage_meta(job_id, "script", lint=lint)
    except Exception:
        logger.warning("digest lint meta write failed for job %s", job_id, exc_info=True)

    # DUE-077: insights for research (combined bodies)
    try:
        combined = "\n\n".join(s.get("body", "") for s in sections)
        await _attach_insights(store, job_id, combined, style=job.get("style") or "balanced", language=output_lang)
    except Exception:
        logger.warning("research insights attach failed for job %s", job_id, exc_info=True)

    store.set_stage_done(job_id, "script")
    yield store.get(job_id)

    # Stage: voice (identical to digest path)
    engine_name = get_setting_safe("tts.engine") or "qwen_tts"
    store.set_stage_running(job_id, "voice", detail=f"{len(lines)} turns via {engine_name}")
    yield store.get(job_id)
    wav = await _voice(
        store, job_id, lines, MEDIA_DIR,
        fmt=fmt, language=output_lang,
        style=job.get("style") or "balanced",
    )
    store.set_stage_done(job_id, "voice")
    yield store.get(job_id)

    # Stage: master (identical to digest path)
    store.set_stage_running(job_id, "master")
    yield store.get(job_id)
    speed, pace_gap = _pacing(store, job_id, job.get("style"))
    music_enabled = _is_music_enabled(store, job_id, job)
    await _master(wav, job_id, speed, music_bed=music_enabled)

    try:
        store.add_stage_meta(job_id, "master", tuning={
            "speed": round(speed, 2),
            "emotion": get_setting_safe("voice.emotion") or "neutral",
            "gap_ms": pace_gap,
            "music_bed": bool(music_enabled),
        })
    except Exception:
        logger.warning("master tuning meta write failed for job %s", job_id, exc_info=True)

    try:
        import subprocess as sp
        probe = await asyncio.to_thread(
            sp.run,
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(MEDIA_DIR / f"{job_id}.mp3")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        duration = float(probe.stdout.strip() or 0)
    except Exception:
        logger.debug("ffprobe duration probe failed for job %s", job_id, exc_info=True)
        duration = 0
    if duration > 0:
        store.update(job_id, audio_seconds=round(duration, 3))

    # DUE-011: embed chapter metadata into the MP3
    if chapters:
        await _embed_chapters(MEDIA_DIR / f"{job_id}.mp3", chapters, duration)

    _apply_script_timings(store, job_id, lines, speed=speed, duration=duration)
    try:
        _finalize_insights_timings(store, job_id)
    except Exception:
        logger.warning("finalize insights timings failed for job %s", job_id, exc_info=True)

    store.set_stage_done(job_id, "master")
    finished = store.finish(job_id)
    # Nostr publish as background task (VOZONDA-NOSTR-2): never blocks or changes job state
    _spawn_background(_publish_job(job_id))
    yield finished


# VOZONDA-TRAY-PRIVACY: an episode with uploaded files and no local script
# model cannot start; the user either starts the local model or allows the
# cloud for this episode.
NO_LOCAL_MODEL_MSG = (
    "this episode has uploaded files and no local model is available; "
    "start the local model or allow the cloud for this episode"
)


async def _run_digest_job(
    store: JobStore, job_id: str, job: dict[str, Any], budget_chars: int | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Digest entry point: the local-only scope, then the shared stages."""
    token = LOCAL_ONLY.set(bool(job.get("local_only")))
    try:
        if job.get("local_only") and not llm_chain():
            yield store.fail(job_id, "fetch", NO_LOCAL_MODEL_MSG)
            return
        async for update in _run_digest_inner(store, job_id, job, budget_chars):
            yield update
    finally:
        LOCAL_ONLY.reset(token)


async def _run_digest_inner(
    store: JobStore, job_id: str, job: dict[str, Any], budget_chars: int | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Digest pipeline: fetch+extract N sources concurrently, then script+voice+master.

    Yields job state updates throughout, same as run_job does for single-source.
    """
    digest_sources: list[str] = job["digest_sources"]
    n = len(digest_sources)
    # the source budget, read once per job (VOZONDA-TRAY-BUDGET)
    job_budget = budget_chars if budget_chars is not None else budget.source_budget_chars()

    def _is_text_source(s: str) -> bool:
        return s.startswith("text:") or not s.startswith(("http://", "https://"))

    def _text_content(s: str) -> str:
        return s[5:].strip() if s.startswith("text:") else s.strip()

    # Separate URL sources from text sources
    url_sources: list[str] = [s for s in digest_sources if not _is_text_source(s)]

    # Stage: fetch (URL sources only, concurrent)
    store.set_stage_running(job_id, "fetch")
    yield store.get(job_id)

    async def _fetch_one(url: str) -> tuple[str, str | None]:
        """Return (url, html_or_None). None signals fetch failure."""
        try:
            html = await fetch_article(url)
            return url, html
        except FetchError:
            return url, None

    # Fetch up to 5 sources concurrently, rest sequential to avoid hammering
    sem = asyncio.Semaphore(5)

    async def _bounded_fetch(url: str) -> tuple[str, str | None]:
        async with sem:
            return await _fetch_one(url)

    fetch_results: list[tuple[str, str | None]] = []
    if url_sources:
        fetch_results = await asyncio.gather(*[_bounded_fetch(u) for u in url_sources])
    store.set_stage_done(job_id, "fetch")

    # Stage: extract (all sources: URL+text)
    store.set_stage_running(job_id, "extract")
    yield store.get(job_id)

    sections: list[dict[str, Any]] = []
    failed_urls: list[str] = []
    # Roles from the source tray in digest_sources order; a job without
    # job_sources rows (legacy) treats every source as main.
    try:
        from . import sources as _sources_mod

        _tray = _sources_mod.job_sources(job)
        if len(_tray) == len(digest_sources):
            _roles = [str(t.get("role") or "main") for t in _tray]
        else:
            _roles = ["main"] * len(digest_sources)
    except Exception:
        logger.debug("digest roles lookup failed, treating all as main", exc_info=True)
        _roles = ["main"] * len(digest_sources)
    fetch_idx = 0
    for i, src in enumerate(digest_sources):
        if _is_text_source(src):
            # Text source: use content directly, no HTTP fetch
            raw_text = _text_content(src)
            # Extract title from first line or default to "Notes"
            lines = raw_text.splitlines()
            first_line = lines[0].strip()[:120] if lines else ""
            title = first_line if first_line else "Notes"
            if len(lines) > 1:
                body = "\n".join(lines[1:]).strip()
            else:
                body = raw_text
            sections.append(
                {"index": len(sections), "position": i, "title": title, "url": f"text:{title}", "body": body, "role": _roles[i]}
            )
        else:
            # URL source: fetch + extract
            if fetch_idx < len(fetch_results):
                url, html = fetch_results[fetch_idx]
                fetch_idx += 1
            else:
                url = src
                html = None
            if html is None:
                failed_urls.append(url)
                continue
            title, body, sec_og = await _extract(url, html=html)
            sections.append({"index": len(sections), "position": i, "title": title, "url": url, "body": body, "role": _roles[i]})
            if sec_og and not sections[0].get("_og"):
                sections[0]["_og"] = sec_og
                sections[0]["_og_url"] = url

    if len(sections) < 2:
        yield store.fail(job_id, "extract", f"too few sources fetched successfully ({len(sections)}/{n}); failed: {failed_urls}")
        return

    # Need-based budget split (VOZONDA-TRAY-ALLOCATION): short sources keep
    # what they need, the rest flows to long ones. A source longer than its
    # share is condensed, not cut (VOZONDA-TRAY-CONDENSE).
    _lengths = [len(s["body"]) for s in sections]
    _sec_roles = [str(s.get("role") or "main") for s in sections]
    _shares = budget.allocate(_lengths, _sec_roles, job_budget)
    _condensed: list[dict[str, Any]] = []
    _truncated: list[dict[str, Any]] = []
    for s, share in zip(sections, _shares):
        total = len(s["body"])
        if total > share:
            _lang = detect_source_lang(s["body"]) or job.get("language") or "auto"
            _new_body, _fallback = await condense_mod.condense_with_flag(s["body"], share, _lang)
            s["body"] = _new_body
            _condensed.append(
                {
                    "position": s["position"],
                    "from_chars": total,
                    "to_chars": len(_new_body),
                    "fallback_cut": bool(_fallback),
                }
            )
            _truncated.append({"position": s["position"], "kept": len(_new_body), "total": total})

    # Digest title: "Digest: <first title> + N more"
    digest_title = f"Digest: {sections[0]['title']}"
    if len(sections) > 1:
        digest_title += f" + {len(sections) - 1} more"
    store.update(job_id, title=digest_title)

    # #155: download og_image or generate template cover for digest
    first_og = sections[0].pop("_og", None)
    if first_og:
        try:
            from .cover import download_og_image
            og_dest = MEDIA_DIR / f"{job_id}-og.png"
            if await download_og_image(first_og, og_dest):
                store.update(job_id, og_image=f"{job_id}-og.png")
        except Exception:
            logger.warning("digest og-image download failed for job %s", job_id, exc_info=True)
    else:
        try:
            from .cover import generate_template_cover
            cover_dest = MEDIA_DIR / f"{job_id}-cover.png"
            style = job.get("style") or "balanced"
            generate_template_cover(digest_title, style=style, output=cover_dest)
            store.update(job_id, og_image=f"{job_id}-cover.png")
        except Exception:
            logger.warning("digest template cover failed for job %s", job_id, exc_info=True)

    src_lang = detect_source_lang(sections[0]["body"])
    if src_lang:
        store.add_stage_meta(job_id, "extract", source_lang=src_lang)
    if failed_urls:
        store.add_stage_meta(job_id, "extract", fetch_failures=failed_urls)
    if _condensed:
        store.add_stage_meta(job_id, "extract", condensed=_condensed)
    if _truncated:
        store.add_stage_meta(job_id, "extract", truncated=_truncated)
    store.set_stage_done(job_id, "extract")
    yield store.get(job_id)

    # Compose default for 2+ sources (maintainer, 2026-09-23): ONE conversation that
    # connects the sources; the per-source digest stays for watchlists/feeds
    # and as the explicit "digest" show.
    if job.get("combine"):
        n = len(sections)
        _combo_lengths = [len(sec["body"]) for sec in sections]
        _combo_roles = [str(sec.get("role") or "main") for sec in sections]
        _combo_shares = budget.allocate(_combo_lengths, _combo_roles, job_budget)

        def _block(sec: dict[str, Any], share: int) -> str:
            pos = sec.get("position", sec["index"])
            # "SOURCE k of n" is the long-standing shape (tests assert it); the
            # bracket number is the citation index a script line carries in "src"
            return f"SOURCE {pos + 1} of {len(digest_sources)} [{pos + 1}]: {sec['title']} ({sec['url']})\n{sec['body'][:share]}"

        _mains = [(sec, sh) for sec, sh in zip(sections, _combo_shares) if str(sec.get("role") or "main") != "context"]
        _ctxs = [(sec, sh) for sec, sh in zip(sections, _combo_shares) if str(sec.get("role") or "main") == "context"]
        combined = (
            f"The listener picked these {n} sources together. Discuss them as ONE conversation: "
            "connect, compare and contrast them, and say which source a claim comes from. "
            "Build the episode on the main material below. "
            "Use the background only where it helps, never as the structure of the episode.\n\n"
            "MAIN MATERIAL the episode is built on:\n"
            + "\n\n".join(_block(sec, sh) for sec, sh in _mains)
        )
        if _ctxs:
            combined += "\n\nBACKGROUND, use only where it helps:\n" + "\n\n".join(
                _block(sec, sh) for sec, sh in _ctxs
            )
        combo_title = job.get("title") or " + ".join(str(sec["title"]) for sec in sections)[:120]
        store.update(job_id, title=combo_title)
        async for updated in _run_from_body(store, job_id, store.get(job_id), combined, combo_title, src_lang, job_budget,
                                            n_sources=n):
            yield updated
        return

    # Stage: script
    store.set_stage_running(job_id, "script", detail="streaming from llm")
    yield store.get(job_id)

    job_hosts = job.get("hosts", 2)
    try:
        job_hosts = int(job_hosts)
    except Exception:
        job_hosts = 2

    fmt = job.get("format") or "dialog"
    output_lang = job.get("language") or "auto"

    host_names = _host_names(_voice_profile(store, job_id))
    title = job.get("title", "")
    lines, description, chapters = await _script_digest(
        sections,
        style=job.get("style") or "balanced",
        language=output_lang,
        n_hosts=job_hosts,
        explicit=bool(job.get("explicit")),
        fmt=fmt,
        host_names=host_names,
        title=title,
        focus=job.get("focus"),
        budget_chars=job_budget,
    )

    if description:
        store.update(job_id, description=description)

    # Attach chapters and store script
    from .script_lint import lint_digest_script
    store.update(
        job_id,
        script=[_stored_line(ln, host_names) for ln in lines],
        chapters=chapters,
    )

    # Run digest lint (pass digest=True for digest-specific checks)
    try:
        lint = lint_digest_script(lines, sections)
        if lint.get("warnings"):
            store.add_stage_meta(job_id, "script", lint=lint)
    except Exception:
        logger.warning("digest lint meta write failed for job %s", job_id, exc_info=True)

    # DUE-077: extract insights from combined digest bodies
    try:
        combined_body = "\n\n".join(s.get("body", "") for s in sections)
        await _attach_insights(store, job_id, combined_body, style=job.get("style") or "balanced", language=output_lang)
    except Exception:
        logger.warning("digest insights attach failed for job %s", job_id, exc_info=True)

    store.set_stage_done(job_id, "script")
    yield store.get(job_id)

    # Stage: voice (identical to single-source path)
    engine_name = get_setting_safe("tts.engine") or "qwen_tts"
    store.set_stage_running(job_id, "voice", detail=f"{len(lines)} turns via {engine_name}")
    yield store.get(job_id)
    wav = await _voice(
        store,
        job_id,
        lines,
        MEDIA_DIR,
        fmt=fmt,
        language=output_lang,
        style=job.get("style") or "balanced",
    )
    store.set_stage_done(job_id, "voice")
    yield store.get(job_id)

    # Stage: master
    store.set_stage_running(job_id, "master")
    yield store.get(job_id)
    speed, pace_gap = _pacing(store, job_id, job.get("style"))
    music_enabled = _is_music_enabled(store, job_id, job)
    await _master(wav, job_id, speed, music_bed=music_enabled)
    try:
        store.add_stage_meta(job_id, "master", tuning={
            "speed": round(speed, 2),
            "emotion": get_setting_safe("voice.emotion") or "neutral",
            "gap_ms": pace_gap,
            "music_bed": bool(music_enabled),
        })
    except Exception:
        logger.warning("digest master tuning meta write failed for job %s", job_id, exc_info=True)

    try:
        import subprocess as sp
        probe = await asyncio.to_thread(
            sp.run,
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(MEDIA_DIR / f"{job_id}.mp3")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        duration = float(probe.stdout.strip() or 0)
    except Exception:
        logger.debug("digest ffprobe duration probe failed for job %s", job_id, exc_info=True)
        duration = 0

    # DUE-011: embed chapter metadata into the MP3
    if chapters:
        await _embed_chapters(MEDIA_DIR / f"{job_id}.mp3", chapters, duration)

    _apply_script_timings(store, job_id, lines, speed=speed, duration=duration)
    try:
        _finalize_insights_timings(store, job_id)
    except Exception:
        logger.warning("digest finalize insights timings failed for job %s", job_id, exc_info=True)

    store.set_stage_done(job_id, "master")
    finished = store.finish(job_id)
    # Nostr publish as background task (VOZONDA-NOSTR-2): never blocks or changes job state
    _spawn_background(_publish_job(job_id))
    yield finished


def _apply_script_timings(
    store: JobStore,
    job_id: str,
    lines: list[dict[str, Any]],
    speed: float = 1.0,
    duration: float = 0.0,
) -> None:
    """Apply ground-truth turn timestamps from renderer timing sidecar or fallback to proportional interpolation."""
    if not lines:
        return
    host_names = _host_names(_voice_profile(store, job_id))
    timing_file = MEDIA_DIR / f"{job_id}.timing.json"

    if timing_file.exists():
        try:
            durations = json.loads(timing_file.read_text())
            if isinstance(durations, list) and len(durations) == len(lines):
                t_acc = 0.0
                timed = []
                sp_factor = max(0.1, speed)
                for ln, dur in zip(lines, durations):
                    timed.append({**_stored_line(ln, host_names), "t0": round(t_acc, 2)})
                    t_acc += float(dur) / sp_factor
                store.update(job_id, script=timed)
                return
        except Exception:
            logger.debug("timing sidecar read failed for job %s, using estimate", job_id, exc_info=True)

    # Fallback to proportional character approximation if timing data unavailable
    if duration > 0:
        total_chars = sum(len(ln.get("text", "")) for ln in lines) or 1
        t_acc = 0.0
        timed = []
        for ln in lines:
            timed.append({**_stored_line(ln, host_names), "t0": round(t_acc, 1)})
            t_acc += duration * len(ln.get("text", "")) / total_chars
        store.update(job_id, script=timed)


async def run_job(store: JobStore, job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Single entry point: the local-only scope, then the shared stages.

    LOCAL_ONLY stays set for the whole run, so every stage that calls
    llm_chain (script, insights, translation) uses the local model only.
    """
    job = store.get(job_id)
    token = LOCAL_ONLY.set(bool(job.get("local_only")))
    try:
        if job.get("local_only") and not llm_chain():
            yield store.fail(job_id, "fetch", NO_LOCAL_MODEL_MSG)
            return
        async for update in _run_job_inner(store, job_id, job):
            yield update
    finally:
        LOCAL_ONLY.reset(token)


async def _run_job_inner(store: JobStore, job_id: str, job: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    # the source budget, read once per job (VOZONDA-TRAY-BUDGET)
    job_budget = budget.source_budget_chars()

    from .doctor import blocking_problem

    # Billing support (DUE-067): charge user if access token provided
    user_id = job.get("user_id")
    provider = job.get("provider", "qwen")
    job_type = "digest" if job.get("digest") else "standard"
    charge_id = None

    if user_id and env("ENABLE_BILLING", "false").lower() == "true":
        try:
            from .billing import charge_job

            charge = charge_job(job_id, user_id, provider, job_type)
            charge_id = charge["charge_id"]
            store.update(job_id, charge_id=charge_id)
            print(f"Billing: charged {charge['amount_sats']} sats for job {job_id}")
        except Exception as e:
            yield store.fail(job_id, "fetch", f"billing error: {e}")
            return

    problem = await asyncio.to_thread(blocking_problem)
    if problem:
        # Refund if billing was charged
        if charge_id:
            try:
                from .billing import refund_charge

                refund_charge(job_id)
                print(f"Billing: refunded job {job_id}")
            except Exception:
                logger.exception("billing refund failed for job %s", job_id)
        yield store.fail(job_id, "fetch", problem)
        return

    # -- digest branch (#122) ------------------------------------------------
    if job.get("digest") and job.get("digest_sources"):
        async for update in _run_digest_job(store, job_id, job, job_budget):
            yield update
        return
    # -- research mode branch (#135) -----------------------------------------
    if job.get("research_mode"):
        async for update in _run_research_job(store, job_id, job):
            yield update
        return
    # -- single-source branch (unchanged) ------------------------------------

    store.set_stage_running(job_id, "fetch")
    yield store.get(job_id)
    fetched_html: str | None = None
    src_lang: str | None = None
    if _looks_like_text(job["url"]):
        # pasted plain text: no network at all
        store.set_stage_done(job_id, "fetch")
        store.set_stage_running(job_id, "extract")
        yield store.get(job_id)
        title, body = "Pasted text", job["url"].strip()
        first_line = body.strip().split("\n")[0].strip()
        if first_line and len(first_line) > 3:
            title = first_line[:120]
        else:
            title = body.strip()[:120]
        store.update(job_id, title=title)
        store.set_stage_done(job_id, "extract")
        yield store.get(job_id)
    else:
        fetch_url = job["url"].strip()
        if not re.match(r"^[a-z][a-z0-9+.-]*://", fetch_url, re.IGNORECASE):
            # bare domain like example.com/x: user meant a link
            fetch_url = f"https://{fetch_url}"
        try:
            fetched_html = await fetch_article(fetch_url)
        except FetchError as e:
            yield store.fail(job_id, "fetch", str(e))
            return
        store.set_stage_done(job_id, "fetch")

        store.set_stage_running(job_id, "extract")
        yield store.get(job_id)
        research_depth = "direct"
        try:
            from .settings_store import get_setting

            research_depth = get_setting("source.research_depth") or "direct"
        except Exception:
            logger.debug("research depth setting lookup failed for job %s", job_id, exc_info=True)
        title, body, og_image = await _extract(
            job["url"], html=fetched_html, depth=research_depth, max_chars=job_budget
        )
        store.update(job_id, title=title)
        # #155: download og_image or generate template cover
        if og_image:
            try:
                from .cover import download_og_image
                og_dest = MEDIA_DIR / f"{job_id}-og.png"
                if await download_og_image(og_image, og_dest):
                    store.update(job_id, og_image=f"{job_id}-og.png")
            except Exception:
                logger.warning("og-image download failed for job %s", job_id, exc_info=True)
        else:
            try:
                from .cover import generate_template_cover
                cover_dest = MEDIA_DIR / f"{job_id}-cover.png"
                style = job.get("style") or "balanced"
                generate_template_cover(title, style=style, output=cover_dest)
                store.update(job_id, og_image=f"{job_id}-cover.png")
            except Exception:
                logger.warning("template cover failed for job %s", job_id, exc_info=True)
        src_lang = detect_source_lang(body)
        if src_lang:
            store.add_stage_meta(job_id, "extract", source_lang=src_lang)
        store.set_stage_done(job_id, "extract")
        yield store.get(job_id)

    async for updated in _run_from_body(store, job_id, job, body, title, src_lang):
        yield updated


def _record_wpm(engine: str, language: str | None, measured: float) -> None:
    """Record a measured WPM value as a rolling average.

    Writes to tts.wpm.<engine>.<lang> when language is known, else to
    tts.wpm.<engine>. Keeps the old key untouched when a language key is written.
    """
    from .settings_store import get_setting as _get_setting
    from .settings_store import set_setting as _set_setting

    lang_key = f"tts.wpm.{engine}.{language.lower()}" if language else None
    engine_key = f"tts.wpm.{engine}"

    if lang_key:
        old_raw = _get_setting(lang_key)
        new_wpm = rolling_wpm(float(old_raw), measured) if old_raw else round(measured, 2)
        _set_setting(lang_key, f"{new_wpm:g}")
    else:
        old_raw = _get_setting(engine_key)
        new_wpm = rolling_wpm(float(old_raw), measured) if old_raw else round(measured, 2)
        _set_setting(engine_key, f"{new_wpm:g}")


async def _finish_from_script(
    store: JobStore,
    job_id: str,
    job: dict[str, Any],
    lines: list[dict[str, Any]],
    fmt: str,
    target_minutes: float | None,
    length_meta: dict[str, Any],
    output_lang: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Voice, master, timings and length calibration for a finished script.

    Shared by run_job and resume_after_review so a reviewed script goes
    through exactly the same tail as an unreviewed one.
    """
    engine_name = get_setting_safe("tts.engine") or "qwen_tts"
    if fmt == "narration":
        store.set_stage_running(job_id, "voice", detail=f"{len(lines)} paragraphs via {engine_name}")
    else:
        store.set_stage_running(job_id, "voice", detail=f"{len(lines)} turns via {engine_name}")
    yield store.get(job_id)
    wav = await _voice(
        store,
        job_id,
        lines,
        MEDIA_DIR,
        fmt=job.get("format") or "dialog",
        language=job.get("language") or "auto",
        style=job.get("style") or "balanced",
    )
    store.set_stage_done(job_id, "voice")
    yield store.get(job_id)

    store.set_stage_running(job_id, "master")
    yield store.get(job_id)
    speed, pace_gap = _pacing(store, job_id, job.get("style"))
    music_enabled = _is_music_enabled(store, job_id, job)
    await _master(wav, job_id, speed, music_bed=music_enabled)
    try:
        store.add_stage_meta(job_id, "master", tuning={
            "speed": round(speed, 2),
            "emotion": get_setting_safe("voice.emotion") or "neutral",
            "gap_ms": pace_gap,
            "music_bed": bool(music_enabled),
        })
    except Exception:
        logger.warning("finish master tuning meta write failed for job %s", job_id, exc_info=True)

    try:
        import subprocess as sp

        probe = await asyncio.to_thread(
            sp.run,
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(MEDIA_DIR / f"{job_id}.mp3")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        duration = float(probe.stdout.strip() or 0)
    except Exception:
        logger.debug("finish ffprobe duration probe failed for job %s", job_id, exc_info=True)
        duration = 0

    _apply_script_timings(store, job_id, lines, speed=speed, duration=duration)
    # DUE-077: finalize takeaway timestamps now that t0 is known
    try:
        _finalize_insights_timings(store, job_id)
    except Exception:
        logger.warning("finish finalize insights timings failed for job %s", job_id, exc_info=True)

    # VOZONDA-LEN-1: record actual minutes and calibrate the engine's wpm as a
    # rolling average so the next estimate for this engine is more precise.
    if target_minutes is not None and duration > 0:
        try:
            actual_minutes = round(duration / 60.0, 2)
            planned = length_meta.get("planned_words")
            actual = length_meta.get("actual_words")
            master_len_meta: dict[str, Any] = {"actual_minutes": actual_minutes}
            if planned and actual is not None:
                master_len_meta["deviation_percent"] = round(deviation_percent(actual, planned), 1)
            store.add_stage_meta(job_id, "master", **master_len_meta)
            if actual:
                minutes = duration / 60.0
                if minutes > 0:
                    measured = actual / minutes
                    # Use the episode's output language for per-language calibration
                    lang = output_lang if output_lang and output_lang != "auto" else None
                    _record_wpm(engine_name, lang, measured)
        except Exception as exc:  # never fail a finished episode over calibration, but say so
            print(f"wpm calibration for {engine_name} not saved: {exc}")

    store.set_stage_done(job_id, "master")

    finished = store.finish(job_id)
    # Nostr publish as background task (VOZONDA-NOSTR-2): never blocks or changes job state
    _spawn_background(_publish_job(job_id))
    yield finished


def _lines_from_stored(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stored script lines (speaker, text, optional display name) back to lines."""
    out = []
    for ln in stored or []:
        text = str(ln.get("text", "")).strip()
        if text:
            out.append({"speaker": str(ln.get("speaker", "A")), "text": text})
    return out


async def resume_after_review(store: JobStore, job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Continue a job paused in awaiting_review with its (possibly edited) script."""
    job = store.get(job_id)
    lines = _lines_from_stored(job.get("script") or [])
    if not lines:
        raise RuntimeError("the reviewed script is empty")
    fmt = job.get("format") or "dialog"
    target_minutes = job.get("target_minutes")
    script_meta = next((s.get("meta") or {} for s in job.get("stages") or [] if s.get("name") == "script"), {})
    length_meta = {k: script_meta.get(k) for k in ("planned_words", "actual_words") if script_meta.get(k) is not None}
    output_lang = job.get("language")
    yield store.update(job_id, state="running")
    async for updated in _finish_from_script(store, job_id, job, lines, fmt, target_minutes, length_meta, output_lang):
        yield updated


async def _run_from_body(
    store: JobStore,
    job_id: str,
    job: dict[str, Any],
    body: str,
    title: str,
    src_lang: str | None,
    budget_chars: int | None = None,
    n_sources: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Script, optional review pause, voice and master for an extracted text.

    Shared by single-source jobs and multi-source jobs that are ONE
    conversation (combine), so both get length control, focus and review.
    """
    cap = budget_chars if budget_chars is not None else budget.source_budget_chars()
    if len(body) > cap:
        _from_chars = len(body)
        _lang = src_lang or detect_source_lang(body) or job.get("language") or "auto"
        body, _fallback_cut = await condense_mod.condense_with_flag(body, cap, _lang)
        store.update(job_id, title=job.get("title") or title)
        if not any(
            s["name"] == "extract" and (s.get("meta") or {}).get("source_lang")
            for s in store.get(job_id).get("stages", [])
        ):
            src_lang = detect_source_lang(body)
            if src_lang:
                store.add_stage_meta(job_id, "extract", source_lang=src_lang)
        store.add_stage_meta(
            job_id,
            "extract",
            condensed=[
                {
                    "position": 0,
                    "from_chars": _from_chars,
                    "to_chars": len(body),
                    "fallback_cut": bool(_fallback_cut),
                }
            ],
            truncated_to=len(body),
        )

    store.set_stage_running(job_id, "script", detail="streaming from llm")
    yield store.get(job_id)

    # hosts: per-job if present (watchlist or DUE-066/DUE-062), else global setting
    job_hosts = job.get("hosts")
    if job_hosts is None:
        try:
            job_hosts = int(str(get_setting_safe("voice.dialog.count") or "2"))
        except Exception:
            job_hosts = 2
    else:
        try:
            job_hosts = int(job_hosts)
        except Exception:
            job_hosts = 2

    fmt = job.get("format") or "dialog"
    output_lang = job.get("language") or "auto"

    # VOZONDA-LEN-1: resolve the target length and cap it by what the source
    # carries; a thin source is never padded with invented material.
    target_minutes: float | None = None
    capped_minutes: float | None = None
    cap_reason: str | None = None
    length_meta: dict[str, Any] = {}
    if fmt != "narration":
        raw_tm = job.get("target_minutes")
        if raw_tm is None:
            try:
                raw_tm = float(get_setting_safe("script.default_minutes") or DEFAULT_MINUTES)
            except Exception:
                raw_tm = DEFAULT_MINUTES
        target_minutes, was_capped = cap_target_minutes(float(raw_tm), len(body.split()))
        if was_capped:
            capped_minutes = target_minutes
            cap_reason = f"source supports about {round(target_minutes)} minutes"

    # DUE-078 / #100: narration path - skip dialog generation
    host_names = _host_names(_voice_profile(store, job_id))
    # Use the passed title parameter (updated during extract) rather than
    # re-reading from the potentially stale job dict.
    if fmt == "narration":
        lines, description = await _narration_script(
            body, output_lang, src_lang, store, job_id,
            host_names=host_names, title=title,
        )
    else:
        lines, description = await _script(
            body,
            job.get("style") or "balanced",
            fmt,
            job.get("tone") or "neutral",
            output_lang,
            n_hosts=job_hosts,
            explicit=bool(job.get("explicit")),
            host_names=host_names,
            title=title,
            tts_engine=job.get("tts_engine") or "",
            emotion=job.get("emotion") or _voice_profile(store, job_id).get("emotion") or "",
            target_minutes=target_minutes,
            length_meta=length_meta,
            focus=job.get("focus"),
            n_sources=n_sources,
        )
    if description:
        store.update(job_id, description=description)
    if fmt == "narration":
        for ln in lines:
            ln["speaker"] = "Narrator"
    store.update(job_id, script=[
        _stored_line(ln, host_names) for ln in lines
    ])
    store.set_stage_done(job_id, "script")

    # Store original source title and generate descriptive episode title from script
    try:
        store.add_stage_meta(job_id, "script", source_title=title)
    except Exception:
        logger.warning("source title meta write failed for job %s", job_id, exc_info=True)
    new_title = await _generate_episode_title(store, job_id, lines, title, llm_chain)
    if new_title:
        store.update(job_id, title=new_title)
        title = new_title

    from .script_lint import lint_script

    llm_prov = job.get("provider") or "qwen"
    llm_model = "qwen3.6-35b" if llm_prov == "qwen" else ("mistral-small-4" if llm_prov == "mistral" else llm_prov)
    try:
        store.add_stage_meta(job_id, "script", lint=lint_script(lines), llm_provider=llm_prov, llm_model=llm_model)
    except Exception:
        store.add_stage_meta(job_id, "script", lint=lint_script(lines))
    # VOZONDA-LEN-1: record planned vs actual length on the script stage
    if target_minutes is not None:
        len_stage_meta: dict[str, Any] = {
            "target_minutes": target_minutes,
            "planned_words": length_meta.get("planned_words"),
            "actual_words": length_meta.get("actual_words"),
        }
        if capped_minutes is not None:
            len_stage_meta["capped_minutes"] = capped_minutes
            len_stage_meta["cap_reason"] = cap_reason
        if length_meta.get("correction"):
            len_stage_meta["correction"] = length_meta["correction"]
        # the rhythm pass leaves its findings here; without them a bench run could
        # not tell whether the pass ran, helped or was discarded (2026-10-02)
        for key in ("rhythm_problems", "rhythm_problems_after", "rhythm_correction_kept", "rhythm_profile"):
            if key in length_meta:
                len_stage_meta[key] = length_meta[key]
        try:
            store.add_stage_meta(job_id, "script", **len_stage_meta)
        except Exception:
            logger.warning("length meta write failed for job %s", job_id, exc_info=True)
    # DUE-077: extract Blinkist-grade insights with source grounding (warn-only)
    try:
        await _attach_insights(store, job_id, body, style=job.get("style") or "balanced", language=output_lang)
    except Exception:
        logger.warning("insights attach failed for job %s", job_id, exc_info=True)
    yield store.get(job_id)

    # UX phase 2: stop after the script when the listener wants to review it;
    # resume_after_review() continues with exactly the same tail.
    if job.get("review_script") and not job.get("script_approved"):
        yield store.update(job_id, state="awaiting_review")
        return

    async for updated in _finish_from_script(store, job_id, job, lines, fmt, target_minutes, length_meta, output_lang):
        yield updated
