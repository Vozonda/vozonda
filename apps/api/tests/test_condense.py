"""An oversized source is condensed, not cut (VOZONDA-TRAY-CONDENSE).

Unit level (fake pipeline._chat_completion): paragraph-boundary chunks with
proportional targets, a fitting result, and the old cut with fallback_cut on
provider failure. Pipeline level: a digest job with one
oversized source records condensed meta and prompts with the condensed text;
a short source never reaches the model.
"""

import asyncio
import re

from vozonda_api import pipeline
from vozonda_api.budget import allocate
from vozonda_api.condense import (
    condense,
    condense_with_flag,
    cut_at_paragraph,
    split_chunks,
)


def _shares_in(prompts: list[str]) -> list[int]:
    return [int(re.search(r"about (\d+) characters", p).group(1)) for p in prompts]  # type: ignore[union-attr]


def test_chunks_split_at_paragraph_boundaries():
    p1, p2, p3 = "A" * 4000, "B" * 4000, "C" * 4000
    text = f"{p1}\n\n{p2}\n\n{p3}"
    chunks = split_chunks(text)
    assert len(chunks) == 2
    assert chunks[0] == f"{p1}\n\n{p2}"
    assert chunks[1] == p3
    # no chunk ends mid-paragraph: rejoining restores the text
    assert "\n\n".join(chunks) == text
    for chunk in chunks:
        assert len(chunk) <= 12000


def test_each_chunk_gets_its_proportional_target_and_result_fits(monkeypatch):
    prompts: list[str] = []

    async def fake_chat(prov, prompt, max_tokens=4096):
        prompts.append(prompt)
        (share,) = _shares_in([prompt])
        return "M" * share

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    text = "\n\n".join(["A" * 4000, "B" * 4000, "C" * 4000])
    target = 3000
    out, fallback = asyncio.run(condense_with_flag(text, target, "de"))
    assert fallback is False
    # 8002 of 12004 chars -> 2000, 4000 of 12004 -> the 1000 remainder
    assert _shares_in(prompts) == [2000, 1000]
    assert "de" in prompts[0]
    assert len(out) <= target


def test_failing_provider_falls_back_to_the_cut(monkeypatch):
    async def failing_chat(prov, prompt, max_tokens=4096):
        raise RuntimeError("no model")

    monkeypatch.setattr(pipeline, "_chat_completion", failing_chat)
    text = "\n\n".join(["word one " * 400, "word two " * 400, "word three " * 400])
    target = 1000
    out, fallback = asyncio.run(condense_with_flag(text, target, "en"))
    assert fallback is True
    assert out == text[:target]
    assert len(out) <= target


def test_model_overshoot_is_trimmed_at_a_paragraph_boundary(monkeypatch):
    async def chat(prov, prompt, max_tokens=4096):
        # a model that rambles: returns the whole chunk despite the share
        return prompt.split("Source section:\n", 1)[1]

    monkeypatch.setattr(pipeline, "_chat_completion", chat)
    text = f'{"firstpara " * 40}\n\n{"secondpara " * 40}'
    target = 200
    out, fallback = asyncio.run(condense_with_flag(text, target, "en"))
    assert fallback is False
    assert out == cut_at_paragraph(text, target)
    assert len(out) <= target


def test_empty_chain_falls_back_to_the_cut(monkeypatch):
    import vozonda_api.providers as providers_mod

    async def fail_if_called(prov, prompt, max_tokens=4096):
        raise AssertionError("model must not be called without providers")

    monkeypatch.setattr(providers_mod, "llm_chain", list)
    monkeypatch.setattr(pipeline, "_chat_completion", fail_if_called)
    text = "x" * 5000
    out, fallback = asyncio.run(condense_with_flag(text, 1000, "en"))
    assert fallback is True
    assert out == "x" * 1000


def test_short_text_is_returned_untouched_without_a_model_call(monkeypatch):
    async def fail_if_called(prov, prompt, max_tokens=4096):
        raise AssertionError("a short source is never sent to the model")

    monkeypatch.setattr(pipeline, "_chat_completion", fail_if_called)
    out = asyncio.run(condense("small text", 5000, "en"))
    assert out == "small text"


