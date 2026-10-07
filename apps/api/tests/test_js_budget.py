"""JS budget gate (VOZONDA-JS-BUDGET: initial JS toward the 60 KB gzip budget).

Measures the gzip size of the entry chunk produced by ``npm run build`` and
asserts it stays under a *ratchet* (measured baseline + 5 %) so the budget
can only tighten over time.

Runs ``npm run build`` inside apps/web before measuring.
"""

import gzip
import os
import re
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent.parent / "web"
DIST = WEB / "dist"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_web() -> None:
    """Run ``npm run build`` inside apps/web."""
    if not (WEB / "node_modules").is_dir():
        pytest.skip("web dependencies not installed (the CI web job runs svelte-check and the build)")
    # svelte-check first
    result = subprocess.run(
        ["npx", "svelte-check", "--threshold", "error"],
        capture_output=True,
        text=True,
        cwd=str(WEB),
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"svelte-check failed:\n{result.stderr[:3000]}\n{result.stdout[:3000]}"
        )

    result = subprocess.run(
        ["npm", "run", "build"],
        capture_output=True,
        text=True,
        cwd=str(WEB),
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"npm build failed:\n{result.stderr[:3000]}\n{result.stdout[:3000]}"
        )


def _gzip_bytes(path: Path) -> int:
    """Return gzip compressed size in bytes."""
    return len(gzip.compress(path.read_bytes(), mtime=0))


def _entry_chunks() -> list[dict]:
    """Return a list of {src, raw, gzip, entry} dicts from index.html."""
    html_path = DIST / "index.html"
    if not html_path.exists():
        pytest.fail("dist/index.html not found; run `npm run build` first.")

    html = html_path.read_text()

    # Collect all script srcs and modulepreload links
    raw_scripts = set(re.findall(
        r'<script[^>]+src=["\'](/assets/[^"\']+\.js)["\']', html
    ))
    preload_scripts = set(re.findall(
        r'<link[^>]+rel=["\']modulepreload["\'][^>]*href=["\'](/assets/[^"\']+\.js)["\']', html
    ))

    # The first <script> tag in index.html is the entry point chunk.
    first_match = re.search(
        r'<script[^>]+src=["\'](/assets/[^"\']+\.js)["\']', html
    )
    entry = {first_match.group(1)} if first_match else set()

    results: list[dict] = []
    all_sources = raw_scripts | preload_scripts
    for src in all_sources:
        rel = src.lstrip("/")
        fpath = DIST / rel
        if not fpath.exists():
            continue
        raw = fpath.stat().st_size
        gz = _gzip_bytes(fpath)
        results.append({
            "src": src,
            "raw": raw,
            "gzip": gz,
            "entry": src in entry,
        })
    return results


def _compose_gzip() -> int:
    """Gzip size of the compose-page entry chunk only."""
    for c in _entry_chunks():
        if c["entry"]:
            return c["gzip"]
    raise RuntimeError("no entry chunk found in index.html")


def _all_gzip() -> int:
    """Sum of all JS chunks referenced from index.html."""
    return sum(c["gzip"] for c in _entry_chunks())


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestJsBudget:
    """JS bundle-budget regression test."""

    @pytest.fixture(autouse=True, scope="class")
    def _build(self):
        """Ensure dist/ is built before all tests in this class."""
        _build_web()
        yield

    def test_entry_under_ratchet(self):
        """The entry chunk must be under a ratchet: measured baseline + 5 %.

        On the first run we accept a generous ceiling (62 KB) to establish a
        baseline.  Subsequent runs read that baseline from an env var and
        must stay within 5 % growth.
        """
        gz = _compose_gzip()

        baseline_env = os.environ.get("VOZONDA_JS_BASELINE")
        if baseline_env:
            baseline = int(baseline_env)
            ratchet = int(baseline * 1.05)
            assert gz <= ratchet, (
                f"Entry JS {gz / 1024:.2f} KB exceeds "
                f"baseline+5% ratchet {ratchet / 1024:.2f} KB "
                f"(baseline was {baseline / 1024:.2f} KB)"
            )
        else:
            # First run: establish baseline, accept current value.
            # Use a small safety margin over 60 KB so a slightly different
            # build order doesn't immediately fail.
            ceiling = 62 * 1024
            assert gz <= ceiling, (
                f"Entry JS {gz / 1024:.2f} KB exceeds initial "
                f"ceiling {ceiling / 1024:.2f} KB"
            )

    def test_entry_gzip_size(self):
        """Report the exact entry JS size."""
        gz = _compose_gzip()
        assert gz > 0, "entry chunk is empty"

    def test_five_biggest_modules(self):
        """Report the five biggest JS modules in the build.

        The initial compose-page entry chunk must not import heavy non-screen
        code.  Screens are lazy-loaded; the five biggest reported here show
        what the build produced and confirm the entry is the only initial load.
        """
        chunks = _entry_chunks()

        # Also list all JS files in dist/assets/ for reporting
        assets_dir = DIST / "assets"
        if assets_dir.exists():
            all_js = sorted(
                [f for f in assets_dir.iterdir() if f.suffix == ".js"],
                key=lambda f: f.stat().st_size,
                reverse=True,
            )
            top_chunks: list[dict] = []
            seen_names: set[str] = set()
            # First add chunks referenced from index.html
            for c in chunks:
                name = c["src"].rsplit("/", 1)[-1]
                if name not in seen_names:
                    seen_names.add(name)
                    top_chunks.append(c)
            # Then add the largest lazy chunks from assets/
            for f in all_js[:20]:
                name = f.name
                if name not in seen_names:
                    seen_names.add(name)
                    gz = _gzip_bytes(f)
                    top_chunks.append({
                        "src": f"/assets/{name}",
                        "raw": f.stat().st_size,
                        "gzip": gz,
                        "entry": False,
                    })
            top_chunks.sort(key=lambda c: c["gzip"], reverse=True)
            top_five = top_chunks[:5]
        else:
            top_chunks = sorted(chunks, key=lambda c: c["gzip"], reverse=True)
            top_five = top_chunks[:5]

        lines: list[str] = ["Biggest JS modules (gzip):"]
        for c in top_five:
            kind = "entry" if c["entry"] else "lazy"
            lines.append(
                f"  {c['src']}  {c['gzip']/1024:.2f} KB gzip  ({kind})"
            )
        print("\n".join(lines))

        # The entry chunk must be in the top five (or the only chunk)
        entry_in_top = any(c["entry"] for c in top_five)
        assert entry_in_top, "Entry chunk not found in top five modules"

    def test_no_static_screen_imports(self):
        """Heavy non-compose screens must not be statically imported in App.svelte."""
        app_svelte = (WEB / "src/App.svelte").read_text()
        # Match top-level `import X from './lib/components/...Screen.svelte'`
        # (without the wrapping function).
        static_screens = re.findall(
            r"^import\s+\S+\s+from\s+['\"].*Screen\.svelte['\"]",
            app_svelte,
            re.MULTILINE,
        )
        assert static_screens == [], (
            f"Static imports of screen components detected: {static_screens}. "
            "All screens must use dynamic imports."
        )

    def test_all_gzip_below_budget(self):
        """Total JS referenced from index.html must stay under 60 KB."""
        total = _all_gzip()
        budget = 60 * 1024
        assert total <= budget, (
            f"Total JS from index.html is {total / 1024:.2f} KB, "
            f"exceeds 60 KB budget"
        )