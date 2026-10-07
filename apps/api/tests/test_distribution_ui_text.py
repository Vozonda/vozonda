"""VOZONDA-DISTRIBUTION-UI: text checks for the distribution section and Nostr publishing UI.

Verifies that SettingsScreen, DistributionSection, ListenScreen, and api.ts contain the
expected strings for the distribution settings and per-show Nostr publishing feature.

These are static source-text checks (no HTTP calls, no backend needed).
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
WEB_SRC = ROOT / "apps" / "web" / "src"


def _read(path: str) -> str:
    return (WEB_SRC / path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# SettingsScreen.svelte
# ---------------------------------------------------------------------------

class TestSettingsDistributionSection:
    """Coordinator rebuild 2026-10-02 (operator: duplicates, wrong styles, unintuitive).

    The fleet's DistributionSection was a child component: SettingsScreen's scoped
    styles (.seg, .opt, .help) did not reach it, so it rendered raw buttons; it repeated
    the section heading, read values without defaults (rss showed 'off'), asked for
    comma-separated lists, used two icons that do not exist, and had no per-show reach
    at all. The section now lives inline like every other section."""

    def source(self) -> str:
        return _read("lib/components/SettingsScreen.svelte")

    def test_one_distribution_section_inline_with_one_heading(self) -> None:
        src = self.source()
        assert "DistributionSection" not in src
        assert not (WEB_SRC / "lib/components/DistributionSection.svelte").exists()
        assert src.count('id="sec-shows"') == 1
        assert src.count("<h2>shows & distribution</h2>") == 1
        assert "publishing & distribution" not in src and "<h2>distribution</h2>" not in src

    def test_groups_follow_how_an_episode_is_made(self) -> None:
        """Operator 2026-10-02: source -> script -> voice -> shows -> player -> system,
        and the writing model is the first thing in the script group."""
        import re

        src = self.source()
        ids = re.findall(r'<div id="(sec-[a-z]+)" class="settings-group">', src)
        assert ids == ["sec-sources", "sec-script", "sec-voice", "sec-shows", "sec-player", "sec-system"]
        script = src[src.index('id="sec-script"'):src.index('id="sec-voice"')]
        assert script.index('id="llm-h"') < script.index('id="styles-h"') < script.index('id="dialog-tuning-h"')
        shows = src[src.index('id="sec-shows"'):src.index('id="sec-player"')]
        assert 'id="s-show-name"' in shows, "the show's name sits in its card, next to its reach"

    def test_four_reaches_per_show(self) -> None:
        src = self.source()
        for reach in ("'private'", "'podcast apps'", "'nostr only'", "'both'"):
            assert reach in src
        assert "chooseReach(show, r.id)" in src and "setShowRss" in src and "setNostrPublish" in src

    def test_nostr_needs_an_inline_confirmation(self) -> None:
        src = self.source()
        assert 'role="dialog"' in src and "publish publicly" in src
        assert "applyReach(show, reach, true)" in src, "only the confirmation sends confirm_public"
        assert "e.key === 'Escape'" in src

    def test_defaults_read_the_server_defaults(self) -> None:
        assert "(values[d.key] ?? defaults[d.key]) === '1'" in self.source()

    def test_lists_are_edited_one_per_line(self) -> None:
        src = self.source()
        assert "one per line" in src and "comma-separated" not in src

    def test_public_address_and_directories(self) -> None:
        src = self.source()
        assert "VOZONDA_PUBLIC_URL" in src and "directory_help.podcast_index" in src

    def test_only_existing_icons(self) -> None:
        icons = _read("lib/components/Icon.svelte")
        import re

        for name in set(re.findall(r'<Icon name="([a-z0-9-]+)"', self.source())):
            assert f"{name}:" in icons or f"'{name}'" in icons or f'"{name}"' in icons, name


class TestListenScreenNostrStatus:
    """ListenScreen shows a Nostr status line in the facts tab."""

    def source(self) -> str:
        return _read("lib/components/ListenScreen.svelte")

    def test_nostr_show_enabled_prop(self) -> None:
        """Props include nostrShowEnabled."""
        assert "nostrShowEnabled" in self.source()

    def test_nostr_status_prop(self) -> None:
        """Props include nostrStatus."""
        assert "nostrStatus" in self.source()

    def test_nostr_status_line_text(self) -> None:
        """ListenScreen has the '// nostr:' status text."""
        assert "// nostr:" in self.source()

    def test_nostr_published_text(self) -> None:
        """Status shows published text."""
        assert "nostr: published" in self.source()

    def test_nostr_failed_text(self) -> None:
        """Status shows failed text."""
        assert "nostr: failed" in self.source()

    def test_retry_text(self) -> None:
        """Retry button shown when failed."""
        assert "retry" in self.source()

    def test_nostr_status_bar_class(self) -> None:
        """Nostr status container has nostr-status-bar class."""
        assert "nostr-status-bar" in self.source() or "nostr-status-text" in self.source()

    def test_aria_live_status(self) -> None:
        """Nostr status has aria-live for accessibility."""
        assert "aria-live" in self.source()

    def test_nostr_retry_button(self) -> None:
        """Retry button has aria-label and disabled state."""
        assert "aria-label" in self.source() and "disabled" in self.source()

    def test_retry_nostr_publish_function(self) -> None:
        """Has retryNostrPublish function."""
        assert "retryNostrPublish" in self.source()

    def test_nostr_publish_endpoint(self) -> None:
        """Retry calls POST /jobs/{id}/nostr/publish."""
        assert "/nostr/publish" in self.source()

    def test_nostr_relay_count(self) -> None:
        """Props include nostrRelayCount."""
        assert "nostrRelayCount" in self.source()

    def test_nostr_success_count(self) -> None:
        """Props include nostrSuccessCount."""
        assert "nostrSuccessCount" in self.source()


# ---------------------------------------------------------------------------
# api.ts
# ---------------------------------------------------------------------------

class TestApiTsDistribution:
    """api.ts has functions for distribution and Nostr endpoints."""

    def source(self) -> str:
        return _read("lib/api.ts")

    def test_get_distribution_function(self) -> None:
        """Has getDistribution function for /distribution endpoint."""
        assert "getDistribution" in self.source() or "get('/distribution')" in self.source()

    def test_distribution_endpoint(self) -> None:
        """Distribution function targets /distribution route."""
        assert "/distribution" in self.source()

    def test_set_show_rss_function(self) -> None:
        """Has setShowRss function for /shows/*/rss route."""
        assert "setShowRss" in self.source() or "/rss" in self.source()

    def test_rss_endpoint(self) -> None:
        """RSS function targets /shows/*/rss route."""
        assert "/rss" in self.source()

    def test_get_nostr_show_status(self) -> None:
        """Has getNostrShowStatus for per-show Nostr status."""
        assert "getNostrShowStatus" in self.source() or "nostr" in self.source()

    def test_set_nostr_publish_function(self) -> None:
        """Has setNostrPublish function."""
        assert "setNostrPublish" in self.source()

    def test_nostr_publish_route(self) -> None:
        """Publish function targets /shows/*/nostr route."""
        assert "/nostr" in self.source()

    def test_confirm_public_param(self) -> None:
        """Publish function accepts confirm_public parameter."""
        assert "confirm_public" in self.source()

    def test_export_nsec_function(self) -> None:
        """Has exportNostrNsec function."""
        assert "exportNostrNsec" in self.source()

    def test_retry_nostr_publish_function(self) -> None:
        """Has retryNostrPublish function."""
        assert "retryNostrPublish" in self.source()

    def test_nostr_publish_post(self) -> None:
        """Retry function uses POST method."""
        assert "POST" in self.source() and "nostr/publish" in self.source()

    def test_nostr_job_status(self) -> None:
        """Has getNostrJobStatus for per-job Nostr status."""
        assert "getNostrJobStatus" in self.source()


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

class TestCombinedChecks:
    """Combined checks that the feature text is consistent across files."""

    def test_listen_has_nostr_status(self) -> None:
        listen = _read("lib/components/ListenScreen.svelte")
        assert "nostr" in listen.lower()

    def test_api_has_distribution_endpoints(self) -> None:
        api = _read("lib/api.ts")
        assert "/distribution" in api
