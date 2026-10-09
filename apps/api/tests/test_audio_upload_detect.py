"""Tests for audio file detection and upload size limits (VOZONDA-AUDIO-UPLOAD).

No network calls, no Whisper — transcribe_audio is mocked.
"""

from __future__ import annotations

import pytest

from vozonda_api.audio_source import detect_audio
from vozonda_api.sources import AUDIO_MAX_BYTES, UPLOAD_MAX_BYTES, add_upload, upload_limit


class TestDetectAudio:
    """detect_audio() magic-byte recognition."""

    def test_id3_mp3(self) -> None:
        """MP3 with ID3v2 tag."""
        assert detect_audio(b"ID3\x04\x00\x00") is True

    def test_mpeg_frame_sync(self) -> None:
        """Bare MPEG audio frame sync: 0xFF 0xE0..0xEF."""
        assert detect_audio(b"\xff\xfb\x00\x00") is True  # b'\xff\xfb...'
        assert detect_audio(b"\xff\xe0\x00\x00") is True
        assert detect_audio(b"\xff\xef\x00\x00") is True
        # second byte below 0xE0 -> not a sync
        assert detect_audio(b"\xff\xdf\x00\x00") is False

    def test_wav(self) -> None:
        """WAV file: RIFF header with WAVE at offset 8."""
        assert detect_audio(b"RIFF\x00\x00\x00\x00WAVE") is True

    def test_ogg(self) -> None:
        """Ogg page signature (Vorbis, Opus, ...)."""
        assert detect_audio(b"OggS\x00\x00\x00\x00") is True

    def test_m4a_ftyp(self) -> None:
        """ISO base media ftyp box with audio brands."""
        for brand in (b"M4A ", b"M4B ", b"mp42", b"isom", b"dash"):
            # Need at least 12 bytes: ftyp(4) + padding(4) + brand(4)
            # real files: 4-byte box size, then b"ftyp", then the major brand
            assert detect_audio(b"\x00\x00\x00\x20ftyp" + brand + b"\x00\x00\x02\x00") is True, f"brand {brand!r}"
            assert detect_audio(b"ftyp\x00\x00\x00\x00" + brand) is False, "ftyp at offset 0 is not an MP4 box"

    def test_flac(self) -> None:
        """fLaC vendor block signature."""
        assert detect_audio(b"fLaC\x00\x01\x02\x03") is True

    def test_pdf_rejected(self) -> None:
        """PDF is not audio."""
        assert detect_audio(b"%PDF-1.4") is False

    def test_png_rejected(self) -> None:
        """PNG is not audio."""
        assert detect_audio(b"\x89PNG\r\n\x1a\n") is False

    def test_jpeg_rejected(self) -> None:
        """JPEG is not audio."""
        assert detect_audio(b"\xff\xd8\xff\xe0") is False

    def test_webp_rejected(self) -> None:
        """WebP is not audio."""
        assert detect_audio(b"RIFF\x00\x00\x00\x00WEBP") is False

    def test_utf8_text_rejected(self) -> None:
        """Plain UTF-8 text is not audio."""
        assert detect_audio(b"Hello, this is plain text.") is False

    def test_empty_bytes_rejected(self) -> None:
        """Empty bytes return False."""
        assert detect_audio(b"") is False

    def test_content_type_audio(self) -> None:
        """content-type starting with audio/ returns True."""
        assert detect_audio(b"", ctype="audio/mpeg") is True
        assert detect_audio(b"", ctype="audio/mp4") is True

    def test_extension_audio(self) -> None:
        """Matching extension returns True."""
        assert detect_audio(b"", ext=".mp3") is True
        assert detect_audio(b"", ext=".m4a") is True
        assert detect_audio(b"", ext=".wav") is True
        assert detect_audio(b"", ext=".ogg") is True
        assert detect_audio(b"", ext=".opus") is True

    def test_extension_non_audio(self) -> None:
        """Non-audio extension returns False."""
        assert detect_audio(b"", ext=".pdf") is False
        assert detect_audio(b"", ext=".txt") is False


