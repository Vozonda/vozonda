"""Per-line source citations (VOZONDA-TRAY-CITATIONS).

Each script line may carry "src" with the numbers of the sources it draws on;
show notes, RSS and Nostr list the sources (uploads by title only, never with
source text). A single-source job has no Sources list.
"""

import asyncio
import json

from vozonda_api.pipeline import _normalize_turns


def _turn(speaker="A", text="a claim from the sources here", **kw):
    d = {"speaker": speaker, "text": text}
    d.update(kw)
    return d


def _dialog4(src0=None, src1=None, src2=None, src3=None):
    lines = [
        _turn("A", "first claim from the sources here"),
        _turn("B", "second claim from the sources here"),
        _turn("A", "third claim from the sources here"),
        _turn("B", "fourth claim from the sources here"),
    ]
    for ln, src in zip(lines, (src0, src1, src2, src3)):
        if src is not None:
            ln["src"] = src
    return lines


def test_src_survives_cleanup_sorted_unique():
    out = _normalize_turns(_dialog4(src0=[2, 1], src1=[1, 1, 2, 2]), "dialog", 2, n_sources=3)
    assert out[0]["src"] == [1, 2]
    assert out[1]["src"] == [1, 2]


def test_src_filtered_out_of_range_and_non_int():
    out = _normalize_turns(
        _dialog4(src0=[0, 4, "x", 2, 2, None, 2.5]),
        "dialog", 2, n_sources=3,
    )
    assert out[0]["src"] == [2]


def test_line_without_src_is_fine():
    out = _normalize_turns(_dialog4(), "dialog", 2, n_sources=3)
    assert len(out) == 4
    assert all("src" not in ln for ln in out)


def test_invalid_src_keeps_the_line():
    out = _normalize_turns(_dialog4(src0=["x", 0, 99]), "dialog", 2, n_sources=3)
    assert len(out) == 4
    assert out[0]["text"].startswith("first claim")
    assert "src" not in out[0]


def test_no_source_count_drops_src():
    out = _normalize_turns(_dialog4(src0=[1, 2]), "dialog", 2)
    assert len(out) == 4
    assert all("src" not in ln for ln in out)


def test_rhythm_layer_keeps_src_and_adds_none():
    from vozonda_api.rhythm import profile_for
    from vozonda_api.rhythm_layer import BACK_CHANNELS, apply_rhythm_layer

    p = profile_for("balanced", 2)
    assert p is not None
    srcs = [[1], [2], [1, 2], [1]]
    lines = []
    for i in range(8):
        text = (
            f"Sentence one about the source material here point {i}. "
            "Sentence two adds detail to the picture. "
            "Sentence three keeps explaining the topic. "
            "Sentence four ends the turn for now."
        )
        lines.append({"speaker": "AB"[i % 2], "text": text, "src": srcs[i % 4]})
    out = apply_rhythm_layer(lines, p, "en", seed="citations")
    assert len(out) >= len(lines)
    # kept lines (verbatim or split parts) cite only sources the input cited
    for ln in out:
        if "src" in ln:
            assert ln["src"] in srcs, ln
    # every input citation still shows on some kept line
    for src in srcs:
        assert any(ln.get("src") == src for ln in out), src
    # added back-channels are short interjections the input never had
    for ln in out:
        if ln["text"] in BACK_CHANNELS["en"]:
            assert "src" not in ln, ln


def test_role_repair_keeps_src():
    from vozonda_api import script_contract as sc

    original = {"speaker": "B", "text": " ".join(f"word{i}" for i in range(40)), "src": [2]}
    new = [
        {"speaker": "B", "text": " ".join(f"word{i}" for i in range(20))},
        {"speaker": "A", "text": " ".join(f"word{i}" for i in range(20, 40))},
    ]
    repaired = sc.accept_repair(original, new, "A", "B")
    assert repaired is not None
    assert [r.get("src") for r in repaired] == [[2], [2]]
    assert sc.splice([original], {0: repaired}) == repaired


def _tray_items():
    return [
        {"position": 0, "kind": "article", "title": "First Story",
         "origin_url": "https://a.example/1", "role": "main", "words": 100,
         "text": "SECRET-SOURCE-TEXT-ONE"},
        {"position": 1, "kind": "file-text", "title": "My Upload",
         "origin_url": None, "role": "main", "words": 50,
         "text": "SECRET-SOURCE-TEXT-TWO"},
    ]


def _multi_row():
    return {
        "id": "ep-multi",
        "title": "Ep",
        "description": "About things",
        "url": "https://a.example/1",
        "digest_sources": json.dumps(["https://a.example/1", "https://b.example/2"]),
        "script": "[]",
        "chapters": None,
        "created_at": 1700000002.0,
        "style": "balanced",
        "format": "dialog",
    }


