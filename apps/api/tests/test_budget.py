"""Source tray budget (VOZONDA-TRAY-BUDGET, docs/plan-multisource-tray.md).

The budget comes from the script model's context window with a settings
override; the tray limit comes from settings. No hardcoded 60_000.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vozonda_api import budget, main
from vozonda_api import settings_store as ss
from vozonda_api import sources as S
from vozonda_api.jobs import JobStore

_CTXT = 262144
COMPUTED = int((_CTXT - 6000 - 16384) * 3.5)
FALLBACK = int((32768 - 6000 - 16384) * 3.5)

SRC = Path(__file__).resolve().parent.parent / "src" / "vozonda_api"


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


@pytest.fixture
def clean(jobs_db):
    budget.clear_cache()
    yield
    with ss._conn() as c:
        c.execute("DELETE FROM settings WHERE key IN ('source.max_chars', 'source.max_sources')")
    budget.clear_cache()


@pytest.fixture
def api(jobs_db, monkeypatch):
    S.init_sources_db()
    monkeypatch.setattr(main, "store", JobStore())

    async def no_run(job_id, runner=None):
        return None

    monkeypatch.setattr(main, "_run", no_run)
    return TestClient(main.app)


def _fake_chain(monkeypatch, base="http://127.0.0.1:9/v1", model="fake-model"):
    from vozonda_api import providers

    monkeypatch.setattr(
        providers, "llm_chain", lambda: [{"name": "local", "base": base, "model": model}]
    )


def _fake_models(monkeypatch, max_model_len, model="fake-model"):
    import httpx

    monkeypatch.setattr(
        httpx, "get", lambda url, timeout=None: _Resp({"data": [{"id": model, "max_model_len": max_model_len}]})
    )


def _broken_probe(monkeypatch):
    import httpx

    def fail(url, timeout=None):
        raise ConnectionError("unreachable")

    monkeypatch.setattr(httpx, "get", fail)


def test_computed_value_for_fake_provider(clean, monkeypatch):
    ss.set_setting("source.max_chars", "auto")
    _fake_chain(monkeypatch)
    _fake_models(monkeypatch, 262144)
    assert budget.computed_budget_chars() == COMPUTED
    assert COMPUTED == 839160


def test_fallback_when_probe_fails(clean, monkeypatch):
    ss.set_setting("source.max_chars", "auto")
    _fake_chain(monkeypatch)
    _broken_probe(monkeypatch)
    assert budget.source_budget_chars() == FALLBACK
    assert FALLBACK == 36344


def test_floor_never_below_20000(clean):
    assert budget.computed_budget_chars(8000) == 20000
    assert budget.computed_budget_chars(100) == 20000
    assert budget.computed_budget_chars(32768) == FALLBACK


def test_numeric_override_wins(clean, monkeypatch):
    _fake_chain(monkeypatch)
    _broken_probe(monkeypatch)
    assert ss.set_setting("source.max_chars", "150000") == "150000"
    assert budget.source_budget_chars() == 150000


def test_auto_computes(clean, monkeypatch):
    assert ss.set_setting("source.max_chars", "auto") == "auto"
    _fake_chain(monkeypatch)
    _fake_models(monkeypatch, 262144)
    # the window allows 839160 chars; the quality cap keeps auto at 120000
    assert budget.source_budget_chars() == budget.AUTO_MAX_CHARS == 120_000


def test_max_sources_default_and_override(clean):
    assert budget.max_sources() == 10
    assert ss.set_setting("source.max_sources", "7") == "7"
    assert budget.max_sources() == 7


def test_invalid_settings_refused(clean):
    for bad in ("abc", "999", "9999999", "0", "-5"):
        with pytest.raises(ValueError):
            ss.set_setting("source.max_chars", bad)
    for bad in ("1", "51", "0", "abc", "2.5"):
        with pytest.raises(ValueError):
            ss.set_setting("source.max_sources", bad)
    assert ss.set_setting("source.max_chars", "10000") == "10000"
    assert ss.set_setting("source.max_chars", "2000000") == "2000000"
    assert ss.set_setting("source.max_sources", "2") == "2"
    assert ss.set_setting("source.max_sources", "50") == "50"


def test_meta_shows_both_values(api, clean, monkeypatch):
    _fake_chain(monkeypatch)
    _fake_models(monkeypatch, 262144)
    ss.set_setting("source.max_chars", "auto")
    ss.set_setting("source.max_sources", "7")
    r = api.get("/meta")
    assert r.status_code == 200, r.text
    limits = r.json()["limits"]
    assert limits["max_source_chars"] == budget.AUTO_MAX_CHARS
    assert limits["max_sources"] == 7


def _note(i: int) -> dict:
    return S.add_note(f"background note {i}\nThe grid runs on one DGX Spark at home, note {i}.")


def test_tray_over_limit_is_refused(api, clean):
    limit = budget.max_sources()
    ids = [_note(i)["id"] for i in range(limit + 1)]
    r = api.post("/jobs", json={"sources": [{"id": sid, "role": "main"} for sid in ids]})
    assert r.status_code == 422, r.text


def test_no_hardcoded_budget_left():
    for name in ("pipeline.py", "main.py"):
        text = (SRC / name).read_text()
        assert "MAX_SOURCE_CHARS" not in text
        assert "60_000" not in text


def test_single_source_extract_receives_job_budget(clean, monkeypatch):
    """F-1: the single-source path must pass the job budget to _extract.

    Fails without the fix (no max_chars kwarg, body capped at the 25000
    default); passes with it (max_chars == job budget, 40000-char body kept).
    """
    import asyncio

    from vozonda_api import budget as budget_mod
    from vozonda_api import pipeline

    job_budget = 50000
    long_body = "x" * 40000
    monkeypatch.setattr(budget_mod, "source_budget_chars", lambda: job_budget)
    monkeypatch.setattr("vozonda_api.doctor.blocking_problem", lambda: None)

    seen: dict = {}

    async def fake_fetch(url):
        return "<html><body>hello</body></html>"

    async def fake_extract(url, html=None, depth="direct", max_chars=None, **kw):
        seen["max_chars"] = max_chars
        return ("Example title", long_body, None)

    captured: dict = {}

    async def fake_tail(store_, job_id_, job_, body_, title_, lang_, *a, **k):
        captured["len"] = len(body_)
        yield store_.finish(job_id_)

    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(pipeline, "_run_from_body", fake_tail)

    store = JobStore()
    job_id = "budget-f1-single"
    try:
        store.get(job_id)
    except KeyError:
        store.create(job_id, url="https://example.com/article")

    async def _drain():
        return [u async for u in pipeline.run_job(store, job_id)]

    asyncio.run(_drain())

    assert seen.get("max_chars") == job_budget
    assert captured.get("len") == len(long_body)
