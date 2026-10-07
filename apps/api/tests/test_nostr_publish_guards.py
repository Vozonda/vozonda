"""Coordinator review of VOZONDA-NOSTR-2 (2026-10-02): guards the fleet tests missed.

The fleet tests replaced _get_show_config with a mock, so the real opt-in rule was
never exercised, and none covered a failed Blossom upload. Operator decision: Nostr
publishing is switched on deliberately per show. A signed episode event on public
relays cannot be taken back, so an event without audio must never go out."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from vozonda_api import nostr_orchestrator as orch


def _settings(values):
    return patch("vozonda_api.settings_store.get_setting", side_effect=lambda k: values.get(k))


def test_only_an_explicit_per_show_opt_in_publishes():
    with _settings({"show.1.nostr": "1"}):
        assert orch._get_show_config("1")["nostr"] == "1"
    with _settings({"nostr.publish_default": "1"}):  # global default alone never publishes a show
        assert orch._get_show_config("1")["nostr"] != "1"
    with _settings({"show.2.nostr": "1", "nostr.publish_default": "1"}):
        assert orch._get_show_config("s1")["nostr"] != "1"
        assert orch._get_show_config("s2")["nostr"] == "1"


def test_a_broken_show_reference_is_skipped_not_raised():
    with _settings({}):
        assert orch._get_show_config("my-show") is None
        assert orch._get_show_config("") is None


def _run_publish(upload_result, servers="https://blossom.example.com"):
    job = {"id": "job-1", "state": "done", "show_slug": "1", "title": "T", "og_image": ""}
    store = MagicMock()
    store.get.return_value = job
    recorded = []
    with patch("vozonda_api.jobs.JobStore", return_value=store), \
         _settings({"show.1.nostr": "1", "nostr.relays": "wss://relay.example.com", "nostr.blossom_servers": servers}), \
         patch.object(orch, "_ensure_show_key", new=AsyncMock(return_value="ab" * 32)), \
         patch.object(orch, "_publish_show_event", new=AsyncMock(return_value="show-id")), \
         patch.object(orch, "_audio_blob_for", return_value=("/tmp/job-1.mp3", "audio/mpeg")), \
         patch.object(orch, "_transcript_path_for", return_value=None), \
         patch.object(orch, "_chapters_path_for", return_value=None), \
         patch.object(orch, "_upload_blob", new=AsyncMock(return_value=upload_result)), \
         patch.object(orch, "_ensure_nostr_publish_table"), \
         patch.object(orch, "_record_publish", side_effect=lambda **kw: recorded.append(kw)), \
         patch.object(orch, "_publish_episode", new=AsyncMock(return_value="ep-id")) as episode:
        asyncio.run(orch.publish_job("job-1"))
    return episode, recorded


def test_no_episode_event_when_every_blossom_upload_failed():
    episode, recorded = _run_publish(upload_result=None)
    episode.assert_not_called()
    assert any("no audio" in (r.get("error") or "") for r in recorded)


def test_no_episode_event_without_blossom_servers():
    episode, _ = _run_publish(upload_result=None, servers="")
    episode.assert_not_called()


def test_an_uploaded_audio_still_publishes_the_episode():
    primary = MagicMock(url="https://blossom.example.com/abc.mp3")
    episode, _ = _run_publish(upload_result=(primary, []))
    episode.assert_called_once()
    assert episode.call_args.args[3] == [("https://blossom.example.com/abc.mp3", "audio/mpeg")]


def test_the_background_publish_task_is_kept_until_it_finishes():
    """asyncio keeps only a weak reference to tasks; an unreferenced one can vanish mid-run."""
    from vozonda_api import pipeline

    async def main():
        gate = asyncio.Event()

        async def slow():
            await gate.wait()

        task = pipeline._spawn_background(slow())
        assert task in pipeline._BACKGROUND_TASKS
        gate.set()
        await task
        await asyncio.sleep(0)
        assert task not in pipeline._BACKGROUND_TASKS

    asyncio.run(main())


def test_the_preflight_is_signed_and_blossom_runs_off_the_event_loop(tmp_path):
    """Live check 2026-10-02: every public server answers HEAD /upload without a
    Blossom authorization with 401 (BUD-06/BUD-11), so the unsigned preflight skipped
    all of them and nothing was ever uploaded. The sync httpx calls also blocked the
    API's event loop for the whole upload."""
    import threading

    audio = tmp_path / "ep.mp3"
    audio.write_bytes(b"x" * 1000)
    seen = {}
    loop_thread = threading.get_ident()

    def fake_preflight(server, sha, size, ctype, **kw):
        seen.setdefault("auth", kw.get("auth_header"))
        seen["preflight_thread"] = threading.get_ident()
        return True

    def fake_upload_and_mirror(**kw):
        seen["upload_thread"] = threading.get_ident()
        return MagicMock(url="https://b.example/abc.mp3"), []

    with patch.object(orch, "preflight_upload", side_effect=fake_preflight), \
         patch.object(orch, "upload_and_mirror", side_effect=fake_upload_and_mirror), \
         patch.object(orch, "sign_event", side_effect=lambda slug, ev: {**ev, "id": "i" * 64, "pubkey": "p" * 64, "sig": "s" * 128}):
        res = asyncio.run(orch._upload_blob(str(audio), "audio/mpeg", ["https://b.example"], "1"))
    assert res is not None
    assert (seen["auth"] or "").startswith("Nostr "), "preflight must carry the upload authorization"
    assert seen["preflight_thread"] != loop_thread and seen["upload_thread"] != loop_thread