def test_rss_item_description_lists_sources(monkeypatch):
    import vozonda_api.routers.feeds as feeds_mod
    import vozonda_api.sources as sources_mod

    monkeypatch.setattr(sources_mod, "job_sources", lambda job, with_text=False: _tray_items())
    item = feeds_mod._feed_item(_multi_row(), "http://testserver", "Thu, 24 Sep 2026 10:00:00 GMT", [])
    assert "Sources:" in item
    assert "[1] First Story — https://a.example/1" in item
    assert "[2] My Upload" in item
    assert "SECRET-SOURCE-TEXT-ONE" not in item
    assert "SECRET-SOURCE-TEXT-TWO" not in item


def test_rss_single_source_has_no_sources_list():
    import vozonda_api.routers.feeds as feeds_mod

    row = dict(_multi_row(), id="ep-single", digest_sources=None, url="https://a.example/1")
    item = feeds_mod._feed_item(row, "http://testserver", "Thu, 24 Sep 2026 10:00:00 GMT", [])
    assert "Sources:" not in item
    assert "Source: https://a.example/1" in item


def test_nostr_content_lists_sources(monkeypatch):
    from vozonda_api import nostr_publish
    import vozonda_api.sources as sources_mod

    monkeypatch.setattr(sources_mod, "job_sources", lambda job, with_text=False: _tray_items())
    job = {
        "title": "Ep", "description": "About things", "digest": True,
        "digest_sources": ["https://a.example/1", "https://b.example/2"],
    }
    event = nostr_publish.build_episode_event(
        {"name": "Show"}, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
    assert event["kind"] == 54
    assert "Sources:" in event["content"]
    assert "[1] First Story — https://a.example/1" in event["content"]
    assert "[2] My Upload" in event["content"]
    assert "SECRET-SOURCE-TEXT-ONE" not in event["content"]
    assert "SECRET-SOURCE-TEXT-TWO" not in event["content"]


def test_nostr_single_source_has_no_sources_list():
    from vozonda_api import nostr_publish

    job = {"title": "Ep", "description": "About things", "url": "https://example.com/1"}
    event = nostr_publish.build_episode_event(
        {"name": "Show"}, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
    assert event["content"] == "About things"


def test_digest_prompt_numbers_sources_and_src_rule(monkeypatch):
    from vozonda_api import pipeline

    seen: dict = {}

    async def fake_script_call(*, prompt, **kw):
        seen["prompt"] = prompt
        lines = [
            {"speaker": "AB"[i % 2], "text": f"turn number {i} here", "section": i // 3,
             "src": [1] if i % 2 == 0 else [2]}
            for i in range(6)
        ]
        return lines, "desc"

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    sections = [
        {"index": 0, "position": 0, "title": "Alpha", "url": "https://a.example/1",
         "body": "alpha body " * 50, "role": "main"},
        {"index": 1, "position": 1, "title": "Beta", "url": "https://b.example/2",
         "body": "beta body " * 50, "role": "main"},
    ]
    out, _desc, _chapters = asyncio.run(pipeline._script_digest(sections, budget_chars=10000))
    prompt = seen["prompt"]
    assert "[1]" in prompt and "[2]" in prompt
    assert '"src"' in prompt
    # the citation rule sits in the output-format part, before the sources
    assert prompt.index('"src"') < prompt.index("SOURCE MATERIAL")
    assert [ln.get("src") for ln in out] == ([[1], [2]] * 3)


def test_combine_prompt_numbers_sources_and_src_rule(tmp_path, monkeypatch):
    import vozonda_api.doctor as doc
    import vozonda_api.jobs as jobs_mod
    from vozonda_api import pipeline
    from vozonda_api.jobs import JobStore

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(doc, "blocking_problem", lambda: None)
    seen: dict = {"prompts": []}

    async def fake_fetch(url):
        return f"<html>{url}</html>"

    async def fake_extract(url, html=None, **kw):
        name = "Bitcoin" if "btc" in url else "Ethereum"
        return f"{name} whitepaper", f"{name} text. " + "word " * 400, None

    async def fake_script_call(*, prompt, **kw):
        seen["prompts"].append(prompt)
        lines = [
            {"speaker": "AB"[i % 2], "text": f"turn number {i} here", "src": [1, 9, "x"]}
            for i in range(6)
        ]
        return lines, "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return tmp_path / f"{job_id}.wav"

    async def fake_master(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))

    store = JobStore()
    store.create("digest-cit", "digest:digest-cit", digest=True,
                 digest_sources=["https://btc.example/wp", "https://eth.example/wp"], combine=True)

    async def go():
        async for _ in pipeline.run_job(store, "digest-cit"):
            pass

    asyncio.run(go())
    assert store.get("digest-cit")["state"] == "done"
    prompt = seen["prompts"][-1]
    assert "SOURCE 1 of 2" in prompt and "SOURCE 2 of 2" in prompt
    assert "[1]" in prompt and "[2]" in prompt
    assert '"src"' in prompt
    # the citation rule sits in the output-format part, before the sources
    assert prompt.index('"src"') < prompt.index("SOURCE 1 of 2")
