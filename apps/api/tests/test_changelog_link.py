"""Version link in App.svelte and FaqScreen.svelte points to the public changelog.

No file in apps/web references dev.html; scripts/gen-dev-page.py does not exist.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB_SRC = ROOT / "apps" / "web" / "src"
APP_SVELTE = WEB_SRC / "App.svelte"
FAQ_SVELTE = WEB_SRC / "lib" / "components" / "FaqScreen.svelte"

CHANGELOG_URL = "https://vozonda.com/changelog/"
CHANGELOG_WITH_TARGET = f'href="{CHANGELOG_URL}" target="_blank" rel="noopener"'


def test_app_svelte_version_link():
    src = APP_SVELTE.read_text(encoding="utf-8")
    assert CHANGELOG_URL in src, "App.svelte version link must point to the changelog"
    assert "target=\"_blank\"" in src, "App.svelte version link must open in new tab"
    assert "rel=\"noopener\"" in src, "App.svelte version link must have rel=noopener"
    # Check the dev-link class is used
    assert 'class="dev-link"' in src, "App.svelte dev-link class must still be present"


def test_faq_screen_version_link():
    src = FAQ_SVELTE.read_text(encoding="utf-8")
    assert CHANGELOG_URL in src, "FaqScreen.svelte version link must point to the changelog"
    assert "target=\"_blank\"" in src, "FaqScreen.svelte version link must open in new tab"
    assert "rel=\"noopener\"" in src, "FaqScreen.svelte version link must have rel=noopener"
    assert 'class="dev-link"' in src, "FaqScreen.svelte dev-link class must still be present"


def test_no_dev_html_references_in_web():
    """No .svelte file in apps/web/src should reference dev.html."""
    for f in sorted(WEB_SRC.rglob("*.svelte")):
        src = f.read_text(encoding="utf-8")
        assert "dev.html" not in src, f"{f} still references dev.html"
    for f in sorted(WEB_SRC.rglob("*.ts")):
        src = f.read_text(encoding="utf-8")
        assert "dev.html" not in src, f"{f} still references dev.html"


def test_gen_dev_page_does_not_exist():
    gen = ROOT / "scripts" / "gen-dev-page.py"
    assert not gen.exists(), "scripts/gen-dev-page.py must not exist"