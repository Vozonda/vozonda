"""An emptied custom prompt means 'use the built-in' for THAT style (2026-10-02).

The settings box saves '' when cleared. The pipeline treated '' as a custom prompt and
then fell back to SCRIPT_PROMPT, so an emptied debate or narration box wrote the episode
with the balanced dialogue prompt."""
import asyncio

import pytest

from vozonda_api import pipeline
from vozonda_api.styles import STYLE_TEMPLATES


def _first_prompt(monkeypatch, style, fmt="dialog", stored=""):
    prompts = []

    async def fake_script_call(*, prompt, **kw):
        prompts.append(prompt)
        return [{"speaker": "AB"[k % 2], "text": "word " * 20} for k in range(20)], "d"

    from vozonda_api import settings_store

    orig = settings_store.get_setting
    monkeypatch.setattr(settings_store, "get_setting",
                        lambda k: stored if k.startswith(("script.style.", "script.balanced", "script.narration")) else orig(k))
    monkeypatch.setattr(pipeline, "script_call", fake_script_call)
    monkeypatch.setattr(pipeline, "llm_chain", lambda: [{"name": "t", "base": "http://x", "model": "m"}])
    try:
        asyncio.run(pipeline._script("Source text. " * 300, style=style, fmt=fmt, language="en", n_hosts=2 if fmt == "dialog" else 1))
    except RuntimeError:
        pass
    return prompts[0]


@pytest.mark.parametrize("style", ["debate", "socrates", "asmr"])
def test_an_emptied_style_box_uses_that_styles_template(monkeypatch, style):
    prompt = _first_prompt(monkeypatch, style)
    opening = STYLE_TEMPLATES[style].splitlines()[0]
    assert opening in prompt, "the style's own template, not the balanced one"


def test_an_emptied_narration_box_uses_the_narration_prompt(monkeypatch):
    prompt = _first_prompt(monkeypatch, "balanced", fmt="narration")
    assert pipeline.NARRATION_BASE.splitlines()[0] in prompt
