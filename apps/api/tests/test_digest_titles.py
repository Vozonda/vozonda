import asyncio

from vozonda_api import pipeline
from vozonda_api.pipeline import _digest_fallback_title, clean_title


def test_clean_title_strips_site_suffixes():
    assert clean_title("Europa Clipper - NASA Science") == "Europa Clipper"
    assert clean_title("Mars (planet) - Wikipedia") == "Mars (planet)"
    assert clean_title("Big News | Example.com") == "Big News"


def test_clean_title_keeps_real_subtitles():
    assert clean_title("Rust - a language for safe code") == "Rust - a language for safe code"
    assert clean_title("Plain title") == "Plain title"


def test_digest_fallback_title_cleaned():
    secs = [{"title": "Europa Clipper - NASA Science"}, {"title": "b"}, {"title": "c"}]
    assert _digest_fallback_title(secs) == "Digest: Europa Clipper + 2 more"


def test_digest_prompt_forbids_speaker_letter(monkeypatch):
    seen = {}

    async def fake_call(prompt, **kw):
        seen["prompt"] = prompt
        turns = [
            {"speaker": "AB"[i % 2], "text": "A longer line of spoken text for the test.", "section": 0}
            for i in range(12)
        ]
        return turns, ""

    monkeypatch.setattr(pipeline, "script_call", fake_call)
    monkeypatch.setattr(pipeline, "llm_chain", lambda: [{"name": "x", "base": "b"}])
    secs = [{"index": 0, "title": "Europa Clipper - NASA Science", "url": "u", "body": "text"}]
    _, _, chapters = asyncio.run(pipeline._script_digest(secs))
    assert "never call themselves" in seen["prompt"]
    assert "Host A" in seen["prompt"] and "labels only" in seen["prompt"]
    assert "NASA Science" not in seen["prompt"]
    assert chapters[0]["title"] == "Europa Clipper"
