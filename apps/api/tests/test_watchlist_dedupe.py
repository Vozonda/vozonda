"""Tests for watchlist deduplication (canonical URL + near-duplicate titles).

Covers every normalization rule, near-duplicate vs genuinely different titles,
the 72 h window edge, cross-feed duplicates, and that non-duplicates pass through.
"""

import time

import pytest

from vozonda_api.watchlist_dedupe import (
    _72H,
    _normalize_title,
    canonical_url,
    is_duplicate,
)

# ---------------------------------------------------------------------------
# canonical_url: normalization rules
# ---------------------------------------------------------------------------


def test_lowercases_scheme_and_host():
    assert canonical_url("HTTPS://WWW.EXAMPLE.COM/article") == "https://example.com/article"


def test_strips_www_prefix():
    assert canonical_url("http://www.example.com/page") == "http://example.com/page"


def test_keeps_non_www_host():
    assert canonical_url("https://blog.example.com/post") == "https://blog.example.com/post"


def test_drops_fragment():
    assert canonical_url("https://example.com/page#top") == "https://example.com/page"


def test_drops_ampersand_fragment():
    assert canonical_url("https://example.com/page#section?foo=bar") == "https://example.com/page"


def test_drops_tracking_params():
    result = canonical_url(
        "https://example.com/article?id=1&utm_source=newsletter&utm_medium=email&fbclid=abc123"
    )
    assert result == "https://example.com/article?id=1"


def test_drops_all_tracking_variants():
    result = canonical_url(
        "https://example.com/page?gclid=xyz&mc_cid=dead&mc_eid=beef&ref=twitter&ref_src=tw"
    )
    assert result == "https://example.com/page"


def test_drops_utm_prefix_anything():
    result = canonical_url("https://example.com/page?utm_campaign=sale&utm_term=black")
    assert result == "https://example.com/page"


def test_keeps_non_tracking_params():
    result = canonical_url("https://example.com/page?category=tech&a=1")
    assert result == "https://example.com/page?a=1&category=tech"


def test_sorts_query_params():
    assert canonical_url("https://example.com/page?z=3&a=1&m=2") == "https://example.com/page?a=1&m=2&z=3"


def test_drops_trailing_slash():
    assert canonical_url("https://example.com/page/") == "https://example.com/page"


def test_keeps_root_slash():
    # root "/" normalises to no trailing slash
    assert canonical_url("https://example.com/") == "https://example.com"


def test_amp_suffix():
    assert canonical_url("https://example.com/article.amp") == "https://example.com/article"


def test_amp_query_param():
    assert canonical_url("https://example.com/page?amp=1&ref=abc") == "https://example.com/page"


def test_amp_query_param_amp_only():
    assert canonical_url("https://example.com/page?amp") == "https://example.com/page"


def test_amp_path_segment():
    assert canonical_url("https://example.com/amp/article") == "https://example.com/article"


def test_amp_path_trailing():
    assert canonical_url("https://example.com/amp/") == "https://example.com"


def test_amp_path_in_middle():
    assert canonical_url("https://example.com/blog/amp/post") == "https://example.com/blog/post"


def test_amp_path_capital():
    assert canonical_url("https://example.com/AMP/article") == "https://example.com/article"


def test_amp_suffix_plus_path():
    assert canonical_url("https://example.com/amp/article.amp") == "https://example.com/article"


def test_amp_query_amp1_only():
    assert canonical_url("https://example.com/page?amp=1") == "https://example.com/page"


def test_amp_query_amp_with_value():
    # amp=1 is stripped but amp=2 is not a recognized variant
    result = canonical_url("https://example.com/page?amp=2&foo=bar")
    assert result == "https://example.com/page?amp=2&foo=bar"


def test_mixed_amp_and_tracking():
    result = canonical_url("https://example.com/article.amp?utm_source=x&ref=foo")
    assert result == "https://example.com/article"


def test_amp_path_with_trailing_slash():
    result = canonical_url("https://example.com/amp/")
    assert result == "https://example.com"


def test_empty_url():
    assert canonical_url("") == ""


