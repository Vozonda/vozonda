"""A truncated LLM answer never ends the script mid-sentence (2026-10-02).

The LLM crashed while streaming a draft; _repair_json closed the half JSON and the
pipeline voiced a script whose last turn was 'The key takeaway is that Lightning moves
transactions off-chain for'. A repaired answer drops its half-written last turn; a
complete answer is never touched, whatever its last turn ends with."""
from vozonda_api.providers.script import _parse_first_json_array

HEAD = '[{"speaker":"A","text":"First complete turn."},{"speaker":"B","text":"Second one, also complete."}'


def test_a_truncated_answer_drops_the_half_written_turn():
    raw, _ = _parse_first_json_array(HEAD + ',{"speaker":"A","text":"The key takeaway is that Lightning moves')
    assert [t["text"] for t in raw] == ["First complete turn.", "Second one, also complete."]


def test_a_truncated_answer_after_a_complete_turn_keeps_it():
    raw, _ = _parse_first_json_array(HEAD + ',{"speaker":"A","text":"That is all."}')
    assert raw[-1]["text"] == "That is all."


def test_a_complete_answer_is_never_trimmed():
    raw, _ = _parse_first_json_array(HEAD + ',{"speaker":"A","text":"Thanks for listening"}]')
    assert raw[-1]["text"] == "Thanks for listening"
