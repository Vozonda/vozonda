"""VOZONDA-CUSTOM-STYLES-API: users pick a rhythm type and name their own roles."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

PAYLOAD: dict[str, Any] = {
    "id": "custom_mock",
    "name": "Mock",
    "doc": "A mock style for tests.",
    "role_a": "a curious host who asks short questions",
    "role_b": "an expert who explains with vivid examples",
    "tone": "warm and curious",
    "rhythm_type": "host_expert",
}


def _make(role: str, words: int) -> dict[str, str]:
    return {"speaker": role, "text": " ".join(["word"] * words)}


def _balanced_turns() -> list[dict[str, str]]:
    """Twelve turns with a host/expert word split, so no role repair is needed."""
    turns: list[dict[str, str]] = []
    for _ in range(6):
        turns.append(_make("A", 15))
        turns.append(_make("B", 30))
    return turns


def _run_script(style: str, prompt_box: dict) -> tuple[list[dict], str]:
    from vozonda_api import pipeline

    async def fake_script_call(*, prompt: str, **kw: Any) -> tuple[list[dict], str]:
        prompt_box["prompt"] = prompt
        return _balanced_turns(), "Test episode description."

    import pytest

    monkey = pytest.MonkeyPatch()
    monkey.setattr(pipeline, "script_call", fake_script_call)
    try:
        return asyncio.run(
            pipeline._script(
                "source text " * 300,
                style=style,
                fmt="dialog",
                tone="neutral",
                language="en",
                n_hosts=2,
                explicit=False,
                host_names=None,
                title="",
                tts_engine="qwen_tts",
                emotion="neutral",
                target_minutes=None,
                length_meta={},
                focus=None,
            )
        )
    finally:
        monkey.undo()


def test_crud(jobs_db, api_client):
    client = api_client
    assert client.get("/styles/custom").json() == {"styles": []}

    r = client.post("/styles/custom", json=dict(PAYLOAD))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "custom_mock"
    assert body["rhythm_type"] == "host_expert"

    r = client.post("/styles/custom", json=dict(PAYLOAD))
    assert r.status_code == 422

    listed = client.get("/styles/custom").json()["styles"]
    assert [s["id"] for s in listed] == ["custom_mock"]

    r = client.put("/styles/custom/custom_mock", json={"name": "Mocked", "tone": "dry"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Mocked"
    assert r.json()["tone"] == "dry"

    r = client.delete("/styles/custom/custom_mock")
    assert r.status_code == 200
    assert r.json() == {"deleted": "custom_mock"}
    assert client.get("/styles/custom").json() == {"styles": []}

    assert client.delete("/styles/custom/custom_mock").status_code == 404
    assert client.put("/styles/custom/custom_mock", json={"name": "x"}).status_code == 404


def test_validation(jobs_db, api_client):
    client = api_client

    def post(**kw: Any):
        payload = dict(PAYLOAD)
        payload.update(kw)
        return client.post("/styles/custom", json=payload)

    assert post(id="").status_code == 422
    assert post(id="plain").status_code == 422
    assert post(id="custom-A!").status_code == 422
    assert post(id="custom_a").status_code == 422
    assert post(id="custom_" + "a" * 31).status_code == 422
    assert post(rhythm_type="nope").status_code == 422
    assert post(name="").status_code == 422
    assert post(name="n" * 41).status_code == 422
    assert post(doc="d" * 121).status_code == 422
    assert post(role_a="").status_code == 422
    assert post(role_a="r" * 401).status_code == 422
    assert post(role_b="").status_code == 422
    assert post(tone="t" * 301).status_code == 422
    assert "rhythm_type" in post(rhythm_type="nope").text

    assert client.post("/styles/custom", json=dict(PAYLOAD)).status_code == 200
    bad = client.put("/styles/custom/custom_mock", json={"rhythm_type": "nope"})
    assert bad.status_code == 422
    bad = client.put("/styles/custom/custom_mock", json={"name": "n" * 41})
    assert bad.status_code == 422
    client.delete("/styles/custom/custom_mock")


def test_builtin_id_rejected(jobs_db, api_client):
    client = api_client
    r = client.post("/styles/custom", json={**PAYLOAD, "id": "balanced"})
    assert r.status_code == 422
    assert "built-in" in r.text
    assert client.put("/styles/custom/balanced", json={"name": "x"}).status_code == 422
    assert client.delete("/styles/custom/balanced").status_code == 422
    assert client.get("/styles/custom").json() == {"styles": []}


def test_meta_lists_custom_style(jobs_db, api_client):
    client = api_client
    assert client.post("/styles/custom", json=dict(PAYLOAD)).status_code == 200
    meta = client.get("/meta").json()
    assert "custom_mock" in meta["styles"]
    assert meta["style_docs"]["custom_mock"] == "A mock style for tests."
    entry = next(m for m in meta["style_meta"] if m["id"] == "custom_mock")
    assert entry["group"] == "custom"
    assert entry["hosts"] == "AB"
    client.delete("/styles/custom/custom_mock")
    assert "custom_mock" not in client.get("/meta").json()["styles"]


def test_script_prompt_uses_roles_and_rhythm_contract(jobs_db, api_client):
    from vozonda_api.rhythm import rhythm_profile_for
    from vozonda_api.script_contract import contract_block

    client = api_client
    assert client.post("/styles/custom", json=dict(PAYLOAD)).status_code == 200

    prompt_box: dict[str, str] = {}
    lines, _desc = _run_script("custom_mock", prompt_box)
    assert len(lines) >= 4
    prompt = prompt_box["prompt"]
    assert "a curious host who asks short questions" in prompt
    assert "an expert who explains with vivid examples" in prompt
    assert "warm and curious" in prompt
    expected = contract_block(rhythm_profile_for("host_expert"))
    assert prompt.startswith(expected)
    assert "STYLE RHYTHM" in prompt
    client.delete("/styles/custom/custom_mock")


def test_deleted_style_falls_back_to_balanced(jobs_db, api_client, caplog):
    from vozonda_api.rhythm import PROFILES
    from vozonda_api.script_contract import contract_block

    client = api_client
    assert client.post("/styles/custom", json=dict(PAYLOAD)).status_code == 200
    assert client.delete("/styles/custom/custom_mock").status_code == 200

    prompt_box: dict[str, str] = {}
    with caplog.at_level(logging.WARNING, logger="vozonda_api.pipeline"):
        _run_script("custom_mock", prompt_box)
    assert any("falling back to balanced" in rec.message for rec in caplog.records)
    assert prompt_box["prompt"].startswith(contract_block(PROFILES["balanced"]))


def test_every_rhythm_type_yields_a_valid_contract():
    from vozonda_api.rhythm import (
        RHYTHM_DESCRIPTIONS,
        RHYTHM_TYPES,
        rhythm_profile_for,
    )
    from vozonda_api.script_contract import contract_block

    assert sorted(RHYTHM_TYPES) == [
        "calm",
        "host_expert",
        "interrogator",
        "narrator_listener",
        "peer",
    ]
    assert sorted(RHYTHM_DESCRIPTIONS) == sorted(RHYTHM_TYPES)
    assert all(len(d.split()) >= 3 for d in RHYTHM_DESCRIPTIONS.values())
    for rhythm_type in RHYTHM_TYPES:
        profile = rhythm_profile_for(rhythm_type)
        block = contract_block(profile)
        assert block.startswith("SUCCESS CRITERIA")
        assert len(block) > 50
    calm = rhythm_profile_for("calm")
    assert calm.hard_max == 25
    assert "No turn is longer than 25 words." in contract_block(calm)
    interrogator = rhythm_profile_for("interrogator")
    assert interrogator.trend.get("B") == (1.0, 0.25)

    # builders borrow numbers from the named built-in profile, without sharing it
    from vozonda_api.rhythm import PROFILES, peer_profile

    peer = peer_profile()
    assert peer is not PROFILES["debate"]
    assert peer.speakers["A"].share == PROFILES["debate"].speakers["A"].share
    assert peer.rules == PROFILES["debate"].rules
