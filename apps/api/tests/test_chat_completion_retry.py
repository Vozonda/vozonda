"""The script writer retries transient HTTP errors before giving up on a provider.

2026-09-28: two Kimi K3 (NVIDIA NIM trial) jobs failed on a single
'504 Gateway Timeout' because _chat_completion only retried JSON drift.
"""

import asyncio

import httpx
import pytest

from vozonda_api import pipeline

PROV = {"name": "kimi_nim", "base": "https://nim.example/v1", "model": "m", "key": "k"}
OK = {"choices": [{"message": {"content": "hello"}}]}


def _patch_client(monkeypatch, responses: list):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item, json=OK if item == 200 else {"error": "x"})

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline.httpx, "AsyncClient", factory)
    monkeypatch.setattr(pipeline, "_llm_retry_sleep", lambda s: asyncio.sleep(0))
    return calls


def test_gateway_errors_and_rate_limits_are_retried(monkeypatch):
    calls = _patch_client(monkeypatch, [504, 429, 200])
    assert asyncio.run(pipeline._chat_completion(PROV, "hi")) == "hello"
    assert len(calls) == 3


def test_connection_errors_are_retried(monkeypatch):
    calls = _patch_client(monkeypatch, [httpx.ConnectError("down"), 200])
    assert asyncio.run(pipeline._chat_completion(PROV, "hi")) == "hello"
    assert len(calls) == 2


def test_client_errors_fail_at_once(monkeypatch):
    calls = _patch_client(monkeypatch, [401, 200])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(pipeline._chat_completion(PROV, "hi"))
    assert len(calls) == 1


def test_a_provider_that_stays_down_gives_up(monkeypatch):
    calls = _patch_client(monkeypatch, [503])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(pipeline._chat_completion(PROV, "hi"))
    assert len(calls) == 1 + len(pipeline.LLM_RETRY_BACKOFF_S)
