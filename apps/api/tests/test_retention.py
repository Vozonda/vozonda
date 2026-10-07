import time

from fastapi.testclient import TestClient


def test_storage_stats_and_purge(tmp_path):
    from vozonda_api.retention import get_storage_stats, purge_old_media

    media_dir = tmp_path / "media"
    media_dir.mkdir()

    # Create a fresh file (1 day old)
    fresh_file = media_dir / "fresh.mp3"
    fresh_file.write_bytes(b"x" * 1000)

    # Create an old file (400 days old)
    old_file = media_dir / "old.mp3"
    old_file.write_bytes(b"y" * 2500)
    old_time = time.time() - (400 * 86400)
    import os

    os.utime(old_file, (old_time, old_time))

    # Check stats
    stats = get_storage_stats(media_dir=media_dir, retention_days=360)
    assert stats["file_count"] == 2
    assert stats["audio_files"] == 2
    assert stats["total_bytes"] == 3500
    assert stats["prunable_files"] == 1
    assert stats["prunable_bytes"] == 2500

    # Purge old media
    res = purge_old_media(media_dir=media_dir, days=360)
    assert res["purged_count"] == 1
    assert res["freed_bytes"] == 2500
    assert res["remaining_bytes"] == 1000
    assert not old_file.exists()
    assert fresh_file.exists()


def test_api_storage_endpoints(tmp_path, monkeypatch):
    import vozonda_api.main as main_mod
    import vozonda_api.providers as prov_mod
    import vozonda_api.retention as ret_mod

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    monkeypatch.setattr(prov_mod, "MEDIA_DIR", media_dir)
    monkeypatch.setattr(ret_mod, "MEDIA_DIR", media_dir)
    monkeypatch.setattr(main_mod, "MEDIA_DIR", media_dir)

    test_file = media_dir / "test.mp3"
    test_file.write_bytes(b"a" * 500)

    client = TestClient(main_mod.app)

    # GET /storage
    res = client.get("/storage")
    assert res.status_code == 200
    data = res.json()
    assert data["file_count"] == 1
    assert data["total_bytes"] == 500
    assert data["retention_days"] == 360

    # POST /storage/purge
    res2 = client.post("/storage/purge", json={"days": 360})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["purged_count"] == 0
    assert data2["remaining_bytes"] == 500
