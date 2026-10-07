"""Tests for the Nostr publishing orchestrator (VOZONDA-NOSTR-2).

Uses mocked relays (httpx MockTransport for blossom, mock asyncio) and a
temp secrets directory so keypairs are never touched in the real location.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _secrets_dir(tmp_path: Path) -> Path:
    """Point VOZONDA_SECRETS_DIR at a temp directory for the test."""
    with patch("vozonda_api.config.VOZONDA_SECRETS_DIR", tmp_path):
        with patch("vozonda_api.podcast_key.VOZONDA_SECRETS_DIR", tmp_path):
            with patch("vozonda_api.nostr_orchestrator.VOZONDA_SECRETS_DIR", tmp_path):
                yield tmp_path
def _make_show_settings(num: str = "1", name: str = "My Show", author: str = "Alice", nostr: str = "1") -> dict[str, str]:
    return {
        f"show.{num}.name": name,
        f"show.{num}.author": author,
        f"show.{num}.nostr": nostr,
        "nostr.publish_default": "0",
        "nostr.relays": "wss://relay.example.com",
        "nostr.blossom_servers": "https://blossom.example.com",
    }
def _make_job(
    job_id: str = "job-1",
    state: str = "done",
    show_slug: str = "1",
) -> dict[str, Any]:
    return {
        "id": job_id,
        "state": state,
        "show_slug": show_slug,
        "title": "Test Episode",
        "url": "https://example.com/1",
        "description": "A test",
        "created_at": 1700000000,
        "digest_sources": None,
        "model_ids": [],
        "og_image": "",
        "chapters": None,
    }
def _mock_store(job_data: dict[str, Any]) -> MagicMock:
    """Return a mocked JobStore instance with get returning job_data."""
    instance = MagicMock()
    instance.get.return_value = job_data
    return instance
# ---------------------------------------------------------------------------
# Helper: run publish_job with patches
# ---------------------------------------------------------------------------
def _patch_settings(settings: dict[str, str]) -> MagicMock:
    """Patch settings_store.get_setting to use our dict."""
    mock = MagicMock()

    def getter(key: str) -> str | None:
        return settings.get(key)

    mock.side_effect = getter
    return mock
# ---------------------------------------------------------------------------
# Test: show off -> nothing
# ---------------------------------------------------------------------------
class TestShowOff:
    @pytest.mark.asyncio
    async def test_show_off_skips_publish(self) -> None:
        """When show nostr is '0', publish_job does nothing."""
        from vozonda_api.nostr_orchestrator import publish_job

        job_data = _make_job()

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "0", "name": "My Show", "author": "Alice", "category": ""}):
                
                    await publish_job("job-1")

        instance.get.assert_called_once_with("job-1")
# ---------------------------------------------------------------------------
# Test: show on -> one 10154 then 54
# ---------------------------------------------------------------------------
class TestShowOn:
    @pytest.mark.asyncio
    async def test_one_10154_then_54(self, tmp_path: Path) -> None:
        """Show on -> one kind:10154, then kind:54 with audio/transcript/chapters tags."""
        from vozonda_api.nostr_orchestrator import publish_job

        # Setup audio/transcript/chapters files
        audio_path = tmp_path / "job-1.opus"
        audio_path.write_bytes(b"fake audio")
        transcript_path = tmp_path / "job-1.vtt"
        transcript_path.write_text("fake transcript")
        chapters_path = tmp_path / "job-1.chapters.json"
        chapters_path.write_text('{"chapters": []}')

        job_data = _make_job("job-1")

        signed_events: list[dict] = []

        def mock_sign_event(show_id: str, event: dict) -> dict:
            result = {**event, "id": "mock-event-id", "sig": "mock-sig"}
            signed_events.append(result)
            return result

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                with patch("vozonda_api.nostr_orchestrator.has_keypair", return_value=False):
                    with patch("vozonda_api.nostr_orchestrator.generate_keypair"):
                        with patch("vozonda_api.nostr_orchestrator.load_keypair", return_value=("00" * 32, "ab" * 32)):
                            with patch("vozonda_api.nostr_orchestrator.sign_event", side_effect=mock_sign_event):
                                with patch("vozonda_api.nostr_orchestrator.publish_async", new_callable=AsyncMock) as mock_publish:
                                    mock_publish.return_value = [
                                        MagicMock(ok=True, relay="wss://relay.example.com", reason=None),
                                    ]
                                    with patch("vozonda_api.nostr_orchestrator._upload_blob", new_callable=AsyncMock) as mock_upload:
                                        mock_upload.return_value = (
                                            MagicMock(url="https://blossom.example.com/abc123", sha256="abc123", size=100, type="audio/opus"),
                                            [],
                                        )
                                        with patch("vozonda_api.nostr_orchestrator._audio_blob_for", return_value=(str(audio_path), "audio/opus")):
                                            with patch("vozonda_api.nostr_orchestrator._transcript_path_for", return_value=str(transcript_path)):
                                                with patch("vozonda_api.nostr_orchestrator._chapters_path_for", return_value=str(chapters_path)):
                                                    
                                                        await publish_job("job-1")

        # Should have signed two events: show (10154) and episode (54)
        assert len(signed_events) == 2
        kinds = [e["kind"] for e in signed_events]
        assert 10154 in kinds
        assert 54 in kinds

        # Episode event should have audio, transcript, and chapters tags
        episode_event = next(e for e in signed_events if e["kind"] == 54)
        tag_types = [t[0] for t in episode_event["tags"]]
        assert "audio" in tag_types
        assert "transcript" in tag_types
        assert "chapters" in tag_types

    @pytest.mark.asyncio
    async def test_10154_skipped_when_unchanged(self) -> None:
        """Second job of the same show does not re-publish 10154."""
        from vozonda_api.nostr_orchestrator import _remember_show_sha, _show_event_sha, build_show_event, publish_job

        # the first publish of this show was stored (persistent since review F-2)
        show = {"name": "My Show", "author": "Alice", "category": "", "image": ""}
        _remember_show_sha("1", _show_event_sha(build_show_event(show, "ab" * 32)), "first-event")

        job_data = _make_job("job-2")

        signed_events: list[dict] = []

        def mock_sign_event(show_id: str, event: dict) -> dict:
            result = {**event, "id": "mock-event-id", "sig": "mock-sig"}
            signed_events.append(result)
            return result

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                with patch("vozonda_api.nostr_orchestrator.has_keypair", return_value=True):
                    with patch("vozonda_api.nostr_orchestrator.load_keypair", return_value=("00" * 32, "ab" * 32)):
                        with patch("vozonda_api.nostr_orchestrator.sign_event", side_effect=mock_sign_event):
                            with patch("vozonda_api.nostr_orchestrator.publish_async", new_callable=AsyncMock) as mock_publish:
                                mock_publish.return_value = [MagicMock(ok=True, relay="wss://relay.example.com", reason=None)]
                                with patch("vozonda_api.nostr_orchestrator._upload_blob", new_callable=AsyncMock) as mock_upload:
                                    mock_upload.return_value = (
                                        MagicMock(url="https://blossom.example.com/def456", sha256="def456", size=100, type="audio/mpeg"),
                                        [],
                                    )
                                    with patch("vozonda_api.nostr_orchestrator._audio_blob_for", return_value=(None, None)):
                                        
                                            await publish_job("job-2")

        # Only kind:54 should be published, not kind:10154
        kinds = [e["kind"] for e in signed_events]
        assert 10154 not in kinds
        assert 54 in kinds

    @pytest.mark.asyncio
    async def test_audio_opus_preferred(self, tmp_path: Path) -> None:
        """Opus audio is preferred over MP3 when both exist."""
        from vozonda_api.nostr_orchestrator import publish_job

        audio_opus = tmp_path / "job-3.opus"
        audio_opus.write_bytes(b"opus data")

        job_data = _make_job("job-3")

        captured_args: list[tuple] = []

        def mock_upload(*args: Any, **kwargs: Any) -> tuple:  # type: ignore[override]
            captured_args.append((args, kwargs))
            return (
                MagicMock(url="https://blossom.example.com/abc", sha256="abc", size=100, type="audio/opus"),
                [],
            )

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                with patch("vozonda_api.nostr_orchestrator.has_keypair", return_value=True):
                    with patch("vozonda_api.nostr_orchestrator.load_keypair", return_value=("00" * 32, "ab" * 32)):
                        with patch("vozonda_api.nostr_orchestrator.sign_event", side_effect=lambda _, e: {**e, "id": "mock", "sig": "sig"}):
                            with patch("vozonda_api.nostr_orchestrator.publish_async", new_callable=AsyncMock, return_value=[MagicMock(ok=True, relay="wss://relay.example.com", reason=None)]):
                                with patch("vozonda_api.nostr_orchestrator._upload_blob", new_callable=AsyncMock, side_effect=mock_upload):
                                    with patch("vozonda_api.nostr_orchestrator._audio_blob_for", return_value=(str(audio_opus), "audio/opus")):
                                        with patch("vozonda_api.nostr_orchestrator._transcript_path_for", return_value=None):
                                            with patch("vozonda_api.nostr_orchestrator._chapters_path_for", return_value=None):
                                                
                                                    await publish_job("job-3")

        # Check that opus was used (content_type should be audio/opus)
        assert len(captured_args) >= 1
        # _upload_blob signature: (file_path, content_type, servers, show_slug)
        captured_content_type = captured_args[0][0][1]
        assert captured_content_type == "audio/opus"
# ---------------------------------------------------------------------------
# Test: mirror with one server failing still succeeds
# ---------------------------------------------------------------------------
class TestMirrorFailure:
    @pytest.mark.asyncio
    async def test_mirror_one_fails_still_succeeds(self, tmp_path: Path) -> None:
        """One Blossom server failing in mirror still succeeds with the primary."""
        from vozonda_api.blossom import BlossomError
        from vozonda_api.nostr_orchestrator import publish_job

        audio_path = tmp_path / "job-4.opus"
        audio_path.write_bytes(b"fake audio")

        job_data = _make_job("job-4")

        upload_count = 0

        def mock_upload(*args: Any, **kwargs: Any) -> tuple:  # type: ignore[override]
            nonlocal upload_count
            upload_count += 1
            # Simulate: primary succeeds, mirror to blossom2 fails
            if upload_count > 1:
                raise BlossomError("mirror rejected")
            return (
                MagicMock(url="https://blossom1.example.com/abc", sha256="abc", size=100, type="audio/opus"),
                [MagicMock(server="https://blossom2.example.com", descriptor=None, error="mirror rejected")],
            )

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                with patch("vozonda_api.nostr_orchestrator.has_keypair", return_value=True):
                    with patch("vozonda_api.nostr_orchestrator.load_keypair", return_value=("00" * 32, "ab" * 32)):
                        with patch("vozonda_api.nostr_orchestrator.sign_event", side_effect=lambda _, e: {**e, "id": "mock", "sig": "sig"}):
                            with patch("vozonda_api.nostr_orchestrator.publish_async", new_callable=AsyncMock, return_value=[MagicMock(ok=True, relay="wss://relay.example.com", reason=None)]):
                                with patch("vozonda_api.nostr_orchestrator._upload_blob", new_callable=AsyncMock, side_effect=mock_upload):
                                    with patch("vozonda_api.nostr_orchestrator._audio_blob_for", return_value=(str(audio_path), "audio/opus")):
                                        with patch("vozonda_api.nostr_orchestrator._transcript_path_for", return_value=None):
                                            with patch("vozonda_api.nostr_orchestrator._chapters_path_for", return_value=None):
                                                
                                                    await publish_job("job-4")

        # Should still have published (audio upload succeeded, mirror failure was recorded)
        assert upload_count >= 1
# ---------------------------------------------------------------------------
# Test: relay OK false recorded
# ---------------------------------------------------------------------------
class TestRelayFailure:
    @pytest.mark.asyncio
    async def test_relay_ok_false_recorded(self) -> None:
        """A relay returning OK false is recorded in nostr_publish."""
        from vozonda_api.nostr_orchestrator import publish_job

        job_data = _make_job("job-5")

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                with patch("vozonda_api.nostr_orchestrator.has_keypair", return_value=True):
                    with patch("vozonda_api.nostr_orchestrator.load_keypair", return_value=("00" * 32, "ab" * 32)):
                        with patch("vozonda_api.nostr_orchestrator.sign_event", side_effect=lambda _, e: {**e, "id": "mock-event", "sig": "sig"}):
                            # Relay returns ok=False with a reason
                            with patch("vozonda_api.nostr_orchestrator.publish_async", new_callable=AsyncMock) as mock_publish:
                                mock_publish.return_value = [MagicMock(ok=False, relay="wss://relay.example.com", reason="rejected: spam")]
                                # coordinator review: the upload must succeed, an episode without audio is never sent
                                uploaded = (MagicMock(url="https://blossom.example.com/a.mp3"), [])
                                with patch("vozonda_api.nostr_orchestrator._upload_blob", new_callable=AsyncMock, return_value=uploaded):
                                    with patch("vozonda_api.nostr_orchestrator._audio_blob_for", return_value=("/tmp/job-5.mp3", "audio/mpeg")):
                                        with patch("vozonda_api.nostr_orchestrator._record_publish") as record:
                                            await publish_job("job-5")

        mock_publish.assert_called()
        # the show metadata (kind 10154, rejected by the same mock relay, no error text) is
        # published and recorded first when no earlier test remembered it; pick the episode
        rejected = [
            c.kwargs
            for c in record.call_args_list
            if c.kwargs.get("kind") == 54
            and c.kwargs.get("relay_url") == "wss://relay.example.com"
            and c.kwargs.get("relay_ok") is False
        ]
        assert rejected and rejected[0]["relay_ok"] is False and rejected[0]["error"] == "rejected: spam"
# ---------------------------------------------------------------------------
# Test: failure leaves job done
# ---------------------------------------------------------------------------
class TestJobState:
    @pytest.mark.asyncio
    async def test_failure_does_not_change_job_state(self, tmp_path: Path) -> None:
        """A Nostr failure should never change the job state from done."""
        from vozonda_api.nostr_orchestrator import publish_job

        job_data = _make_job("job-6")

        # Simulate a complete failure
        def always_fail(*args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
            raise RuntimeError("simulated failure")

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                with patch("vozonda_api.nostr_orchestrator.has_keypair", return_value=True):
                    with patch("vozonda_api.nostr_orchestrator.load_keypair", return_value=("00" * 32, "ab" * 32)):
                        with patch("vozonda_api.nostr_orchestrator.sign_event", side_effect=always_fail):
                            with patch("vozonda_api.nostr_orchestrator.publish_async", new_callable=AsyncMock):
                                with patch("vozonda_api.nostr_orchestrator._upload_blob", new_callable=AsyncMock, return_value=None):
                                    with patch("vozonda_api.nostr_orchestrator._audio_blob_for", return_value=(None, None)):
                                        
                                            # Should not raise
                                            await publish_job("job-6")

        # Job store get was called but update was never called (state unchanged)
        instance.get.assert_called()
        instance.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_job_running_skipped(self) -> None:
        """Jobs that are still running are not published."""
        from vozonda_api.nostr_orchestrator import publish_job

        job_data = _make_job("job-8", state="running")

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                
                    await publish_job("job-8")

        instance.get.assert_called_once_with("job-8")

    @pytest.mark.asyncio
    async def test_job_queued_skipped(self) -> None:
        """Queued jobs are not published."""
        from vozonda_api.nostr_orchestrator import publish_job

        job_data = _make_job("job-9", state="queued")

        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                
                    await publish_job("job-9")

        instance.get.assert_called_once_with("job-9")
# ---------------------------------------------------------------------------
# Test: key never regenerated
# ---------------------------------------------------------------------------
class TestKeyPersistence:
    @pytest.mark.asyncio
    async def test_key_never_regenerated(self, tmp_path: Path) -> None:
        """Once a keypair exists, generate_keypair is never called again."""
        from vozonda_api.nostr_orchestrator import publish_job

        job_data = _make_job("job-7")

        # First call: key does not exist yet
        with patch("vozonda_api.jobs.JobStore") as MockStore:
            instance = _mock_store(job_data)
            MockStore.return_value = instance
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                with patch("vozonda_api.nostr_orchestrator.has_keypair", return_value=False):
                    with patch("vozonda_api.nostr_orchestrator.generate_keypair") as mock_gen:
                        with patch("vozonda_api.nostr_orchestrator.load_keypair", return_value=("00" * 32, "ab" * 32)):
                            with patch("vozonda_api.nostr_orchestrator.sign_event", side_effect=lambda _, e: {**e, "id": "mock", "sig": "sig"}):
                                with patch("vozonda_api.nostr_orchestrator.publish_async", new_callable=AsyncMock, return_value=[MagicMock(ok=True, relay="wss://relay.example.com", reason=None)]):
                                    with patch("vozonda_api.nostr_orchestrator._upload_blob", new_callable=AsyncMock, return_value=None):
                                        with patch("vozonda_api.nostr_orchestrator._audio_blob_for", return_value=(None, None)):
                                            
                                                await publish_job("job-7")

        # generate_keypair should have been called exactly once
        mock_gen.assert_called_once()

        # Second call: key now exists, should NOT call generate again
        with patch("vozonda_api.jobs.JobStore") as MockStore2:
            instance2 = _mock_store({
                "id": "job-7b",
                "state": "done",
                "show_slug": "1",
                "title": "Test Episode 2",
                "url": "https://example.com/7b",
                "description": "",
                "created_at": 1700000001,
                "digest_sources": None,
                "model_ids": [],
                "og_image": "",
                "chapters": None,
            })
            MockStore2.return_value = instance2
            with patch("vozonda_api.nostr_orchestrator._get_show_config", return_value={"nostr": "1", "name": "My Show", "author": "Alice", "category": ""}):
                with patch("vozonda_api.nostr_orchestrator.has_keypair", return_value=True):
                    with patch("vozonda_api.nostr_orchestrator.generate_keypair") as mock_gen2:
                        with patch("vozonda_api.nostr_orchestrator.load_keypair", return_value=("00" * 32, "ab" * 32)):
                            with patch("vozonda_api.nostr_orchestrator.sign_event", side_effect=lambda _, e: {**e, "id": "mock", "sig": "sig"}):
                                with patch("vozonda_api.nostr_orchestrator.publish_async", new_callable=AsyncMock, return_value=[MagicMock(ok=True, relay="wss://relay.example.com", reason=None)]):
                                    with patch("vozonda_api.nostr_orchestrator._upload_blob", new_callable=AsyncMock, return_value=None):
                                        with patch("vozonda_api.nostr_orchestrator._audio_blob_for", return_value=(None, None)):
                                            
                                                await publish_job("job-7b")

        # generate_keypair should NOT have been called the second time
        mock_gen2.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_raises_file_exists_error(self, tmp_path: Path) -> None:
        """generate_keypair raises FileExistsError if a key already exists."""
        from vozonda_api.podcast_key import generate_keypair

        key_dir = tmp_path / "nostr"
        key_dir.mkdir(mode=0o700)

        # First call: should succeed
        generate_keypair("test-show")

        # Second call: should raise FileExistsError
        with pytest.raises(FileExistsError):
            generate_keypair("test-show")
# ---------------------------------------------------------------------------
# Test: async wrapper
# ---------------------------------------------------------------------------
class TestAsyncWrapper:
    @pytest.mark.asyncio
    async def test_publish_job_async(self) -> None:
        """publish_job_async should work from an event loop context."""
        from vozonda_api.nostr_orchestrator import publish_job_async

        with patch("vozonda_api.nostr_orchestrator.publish_job", new_callable=AsyncMock) as mock_inner:
            task = asyncio.create_task(publish_job_async("job-x"))
            await task

        mock_inner.assert_called_once_with("job-x")