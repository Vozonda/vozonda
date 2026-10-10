"""'Who can listen?' cards (#56): text checks on the web sources (no browser), in the style of
test_custom_styles_ui.py. They pin the behaviour, not just the words: how a level is derived, what each
level sets, the safe order of the switches, and that nothing pretends a feature exists."""

from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib"
CARD = (WEB / "components" / "ReachCard.svelte").read_text(encoding="utf-8")
SETTINGS = (WEB / "components" / "SettingsScreen.svelte").read_text(encoding="utf-8")


def _apply_reach() -> str:
    start = SETTINGS.index("async function applyReach(")
    return SETTINGS[start:SETTINGS.index("async function confirmPublish(", start)]


# ---- ReachCard -----------------------------------------------------------------------------------

def test_three_levels_and_the_question():
    assert "who can listen to {show.name}?" in CARD
    for label in (">only in vozonda<", ">my podcast app<", ">public<"):
        assert label in CARD, label


def test_level_is_derived_from_the_three_switches():
    # a nostr-only show is public; rss with public is public; rss alone is the private feed
    assert "nostrOn || (rssOn && publicOn) ? 'public' : rssOn ? 'podcast' : 'vozonda'" in CARD


def test_what_each_level_sets():
    assert "{ rss: true, public: false, nostr: false }" in CARD  # my podcast app
    assert "{ rss: false, public: false, nostr: false }" in CARD  # only in vozonda
    assert "onchoose({ rss: draftRss, public: true, nostr: draftNostr && !noNostr })" in CARD


def test_public_keeps_at_least_one_channel():
    assert "if (!rss && !nostr) return" in CARD
    assert "disabled={!draftRss && !draftNostr}" in CARD


def test_public_is_confirmed_once():
    assert "make {show.name} public?" in CARD
    assert "anyone can listen; directories and apps may keep copies." in CARD


def test_the_default_show_cannot_publish_to_nostr():
    assert "const noNostr = $derived(!!show.fixed)" in CARD
    assert "disabled={noNostr}" in CARD
    assert "the default show has no nostr key of its own" in CARD


def test_warnings_when_the_choice_cannot_work_from_this_address():
    assert "your phone cannot reach this address" in CARD
    assert "apple and spotify cannot reach ${host}: only your own devices do." in CARD


def test_checklist_is_honest():
    assert "https://github.com/Vozonda/vozonda/issues/58" in CARD and "not yet supported" in CARD
    # no check mark for a feature that does not exist yet (the fleet draft ticked 'square cover' for any feed)
    assert "hasCover" not in CARD
    assert "address.scope === 'internet'" in CARD and "address.answers === true" in CARD


# ---- SettingsScreen ------------------------------------------------------------------------------

def test_settings_render_a_card_per_show_and_drop_the_old_control():
    assert "<ReachCard {show} address={dist.address}" in SETTINGS
    for gone in ("MASTER_REACHES", "chooseReach(", "const REACHES", "reachOf("):
        assert gone not in SETTINGS, gone


def test_switches_change_in_a_safe_order():
    """Narrow first, open last: a change never exposes more than its end state."""
    body = _apply_reach()
    order = [body.index(step) for step in (
        "if (!t.public && isPublic) await setShowPublic(s.slug, false)",
        "if (!t.nostr && s.nostr === '1') await setNostrPublish(s.slug, false)",
        "if ((s.rss === '1') !== t.rss) await setShowRss(s.slug, t.rss)",
        "if (t.public && !isPublic) await setShowPublic(s.slug, true)",
        "if (t.nostr && s.nostr !== '1') await setNostrPublish(s.slug, true, true)",
    )]
    assert order == sorted(order)


def test_turning_nostr_on_is_confirmed_first():
    body = _apply_reach()
    assert "if (t.nostr && s.nostr !== '1' && !nostrConfirmed)" in body
    assert body.index("!nostrConfirmed") < body.index("setNostrPublish(s.slug, true, true)")
    assert "await applyReach(show, target, true)" in SETTINGS
