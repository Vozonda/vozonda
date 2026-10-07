from vozonda_api.fetcher import resolve_nostr_url


def test_resolve_nostr_uris():
    assert resolve_nostr_url("nostr:nevent1qqs8a0abcdef123") == "https://njump.me/nevent1qqs8a0abcdef123"
    assert resolve_nostr_url("nostr:naddr1qqs8a0abcdef456") == "https://njump.me/naddr1qqs8a0abcdef456"
    assert resolve_nostr_url("nostr:note1qqs8a0abcdef789") == "https://njump.me/note1qqs8a0abcdef789"
    assert resolve_nostr_url("nostr:npub1qqs8a0abcdef999") == "https://njump.me/npub1qqs8a0abcdef999"


def test_resolve_nostr_gateway_urls():
    assert resolve_nostr_url("https://habla.news/a/naddr1qqs8a0abcdef456") == "https://njump.me/naddr1qqs8a0abcdef456"
    assert resolve_nostr_url("https://coracle.social/note1qqs8a0abcdef789") == "https://njump.me/note1qqs8a0abcdef789"
    assert resolve_nostr_url("https://snort.social/e/nevent1qqs8a0abcdef123") == "https://njump.me/nevent1qqs8a0abcdef123"
    assert resolve_nostr_url("https://example.com/regular-page") == "https://example.com/regular-page"
