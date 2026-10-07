"""Tests for export_public.sh"""

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
EXPORT_SCRIPT = SCRIPT_DIR / "export_public.sh"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _run_export(target: Path) -> subprocess.CompletedProcess[str]:
    """Run export_public.sh into the given target directory."""
    return subprocess.run(
        [str(EXPORT_SCRIPT), str(target)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )


def _run_scan(repo: Path, allowlist: Path) -> subprocess.CompletedProcess[str]:
    """Run public_scan.py on a repo directory."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "public_scan.py"), "--repo", str(repo),
         "--allowlist", str(allowlist)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_excluded_paths_absent(tmp_path: Path) -> None:
    """Paths excluded from the export must not appear in the target."""
    target = tmp_path / "export"
    result = _run_export(target)
    assert result.returncode == 0, f"export failed: {result.stderr}\n{result.stdout}"

    assert not (target / "docs" / "archive").exists(), "docs/archive should be absent"
    assert not (target / ".fleet-generated").exists(), ".fleet-generated should be absent"
    assert not (target / "opencode.json").exists(), "opencode.json should be absent"


def test_scan_passes_on_export(tmp_path: Path) -> None:
    """The public scan must be clean on the exported copy."""
    target = tmp_path / "export"
    result = _run_export(target)
    assert result.returncode == 0, f"export failed: {result.stderr}\n{result.stdout}"

    scan_result = _run_scan(target, SCRIPT_DIR / "public_scan.allow")
    assert scan_result.returncode == 0, f"scan found issues:\n{scan_result.stdout}"


def test_planted_private_path_makes_scan_fail(tmp_path: Path) -> None:
    """A private path planted in the export makes the scan fail."""
    target = tmp_path / "export"
    result = _run_export(target)
    assert result.returncode == 0, f"export failed: {result.stderr}\n{result.stdout}"

    # Planted private path + content (git-add so the scanner sees it)
    planted = target / ".fleet-generated" / "private.md"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("/data/secrets/should-not-be-public\n")
    subprocess.run(["git", "-C", str(target), "add", str(planted)], check=True)

    scan_result = _run_scan(target, SCRIPT_DIR / "public_scan.allow")
    assert scan_result.returncode == 1, "Expected scan to flag planted private data"
    assert "internal_file" in scan_result.stdout or "host_path" in scan_result.stdout