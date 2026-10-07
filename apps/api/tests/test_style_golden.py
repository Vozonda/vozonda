"""Golden fixture tests for per-style script prompts.

Freezes the exact prompt that pipeline._script builds for every style in
STYLE_IDS. Run with VOZONDA_UPDATE_GOLDEN=1 or --update-golden to regenerate.
"""

import json
import os
import random
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "style_prompts"
UPDATE_GOLDEN = os.environ.get("VOZONDA_UPDATE_GOLDEN") == "1" or "--update-golden" in sys.argv


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--update-golden", action="store_true", help="Regenerate golden fixtures")


def pytest_configure(config: pytest.Config) -> None:
    global UPDATE_GOLDEN
    if config.getoption("--update-golden"):
        UPDATE_GOLDEN = True


async def _fake_script_call(
    *,
    prompt: str,
    model: str = "qwen3.6-35b",
    base: str = "http://127.0.0.1:30001/v1",
    key: str = "",
    max_tokens: int = 16384,
    temperature: float = 0.7,
    timeout: float = 600.0,
) -> tuple[list[dict[str, Any]], str]:
    """Fake script_call that records the prompt and returns a valid two-speaker script."""
    _fake_script_call.last_prompt = prompt
    return [
        {"speaker": "A", "text": "Welcome to the episode."},
        {"speaker": "B", "text": "Thanks for having me."},
        {"speaker": "A", "text": "Let's dive in."},
        {"speaker": "B", "text": "Sounds good."},
    ], "Test episode description."


def _fake_llm_chain() -> list[dict]:
    """Fake llm_chain that returns one fake provider."""
    return [{"name": "fake", "base": "http://fake", "model": "fake", "key": ""}]


def _load_fixture(style: str) -> dict[str, Any] | None:
    path = FIXTURE_DIR / f"{style}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _save_fixture(style: str, data: dict[str, Any]) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{style}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _diff(first: str, second: str) -> str:
    import difflib
    return "\n".join(difflib.unified_diff(first.splitlines(), second.splitlines(), lineterm=""))


def _get_style_directives(style: str) -> dict[str, str]:
    """Get style directives from providers/__init__.py resolve_emotion_delivery for both tag modes."""
    from vozonda_api.providers import resolve_emotion_delivery

    with_tags = resolve_emotion_delivery("voxtral", emotion="neutral", style=style)
    without_tags = resolve_emotion_delivery("qwen_tts", emotion="neutral", style=style)
    return {
        "with_tags": with_tags.get("prompt_directive", ""),
        "without_tags": without_tags.get("prompt_directive", ""),
    }


def _get_rhythm_profile(style: str):
    """Get the rhythm profile for a style."""
    from vozonda_api.rhythm import profile_for
    return profile_for(style, 3 if style == "dude" else 2)


@pytest.fixture(autouse=True)
def _deterministic_random():
    """Ensure deterministic random state for each test."""
    random.seed(1234)
    from vozonda_api import rhythm
    rhythm._rng = random.Random(1234)
    yield
    rhythm._rng = random.Random()


class TestStyleGolden:
    """Test that per-style prompts match golden fixtures."""

    @pytest.mark.parametrize("style", [
        "asmr", "meditation", "eli5", "balanced",
        "storyteller", "serious", "slang",
        "sensational", "debate", "clash", "conspiracy", "futbol",
        "socrates", "dude",
        "true_crime", "tech_roast",
        "noir", "trivia", "courtroom", "crisis_room",
    ])
    def test_style_prompt_matches_golden(self, style: str):
        """Test that the prompt for each style matches the golden fixture."""
        # Ensure deterministic random state - patch random in rhythm module
        import random as random_module

        from vozonda_api import rhythm
        
        # Create a deterministic RNG
        deterministic_rng = random_module.Random(1234)
        
        # Patch rhythm's plan_for_profile to use our deterministic RNG
        original_plan_for_profile = rhythm.plan_for_profile
        
        def patched_plan_for_profile(words: int, p: rhythm.Profile, rng: random_module.Random | None = None):
            return original_plan_for_profile(words, p, deterministic_rng)
        
        def patched_randint(a, b):
            return deterministic_rng.randint(a, b)
        
        with patch("vozonda_api.pipeline.script_call", _fake_script_call), \
             patch("vozonda_api.pipeline.llm_chain", new=_fake_llm_chain), \
             patch("vozonda_api.pipeline._chat_completion", new_callable=AsyncMock) as mock_chat, \
             patch("vozonda_api.rhythm.plan_for_profile", patched_plan_for_profile), \
             patch("vozonda_api.rhythm.random.randint", patched_randint):

            mock_chat.return_value = json.dumps([
                {"speaker": "A", "text": "Welcome to the episode."},
                {"speaker": "B", "text": "Thanks for having me."},
                {"speaker": "A", "text": "Let's dive in."},
                {"speaker": "B", "text": "Sounds good."},
            ]) + "\nDESCRIPTION: Test episode description."

            # Call pipeline._script to build the prompt
            import asyncio

            from vozonda_api.pipeline import _script

            async def run_script():
                return await _script(
                    body="source text " * 300,
                    style=style,
                    fmt="dialog",
                    tone="neutral",
                    language="en",
                    n_hosts=3 if style == "dude" else 2,
                    explicit=False,
                    host_names=None,
                    title="",
                    tts_engine="qwen_tts",
                    emotion="neutral",
                    target_minutes=6,
                    length_meta={},
                    focus=None,
                )

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            _, _ = loop.run_until_complete(run_script())

            # Get the prompt that was passed to script_call
            prompt = _fake_script_call.last_prompt

            # Collect all style data
            from vozonda_api.pipeline import _STYLE_SPEAKER_INSTRUCTS
            from vozonda_api.styles import HOOK_BRIEFS, SCRIPT_PARAMS, STYLE_DOCS

            style_data = {
                "style": style,
                "prompt": prompt,
                "style_docs": STYLE_DOCS.get(style, ""),
                "hook_brief": HOOK_BRIEFS.get(style, ""),
                "script_params": SCRIPT_PARAMS.get(style, {}),
                "speaker_instructs": _STYLE_SPEAKER_INSTRUCTS.get(style, {}),
                "style_directives": _get_style_directives(style),
            }

            # Compare with fixture or update
            fixture = _load_fixture(style)
            if fixture is None or UPDATE_GOLDEN:
                if UPDATE_GOLDEN or fixture is None:
                    _save_fixture(style, style_data)
                    if fixture is None:
                        pytest.skip(f"Created new golden fixture for {style}")
                else:
                    pytest.skip(f"Fixture updated for {style}")

            # Compare prompt
            if fixture["prompt"] != prompt:
                diff = _diff(fixture["prompt"], prompt)
                pytest.fail(f"Prompt mismatch for style '{style}':\n{diff}")

            # Compare other fields
            for key in ("style_docs", "hook_brief", "script_params", "speaker_instructs", "style_directives"):
                if fixture[key] != style_data[key]:
                    diff = _diff(json.dumps(fixture[key], indent=2, sort_keys=True), json.dumps(style_data[key], indent=2, sort_keys=True))
                    pytest.fail(f"{key} mismatch for style '{style}':\n{diff}")


if __name__ == "__main__":
    # Allow running directly with --update-golden
    if "--update-golden" in sys.argv:
        os.environ["VOZONDA_UPDATE_GOLDEN"] = "1"
    pytest.main([__file__, "-v"])