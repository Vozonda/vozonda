"""Script form check (prompt tuning 2026-09-25).

The rhythm rules sit before a source of several thousand words, so the local
model had drifted from them by the time it wrote: every turn 20-30 words, no
quick reactions. A short form check AFTER the source (like the three-host
FINAL CHECK) keeps them close. A worked content example was tried and dropped:
the model copied it verbatim into the episode (v2, a bakery in a Lightning
Network episode), which breaks grounding.
"""

import asyncio

from vozonda_api import pipeline
from vozonda_api.styles import STYLE_TEMPLATES


def _prompts(monkeypatch, **kw):
    seen: list[str] = []

    async def fake_script_call(*, prompt, **kwargs):
        seen.append(prompt)
        return [{"speaker": "A" if i % 2 else "B", "text": "word " * 20} for i in range(12)], "d"

    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    asyncio.run(pipeline._script("SOURCE-MARKER text about things", **kw))
    return seen


def test_dialog_prompt_ends_with_the_form_check(monkeypatch):
    prompt = _prompts(monkeypatch)[0]
    assert "FORM CHECK" in prompt
    assert prompt.index("FORM CHECK") > prompt.index("SOURCE-MARKER")
    assert "its own turn" in prompt[prompt.index("FORM CHECK"):]


def test_narration_has_no_dialog_form_check(monkeypatch):
    prompt = _prompts(monkeypatch, fmt="narration")[0]
    assert "FORM CHECK" not in prompt


def test_no_worked_content_example_in_any_style():
    for name, template in STYLE_TEMPLATES.items():
        assert "bakery" not in template and "1890" not in template, name
