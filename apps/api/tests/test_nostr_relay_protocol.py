"""Relay conversation as NIP-01 / NIP-42 define it (coordinator review of NOSTR-1, 2026-10-02).

The first client read exactly one frame after EVENT: a NOTICE before the OK counted as a
failure, an OK for another event id counted for ours, and after a NIP-42 AUTH the OK of
the AUTH event was reported as 'published' although the EVENT was never accepted. Its
publish() also used asyncio.run, which raises inside the API's running event loop.
NIP-01: relays answer ["OK", <event id>, true|false, <message>] and may send
["NOTICE", <message>] at any time; NIP-42: ["AUTH", <challenge>] and an OK false whose
message starts with "auth-required:". vozonda has no user key here, so such relays are
skipped with that reason."""

import asyncio
import json

import pytest

from vozonda_api import nostr_relay

EVENT = {"id": "e" * 64, "pubkey": "p" * 64, "kind": 54, "created_at": 1, "tags": [], "content": "", "sig": "s" * 128}


class FakeWS:
    def __init__(self, frames, delay=0.0):
        self.frames = list(frames)
        self.sent: list = []
        self.delay = delay
        self.closed = False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        if not self.frames:
            await asyncio.sleep(3600)
        await asyncio.sleep(self.delay)
        return json.dumps(self.frames.pop(0))

    async def close(self):
        self.closed = True


def _connect_with(per_relay):
    async def connect(url, **kw):
        ws = per_relay[url]
        if isinstance(ws, Exception):
            raise ws
        return ws
    return connect


def _run(monkeypatch, per_relay, timeout=1.0):
    monkeypatch.setattr(nostr_relay, "_connect", _connect_with(per_relay))
    return {r.relay: r for r in asyncio.run(nostr_relay.publish_async(EVENT, list(per_relay), timeout=timeout))}


def test_notice_before_ok_is_not_a_failure(monkeypatch):
    res = _run(monkeypatch, {"wss://a": FakeWS([["NOTICE", "hello"], ["OK", EVENT["id"], True, ""]])})
    assert res["wss://a"].ok is True


def test_ok_for_another_event_is_ignored(monkeypatch):
    other = "f" * 64
    res = _run(monkeypatch, {"wss://a": FakeWS([["OK", other, True, ""], ["OK", EVENT["id"], False, "blocked: spam"]])})
    assert res["wss://a"].ok is False and "blocked" in res["wss://a"].reason


def test_auth_challenge_then_auth_required_is_skipped_not_published(monkeypatch):
    ws = FakeWS([["AUTH", "challenge-1"], ["OK", EVENT["id"], False, "auth-required: sign in"]])
    res = _run(monkeypatch, {"wss://a": ws})
    assert res["wss://a"].ok is None and "auth required" in res["wss://a"].reason
    assert all(frame[0] == "EVENT" for frame in ws.sent), "no AUTH event is sent without a user key"


def test_auth_challenge_alone_times_out_as_skipped(monkeypatch):
    res = _run(monkeypatch, {"wss://a": FakeWS([["AUTH", "challenge-1"]])}, timeout=0.2)
    assert res["wss://a"].ok is None and "auth required" in res["wss://a"].reason


def test_event_frame_and_close(monkeypatch):
    ws = FakeWS([["OK", EVENT["id"], True, ""]])
    _run(monkeypatch, {"wss://a": ws})
    assert ws.sent == [["EVENT", EVENT]] and ws.closed


def test_one_relay_failing_never_affects_the_others(monkeypatch):
    res = _run(monkeypatch, {
        "wss://ok": FakeWS([["OK", EVENT["id"], True, ""]]),
        "wss://down": OSError("refused"),
        "wss://slow": FakeWS([], delay=0),
    }, timeout=0.2)
    assert res["wss://ok"].ok is True
    assert res["wss://down"].ok is None and "connect" in res["wss://down"].reason
    assert res["wss://slow"].ok is None and "timeout" in res["wss://slow"].reason


def test_publish_async_runs_inside_a_running_loop(monkeypatch):
    monkeypatch.setattr(nostr_relay, "_connect", _connect_with({"wss://a": FakeWS([["OK", EVENT["id"], True, ""]])}))

    async def caller():  # what the orchestrator does from the API's event loop
        return await nostr_relay.publish_async(EVENT, ["wss://a"])

    assert asyncio.run(caller())[0].ok is True


def test_sync_publish_refuses_a_running_loop_with_a_clear_error(monkeypatch):
    async def caller():
        with pytest.raises(RuntimeError, match="publish_async"):
            nostr_relay.publish(EVENT, ["wss://a"])

    asyncio.run(caller())
