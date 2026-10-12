#!/usr/bin/env python3
"""Unified release, version bump, and changelog synchronization script for Vozonda.

Keeps all package manifests, version files, CHANGELOG.md, and public website
changelog in strict sync:
1. apps/api/pyproject.toml
2. apps/api/src/vozonda_api/version.py
3. apps/web/package.json
4. packages/npm/package.json
5. CHANGELOG.md (promotes [Unreleased] to [X.Y.Z] - YYYY-MM-DD)
6. Optional website sync (vozonda-website changelog & deploy)

Usage:
    python3 scripts/bump_version.py 0.7.5
    python3 scripts/bump_version.py patch
    python3 scripts/bump_version.py minor
    python3 scripts/bump_version.py 0.7.5 --sync-website
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "apps" / "api" / "pyproject.toml"
VERSION_PY_PATH = REPO_ROOT / "apps" / "api" / "src" / "vozonda_api" / "version.py"
WEB_PACKAGE_JSON = REPO_ROOT / "apps" / "web" / "package.json"
NPM_PACKAGE_JSON = REPO_ROOT / "packages" / "npm" / "package.json"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


def get_current_version() -> str:
    """Read the current base version from version.py."""
    content = VERSION_PY_PATH.read_text(encoding="utf-8")
    m = re.search(r'^BASE_VERSION\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not m:
        raise ValueError(f"Could not find BASE_VERSION in {VERSION_PY_PATH}")
    return m.group(1)


def compute_next_version(current: str, target: str) -> str:
    """Compute target version from semver keyword or literal version string."""
    if target in ("patch", "minor", "major"):
        parts = current.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"Current version '{current}' is not SemVer X.Y.Z")
        major, minor, patch = map(int, parts)
        if target == "patch":
            patch += 1
        elif target == "minor":
            minor += 1
            patch = 0
        elif target == "major":
            major += 1
            minor = 0
            patch = 0
        return f"{major}.{minor}.{patch}"
    if not re.match(r"^\d+\.\d+\.\d+$", target):
        raise ValueError(f"Invalid target version: {target}. Must be X.Y.Z or patch/minor/major")
    return target


def bump_pyproject(new_ver: str, dry_run: bool) -> None:
    content = PYPROJECT_PATH.read_text(encoding="utf-8")
    updated, n = re.subn(r'version\s*=\s*["\'][^"\']+["\']', f'version = "{new_ver}"', content, count=1)
    if n == 0:
        raise ValueError("Failed to update version in pyproject.toml")
    if not dry_run:
        PYPROJECT_PATH.write_text(updated, encoding="utf-8")


def bump_version_py(new_ver: str, dry_run: bool) -> None:
    content = VERSION_PY_PATH.read_text(encoding="utf-8")
    updated, n = re.subn(r'^BASE_VERSION\s*=\s*["\'][^"\']+["\']', f'BASE_VERSION = "{new_ver}"', content, count=1, flags=re.MULTILINE)
    if n == 0:
        raise ValueError("Failed to update BASE_VERSION in version.py")
    if not dry_run:
        VERSION_PY_PATH.write_text(updated, encoding="utf-8")


def bump_package_json(path: Path, new_ver: str, dry_run: bool) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = new_ver
    if not dry_run:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def promote_changelog(new_ver: str, dry_run: bool) -> bool:
    """Promote [Unreleased] section to [new_ver] - YYYY-MM-DD in CHANGELOG.md."""
    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    today = date.today().isoformat()
    # Check if section for new_ver already exists
    if f"## [{new_ver}]" in content:
        return False
    # Replace ## [Unreleased]
    header = f"## [{new_ver}] - {today}"
    updated, n = re.subn(r"## \[Unreleased\]", header, content, count=1)
    if n == 0:
        print("Warning: No '## [Unreleased]' section found in CHANGELOG.md")
        return False
    if not dry_run:
        CHANGELOG_PATH.write_text(updated, encoding="utf-8")
    return True


def sync_website_changelog(dry_run: bool) -> bool:
    """Sync CHANGELOG.md changes to vozonda-website repository."""
    website_repo = Path(os.environ.get("VOZONDA_WEBSITE_DIR", REPO_ROOT.parent / "vozonda-website"))
    tools_dir = Path(os.environ.get("VOZONDA_TOOLS_DIR", REPO_ROOT.parent.parent / "scripts" / "floki" / "sites" / "vozonda-tools"))
    changelog_py = tools_dir / "changelog.py"
    build_py = website_repo / "build.py"

    if not website_repo.exists() or not changelog_py.exists():
        print("Note: Website repo or changelog tool not found; skipping website sync.")
        return False

    if dry_run:
        print(f"[dry-run] Would run {changelog_py} and {build_py}")
        return True

    print("Rebuilding website changelog and shell pages...")
    subprocess.run([sys.executable, str(changelog_py)], cwd=website_repo, check=True)
    if build_py.exists():
        subprocess.run([sys.executable, str(build_py)], cwd=website_repo, check=True)

    # Check git status of website repo
    status = subprocess.run(["git", "status", "--porcelain"], cwd=website_repo, capture_output=True, text=True, check=True).stdout
    if status.strip():
        print("Changes detected in website repo. Staging and committing...")
        subprocess.run(["git", "add", "changelog/index.html", "roadmap/index.html", "sitemap.xml", "404/index.html", "blind-test/index.html", "compare/index.html", "support/index.html"], cwd=website_repo, check=False)
        subprocess.run(["git", "commit", "-m", "auto: sync changelog and pages from app release"], cwd=website_repo, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=website_repo, check=True)
        print("Website repo updated and pushed to origin main.")
    else:
        print("Website repo is already up to date.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronized version bumper and release tool for Vozonda")
    parser.add_argument("version", help="Target version (e.g. 0.7.5) or semver bump keyword (patch, minor, major)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")
    parser.add_argument("--sync-website", action="store_true", help="Sync website changelog and trigger deploy")
    parser.add_argument("--tag", action="store_true", help="Create git tag vX.Y.Z after committing")
    args = parser.parse_args()

    curr_ver = get_current_version()
    new_ver = compute_next_version(curr_ver, args.version)
    print(f"Bumping version: {curr_ver} -> {new_ver} (dry_run={args.dry_run})")

    bump_pyproject(new_ver, args.dry_run)
    bump_version_py(new_ver, args.dry_run)
    bump_package_json(WEB_PACKAGE_JSON, new_ver, args.dry_run)
    bump_package_json(NPM_PACKAGE_JSON, new_ver, args.dry_run)
    promoted = promote_changelog(new_ver, args.dry_run)
    print(f"Updated manifests and version files for v{new_ver} (changelog promoted: {promoted})")

    if args.sync_website:
        sync_website_changelog(args.dry_run)


if __name__ == "__main__":
    main()
