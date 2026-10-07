"""Tests for the script provider (streaming + non-streaming)."""

import asyncio
import json
from unittest.mock import MagicMock, patch
from inspect import signature

import pytest

from vozonda_api.providers.script import (
    _repair_json,
    _parse_first_json_array,
    script_call,
    script_call_nonstreaming,
)


class _StreamingLine:
    """Mock line iterator for streaming responses.

    Returns str to match httpx's aiter_lines() contract: it yields
    decoded strings, the caller must not call .decode() (live bug
    bitcoin-0815, fixed 2026-08-25).
    """

    def __init__(self, lines):
        self._iter = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _StreamContext:
    """Mock async context manager for httpx.stream()."""

    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def aiter_lines(self):
        return _StreamingLine(self.lines)

    def raise_for_status(self):
        pass


class _HttpClient:
    """Mock httpx.AsyncClient for streaming."""

    def __init__(self, stream_ctx=None):
        self._stream_ctx = stream_ctx

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def stream(self, method, url, json=None, headers=None):
        return _StreamContext(self._stream_ctx)


def _make_stream_chunk(content):
    """Build an OpenAI streaming data line from content."""
    payload = {"choices": [{"delta": {"content": content}}]}
    return "data: " + json.dumps(payload)


def _build_mock_client(lines):
    """Build a mock httpx.AsyncClient that streams the given lines."""
    return _HttpClient(stream_ctx=lines)


