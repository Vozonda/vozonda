"""Gate: no unused CSS selectors in Svelte components.

Runs ``svelte-check --output machine`` and fails on any
``css_unused_selector`` diagnostic (the old 52 warnings from the
compose UI the source tray replaced).

The fresh-worktree approach (git archive + npm ci) is used so the
test is independent of the workspace's read-only node_modules.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _get_repo_root() -> Path:
    """Return the git repo root directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip())


def test_no_unused_css_selectors() -> None:
    """svelte-check must not report css_unused_selector warnings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir) / "apps" / "web"
        clone_dir.mkdir(parents=True)

        # Use git archive to get a clean copy of the repo
        repo_root = _get_repo_root()
        archive_proc = subprocess.run(
            ["git", "archive", "HEAD"],
            capture_output=True,
            cwd=str(repo_root),
            check=False,
        )
        if archive_proc.returncode != 0:
            raise RuntimeError(
                f"git archive failed: {archive_proc.stderr.decode()}"
            )

        # Extract the archive
        tar_proc = subprocess.run(
            ["tar", "-x", "-C", str(clone_dir.parent)],
            input=archive_proc.stdout,
            capture_output=True,
            check=False,
        )
        if tar_proc.returncode != 0:
            raise RuntimeError(
                f"tar extraction failed: {tar_proc.stderr.decode()}"
            )

        # Install deps (fresh install in the temp directory)
        subprocess.run(
            ["npm", "ci", "--silent"],
            cwd=str(clone_dir),
            capture_output=True,
            text=True,
            check=False,
        )

        # Run svelte-check in machine-output mode
        result = subprocess.run(
            ["npx", "svelte-check", "--output", "machine", "--threshold", "warning"],
            capture_output=True,
            text=True,
            cwd=str(clone_dir),
            check=False,
        )
        output = result.stdout + result.stderr

        # Clean up the clone directory
        shutil.rmtree(str(clone_dir))

        # Parse machine output for css_unused_selector diagnostics
        unused_lines: list[str] = []
        for line in output.splitlines():
            if "css_unused_selector" in line:
                unused_lines.append(line.strip())

        if unused_lines:
            sys.stderr.write(
                f"FAIL: {len(unused_lines)} css_unused_selector warnings remain\n"
            )
            for ul in unused_lines:
                sys.stderr.write(f"  {ul}\n")
            sys.exit(1)


def test_launch_status_css_present() -> None:
    """The .launch-status rule and @keyframes editorialFade must exist in App.svelte.

    This catches regressions where a CSS rule used in markup is accidentally
    removed during a cleanup pass.  Without the fix this test fails because the
    selector .launch-status and keyframes editorialFade are missing from the
    <style> block.
    """
    app_path = _get_repo_root() / "apps" / "web" / "src" / "App.svelte"
    content = app_path.read_text()

    # The markup at line 1530 uses class="launch-status" — the CSS rule must exist.
    assert ".launch-status" in content, (
        "CSS selector .launch-status missing; markup at line 1530 uses it"
    )

    # The fade-in animation that gives the status element its visual behaviour.
    assert "@keyframes editorialFade" in content, (
        "@keyframes editorialFade missing; referenced by .launch-status animation"
    )


if __name__ == "__main__":
    test_no_unused_css_selectors()
