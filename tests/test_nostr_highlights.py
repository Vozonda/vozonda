"""Tests for NIP-84 swarm transcript highlights (kind 9802)."""

import pytest

from vozonda_api.nostr_highlights import (
    HIGHLIGHT_KIND,
    MAX_HIGHLIGHT_LENGTH,
    build_highlight_event,
    build_highlight_filter,
    clean_highlight_url,
    get_highlight_alt,
    get_highlight_sources,
    is_valid_highlight,
    parse_highlight,
)

# Sample 64-char hex keys (not real, just format-valid)
AUTHOR = "a" * 64
USER = "b" * 64
OTHER = "c" * 64
EPISODE_URL = "https://example.com/articles/deep-dive?utm_source=twitter&utm_medium=social&fbclid=xyz&id=42"
CLEANED_URL = "https://example.com/articles/deep-dive?id=42"


def test_highlight_kind_constant():
    assert HIGHLIGHT_KIND == 9802


def test_clean_highlight_url_strips_trackers():
    assert clean_highlight_url(EPISODE_URL) == CLEANED_URL
    # fragment stripped
    assert clean_highlight_url("https://example.com/page#section") == "https://example.com/page"
    # plain url unchanged
    assert clean_highlight_url("https://example.com/page") == "https://example.com/page"
    with pytest.raises(ValueError):
        clean_highlight_url("not-a-url")
    with pytest.raises(ValueError):
        clean_highlight_url("ftp://example.com/file")
    with pytest.raises(ValueError):
        clean_highlight_url("")


def test_build_highlight_basic():
    evt = build_highlight_event("This is a great insight.", EPISODE_URL)
    assert evt["kind"] == HIGHLIGHT_KIND
    assert evt["content"] == "This is a great insight."
    # r tag must be cleaned url
    assert any(t == ["r", CLEANED_URL] for t in evt["tags"])
    # alt tag present
    assert any(t[0] == "alt" for t in evt["tags"])
    # alt default = highlight
    assert any(t == ["alt", "highlight"] for t in evt["tags"])
    # created_at present
    assert isinstance(evt["created_at"], int)
    # valid
    ok, _ = is_valid_highlight(evt)
    assert ok


def test_build_highlight_with_context_and_p():
    evt = build_highlight_event(
        "key sentence",
        "https://example.com/episode/1",
        context="surrounding paragraph with more context",
        author_pubkey=AUTHOR,
        author_relay="wss://relay.damus.io",
        author_role="author",
        alt="highlight",
    )
    assert evt["content"] == "key sentence"
    assert any(t[0] == "r" and t[1] == "https://example.com/episode/1" for t in evt["tags"])
    assert any(t == ["alt", "highlight"] for t in evt["tags"])
    assert any(t[0] == "context" and "surrounding paragraph" in t[1] for t in evt["tags"])
    # p tag shape: ["p", hex, relay, role]
    p_tags = [t for t in evt["tags"] if t[0] == "p"]
    assert len(p_tags) == 1
    assert p_tags[0][1] == AUTHOR.lower()
    assert p_tags[0][2] == "wss://relay.damus.io"
    assert p_tags[0][3] == "author"
    ok, _ = is_valid_highlight(evt)
    assert ok


def test_build_highlight_with_p_no_relay_but_role():
    evt = build_highlight_event("text", "https://example.com/a", author_pubkey=AUTHOR, author_role="editor")
    p_tags = [t for t in evt["tags"] if t[0] == "p"]
    assert p_tags[0][1] == AUTHOR
    # role still present with empty relay placeholder per spec
    assert p_tags[0][2] == ""
    assert p_tags[0][3] == "editor"


def test_build_highlight_pubkey_and_alt_custom():
    evt = build_highlight_event("hi", "https://example.com/a", alt="custom alt", pubkey=USER)
    assert evt["pubkey"] == USER.lower()
    assert any(t == ["alt", "custom alt"] for t in evt["tags"])


def test_build_highlight_validation_empty_content():
    with pytest.raises(ValueError):
        build_highlight_event("", "https://example.com/a")
    with pytest.raises(ValueError):
        build_highlight_event("   ", "https://example.com/a")


def test_build_highlight_validation_too_long():
    with pytest.raises(ValueError):
        build_highlight_event("x" * (MAX_HIGHLIGHT_LENGTH + 1), "https://example.com/a")
    with pytest.raises(ValueError):
        build_highlight_event("ok", "https://example.com/a", context="y" * 5001)