def _make_nonstream_mock(json_return):
    """Build a mock httpx.AsyncClient for non-streaming tests."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=json_return)

    async def mock_aenter(self):
        return mock_client

    async def mock_aexit(self, *a):
        pass

    async def mock_post(*args, **kwargs):
        return mock_resp

    mock_client = MagicMock()
    mock_client.__aenter__ = mock_aenter
    mock_client.__aexit__ = mock_aexit
    mock_client.post = mock_post
    return mock_client


def test_script_call_extracts_json_array_from_stream() -> None:
    """Streaming: JSON array extracted from accumulated content."""
    lines = [
        _make_stream_chunk('[{"speaker":"A","text":"hi"}'),
        _make_stream_chunk(',{"speaker":"B","text":"bye"}]'),
        _make_stream_chunk(""),
        _make_stream_chunk("\nDESCRIPTION: test desc"),
        "data: [DONE]",
    ]
    mock_client = _build_mock_client(lines)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result, desc = asyncio.run(script_call(
            prompt="test prompt",
            base="http://127.0.0.1:30001/v1",
            model="test-model",
        ))
    assert len(result) == 2
    assert result[0]["speaker"] == "A"
    assert result[0]["text"] == "hi"
    assert result[1]["speaker"] == "B"
    assert result[1]["text"] == "bye"
    assert desc == "test desc"


def test_script_call_handles_no_space_data_prefix() -> None:
    """Streaming: some proxies send 'data:{...}' without space."""
    lines = [
        _make_stream_chunk('[{"speaker":"A","text":"hello"}]'),
        "data:[DONE]",
    ]
    mock_client = _build_mock_client(lines)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result, _ = asyncio.run(script_call(
            prompt="test prompt",
            base="http://127.0.0.1:30001/v1",
            model="test-model",
        ))
    assert len(result) == 1
    assert result[0]["speaker"] == "A"
    assert result[0]["text"] == "hello"


def test_script_call_raises_on_no_json() -> None:
    """Streaming: raises ValueError when no JSON array found."""
    lines = [
        _make_stream_chunk("no json here"),
        "data: [DONE]",
    ]
    mock_client = _build_mock_client(lines)
    with patch("httpx.AsyncClient", return_value=mock_client), pytest.raises(ValueError, match="no JSON array in output"):
            asyncio.run(script_call(
                prompt="test prompt",
                base="http://127.0.0.1:30001/v1",
                model="test-model",
            ))


def test_script_call_strips_thinking_tags() -> None:
    """Streaming: thinking tags are stripped before JSON extraction."""
    lines = [
        _make_stream_chunk("<thinking>ok</thinking>"),
        _make_stream_chunk('[{"speaker":"A","text":"clean"}]'),
        "data: [DONE]",
    ]
    mock_client = _build_mock_client(lines)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result, _ = asyncio.run(script_call(
            prompt="test prompt",
            base="http://127.0.0.1:30001/v1",
            model="test-model",
        ))
    assert len(result) == 1
    assert result[0]["text"] == "clean"


def test_script_call_nonstreaming_basic() -> None:
    """Non-streaming: single response parsed correctly."""
    mock_client = _make_nonstream_mock({
        "choices": [{"message": {
            "content": '[{"speaker":"A","text":"hi"}]\nDESCRIPTION: test'
        }}]
    })
    with patch("httpx.AsyncClient", return_value=mock_client):
        result, desc = asyncio.run(script_call_nonstreaming(
            prompt="test prompt",
            base="http://127.0.0.1:30001/v1",
            model="test-model",
        ))
    assert len(result) == 1
    assert result[0]["speaker"] == "A"
    assert result[0]["text"] == "hi"
    assert desc == "test"


def test_script_call_nonstreaming_raises_on_no_json() -> None:
    """Non-streaming: raises ValueError when no JSON array found."""
    mock_client = _make_nonstream_mock({
        "choices": [{"message": {"content": "no json at all"}}]
    })
    with patch("httpx.AsyncClient", return_value=mock_client), pytest.raises(ValueError, match="no JSON array in output"):
            asyncio.run(script_call_nonstreaming(
                prompt="test prompt",
                base="http://127.0.0.1:30001/v1",
                model="test-model",
            ))


def test_script_call_nonstreaming_strips_thinking_tags() -> None:
    """Non-streaming: thinking tags stripped before JSON extraction."""
    mock_client = _make_nonstream_mock({
        "choices": [{"message": {
            "content": "<thinking>blah</thinking>\n[{\"speaker\":\"A\",\"text\":\"clean\"}]"
        }}]
    })
    with patch("httpx.AsyncClient", return_value=mock_client):
        result, _ = asyncio.run(script_call_nonstreaming(
            prompt="test prompt",
            base="http://127.0.0.1:30001/v1",
            model="test-model",
        ))
    assert len(result) == 1
    assert result[0]["text"] == "clean"


def test_script_call_description_truncated_at_280() -> None:
    """Streaming: description truncated to 280 chars."""
    long_desc = "x" * 400
    lines = [
        _make_stream_chunk('[{"speaker":"A","text":"hi"}]'),
        _make_stream_chunk(f"\nDESCRIPTION: {long_desc}"),
        "data: [DONE]",
    ]
    mock_client = _build_mock_client(lines)
    with patch("httpx.AsyncClient", return_value=mock_client):
        _, desc = asyncio.run(script_call(
            prompt="test prompt",
            base="http://127.0.0.1:30001/v1",
            model="test-model",
        ))
    assert len(desc) == 280


def test_script_call_handles_empty_chunks() -> None:
    """Streaming: empty lines and malformed JSON chunks are skipped."""
    lines = [
        "",
        "data: ",
        "data: not-json-at-all",
        _make_stream_chunk('[{"speaker":"A","text":"ok"}]'),
        "data: [DONE]",
    ]
    mock_client = _build_mock_client(lines)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result, _ = asyncio.run(script_call(
            prompt="test prompt",
            base="http://127.0.0.1:30001/v1",
            model="test-model",
        ))
    assert len(result) == 1
    assert result[0]["text"] == "ok"


# ---- JSON repair & truncated output tests ----


def test_repair_unclosed_bracket():
    assert _repair_json('[{"a":1') == '[{"a":1}]'


def test_repair_unclosed_string():
    assert _repair_json('[{"a":"foo') == '[{"a":"foo"}]'


def test_repair_unclosed_object_in_array():
    inp = '[{"speaker":"A","text":"hello'
    out = _repair_json(inp)
    assert out == '[{"speaker":"A","text":"hello"}]'


def test_repair_trailing_comma():
    assert _repair_json('[{"a":1,}]') == '[{"a":1}]'


def test_repair_multiple_unclosed():
    inp = '[{"a":1,"b":[2,"unterminated'
    out = _repair_json(inp)
    assert out == '[{"a":1,"b":[2,"unterminated"]}]'


def test_repair_empty_is_noop():
    assert _repair_json('[1,2,3]') == '[1,2,3]'


def test_repair_bad_structure():
    # Cannot fix arbitrary bad structures
    assert _repair_json("][") is None


def test_parse_first_json_array_truncated_repaired():
    """Truncated JSON (token cutoff) is repaired; the half-written last turn is dropped
    (2026-10-02: a script ending mid-sentence was voiced), complete turns stay."""
    content = '[{"speaker":"A","text":"A complete turn."},{"speaker":"B","text":"long article content goes'
    result, offset = _parse_first_json_array(content)
    assert len(result) == 1
    assert result[0]["speaker"] == "A"
    assert result[0]["text"] == "A complete turn."


def test_parse_first_json_array_complete():
    """Complete JSON is parsed without repair."""
    content = '[{"speaker":"A","text":"hi"},{"speaker":"B","text":"bye"}] extra'
    result, offset = _parse_first_json_array(content)
    assert len(result) == 2


def test_script_call_max_tokens_default_16384():
    """Default max_tokens should be 16384 to account for thinking budget."""
    sig = signature(script_call)
    assert sig.parameters["max_tokens"].default == 16384
    sig2 = signature(script_call_nonstreaming)
    assert sig2.parameters["max_tokens"].default == 16384


def test_parse_first_json_array_with_section_tags():
    """Bracketed tags like [SECTION:0:Title] before JSON array do not break extraction."""
    content = '[SECTION:0:Story 1] Intro text\n[{"speaker":"A","text":"hi"}]\nDESCRIPTION: desc'
    result, offset = _parse_first_json_array(content)
    assert len(result) == 1
    assert result[0]["text"] == "hi"


def test_parse_first_json_array_with_code_fences():
    """Markdown code fences around JSON array do not break extraction."""
    content = '```json\n[{"speaker":"A","text":"fenced"}]\n```\nDESCRIPTION: desc'
    result, offset = _parse_first_json_array(content)
    assert len(result) == 1
    assert result[0]["text"] == "fenced"


def test_script_call_strips_thinking_tags_with_truncated_json():
    """Streaming: thinking tags stripped, truncated JSON repaired."""
    lines = [
        _make_stream_chunk("<thinking>lots of reasoning about the article</thinking>"),
        _make_stream_chunk('[{"speaker":"A","text":"Done here."},{"speaker":"B","text":"cut off mi'),
        "data: [DONE]",
    ]
    mock_client = _build_mock_client(lines)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result, _ = asyncio.run(script_call(
            prompt="test prompt",
            base="http://127.0.0.1:30001/v1",
            model="test-model",
        ))
    assert len(result) == 1
    assert result[0]["text"] == "Done here.", "the half-written turn is dropped"
