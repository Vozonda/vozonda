"""Script turn normalisation (2026-09-23): a digest arrived as whole sections in
single objects ('[SECTION:0:Bitcoin] A: "..." B: "..."') and played as ONE voice."""

import pytest

from vozonda_api.pipeline import _normalize_turns

# the shape job digest-42e925 received, shortened
BROKEN = [
    {"speaker": "A", "text": '[SECTION:0:Bitcoin] A: "Willkommen zu unserer Zusammenfassung." B: "Danke, legen wir los." A: "Das Whitepaper von 2008."'},
    {"speaker": "A", "text": "Als Nächstes: Ethereum."},
    {"speaker": "A", "text": '[SECTION:1:Ethereum] B: "Buterin beschreibt Smart Contracts." A: "Und dezentrale Anwendungen."'},
    {"speaker": "A", "text": "Das war unsere Zusammenfassung."},
]


def test_inline_turns_are_split_and_section_tags_dropped():
    out = _normalize_turns(BROKEN, "dialog", 2)
    assert [t["speaker"] for t in out] == ["A", "B", "A", "A", "B", "A", "A"]
    assert out[0]["text"] == "Willkommen zu unserer Zusammenfassung."
    assert not any("SECTION" in t["text"] or t["text"].startswith(('A:', 'B:')) for t in out)


def test_prose_with_a_colon_is_not_split():
    lines = [{"speaker": "A", "text": "Plan B: cheaper, and option A: faster."},
             {"speaker": "B", "text": "Right."}, {"speaker": "A", "text": "So?"}, {"speaker": "B", "text": "Yes."}]
    assert _normalize_turns(lines, "dialog", 2)[0]["text"] == "Plan B: cheaper, and option A: faster."


def test_single_speaker_dialog_is_rejected_for_two_hosts():
    one_voice = [{"speaker": "A", "text": f"line {i}"} for i in range(6)]
    with pytest.raises(ValueError, match="single speaker"):
        _normalize_turns(one_voice, "dialog", 2)
    assert len(_normalize_turns(one_voice, "dialog", 1)) == 6
    assert len(_normalize_turns(one_voice, "narration", 2)) == 6


def test_section_index_is_kept_for_chapters():
    lines = [{"speaker": s, "text": "t", "section": i // 2} for i, s in enumerate("ABABAB")]
    assert [t["section"] for t in _normalize_turns(lines, "dialog", 2)] == [0, 0, 1, 1, 2, 2]
