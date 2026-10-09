"""Audio transcription and punctuation restoration.

Transcribes audio files (mp3, m4a, wav, ogg, opus) and podcast enclosures
using faster-whisper, then restores punctuation with the local LLM punctuate
pattern with word-for-word validation.

Privacy: audio bytes are never written to disk in test paths; only the
transcribed text is kept.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

import httpx

from .env import env

logger = logging.getLogger(__name__)

# Audio extensions that the source tray accepts.
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".ogg", ".opus")
# Maximum audio duration we will transcribe (seconds).
MAX_AUDIO_DURATION_S = 3600  # 1 hour

# Whisper model from env (default 'base').
WHISPER_MODEL = env("WHISPER_MODEL", "base")

# Punctuation chunk size (approximate words per chunk).
PUNCTUATION_CHUNK_WORDS = 300
# local servers (vLLM, Ollama) batch parallel requests; 4 keeps a small machine responsive
PUNCTUATION_CONCURRENCY = int(env("PUNCTUATION_CONCURRENCY", "4"))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9\u00c0-\u024f]+", text.lower())


# ISO base media brands for M4A/AAC files.
_ISO_AUDIO_BRANDS = (b"M4A ", b"M4B ", b"mp42", b"isom", b"dash")


def detect_audio(data: bytes, ctype: str = "", ext: str = "") -> bool:
    """Return True if the content looks like an audio file.

    Recognised formats and their magic bytes::

        MP3:  ID3v2 tag (b'ID3') or an MPEG audio frame sync (11 set bits)
        WAV:  RIFF header with b'WAVE' at offset 8
        Ogg:  page signature b'OggS' (Vorbis, Opus)
        M4A:  ISO base media 'ftyp' box at offset 4, brand M4A , M4B , mp42, isom or dash at offset 8
        FLAC: b'fLaC'

    The ctype and ext arguments keep working as before: a content-type
    starting with ``audio/`` or a matching extension returns True without
    inspecting the bytes.
    """
    if ctype and any(ctype.startswith(p) for p in ("audio/",)):
        return True
    if ext and ext.lower() in AUDIO_EXTS:
        return True
    if not data:
        return False
    # ID3v2 tag (MP3 with metadata)
    if data[:3] == b"ID3":
        return True
    # MPEG audio frame sync (bare MP3 stream)
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return True
    # WAV
    if data[:4] == b"RIFF" and len(data) > 8 and data[8:12] == b"WAVE":
        return True
    # Ogg (Vorbis, Opus)
    if data[:4] == b"OggS":
        return True
    # ISO base media file (M4A / AAC)
    # the first 4 bytes are the box size, the box type follows at offset 4
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _ISO_AUDIO_BRANDS:
        return True
    # FLAC
    return data[:4] == b"fLaC"


async def transcribe_audio(
    file_path: str | None = None,
    file_bytes: bytes | None = None,
) -> tuple[str, str, int, str | None]:
    """Transcribe an audio file using faster-whisper.

    Args:
        file_path: Path to the audio file.
        file_bytes: Raw audio bytes (file_path takes precedence).

    Returns:
        (title, text, duration_seconds, language) or raises SourceError.
    """
    from .sources import SourceError

    tmp: tempfile.NamedTemporaryFile | None = None
    actual_path: str = ""

    try:
        if file_bytes is not None:
            tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
                suffix=".audio", delete=False
            )
            tmp.write(file_bytes)
            tmp.close()
            actual_path = tmp.name
        elif file_path:
            actual_path = file_path
        else:
            raise SourceError("unreadable", "no audio data provided")

        duration = _get_audio_duration(actual_path)
        if duration > MAX_AUDIO_DURATION_S:
            raise SourceError(
                "too_large",
                f"audio is {int(duration)}s (max {MAX_AUDIO_DURATION_S}s). "
                "Split the file or provide a transcript.",
            )

        result = await asyncio.to_thread(_run_whisper_sync, actual_path, whisper_timeout(duration))
        text = result.get("text", "").strip()
        if not text:
            raise SourceError("too_short", "the audio has no detectable speech")

        lang = result.get("language")
        title = f"Audio source ({int(duration)}s)"
        return title, text, int(duration), lang

    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("unreadable", f"transcription failed: {exc}") from exc
    finally:
        if tmp:
            with contextlib.suppress(OSError):
                os.unlink(actual_path)


def _get_audio_duration(file_path: str) -> float:
    """Get the duration of an audio file using ffprobe (if available).

    Returns duration in seconds. Unknown duration is 0.
    """
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return 0.0


def whisper_timeout(duration_s: float) -> float:
    """Seconds the Whisper subprocess may take: model load plus the audio at real time.

    A fixed 300 s cut off long files on an ordinary CPU (an hour of audio with the base
    model can take longer than five minutes). Unknown length gets the full one-hour budget.
    """
    length = duration_s if duration_s > 0 else MAX_AUDIO_DURATION_S
    return max(300.0, 120.0 + length)


def _run_whisper_sync(file_path: str, timeout: float = 300.0) -> dict[str, Any]:
    """Run the Whisper transcription (synchronous).

    Called via asyncio.to_thread from the async context.
    In tests this is monkey-patched to avoid needing torch/faster-whisper.
    """
    import subprocess

    from .sources import SourceError

    try:
        res = subprocess.run(
            [
                sys.executable,
                "-c",
                _WHISPER_SCRIPT_TEMPLATE,
                file_path,
                WHISPER_MODEL,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if res.returncode != 0:
            err = (res.stderr or "").strip()
            raise SourceError("unreadable", f"transcription failed: {err}")
        return json.loads(res.stdout)
    except FileNotFoundError:
        raise SourceError("unreadable", "whisper is not available")
    except subprocess.TimeoutExpired:
        raise SourceError("unreadable", f"transcription took longer than {int(timeout)} s")


# Template for the inline Whisper script that runs in the renderer's venv.
# The renderer venv has faster-whisper installed; the API venv may not.
# The file path is passed as the first argument (sys.argv[1]).
# The model name is passed as the second argument (sys.argv[2]).
_WHISPER_SCRIPT_TEMPLATE = """\
import json, sys, os
try:
    from faster_whisper import WhisperModel
    model = WhisperModel(sys.argv[2], device="cpu", compute_type="int8")
    # vad_filter skips silence: faster, and no invented text in quiet passages
    segments, info = model.transcribe(sys.argv[1], language=None, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    lang = info.language or "en"
    print(json.dumps({"text": text, "language": lang}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)
"""


async def restore_punctuation(text: str) -> tuple[str, bool]:
    """Restore punctuation to raw whisper output with word-for-word validation.

    Splits the text into chunks of about 300 words at word boundaries,
    restores each chunk with its own request, and checks each chunk word
    for word. A chunk that fails the check keeps its raw text; the others
    keep their restored text. The result is the chunks joined with a space.

    Each punctuation request sends "chat_template_kwargs": {"enable_thinking": false}
    like the script provider and uses httpx.AsyncClient (no blocking call in the
    event loop); max_tokens fits one chunk.

    Args:
        text: Raw transcribed text (may be unpunctuated).

    Returns:
        (punctuated_text, validated).
    """
    if not text or not text.strip():
        return text, True

    # Split original into words for chunking
    words = re.findall(r"\S+", text)
    if not words:
        return text, True

    # Split into chunks of ~PUNCTUATION_CHUNK_WORDS words at word boundaries
    chunks: list[str] = []
    for i in range(0, len(words), PUNCTUATION_CHUNK_WORDS):
        chunk_words = words[i : i + PUNCTUATION_CHUNK_WORDS]
        chunks.append(" ".join(chunk_words))

    # Chunks run in parallel (PUNCTUATION_CONCURRENCY at a time); gather keeps their order.
    sem = asyncio.Semaphore(PUNCTUATION_CONCURRENCY)

    async def one(chunk: str) -> tuple[str, bool]:
        original_words = _words(chunk)
        if not original_words:
            return chunk, True
        try:
            async with sem:
                punctuated = await _llm_punctuate_async(chunk)
        except Exception as exc:
            logger.warning("punctuation restore failed for chunk: %s", exc, exc_info=True)
            return chunk, False
        # word for word: punctuation and capitals may change, the words and their order may not
        if not punctuated or _words(punctuated) != original_words:
            logger.debug("punctuation restore changed the words, keeping the raw chunk")
            return chunk, False
        return punctuated.strip(), True

    results = await asyncio.gather(*(one(c) for c in chunks))
    restored_chunks = [text for text, _ in results]
    all_validated = all(ok for _, ok in results)

    return " ".join(restored_chunks), all_validated


async def _llm_punctuate_async(text: str) -> str:
    """Send text to the local LLM for punctuation restoration (async).

    Uses httpx.AsyncClient with chat_template_kwargs to disable thinking.
    max_tokens is sized for a single chunk (~300 words).
    """
    from .providers import LLM_BASE, LLM_MODEL

    prompt = (
        "Restore punctuation and capitalization to the following text.\n"
        "Do not add, remove, or reorder any words.\n"
        "Output ONLY the punctuated text, nothing else.\n\n"
        f"{text}"
    )

    # ~300 words * ~5 chars/word + prompt overhead = ~2000 tokens, use 4096 for safety
    max_tokens = 4096

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{LLM_BASE.rstrip('/')}/chat/completions",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data["choices"][0]["message"]["content"].strip()
        if not result:
            raise ValueError("punctuation model returned empty text")
        return result


# ---------------------------------------------------------------------------
# Existing transcript extraction
# ---------------------------------------------------------------------------

# Regex patterns for podcast transcript tags.
_PODCAST_TRANSCRIPT_RE = re.compile(
    r"<podcast:transcript[^>]*>\s*(.*?)\s*</podcast:transcript>",
    re.DOTALL,
)


def extract_existing_transcript(source_text: str | None) -> str | None:
    """Extract an existing transcript from source text (RSS / podcast).

    Some sources include a <podcast:transcript> tag with a pre-existing
    transcript.  Extract and return it without re-transcribing.

    Args:
        source_text: The full source text to search.

    Returns:
        The extracted transcript text, or None if no transcript found.
    """
    if not source_text:
        return None

    match = _PODCAST_TRANSCRIPT_RE.search(source_text)
    if match:
        return match.group(1).strip()

    return None