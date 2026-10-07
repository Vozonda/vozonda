from fastapi.testclient import TestClient


def test_normalize_voice_clamps_and_drops():
    from vozonda_api.voices import normalize_voice

    clean = normalize_voice(
        {
            "a.name": "  DerGigi  ",
            "b.timbre": "sohee",
            "b.name": "x" * 100,
            "count": 9,
            "gap_ms": 5,
            "speed": 42,
            "bogus.timbre": "aiden",
            "junk": 1,
        }
    )
    assert clean["a.name"] == "DerGigi"
    assert clean["b.timbre"] == "sohee"
    assert len(clean["b.name"]) == 24
    assert clean["count"] == 3
    assert clean["gap_ms"] == 50
    assert clean["speed"] == 2.0
    assert "bogus.timbre" not in clean
    assert "junk" not in clean
    # invalid timbre id is dropped (whitelist)
    assert "a.timbre" not in normalize_voice({"a.timbre": "nope"})
    # empty / non-dict input yields empty profile
    assert normalize_voice(None) == {}
    assert normalize_voice("nope") == {}
    # solo.name is accepted and clamped
    assert normalize_voice({"solo.name": "  NarratorName  "}) == {"solo.name": "NarratorName"}
    assert len(normalize_voice({"solo.name": "x" * 40})["solo.name"]) == 24


def test_host_names_includes_solo_name(monkeypatch):
    from vozonda_api import pipeline

    monkeypatch.setattr(pipeline, "get_setting_safe", lambda key: "GlobalNarrator" if key == "voice.solo.name" else None)
    # profile wins over global
    names = pipeline._host_names({"solo.name": "MyNarrator"})
    assert names == {"NARRATOR": "MyNarrator"}
    # no profile -> global fallback
    names = pipeline._host_names({})
    assert names == {"NARRATOR": "GlobalNarrator"}
    # long names clamp to 24 chars
    names = pipeline._host_names({"solo.name": "y" * 40})
    assert names["NARRATOR"] == "y" * 24


def test_host_names_prefers_profile_over_globals(monkeypatch):
    from vozonda_api import pipeline

    monkeypatch.setattr(pipeline, "get_setting_safe", lambda key: "GlobalA" if key == "voice.a.name" else None)
    # profile wins over global for a, global fills b, c stays absent
    names = pipeline._host_names({"a.name": "ProfilA", "b.name": "ProfilB"})
    assert names == {"A": "ProfilA", "B": "ProfilB"}
    # no profile -> global fallback only
    names = pipeline._host_names({})
    assert names == {"A": "GlobalA"}
    # long names clamp to 24 chars
    names = pipeline._host_names({"c.name": "y" * 40})
    assert names["C"] == "y" * 24


def test_job_store_roundtrip_voice_profile(jobs_db):
    import vozonda_api.jobs as jobs_mod

    store = jobs_mod.JobStore()
    store.create("vp1", "https://example.com/a", "balanced", "dialog", voice={"a.name": "Gigi", "count": 3})
    job = store.get("vp1")
    assert job["voice_profile"] == {"a.name": "Gigi", "count": 3}
    # legacy job has no profile
    store.create("vp2", "https://example.com/b")
    assert store.get("vp2")["voice_profile"] is None


def test_watchlist_voice_profile_crud(jobs_db):
    import vozonda_api.jobs as jobs_mod

    jobs_mod.JobStore()

    from vozonda_api.watchlist import create_watchlist, get_watchlist, update_enabled

    wl = create_watchlist("https://example.com/f.xml", voice={"b.timbre": "ryan", "count": 2})
    wid = wl["id"]
    assert get_watchlist(wid)["voice_profile"] == {"b.timbre": "ryan", "count": 2}
    # update writes a new profile
    updated = update_enabled(wid, True, voice={"a.name": "Solo", "count": 3})
    assert updated["voice_profile"] == {"a.name": "Solo", "count": 3}
    # enabled-only update keeps the profile
    assert update_enabled(wid, False)["voice_profile"] == {"a.name": "Solo", "count": 3}


def test_api_jobs_accept_and_sanitize_voice(jobs_db, api_client, monkeypatch):
    import vozonda_api.main as main_mod

    async def _noop(job_id, runner=None):
        return None

    monkeypatch.setattr(main_mod, "_run", _noop)
    client = api_client

    resp = client.post(
        "/jobs",
        json={
            "url": "https://example.com/article",
            "style": "balanced",
            "format": "dialog",
            "language": "auto",
            "hosts": 2,
            "voice": {"a.name": "Gigi", "c.timbre": "not-a-voice", "count": 7},
        },
    )
    assert resp.status_code == 200
    vp = resp.json()["voice_profile"]
    assert vp["a.name"] == "Gigi"
    assert vp["count"] == 3  # clamped
    assert "c.timbre" not in vp  # unknown timbre dropped


def test_pipeline_reader_chain_job_beats_global(jobs_db):
    import vozonda_api.jobs as jobs_mod
    from vozonda_api.pipeline import _PROFILE_KEYS, _voice_profile

    store = jobs_mod.JobStore()
    store.create("chain1", "https://example.com/c", voice={"gap_ms": 250})
    vp = _voice_profile(store, "chain1")
    assert _PROFILE_KEYS["voice.gap_ms"] == "gap_ms"
    assert vp == {"gap_ms": 250}
    # missing/legacy job resolves to empty dict, reader falls back later
    store.create("chain2", "https://example.com/d")
    assert _voice_profile(store, "chain2") == {}


def test_audio_probe_endpoint():
    import vozonda_api.main as main_mod

    client = TestClient(main_mod.app)

    # The probe lives in the (test) media dir. The test used to depend on a
    # sample mp3 that only existed untracked in one checkout, so it failed in
    # every fresh clone and fleet worktree.
    probe = main_mod.MEDIA_DIR / "probe-ryan.mp3"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_bytes(b"ID3" + b"\x00" * 2048)

    # Valid probe should return 200 and audio/mpeg
    resp = client.get("/audio/probe-ryan.mp3")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert len(resp.content) > 1000

    # Unknown probe should return 404
    resp404 = client.get("/audio/probe-nonexistent_voice.mp3")
    assert resp404.status_code == 404