def test_preserves_params_after_tracking_removal():
    result = canonical_url("https://example.com/page?foo=bar&utm_source=bad&baz=qux")
    assert result == "https://example.com/page?baz=qux&foo=bar"


# ---------------------------------------------------------------------------
# _normalize_title
# ---------------------------------------------------------------------------


def test_normalize_strips_punctuation():
    assert _normalize_title("Hello, World!") == "hello world"


def test_normalize_collapses_whitespace():
    assert _normalize_title("Hello   World") == "hello world"


def test_normalize_lowercase():
    assert _normalize_title("HELLO WORLD") == "hello world"


def test_normalize_empty():
    assert _normalize_title("") == ""


def test_normalize_preserves_digits():
    # dots between digits are replaced with a space
    assert _normalize_title("Python 3.12 Released!") == "python 3 12 released"


def test_normalize_title_differing_only_in_punctuation():
    # Titles differing only in punctuation normalize to the exact same string
    t1 = "Breaking News: AI Model (v2) - Released!"
    t2 = "Breaking News AI Model v2 Released"
    assert _normalize_title(t1) == _normalize_title(t2)
    assert _normalize_title("fast/slow-thinking: a guide") == "fast slow thinking a guide"



# ---------------------------------------------------------------------------
# is_duplicate: canonical URL match
# ---------------------------------------------------------------------------


