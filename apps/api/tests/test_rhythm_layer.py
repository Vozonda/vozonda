"""Deterministic rhythm layer (2026-10-02): split, insert and drop quick reactions by code.

The model writes content and roles; quick-reaction share and over-long monologues are
mechanical and are enforced here (bench: the 35B gave 0 or 48 percent quick turns
against a 15-35 percent target)."""

from itertools import pairwise

from vozonda_api.rhythm import PROFILES, QUICK_MAX
from vozonda_api.rhythm_layer import BACK_CHANNELS, applies_to, apply_rhythm_layer


def _w(n, word="word"):
    return " ".join([word] * n)


def _quick_share(lines):
    return sum(1 for ln in lines if len(ln["text"].split()) <= QUICK_MAX) / len(lines)


def _all_words(lines, exclude=()):
    return [w for ln in lines if ln["text"] not in exclude for w in ln["text"].split()]


def _monologues(n=20, words=30):
    half = (words - 4) // 2
    return [{"speaker": "AB"[i % 2], "text": f"Turn {i} {_w(half)}. Then {_w(words - 4 - half)} end."}
            for i in range(n)]


def test_too_few_quick_reactions_are_raised_into_the_band_without_touching_content():
    p = PROFILES["balanced"]
    src = _monologues()
    out = apply_rhythm_layer(src, p, "en", seed="job-1")
    lo, hi = p.quick_share
    assert lo <= _quick_share(out) <= hi
    assert _all_words(out, exclude=set(BACK_CHANNELS["en"])) == _all_words(src)
    for i, ln in enumerate(out):
        if ln["text"] in BACK_CHANNELS["en"]:
            assert out[i - 1]["speaker"] == out[i + 1]["speaker"] != ln["speaker"], "a reaction sits inside a turn"
    assert all(a["speaker"] != b["speaker"] for a, b in pairwise(out))


def test_back_channels_vary_and_never_repeat_back_to_back():
    out = apply_rhythm_layer(_monologues(40), PROFILES["balanced"], "en", seed=3)
    reactions = [ln["text"] for ln in out if ln["text"] in BACK_CHANNELS["en"]]
    assert len(set(reactions)) >= min(len(reactions), 5)
    assert all(a != b for a, b in pairwise(reactions))


def test_same_input_and_seed_give_the_same_script():
    a = apply_rhythm_layer(_monologues(), PROFILES["debate"], "en", seed="x")
    assert a == apply_rhythm_layer(_monologues(), PROFILES["debate"], "en", seed="x")


def test_german_uses_german_back_channels_and_unknown_languages_get_none_inserted():
    de = apply_rhythm_layer(_monologues(), PROFILES["balanced"], "de-DE", seed=1)
    assert any(ln["text"] in BACK_CHANNELS["de"] for ln in de)
    fr = apply_rhythm_layer(_monologues(), PROFILES["balanced"], "fr", seed=1)
    assert _all_words(fr) == _all_words(_monologues())


def test_reactions_the_model_wrote_are_never_removed_even_above_the_band():
    """Operator decision: interjections make the talk human; the layer only adds."""
    src = []
    for i in range(15):
        src += [{"speaker": "A", "text": f"Point {i} {_w(8)}."}, {"speaker": "B", "text": "Krass."},
                {"speaker": "A", "text": f"More {i} {_w(8)}."}, {"speaker": "B", "text": "Mhm."}]
    out = apply_rhythm_layer(src, PROFILES["balanced"], "de", seed=0)
    assert out == src


def test_monologues_over_the_band_are_split_at_sentence_ends_only():
    p = PROFILES["balanced"]
    long_turn = " ".join(f"This is sentence number {i} of the long turn." for i in range(20))
    src = _monologues(8) + [{"speaker": "B", "text": long_turn}] + _monologues(8)
    out = apply_rhythm_layer(src, p, "en", seed=0)
    limit = round(max(b[1] for b in p.speakers["B"].bands) * 1.3)
    assert all(len(ln["text"].split()) <= limit for ln in out)
    assert _all_words(out, exclude=set(BACK_CHANNELS["en"])) == _all_words(src)
    assert all(ln["text"].endswith((".", "?")) for ln in out)
    assert all(a["speaker"] != b["speaker"] for a, b in pairwise(out)), "a reaction sits between the parts"
    fr = apply_rhythm_layer(src, p, "fr", seed=0)
    assert _all_words(fr) == _all_words(src) and len(fr) <= len(src), "no back-channels: never split"


def test_calm_and_rhythm_free_styles_are_untouched():
    assert not applies_to(PROFILES["asmr"]) and not applies_to(PROFILES["meditation"])
    assert not applies_to(None)
    src = _monologues()
    assert apply_rhythm_layer(src, PROFILES["asmr"], "en") == src
    assert apply_rhythm_layer(src, None, "en") == src


def test_rare_third_never_gets_an_inserted_reaction():
    p = PROFILES["dude"]
    src = [{"speaker": "ABC"[i % 3], "text": f"S {i} {_w(28)}."} for i in range(21)]
    out = apply_rhythm_layer(src, p, "en", seed=2)
    assert all(ln["speaker"] != p.rare_third for ln in out if ln["text"] in BACK_CHANNELS["en"])


def test_never_inserts_a_bare_mhm():
    assert all(b.rstrip(".").lower() not in {"mhm", "mm", "uh-huh"} for pool in BACK_CHANNELS.values() for b in pool)


def test_never_inserts_a_back_channel_the_hosts_already_use():
    src = _monologues(20)
    src[0]["text"] = "Interesting. " + src[0]["text"]
    src[3]["text"] = "Exactly."
    out = apply_rhythm_layer(src, PROFILES["balanced"], "en", seed=5)
    inserted = [ln["text"] for ln in out if ln not in src and ln["text"] in BACK_CHANNELS["en"]]
    assert inserted and "Interesting." not in inserted and "Exactly." not in inserted
    assert len(set(inserted)) == len(inserted), "each inserted reaction is used once while the pool lasts"
