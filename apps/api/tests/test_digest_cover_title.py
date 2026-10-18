"""Tests for digest cover title rendering (VOZONDA-21).

Covers:
- Template cover is generated after the final episode title is known.
- Uses the final title if _generate_episode_title returns one.
- Falls back to digest_title if _generate_episode_title returns None.
"""
import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("VOZONDA_DB", str(db))
    import vozonda_api.jobs as jobs_mod
    importlib.reload(jobs_mod)
    from vozonda_api.jobs import JobStore as JS
    return JS()


@pytest.mark.asyncio
async def test_digest_cover_uses_final_title(tmp_store, tmp_path, monkeypatch):
    """Cover is generated with the final title when _generate_episode_title returns one."""
    import vozonda_api.pipeline as pl_mod
    monkeypatch.setattr(pl_mod, "MEDIA_DIR", tmp_path)

    job_id = "digest-cover-test"
    tmp_store.create(
        job_id,
        "digest:test",
        digest=True,
        digest_sources=["http://a.com", "http://b.com"],
    )

    # Mock _generate_episode_title to return a final title
    final_title = "Three Stories About Rivers"
    monkeypatch.setattr(
        pl_mod,
        "_generate_episode_title",
        lambda *args, **kwargs: AsyncMock(return_value=final_title)(),
    )

    # Mock generate_template_cover to record its arguments
    cover_title_recorded = []

    def mock_generate_template_cover(title, style, output):
        cover_title_recorded.append(title)

    monkeypatch.setattr(pl_mod, "generate_template_cover", mock_generate_template_cover)

    # Mock _script_digest to return lines and chapters
    async def fake_script_digest(*args, **kwargs):
        return (
            [
                {"speaker": "A", "text": "Hello"},
                {"speaker": "B", "text": "World"},
            ],
            "Description",
            [{"index": 0, "title": "Story A", "url": "http://a.com", "word_offset": 0}],
        )
    monkeypatch.setattr(pl_mod, "_script_digest", fake_script_digest)

    # Mock lint_digest_script
    import vozonda_api.script_lint as sl_mod
    monkeypatch.setattr(sl_mod, "lint_digest_script", lambda *args, **kwargs: {"warnings": []})

    # Mock _attach_insights
    monkeypatch.setattr(pl_mod, "_attach_insights", lambda *args, **kwargs: asyncio.sleep(0))

    # Mock _voice and _master to avoid actual TTS/ffmpeg
    async def fake_voice(*args, **kwargs):
        return tmp_path / "test.wav"
    monkeypatch.setattr(pl_mod, "_voice", fake_voice)
    monkeypatch.setattr(pl_mod, "_master", lambda *args, **kwargs: asyncio.sleep(0))

    # Mock _pacing
    monkeypatch.setattr(pl_mod, "_pacing", lambda *args, **kwargs: (1.0, 380))

    # Mock _is_music_enabled
    monkeypatch.setattr(pl_mod, "_is_music_enabled", lambda *args, **kwargs: False)

    # Mock ffprobe
    monkeypatch.setattr(pl_mod, "asyncio", __import__("asyncio"))
    monkeypatch.setattr(
        pl_mod.asyncio,
        "to_thread",
        lambda func, *args, **kwargs: type("Probe", (), {"stdout": "10.0"})(),
    )

    # Mock _apply_script_timings
    monkeypatch.setattr(pl_mod, "_apply_script_timings", lambda *args, **kwargs: None)

    # Mock _finalize_insights_timings
    monkeypatch.setattr(pl_mod, "_finalize_insights_timings", lambda *args, **kwargs: None)

    # Mock _spawn_background
    monkeypatch.setattr(pl_mod, "_spawn_background", lambda *args, **kwargs: None)

    # Mock _publish_job
    monkeypatch.setattr(pl_mod, "_publish_job", lambda *args, **kwargs: None)

    # Mock _voice_profile
    monkeypatch.setattr(pl_mod, "_voice_profile", lambda *args, **kwargs: {})

    # Mock _host_names
    monkeypatch.setattr(pl_mod, "_host_names", lambda *args, **kwargs: {})

    # Mock detect_source_lang
    monkeypatch.setattr(pl_mod, "detect_source_lang", lambda *args, **kwargs: "en")

    # Mock condense_with_flag
    monkeypatch.setattr(pl_mod.condense_mod, "condense_with_flag", lambda *args, **kwargs: ("body", False))

    # Mock budget.source_budget_chars
    monkeypatch.setattr(pl_mod.budget, "source_budget_chars", lambda: 50000)

    # Mock budget.allocate
    monkeypatch.setattr(pl_mod.budget, "allocate", lambda *args, **kwargs: [50000] * len(args[0]))

    # Mock _extract
    async def fake_extract(*args, **kwargs):
        return ("Story A", "body content", None)
    monkeypatch.setattr(pl_mod, "_extract", fake_extract)

    # Mock fetch_article
    async def fake_fetch(url):
        return "<html><body>content</body></html>"
    monkeypatch.setattr(pl_mod, "fetch_article", fake_fetch)

    # Mock clean_title
    monkeypatch.setattr(pl_mod, "clean_title", lambda *args, **kwargs: args[0] if args else "")

    # Mock _digest_fallback_title
    monkeypatch.setattr(pl_mod, "_digest_fallback_title", lambda *args, **kwargs: "Digest: Story A + 1 more")

    

    import vozonda_api.sources as sources_mod
    monkeypatch.setattr(sources_mod, "job_sources", lambda *args, **kwargs: [])

    # Mock get_setting_safe
    monkeypatch.setattr(pl_mod, "get_setting_safe", lambda *args, **kwargs: None)

    # Mock llm_chain
    monkeypatch.setattr(pl_mod, "llm_chain", lambda *args, **kwargs: [])

    # Mock LOCAL_ONLY
    monkeypatch.setattr(pl_mod, "LOCAL_ONLY", type("Token", (), {"set": lambda *a, **k: None, "reset": lambda *a, **k: None})())

    # Run the digest pipeline
    job = tmp_store.get(job_id)
    async for _ in pl_mod._run_digest_inner(tmp_store, job_id, job):
        pass

    # Verify cover was generated with the final title
    assert len(cover_title_recorded) == 1
    assert cover_title_recorded[0] == final_title