def _show_publish(monkeypatch, tmp_path, show, relay_ok=True):
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    jobs_mod.init_db()
    published = []

    async def fake_publish(event, relays):
        published.append(event)
        return [MagicMock(ok=relay_ok, relay="wss://r.example", reason=None if relay_ok else "blocked")]

    with patch.object(orch, "sign_event", side_effect=lambda slug, ev: {**ev, "id": f"id{len(published)}", "sig": "s"}), \
         patch.object(orch, "publish_async", side_effect=fake_publish), \
         patch.object(orch, "_load_relay_urls", return_value=["wss://r.example"]):
        res = asyncio.run(orch._publish_show_event("1", show, "ab" * 32))
    return res, published


def test_show_metadata_is_not_republished_after_a_restart(monkeypatch, tmp_path):
    """Review F-2: the 'already published' memory lived in process memory only."""
    show = {"name": "Show", "author": "A", "category": "Tech", "image": ""}
    first, _ = _show_publish(monkeypatch, tmp_path, show)
    orch.__dict__.pop("_show_meta_cache", None)  # a restart: nothing in memory survives
    second, published = _show_publish(monkeypatch, tmp_path, show)
    assert first and second is None and published == []


def test_any_changed_field_republishes_the_show(monkeypatch, tmp_path):
    show = {"name": "Show", "author": "A", "category": "Tech", "image": ""}
    _show_publish(monkeypatch, tmp_path, show)
    again, published = _show_publish(monkeypatch, tmp_path, {**show, "name": "Show, renamed"})
    assert again and len(published) == 1, "a changed field of the event republishes it"


def test_a_show_event_no_relay_accepted_is_tried_again(monkeypatch, tmp_path):
    show = {"name": "Show", "author": "A", "category": "Tech", "image": ""}
    _show_publish(monkeypatch, tmp_path, show, relay_ok=False)
    again, published = _show_publish(monkeypatch, tmp_path, show)
    assert again and len(published) == 1


def test_a_display_name_never_becomes_a_p_tag():
    """NIP-01: a p tag holds a 32-byte lowercase hex pubkey; 'Alice' made an invalid tag."""
    from vozonda_api.nostr_publish import build_show_event

    tags = build_show_event({"name": "S", "author": "Alice"}, "ab" * 32)["tags"]
    assert not any(t[0] == "p" for t in tags)
    tags = build_show_event({"name": "S", "author": "cd" * 32}, "ab" * 32)["tags"]
    assert ["p", "cd" * 32] in tags
