"""VOZONDA-20: the single-source script prompt title drops the site suffix."""

import asyncio
from typing import Any

import pytest

import vozonda_api.pipeline as pipeline_mod


class _FakeStore:
    """Minimal store mock - the pipeline calls several methods on it."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def upsert_job(self, job_id: str, _job: dict) -> None:
        self._data[job_id] = _job

    def set_stage_running(self, job_id: str, _stage: str, detail: str = "") -> dict:
        return self._data.get(job_id, {})

    def update(self, _job_id: str, **kwargs: Any) -> dict:
        return self._data.get(_job_id, {})

    def add_stage_meta(self, _job_id: str, _stage: str, **kwargs: Any) -> dict:
        return self._data.get(_job_id, {})

    def set_stage_done(self, _job_id: str, _stage: str) -> dict:
        return self._data.get(_job_id, {})

    def fail(self, _job_id: str, _stage: str, _error: str) -> dict:
        return self._data.get(_job_id, {})

    def finish(self, _job_id: str) -> dict:
        return self._data.get(_job_id, {})

    def __getattr__(self, name: str) -> Any:
        """Any unstubbed method returns an empty dict so the pipeline proceeds."""
        def _fallback(*_args: Any, **_kwargs: Any) -> Any:
            return {}
        return _fallback


async def _capture_script(*args: Any, title: str = "", **kwargs: Any):
    """Minimal script that captures the ``title`` kwarg on the function object."""
    _capture_script._captured_title = title  # type: ignore[attr-defined]
    return (
        [{"speaker": "host_a", "text": "Hi!", "start_ms": 0, "end_ms": 1000}],
        "",
    )


async def _async_gen_return(*args: Any, **kwargs: Any) -> None:
    """Fake async generator that yields nothing and finishes immediately."""
    return
    yield  # type: ignore[misc]


async def _attach_insights(*_args: Any, **_kwargs: Any) -> None:
    """No-op async that the pipeline awaits."""


async def _fake_episode_title(*_args: Any, **_kwargs: Any) -> str:
    return "Generated Title"


@pytest.fixture()
def pipeline_fakes(monkeypatch, tmp_path):
    """Patch every stage around _run_from_body so only its own logic runs."""
    monkeypatch.setattr(pipeline_mod, "_script", _capture_script)
    monkeypatch.setattr(pipeline_mod, "_narration_script", _capture_script)
    monkeypatch.setattr(pipeline_mod, "_generate_episode_title", _fake_episode_title)
    monkeypatch.setattr(pipeline_mod, "_voice", lambda *a, **k: tmp_path / "voice.mp3")
    monkeypatch.setattr(pipeline_mod, "_master", lambda *a, **k: tmp_path / "master.mp3")
    monkeypatch.setattr(pipeline_mod, "_attach_insights", _attach_insights)
    monkeypatch.setattr(pipeline_mod, "_host_names", lambda *a, **k: {"host_a": "Host A"})
    monkeypatch.setattr(pipeline_mod, "_voice_profile", lambda *a, **k: {"voice": "alloy"})
    monkeypatch.setattr(pipeline_mod, "detect_source_lang", lambda *a, **k: "en")
    monkeypatch.setattr(pipeline_mod, "_finish_from_script", _async_gen_return)


def _run_prompt_title(store, job_id, job, body, title, n_sources):
    """Drive _run_from_body to completion, the way run_job callers do."""

    async def go():
        gen = pipeline_mod._run_from_body(
            store, job_id, job, body, title, "en", n_sources=n_sources
        )
        async for _ in gen:
            pass

    asyncio.run(go())


def test_single_source_prompt_title_drops_wikipedia_suffix(pipeline_fakes):
    """A Wikipedia source titled 'Daylight saving time - Wikipedia' reaches
    the script prompt as title='Daylight saving time'."""
    body = "Long explanation of DST here."
    store = _FakeStore()
    job_id = "test-single"
    store.upsert_job(job_id, {"id": job_id})

    job: dict[str, Any] = {
        "id": job_id,
        "format": "podcast",
        "n_sources": 1,
        "language": "en",
        "style": "balanced",
        "tone": "neutral",
        "explicit": False,
        "tts_engine": "dummy",
        "emotion": "",
        "hosts": 2,
    }

    _run_prompt_title(store, job_id, job, body, "Daylight saving time - Wikipedia", n_sources=1)

    assert _capture_script._captured_title == "Daylight saving time"  # type: ignore[attr-defined]


def test_combined_job_prompt_title_is_empty(pipeline_fakes):
    """A combined job (n_sources=2) still passes an empty title to the script prompt."""
    body = "Combined content here."
    store = _FakeStore()
    job_id = "test-combined"
    store.upsert_job(job_id, {"id": job_id})

    job: dict[str, Any] = {
        "id": job_id,
        "format": "podcast",
        "n_sources": 2,
        "language": "en",
    }

    _run_prompt_title(store, job_id, job, body, "Combined Title - Site", n_sources=2)

    assert _capture_script._captured_title == ""  # type: ignore[attr-defined]
