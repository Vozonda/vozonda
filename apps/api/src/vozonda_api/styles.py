"""Style catalogue for vozonda dialogue scripts.

Personas, tunable parameters and one-line docs live here so the whole
voice of the product is editable in one file. pipeline.py only consumes
what this module exports.

The canonical style data is defined in style_registry.py. This module
re-exports derived read-only views for backwards compatibility.
"""

from .style_registry import (
    EMOTION_DOCS,
    EMOTION_IDS,
    EMOTION_INSTRUCTS,
    HOOK_BRIEFS,
    SCRIPT_PROMPT,
    STYLE_DOCS,
    STYLE_IDS,
    STYLE_TEMPLATES,
    STYLES,
    dialog_rules,
    get_setting_safe,
)
from .style_registry import SCRIPT_PARAMS_FLAT as SCRIPT_PARAMS

__all__ = [
    "EMOTION_DOCS", "EMOTION_IDS", "EMOTION_INSTRUCTS", "FORM_CHECK", "HOOK_BRIEFS",
    "SCRIPT_PARAMS", "SCRIPT_PROMPT", "STYLES", "STYLE_DOCS", "STYLE_IDS",
    "STYLE_TEMPLATES", "dialog_rules", "get_setting_safe",
]

# Appended AFTER the source text (pipeline._script): the rules above sit before
# thousands of source words and the local model drifts from them by the time
# it writes (bench 2026-09-25: every turn 20-30 words, no quick reactions).
FORM_CHECK = (
    "FORM CHECK before answering, then write the JSON: "
    "(1) about one turn in five is a quick reaction of one to five words that stands alone as its own turn; "
    "(2) turn lengths vary, long turns only where a host explains or tells an example; "
    "(3) about one turn in six is a question, and every question gets a concrete answer; "
    "(4) the hosts speak casually in the episode language (in English with contractions such as it's, don't, that's); "
    "(5) every fact comes from the source text above, nothing from these instructions; "
    "(6) when SUCCESS CRITERIA open this prompt, the word split and turn lengths meet them."
)