@pytest.mark.asyncio
async def test_digest_cover_uses_fallback_title(tmp_store, tmp_path, monkeypatch):
    """Cover is generated with the fallback title when _generate_episode_title returns None."""
    import vozonda_api.pipeline as pl_mod
    monkeypatch.setattr(pl_mod, "MEDIA_DIR", tmp_path)

    job_id = "digest-cover-fallback"
    tmp_store.create(
        job_id,
        "digest:test",
        digest=True,
        digest_sources=["http://a.com", "http://b.com"],
    )

    # Mock _generate_episode_title to return None
    monkeypatch.setattr(
        pl_mod,
        "_generate_episode_title",
        lambda *args, **kwargs: AsyncMock(return_value=None)(),
    )

    # Mock generate_template_cover to record its arguments
    cover_title_recorded = []

    def mock_generate_template_cover(title, style, output):
        cover_title_recorded.append(title)

    monkeypatch.setattr(pl_mod, "generate_template_cover", mock_generate_template_cover)

    # Mock _script_digest to return lines and chapters
    async def fake_script_digest(*args, **kwargs):
        return (
            [
                {"speaker": "A", "text": "Hello"},
                {"speaker": "B", "text": "World"},
            ],
            "Description",
            [{"index": 0, "title": "Story A", "url": "http://a.com", "word_offset": 0}],
        )
    monkeypatch.setattr(pl_mod, "_script_digest", fake_script_digest)

    # Mock lint_digest_script
    import vozonda_api.script_lint as sl_mod
    monkeypatch.setattr(sl_mod, "lint_digest_script", lambda *args, **kwargs: {"warnings": []})

    # Mock _attach_insights
    monkeypatch.setattr(pl_mod, "_attach_insights", lambda *args, **kwargs: asyncio.sleep(0))

    # Mock _voice and _master to avoid actual TTS/ffmpeg
    async def fake_voice(*args, **kwargs):
        return tmp_path / "test.wav"
    monkeypatch.setattr(pl_mod, "_voice", fake_voice)
    monkeypatch.setattr(pl_mod, "_master", lambda *args, **kwargs: asyncio.sleep(0))

    # Mock _pacing
    monkeypatch.setattr(pl_mod, "_pacing", lambda *args, **kwargs: (1.0, 380))

    # Mock _is_music_enabled
    monkeypatch.setattr(pl_mod, "_is_music_enabled", lambda *args, **kwargs: False)

    # Mock ffprobe
    monkeypatch.setattr(pl_mod, "asyncio", __import__("asyncio"))
    monkeypatch.setattr(
        pl_mod.asyncio,
        "to_thread",
        lambda func, *args, **kwargs: type("Probe", (), {"stdout": "10.0"})(),
    )

    # Mock _apply_script_timings
    monkeypatch.setattr(pl_mod, "_apply_script_timings", lambda *args, **kwargs: None)

    # Mock _finalize_insights_timings
    monkeypatch.setattr(pl_mod, "_finalize_insights_timings", lambda *args, **kwargs: None)

    # Mock _spawn_background
    monkeypatch.setattr(pl_mod, "_spawn_background", lambda *args, **kwargs: None)

    # Mock _publish_job
    monkeypatch.setattr(pl_mod, "_publish_job", lambda *args, **kwargs: None)

    # Mock _voice_profile
    monkeypatch.setattr(pl_mod, "_voice_profile", lambda *args, **kwargs: {})

    # Mock _host_names
    monkeypatch.setattr(pl_mod, "_host_names", lambda *args, **kwargs: {})

    # Mock detect_source_lang
    monkeypatch.setattr(pl_mod, "detect_source_lang", lambda *args, **kwargs: "en")

    # Mock condense_with_flag
    monkeypatch.setattr(pl_mod.condense_mod, "condense_with_flag", lambda *args, **kwargs: ("body", False))

    # Mock budget.source_budget_chars
    monkeypatch.setattr(pl_mod.budget, "source_budget_chars", lambda: 50000)

    # Mock budget.allocate
    monkeypatch.setattr(pl_mod.budget, "allocate", lambda *args, **kwargs: [50000] * len(args[0]))

    # Mock _extract
    async def fake_extract(*args, **kwargs):
        return ("Story A", "body content", None)
    monkeypatch.setattr(pl_mod, "_extract", fake_extract)

    # Mock fetch_article
    async def fake_fetch(url):
        return "<html><body>content</body></html>"
    monkeypatch.setattr(pl_mod, "fetch_article", fake_fetch)

    # Mock clean_title
    monkeypatch.setattr(pl_mod, "clean_title", lambda *args, **kwargs: args[0] if args else "")

    # Mock _digest_fallback_title
    monkeypatch.setattr(pl_mod, "_digest_fallback_title", lambda *args, **kwargs: "Digest: Story A + 1 more")

    

    import vozonda_api.sources as sources_mod
    monkeypatch.setattr(sources_mod, "job_sources", lambda *args, **kwargs: [])

    # Mock get_setting_safe
    monkeypatch.setattr(pl_mod, "get_setting_safe", lambda *args, **kwargs: None)

    # Mock llm_chain
    monkeypatch.setattr(pl_mod, "llm_chain", lambda *args, **kwargs: [])

    # Mock LOCAL_ONLY
    monkeypatch.setattr(pl_mod, "LOCAL_ONLY", type("Token", (), {"set": lambda *a, **k: None, "reset": lambda *a, **k: None})())

    # Run the digest pipeline
    job = tmp_store.get(job_id)
    async for _ in pl_mod._run_digest_inner(tmp_store, job_id, job):
        pass

    # Verify cover was generated with the fallback title
    assert len(cover_title_recorded) == 1
    assert cover_title_recorded[0] == "Digest: Story A + 1 more"
