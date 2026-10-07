"""Credentials in settings never leave the server (audit 2026-09-22)."""

from fastapi.testclient import TestClient

from vozonda_api import settings_store
from vozonda_api.main import app


def test_get_settings_masks_api_key_and_mask_write_keeps_it():
    settings_store.set_setting("llm.api_key", "sk-real-secret")
    client = TestClient(app)
    body = client.get("/settings").json()
    assert body["settings"]["llm.api_key"] == settings_store.SECRET_MASK
    assert "sk-real-secret" not in client.get("/settings").text
    # the UI writes the mask back on save: the real key must survive
    settings_store.set_setting("llm.api_key", settings_store.SECRET_MASK)
    assert settings_store.get_setting("llm.api_key") == "sk-real-secret"
    settings_store.set_setting("llm.api_key", "")


def test_unset_key_is_not_masked():
    settings_store.set_setting("llm.api_key", "")
    assert TestClient(app).get("/settings").json()["settings"].get("llm.api_key", "") == ""