def test_duplicate_same_canonical_url():
    e1 = {"link": "https://example.com/article", "title": "A", "created_at": 1000}
    e2 = {"link": "https://www.example.com/article", "title": "B", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_duplicate_with_tracking_params():
    e1 = {"link": "https://example.com/x?id=1", "title": "A", "created_at": 1000}
    e2 = {"link": "https://example.com/x?id=1&utm_source=fb", "title": "B", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_duplicate_amp_equivalent():
    e1 = {"link": "https://example.com/post.amp", "title": "A", "created_at": 1000}
    e2 = {"link": "https://example.com/post", "title": "B", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_duplicate_amp_query_equivalent():
    e1 = {"link": "https://example.com/page?amp=1", "title": "A", "created_at": 1000}
    e2 = {"link": "https://example.com/page", "title": "B", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_duplicate_amp_path_equivalent():
    e1 = {"link": "https://example.com/amp/post", "title": "A", "created_at": 1000}
    e2 = {"link": "https://example.com/post", "title": "B", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_not_different_urls():
    e1 = {"link": "https://example.com/article-a", "title": "A", "created_at": 1000}
    e2 = {"link": "https://example.com/article-b", "title": "B", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is False


# ---------------------------------------------------------------------------
# is_duplicate: title normalization
# ---------------------------------------------------------------------------


def test_duplicate_similar_titles():
    e1 = {"link": "https://example.com/a", "title": "Breaking News: AI Revolution", "created_at": 1000}
    e2 = {"link": "https://example.com/b", "title": "breaking news ai revolution", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_not_different_titles():
    e1 = {"link": "https://example.com/a", "title": "Breaking News: AI Revolution", "created_at": 1000}
    e2 = {"link": "https://example.com/b", "title": "Climate Change Summit Concludes", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is False


def test_empty_title_no_match():
    e1 = {"link": "https://example.com/a", "title": "", "created_at": 1000}
    e2 = {"link": "https://example.com/b", "title": "Something", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is False


def test_short_title_no_match():
    e1 = {"link": "https://example.com/a", "title": "Hi", "created_at": 1000}
    e2 = {"link": "https://example.com/b", "title": "Hi there", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is False


def test_title_case_difference_is_duplicate():
    e1 = {"link": "https://example.com/a", "title": "The Future of Computing", "created_at": 1000}
    e2 = {"link": "https://example.com/b", "title": "THE FUTURE OF COMPUTING", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_title_punctuation_difference():
    e1 = {"link": "https://example.com/a", "title": "Hello, World!", "created_at": 1000}
    e2 = {"link": "https://example.com/b", "title": "Hello World", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_title_differs_only_in_punctuation_is_duplicate():
    e1 = {"link": "https://example.com/a", "title": "Headline: Subhead - Part 1!", "created_at": 1000}
    e2 = {"link": "https://example.com/b", "title": "Headline Subhead Part 1", "created_at": 2000}
    assert is_duplicate(e2, [e1]) is True


def test_cross_feed_duplicate():
    """Two different feeds carry the same story -- should be deduplicated."""
    now = time.time()
    e1 = {"link": "https://feed-a.com/article?id=1", "title": "Same Story Here", "created_at": now}
    e2 = {"link": "https://feed-b.com/article?id=1", "title": "Same Story Here!", "created_at": now}
    assert is_duplicate(e2, [e1]) is True


# ---------------------------------------------------------------------------
# is_duplicate: 72 h window edge cases
# ---------------------------------------------------------------------------


def test_within_72h_window():
    now = 10000.0
    e1 = {"link": "https://example.com/a", "title": "Breaking News Story", "created_at": now}
    e2 = {"link": "https://example.com/b", "title": "breaking news story", "created_at": now + 3600}
    assert is_duplicate(e2, [e1]) is True


def test_72h_boundary_exactly():
    now = 10000.0
    e1 = {"link": "https://example.com/a", "title": "Breaking News Story", "created_at": now}
    e2 = {"link": "https://example.com/b", "title": "breaking news story", "created_at": now + _72H}
    assert is_duplicate(e2, [e1]) is True


def test_72h_window_exceeded():
    now = 10000.0
    e1 = {"link": "https://example.com/a", "title": "Breaking News Story", "created_at": now}
    e2 = {
        "link": "https://example.com/b",
        "title": "breaking news story",
        "created_at": now + _72H + 1,
    }
    assert is_duplicate(e2, [e1]) is False


def test_72h_window_exceeded_canonical_url():
    now = 10000.0
    e1 = {"link": "https://example.com/a", "title": "Breaking News Story", "created_at": now}
    e2 = {
        "link": "https://example.com/a?utm_source=new",
        "title": "A Different Title Later",
        "created_at": now + _72H + 1,
    }
    assert is_duplicate(e2, [e1]) is False


def test_no_created_at_still_matches_title():
    """Entries without created_at (older jobs) still deduplicate by canonical URL."""
    e1 = {"link": "https://example.com/a?id=1", "title": "Old Story"}
    e2 = {"link": "https://example.com/a?id=1&utm_source=x", "title": "Different Title"}
    assert is_duplicate(e2, [e1]) is True


def test_no_created_at_different_title_no_url_match():
    """Old entry without created_at, different title and URL -- not a duplicate."""
    e1 = {"link": "https://example.com/old", "title": "Old Story"}
    e2 = {"link": "https://example.com/new", "title": "brand new story here"}
    assert is_duplicate(e2, [e1]) is False


# ---------------------------------------------------------------------------
# is_duplicate: empty / edge case inputs
# ---------------------------------------------------------------------------


def test_empty_recent_entries():
    e = {"link": "https://example.com/a", "title": "A", "created_at": 1000}
    assert is_duplicate(e, []) is False


def test_multiple_references():
    now = time.time()
    refs = [
        {"link": "https://example.com/a", "title": "The Future of Computing", "created_at": now},
        {"link": "https://example.com/b", "title": "Beta", "created_at": now},
    ]
    e = {"link": "https://example.com/c", "title": "the future of computing", "created_at": now}
    assert is_duplicate(e, refs) is True  # matches the long title


def test_no_false_positive_short_titles():
    now = time.time()
    refs = [{"link": "https://example.com/a", "title": "X", "created_at": now}]
    e = {"link": "https://example.com/b", "title": "X Y", "created_at": now}
    assert is_duplicate(e, refs) is False


# ---------------------------------------------------------------------------
# Integration: poll_single skips duplicates and logs
# ---------------------------------------------------------------------------


def _stub_poller_speed(monkeypatch):
    """F-1: skip real DNS (guard_url getaddrinfo) and the real background
    pipeline (_run imports engines, runs doctor subprocess). Assertions on
    created jobs, seen rows and tasks are unchanged."""
    import vozonda_api.main as main_mod
    from vozonda_api import watchlist_poller as wp

    async def _noop(job_id, runner=None):
        return None

    monkeypatch.setattr(main_mod, "_run", _noop)
    monkeypatch.setattr(wp, "guard_url", lambda url: None)


def test_poll_single_skips_duplicates(jobs_db, monkeypatch):
    """poll_single creates a job for a new URL but skips a duplicate."""
    import asyncio

    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    _stub_poller_speed(monkeypatch)
    store = jobs_mod.JobStore()
    monkeypatch.setattr(main_mod.app.state, "settings_store", store, raising=False)
    monkeypatch.setattr(main_mod.app.state, "tasks", {}, raising=False)
    monkeypatch.setattr(main_mod.app.state, "listeners", {}, raising=False)

    # Seed DB with one job so the poller sees an existing entry
    from vozonda_api.main import _readable_id

    jid = _readable_id("https://feed-a.com/article?id=1")
    store.create(jid, "https://feed-a.com/article?id=1", "balanced", "dialog", "neutral", "auto")
    store.finish(jid)

    # Minimal RSS feed with one entry (same URL as seeded job)
    rss = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Existing Article</title>
          <link>https://feed-a.com/article?id=1</link>
          <guid>12345</guid>
        </item>
      </channel>
    </rss>"""

    from unittest.mock import AsyncMock, patch

    from vozonda_api import watchlist_poller as wp

    tasks, listeners = {}, {}
    wl = {
        "id": "wl1",
        "feed_url": "https://example.com/rss",
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
        "enabled": True,
    }

    with patch.object(wp, "fetch_feed_text", new=AsyncMock(return_value=rss)):
        result = asyncio.run(wp.poll_single(wl, store, tasks, listeners))

    # The existing URL was already in DB -> skip, created == []
    assert result == []

    # Verify no tasks were created
    assert len(tasks) == 0


def test_poll_single_allows_new_unique_url(jobs_db, monkeypatch):
    """poll_single creates a job for a URL that does not exist in DB."""
    import asyncio

    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    _stub_poller_speed(monkeypatch)
    store = jobs_mod.JobStore()
    monkeypatch.setattr(main_mod.app.state, "settings_store", store, raising=False)
    monkeypatch.setattr(main_mod.app.state, "tasks", {}, raising=False)
    monkeypatch.setattr(main_mod.app.state, "listeners", {}, raising=False)

    rss = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>New Article</title>
          <link>https://feed-a.com/new?id=42</link>
          <guid>99999</guid>
        </item>
      </channel>
    </rss>"""

    from unittest.mock import AsyncMock, patch

    from vozonda_api import watchlist_poller as wp

    tasks, listeners = {}, {}
    wl = {
        "id": "wl-new",
        "feed_url": "https://example.com/rss",
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
        "enabled": True,
    }

    with patch.object(wp, "fetch_feed_text", new=AsyncMock(return_value=rss)):
        result = asyncio.run(wp.poll_single(wl, store, tasks, listeners))

    # New URL should be queued
    assert len(result) == 1
    assert len(tasks) == 1


def test_poll_single_skips_non_duplicate_across_two_feeds(jobs_db, monkeypatch):
    """Two feeds, different URLs -- second feed's entry is also created."""
    import asyncio

    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod

    _stub_poller_speed(monkeypatch)
    store = jobs_mod.JobStore()
    monkeypatch.setattr(main_mod.app.state, "settings_store", store, raising=False)
    monkeypatch.setattr(main_mod.app.state, "tasks", {}, raising=False)
    monkeypatch.setattr(main_mod.app.state, "listeners", {}, raising=False)

    rss_a = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Feed A</title>
        <item>
          <title>Feed A Article</title>
          <link>https://feed-a.com/article?id=1</link>
          <guid>1</guid>
        </item>
      </channel>
    </rss>"""

    rss_b = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Feed B</title>
        <item>
          <title>Feed B Article</title>
          <link>https://feed-b.com/article?id=2</link>
          <guid>2</guid>
        </item>
      </channel>
    </rss>"""

    from unittest.mock import patch

    from vozonda_api import watchlist_poller as wp

    tasks, listeners = {}, {}

    wl_a = {
        "id": "wl-a",
        "feed_url": "https://example.com/a",
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
        "enabled": True,
    }
    wl_b = {
        "id": "wl-b",
        "feed_url": "https://example.com/b",
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
        "enabled": True,
    }

    with patch.object(wp, "fetch_feed_text", side_effect=[rss_a, rss_b]):
        r_a = asyncio.run(wp.poll_single(wl_a, store, tasks, listeners))
        r_b = asyncio.run(wp.poll_single(wl_b, store, tasks, listeners))

    # Feed A: first to poll, creates job
    assert len(r_a) == 1
    # Feed B: different URL, also creates job
    assert len(r_b) == 1


# ---------------------------------------------------------------------------
# Cross-watchlist deduplication integration tests (VOZONDA-WATCH-DEDUPE-FIX)
# ---------------------------------------------------------------------------


def test_poll_single_cross_watchlist_dedup_two_separate_polls(jobs_db, monkeypatch):
    """Integration test: two watchlists polled in two separate poll_single calls.

    The second feed carries the same story with ?utm_source= and a slightly
    different title (differs in punctuation). Only one job is created across both
    polls.
    Plus: an entry older than 72 h no longer blocks; a subsequent poll after 72 h
    creates a job.
    """
    import asyncio
    from unittest.mock import AsyncMock, patch

    import vozonda_api.jobs as jobs_mod
    import vozonda_api.main as main_mod
    from vozonda_api import watchlist_poller as wp
    from vozonda_api.watchlist import get_seen_entries

    _stub_poller_speed(monkeypatch)
    store = jobs_mod.JobStore()
    monkeypatch.setattr(main_mod.app.state, "settings_store", store, raising=False)
    monkeypatch.setattr(main_mod.app.state, "tasks", {}, raising=False)
    monkeypatch.setattr(main_mod.app.state, "listeners", {}, raising=False)

    rss_a = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Feed Alpha</title>
        <item>
          <title>AI Breakthrough: New Reasoning Model (v2) Released!</title>
          <link>https://example.com/story/ai-2026?utm_source=alpha_newsletter</link>
          <guid>alpha-1</guid>
        </item>
      </channel>
    </rss>"""

    # Feed Beta has the same canonical story with ?utm_source= and a title differing in punctuation
    rss_b = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Feed Beta</title>
        <item>
          <title>AI Breakthrough New Reasoning Model v2 Released</title>
          <link>https://example.com/story/ai-2026?utm_source=beta_rss&amp;ref=twitter</link>
          <guid>beta-1</guid>
        </item>
      </channel>
    </rss>"""

    tasks, listeners = {}, {}

    wl_a = {
        "id": "wl-alpha",
        "feed_url": "https://example.com/alpha.xml",
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
        "enabled": True,
    }
    wl_b = {
        "id": "wl-beta",
        "feed_url": "https://example.com/beta.xml",
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
        "enabled": True,
    }

    t0 = 100_000.0

    # 1. First poll_single call: Feed Alpha produces 1 job
    with patch.object(wp, "fetch_feed_text", new=AsyncMock(return_value=rss_a)):
        r_a = asyncio.run(wp.poll_single(wl_a, store, tasks, listeners, now=t0))

    assert len(r_a) == 1
    assert len(tasks) == 1
    job_id_a = r_a[0]

    # Verify persistent SQLite table watchlist_seen holds the entry across watchlists
    seen = get_seen_entries()
    assert len(seen) == 1
    assert seen[0]["canonical_url"] == "https://example.com/story/ai-2026"
    assert seen[0]["normalized_title"] == "ai breakthrough new reasoning model v2 released"
    assert seen[0]["job_id"] == job_id_a
    assert seen[0]["watchlist_id"] == "wl-alpha"

    # 2. Second poll_single call: Feed Beta polled separately within 72 h (e.g. 2 hours later)
    t1 = t0 + 7200.0
    with patch.object(wp, "fetch_feed_text", new=AsyncMock(return_value=rss_b)):
        r_b = asyncio.run(wp.poll_single(wl_b, store, tasks, listeners, now=t1))

    # Duplicate must be detected across watchlists: only one job created in total!
    assert r_b == []
    assert len(tasks) == 1

    # 3. Plus: an entry older than 72 h no longer blocks
    t2 = t0 + (72 * 3600) + 1.0  # past 72 h window

    # Feed Gamma carries the same article after 72 h with a different tracking param
    rss_c = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Feed Gamma</title>
        <item>
          <title>AI Breakthrough New Reasoning Model v2 Released</title>
          <link>https://example.com/story/ai-2026?utm_source=gamma_feed</link>
          <guid>gamma-1</guid>
        </item>
      </channel>
    </rss>"""

    wl_c = {
        "id": "wl-gamma",
        "feed_url": "https://example.com/gamma.xml",
        "style": "balanced",
        "format": "dialog",
        "language": "auto",
        "hosts": 2,
        "enabled": True,
    }

    with patch.object(wp, "fetch_feed_text", new=AsyncMock(return_value=rss_c)):
        r_c = asyncio.run(wp.poll_single(wl_c, store, tasks, listeners, now=t2))

    # Since entry is older than 72 h, it has been pruned and no longer blocks!
    assert len(r_c) == 1
    assert len(tasks) == 2


def test_watchlist_seen_table_persistence_and_pruning(jobs_db, monkeypatch):
    """Test watchlist_seen table recording and pruning."""
    from vozonda_api.watchlist import (
        clear_seen_entries,
        get_seen_entries,
        prune_seen_entries,
        record_seen_entry,
    )

    clear_seen_entries()

    now = 1000.0
    record_seen_entry(
        url="https://example.com/page?utm_source=test",
        title="Sample Title: With Punctuation!",
        first_seen=now,
        job_id="job-1",
        watchlist_id="wl-1",
    )

    rows = get_seen_entries()
    assert len(rows) == 1
    assert rows[0]["canonical_url"] == "https://example.com/page"
    assert rows[0]["normalized_title"] == "sample title with punctuation"
    assert rows[0]["first_seen"] == 1000.0
    assert rows[0]["job_id"] == "job-1"
    assert rows[0]["watchlist_id"] == "wl-1"

    # Pruning with timestamp within 72 h retains the row
    deleted = prune_seen_entries(now=now + 3600.0)
    assert deleted == 0
    assert len(get_seen_entries()) == 1

    # Pruning after 72 h deletes the row
    deleted = prune_seen_entries(now=now + (72 * 3600) + 1.0)
    assert deleted == 1
    assert len(get_seen_entries()) == 0

# ---------------------------------------------------------------------------
# Coordinator review of db257f8: titles that differ in a number are different
# stories (a release, a price, a rate). A plain similarity ratio cannot see that.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("Apple releases iOS 18", "Apple releases iOS 19"),
        ("Rust 1.82 released", "Rust 1.83 released"),
        ("Bitcoin falls below $60,000", "Bitcoin falls below $50,000"),
        ("OpenAI announces GPT-6", "OpenAI announces GPT-5"),
        ("Fed raises rates by 0.25%", "Fed raises rates by 0.50%"),
    ],
)
def test_titles_differing_in_a_number_are_not_duplicates(a, b):
    from vozonda_api.watchlist_dedupe import is_duplicate

    now = time.time()
    entry = {"link": "https://one.example/a", "title": a, "created_at": now}
    ref = {"link": "https://two.example/b", "title": b, "created_at": now}
    assert not is_duplicate(entry, [ref])


@pytest.mark.parametrize(
    "a,b",
    [
        ("Apple releases iOS 18!", "Apple releases iOS 18"),
        ("Apple releases iOS 18 with new AI features", "Apple releases iOS 18 with new AI feature"),
        ("Rust 1.82 released: what's new", "Rust 1.82 released - what's new"),
    ],
)
def test_near_identical_titles_with_same_numbers_are_duplicates(a, b):
    from vozonda_api.watchlist_dedupe import is_duplicate

    now = time.time()
    entry = {"link": "https://one.example/a", "title": a, "created_at": now}
    ref = {"link": "https://two.example/b", "title": b, "created_at": now}
    assert is_duplicate(entry, [ref])