def _digest_env(tmp_path, monkeypatch, chat):
    import vozonda_api.doctor as doc
    import vozonda_api.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(doc, "blocking_problem", lambda: None)
    seen: dict = {"prompts": [], "chats": 0}

    async def fake_chat(prov, prompt, max_tokens=4096):
        seen["chats"] += 1
        return await chat(prov, prompt, max_tokens)

    async def fake_script_call(*, prompt, **kw):
        seen["prompts"].append(prompt)
        turns = [{"speaker": "AB"[i % 2], "text": f"turn {i}", "section": i // 3} for i in range(6)]
        return turns, "desc"

    async def fake_voice(store, job_id, lines, workdir, **kw):
        return tmp_path / f"{job_id}.wav"

    async def fake_master(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "_voice", fake_voice)
    monkeypatch.setattr(pipeline, "_master", fake_master)
    monkeypatch.setattr(pipeline, "_attach_insights", lambda *a, **k: asyncio.sleep(0))
    # the episode title call is not a condense call: keep it out of the chat count
    monkeypatch.setattr(pipeline, "_generate_episode_title", lambda *a, **k: asyncio.sleep(0))
    from vozonda_api.jobs import JobStore as JS

    return JS(), seen


def _drain(store, job_id, budget_chars):
    async def go():
        job = store.get(job_id)
        async for _ in pipeline._run_digest_job(store, job_id, job, budget_chars):
            pass

    asyncio.run(go())


def _extract_meta(job):
    stages = {s["name"]: s for s in job.get("stages", [])}
    return (stages.get("extract", {}).get("meta", {}) or {}).get("condensed", [])


def test_digest_with_one_oversized_source_records_condensed_meta(tmp_path, monkeypatch):
    async def chat(prov, prompt, max_tokens=4096):
        (share,) = _shares_in([prompt])
        return "M" * share

    store, seen = _digest_env(tmp_path, monkeypatch, chat)
    paras = ["fact 42 carburetors " * 100] * 3
    long_body = "\n".join(paras).strip()
    short_body = ("brief background " * 20).strip()
    store.create(
        "digest-cond1",
        "digest:digest-cond1",
        digest=True,
        digest_sources=["text:Long paper\n" + long_body, "text:Short note\n" + short_body],
    )
    budget_chars = 3000
    shares = allocate([len(long_body), len(short_body)], ["main", "main"], budget_chars)
    assert shares[0] < len(long_body)
    _drain(store, "digest-cond1", budget_chars)
    job = store.get("digest-cond1")
    assert job["state"] == "done", job.get("error")
    condensed = _extract_meta(job)
    assert condensed == [
        {
            "position": 0,
            "from_chars": len(long_body),
            "to_chars": shares[0],
            "fallback_cut": False,
        }
    ]
    # the prompt holds the condensed text, not the cut original
    assert "M" * shares[0] in seen["prompts"][-1]
    assert "fact 42 carburetors" not in seen["prompts"][-1]
    # the short source never reached the model: one chunk, one call
    assert seen["chats"] == 1


def test_digest_with_failing_provider_records_fallback_cut(tmp_path, monkeypatch):
    async def chat(prov, prompt, max_tokens=4096):
        raise RuntimeError("no model")

    store, seen = _digest_env(tmp_path, monkeypatch, chat)
    long_body = "\n".join(["fact 42 carburetors " * 100] * 3).strip()
    short_body = "brief background"
    store.create(
        "digest-cond2",
        "digest:digest-cond2",
        digest=True,
        digest_sources=["text:Long paper\n" + long_body, "text:Short note\n" + short_body],
    )
    budget_chars = 3000
    shares = allocate([len(long_body), len(short_body)], ["main", "main"], budget_chars)
    _drain(store, "digest-cond2", budget_chars)
    job = store.get("digest-cond2")
    assert job["state"] == "done", job.get("error")
    condensed = _extract_meta(job)
    assert condensed == [
        {
            "position": 0,
            "from_chars": len(long_body),
            "to_chars": shares[0],
            "fallback_cut": True,
        }
    ]
    assert "fact 42" in seen["prompts"][-1]


def test_digest_with_short_sources_never_calls_the_model(tmp_path, monkeypatch):
    async def chat(prov, prompt, max_tokens=4096):
        raise AssertionError("a short source is never sent to the model")

    store, _seen = _digest_env(tmp_path, monkeypatch, chat)
    store.create(
        "digest-cond3",
        "digest:digest-cond3",
        digest=True,
        digest_sources=["text:Note one\nshort body one", "text:Note two\nshort body two"],
    )
    _drain(store, "digest-cond3", 20000)
    job = store.get("digest-cond3")
    assert job["state"] == "done", job.get("error")
    assert _extract_meta(job) == []
