"""POST /jobs accepts a language name and stores its code.

2026-09-28: a job created with language "German" got a German script (the
prompt takes the name as is) but the English cast and English voices, which
key on the code; Magpie read German with an American accent.

F-1: the mapping is pure (JobIn validator), so the five name variants are
proven at unit level with no HTTP, no DB and no background pipeline. One
integration test posts once to prove the validator is wired to POST /jobs.
"""


def test_language_names_map_to_codes():
    from vozonda_api.main import JobIn

    body = {"text": "Ein kurzer Text. " * 40, "review_script": True}
    for given, code in (("German", "de"), ("german", "de"), ("DE", "de"), ("English", "en"), ("auto", "auto")):
        assert JobIn(**{**body, "language": given}).language == code


def test_language_name_posted_once_becomes_code(api_client, monkeypatch):
    import vozonda_api.main as main_mod

    async def _noop(job_id, runner=None):
        return None

    monkeypatch.setattr(main_mod, "_run", _noop)
    r = api_client.post(
        "/jobs", json={"text": "Ein kurzer Text. " * 40, "language": "German", "review_script": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["language"] == "de"


def test_unknown_language_is_rejected_not_cast_as_english(api_client):
    r = api_client.post(
        "/jobs", json={"text": "Ein kurzer Text. " * 40, "language": "Klingon", "review_script": True}
    )
    assert r.status_code == 422
    assert "language" in r.text