def test_build_highlight_validation_bad_url_and_pubkey():
    with pytest.raises(ValueError):
        build_highlight_event("ok", "not a url")
    with pytest.raises(ValueError):
        build_highlight_event("ok", "https://example.com/a", author_pubkey="not-hex")
    with pytest.raises(ValueError):
        build_highlight_event("ok", "https://example.com/a", pubkey="bad")


def test_is_valid_highlight_missing_tags():
    evt = build_highlight_event("hello world", "https://example.com/a")
    ok, _ = is_valid_highlight(evt)
    assert ok
    # missing r
    no_r = dict(evt, tags=[t for t in evt["tags"] if t[0] != "r"])
    assert not is_valid_highlight(no_r)[0]
    # missing alt
    no_alt = dict(evt, tags=[t for t in evt["tags"] if t[0] != "alt"])
    assert not is_valid_highlight(no_alt)[0]
    # empty content
    empty = dict(evt, content="   ")
    assert not is_valid_highlight(empty)[0]
    # wrong kind
    assert not is_valid_highlight(dict(evt, kind=1))[0]
    # invalid p hex
    bad_p = dict(evt, tags=evt["tags"] + [["p", "nothex"]])
    assert not is_valid_highlight(bad_p)[0]
    # invalid pubkey
    assert not is_valid_highlight(dict(evt, pubkey="bad"))[0]


def test_parse_highlight():
    evt = build_highlight_event(
        "selected quote",
        "https://example.com/episode/2",
        context="full context here",
        author_pubkey=AUTHOR,
    )
    evt["id"] = "d" * 64
    evt["pubkey"] = USER
    parsed = parse_highlight(evt)
    assert parsed is not None
    assert parsed["content"] == "selected quote"
    assert parsed["source_url"] == "https://example.com/episode/2"
    assert parsed["alt"] == "highlight"
    assert parsed["context"] == "full context here"
    assert parsed["author_pubkeys"] == [AUTHOR.lower()]
    assert parsed["pubkey"] == USER
    assert parsed["created_at"] == evt["created_at"]
    # helpers
    assert get_highlight_sources(evt) == ["https://example.com/episode/2"]
    assert get_highlight_alt(evt) == "highlight"


def test_parse_highlight_invalid_returns_none():
    bad = {"kind": 9802, "content": "", "tags": []}
    assert parse_highlight(bad) is None
    assert parse_highlight({"kind": 1, "content": "hi", "tags": [["r", "https://a.com"], ["alt", "x"]]}) is None


def test_build_highlight_filter():
    filt = build_highlight_filter(EPISODE_URL)
    assert filt["kinds"] == [9802]
    assert filt["#r"] == [CLEANED_URL]
    assert filt["limit"] == 100
    # custom limit
    filt2 = build_highlight_filter("https://example.com/a", limit=50)
    assert filt2["limit"] == 50
    # invalid
    with pytest.raises(ValueError):
        build_highlight_filter("")
    with pytest.raises(ValueError):
        build_highlight_filter("https://example.com/a", limit=0)
    with pytest.raises(ValueError):
        build_highlight_filter("https://example.com/a", limit=999)


def test_highlight_filter_cleaned_url_used_for_query():
    """Relay query must use cleaned url, not raw with trackers."""
    raw = "https://example.com/ep?id=1&utm_source=foo"
    filt = build_highlight_filter(raw)
    # raw tracker stripped
    assert filt["#r"] == ["https://example.com/ep?id=1"]
    # event's r tag also cleaned, so filter matches
    evt = build_highlight_event("hi", raw)
    r_in_event = [t[1] for t in evt["tags"] if t[0] == "r"][0]
    assert r_in_event == filt["#r"][0]


def test_highlight_alt_default_and_custom():
    evt_default = build_highlight_event("text", "https://example.com/a")
    assert any(t == ["alt", "highlight"] for t in evt_default["tags"])
    evt_custom = build_highlight_event("text", "https://example.com/a", alt="my alt")
    assert any(t == ["alt", "my alt"] for t in evt_custom["tags"])


def test_full_flow_signable_template():
    """Construct, validate and parse like frontend would before signing."""
    content = "The sovereign stack is the proof."
    context = "Paragraph before. The sovereign stack is the proof. Paragraph after."
    url = "https://sovgrid.org/blog/sovereign-ai"
    evt = build_highlight_event(content, url, context=context, author_pubkey=AUTHOR, pubkey=USER)
    # would be signed via NIP-07 -> add id/sig/pubkey after, but template validates
    assert is_valid_highlight(evt)[0]
    parsed = parse_highlight(evt)
    assert parsed is not None
    assert parsed["content"] == content
    assert parsed["context"] == context
    # filter for same url finds it
    filt = build_highlight_filter(url)
    assert filt["#r"][0] in get_highlight_sources(evt)
