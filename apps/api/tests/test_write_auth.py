"""Write auth is open only for the local single-user default (audit 2026-09-22)."""

import pytest
from fastapi.testclient import TestClient

from vozonda_api.main import app

PEAKS = {"peaks": [0.1, 0.5]}


@pytest.fixture
def client(monkeypatch):
    for var in ("VOZONDA_TOKEN", "VOZONDA_ENABLE_BILLING", "VOZONDA_HOST"):
        monkeypatch.delenv(var, raising=False)
    return TestClient(app)


def test_local_default_stays_open(client):
    assert client.put("/audio/wa-open.peaks.json", json=PEAKS).status_code == 200


def test_fails_closed_without_token_when_billing_is_on(client, monkeypatch):
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
    r = client.put("/audio/wa-billing.peaks.json", json=PEAKS)
    assert r.status_code == 503 and "VOZONDA_TOKEN" in r.text


def test_fails_closed_without_token_when_bound_beyond_loopback(client, monkeypatch):
    monkeypatch.setenv("VOZONDA_HOST", "0.0.0.0")
    assert client.put("/audio/wa-exposed.peaks.json", json=PEAKS).status_code == 503


def test_token_is_checked(client, monkeypatch):
    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    assert client.put("/audio/wa-tok.peaks.json", json=PEAKS).status_code == 401
    assert client.put("/audio/wa-tok.peaks.json", json=PEAKS,
                      headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.put("/audio/wa-tok.peaks.json", json=PEAKS,
                      headers={"Authorization": "Bearer s3cret"}).status_code == 200


@pytest.mark.parametrize("method,path", [
    ("post", "/shows"), ("put", "/shows/1"), ("delete", "/shows/1"),
    ("delete", "/auth/nostr/identities/" + "a" * 64),
])
def test_previously_open_write_routes_now_require_the_token(client, monkeypatch, method, path):
    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    r = getattr(client, method)(path, **({"json": {}} if method in ("post", "put") else {}))
    assert r.status_code == 401, (method, path, r.status_code)


def test_probe_with_a_foreign_base_url_needs_the_token(client, monkeypatch):
    monkeypatch.setenv("VOZONDA_TOKEN", "s3cret")
    r = client.get("/llm/probe", params={"engine": "custom", "custom_base": "http://attacker.example/v1"})
    assert r.status_code == 401