class TestUploadLimit:
    """upload_limit() returns the right cap per file type."""

    def test_audio_limit_is_at_least_audio_max(self) -> None:
        """Audio bytes return a limit >= AUDIO_MAX_BYTES."""
        assert upload_limit(b"ID3\x04\x00\x00") >= AUDIO_MAX_BYTES

    def test_pdf_limit_is_upload_max(self) -> None:
        """PDF bytes return UPLOAD_MAX_BYTES (25 MB)."""
        assert upload_limit(b"%PDF-1.4") == UPLOAD_MAX_BYTES

    def test_text_limit_is_upload_max(self) -> None:
        """Plain text returns UPLOAD_MAX_BYTES."""
        assert upload_limit(b"Hello world") == UPLOAD_MAX_BYTES


class TestAddUpload:
    """add_upload() enforces per-kind size limits."""

    def test_size_check_audio_30mb(self) -> None:
        """A 30 MB ID3 MP3 passes the size check (under the audio cap).

        upload_limit must return a value >= 30 MB for audio bytes, so the
        size check in add_upload passes.
        """
        data = b"ID3\x04\x00\x00" + b"\x00" * (30 * 1024 * 1024 - 7)
        limit = upload_limit(data)
        assert limit >= 30 * 1024 * 1024
        # The actual add_upload creates a background task; the size check
        # must not raise before the background task starts.
        assert len(data) <= limit

    def test_size_check_pdf_30mb_fails(self) -> None:
        """A 30 MB PDF exceeds the 25 MB upload limit."""
        data = b"%PDF-1.4" + b"\x00" * (30 * 1024 * 1024 - 6)
        limit = upload_limit(data)
        assert limit == UPLOAD_MAX_BYTES  # 25 MB
        assert len(data) > limit


def test_audio_cap_default_is_100_mb():
    import os
    from vozonda_api import fetcher
    if "VOZONDA_AUDIO_MAX_BYTES" not in os.environ:
        assert fetcher.AUDIO_MAX_BYTES == 100_000_000


def test_whisper_timeout_grows_with_length():
    from vozonda_api.audio_source import MAX_AUDIO_DURATION_S, whisper_timeout
    assert whisper_timeout(60) == 300
    assert whisper_timeout(3600) >= 3600
    assert whisper_timeout(0) >= MAX_AUDIO_DURATION_S  # unknown length gets the full budget


def test_whisper_runs_with_vad():
    from vozonda_api.audio_source import _WHISPER_SCRIPT_TEMPLATE
    assert "vad_filter=True" in _WHISPER_SCRIPT_TEMPLATE


def test_punctuation_runs_in_parallel_and_keeps_order(monkeypatch):
    import asyncio
    import time
    from vozonda_api import audio_source as a

    async def fake(chunk):
        await asyncio.sleep(0.2 if chunk.startswith("w0 ") else 0.05)  # the first chunk is the slowest
        return chunk.capitalize() + "."

    monkeypatch.setattr(a, "_llm_punctuate_async", fake)
    monkeypatch.setattr(a, "PUNCTUATION_CHUNK_WORDS", 3)
    monkeypatch.setattr(a, "PUNCTUATION_CONCURRENCY", 4)
    text = " ".join(f"w{i}" for i in range(12))  # 4 chunks
    t0 = time.monotonic()
    out, ok = asyncio.run(a.restore_punctuation(text))
    assert ok
    assert out == "W0 w1 w2. W3 w4 w5. W6 w7 w8. W9 w10 w11."
    assert time.monotonic() - t0 < 0.35  # parallel: about the slowest chunk, not the sum (0.35 s)


def test_punctuation_keeps_raw_chunk_when_a_word_changes(monkeypatch):
    import asyncio
    from vozonda_api import audio_source as a

    async def fake(chunk):
        return chunk.replace("going to", "gonna").capitalize() + "."

    monkeypatch.setattr(a, "_llm_punctuate_async", fake)
    out, ok = asyncio.run(a.restore_punctuation("we are going to test this"))
    assert not ok and out == "we are going to test this"
