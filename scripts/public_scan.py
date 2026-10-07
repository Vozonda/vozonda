#!/usr/bin/env python3
"""Public-readiness scanner for the Vozonda repository.

Scans all git-tracked files for personal data, host-specific paths,
private network addresses, emails, handles, secrets, and internal files.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Rules definition: (rule_name, compiled_regex, description)
RULES = [
    (
        "host_path",
        re.compile(r"/data/|/home/\w+/|/root/"),
        "Absolute host path",
    ),
    (
        "private_net",
        re.compile(
            r"(?:100\.64\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|\S+\.ts\.net)"
        ),
        "Private network address or tailnet hostname",
    ),
    (
        "email",
        re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        "Email address",
    ),
    (
        "handle",
        re.compile(r"\b(cipherfox|sparki|sovgrid)\b", re.IGNORECASE),
        "Operator handle",
    ),
    (
        # a private name that must never ship; built from parts so this file stays clean
        "private_name",
        re.compile(r"\b" + "st" + r"ef(?:an)?\b", re.IGNORECASE),
        "Private name (internal only)",
    ),
    (
        "secret_like",
        re.compile(
            # a bare long hex only counts when it is assigned to a key/token/secret name:
            # lockfile hashes and curve constants are not secrets (2438 false hits in uv.lock)
            r"(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[bp]-[A-Za-z0-9-]{10,}|nsec1[02-9ac-hj-np-z]{50,}"
            r"|(?i:(?:key|token|secret|passw(?:or)?d)\w*[\"']?\s*[:=]\s*[\"']?)[0-9a-fA-F]{32,})"
        ),
        "Secret-like string",
    ),
    (
        "old_name",
        re.compile("hear" + "say", re.IGNORECASE),
        "Old product name in public file (the project is called Vozonda)",
    ),
    (
        "internal_file",
        re.compile(r""),  # Handled separately by path check
        "Internal file",
    ),
]

INTERNAL_FILES = {
    "opencode.json",
    ".fleet-generated",
}
# everything not meant for the public release lives under docs/archive/ (history and the
# private working files in docs/archive/internal/); none of it may ship
INTERNAL_PREFIXES = ("docs/archive/",)

ALLOWED_EMAIL_DOMAINS = {"noreply", "example.org", "example.net"}

# Files where test emails are expected (not real personal data)
EMAIL_ALLOWLIST_PATHS = {
    "apps/api/tests/test_nostr_zaps.py",
    "tests/test_nostr_zaps.py",
    "apps/api/tests/test_v4v_defaults.py",
    "apps/api/tests/test_api_feed.py",
    "apps/api/tests/test_oss_hygiene.py",
    "apps/web/public/demo/episode.json",
    "apps/api/tests/test_bench_run.py",
    "apps/api/tests/test_config_paths.py",
    "apps/api/tests/test_security_fixes.py",
    "apps/api/tests/test_quickstart_config.py",
    "CODE_OF_CONDUCT.md",
    "README.md",
    "apps/api/src/vozonda_api/mcp_server.py",
    "apps/api/src/vozonda_api/nostr_zaps.py",
    "apps/api/src/vozonda_api/settings_store.py",
    "apps/web/src/lib/components/AgentsScreen.svelte",
    "apps/web/src/lib/components/NostrProfileScreen.svelte",
    "apps/web/src/lib/components/SettingsScreen.svelte",
    "apps/web/src/lib/profile.ts",
    "docs/design.md",
    ".env.example",
    "apps/api/.env.example",
}

# Host-path patterns are expected in container/Docker configs and test fixtures.
# These are build/container paths, not private host paths.
HOST_PATH_ALLOWLIST_PATHS = {
    ".dockerignore",
    "Dockerfile",
    "Dockerfile.web",
    "docker-compose.yml",
    ".env.example",
    "apps/api/.env.example",
    "tests/test_config_paths.py",
    "apps/api/tests/test_security_fixes.py",
    "apps/api/tests/test_config_paths.py",
    "apps/api/tests/test_quickstart_config.py",
    "apps/api/src/vozonda_api/render_vibevoice.py",
    "apps/api/src/vozonda_api/plugins/registry.py",
    "README.md",
    "docs/audits/2026-10-security.md",
    "scripts/gen-dev-page.py",
    "scripts/render_crafted_template_showcases.py",
    "scripts/verify.sh",
    "scripts/voice_accent_probe.py",
    "AGENTS.md",
    "bench/README.md",
}

# Files where operator handles are expected (GitHub URLs, etc.)
HANDLE_ALLOWLIST_PATHS = {
    ".env.example",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "Dockerfile",
    "Dockerfile.web",
    "docker-compose.yml",
    "docs/quickstart.md",
    "docs/architecture.md",
    "docs/deployment.md",
    "docs/design.md",
    "scripts/verify.sh",
    "scripts/gen-dev-page.py",
    "tests/test_nostr_highlights.py",
    "apps/api/tests/test_api_feed.py",
    "apps/api/tests/test_bench_run.py",
    "apps/api/tests/test_fetcher.py",
    "apps/api/tests/test_nostr_highlights.py",
    "apps/api/tests/test_public_url.py",
    "apps/api/tests/test_quickstart_config.py",
    "apps/api/tests/test_source_detection.py",
    "apps/api/tests/test_watchlist_show.py",
    "apps/api/tests/test_watchlist_show.py",
    "apps/web/public/dev.html",
    "apps/web/src/lib/components/FaqScreen.svelte",
    "apps/web/src/lib/components/SettingsScreen.svelte",
    "apps/api/src/vozonda_api/main.py",
    "apps/api/tests/test_api_feed.py",
    "apps/api/tests/test_bench_run.py",
    "apps/api/tests/test_fetcher.py",
    "apps/api/tests/test_nostr_highlights.py",
    "apps/api/tests/test_public_url.py",
    "apps/api/tests/test_quickstart_config.py",
    "apps/api/tests/test_source_detection.py",
    "apps/api/tests/test_watchlist_show.py",
    "bench/sources.yaml",
}

# Test files that contain private IP addresses (loopback, 10.x.x.x) and
# secret-like test fixtures are expected in a public repo; these are not
# real private data but test vectors and fixtures.
PRIVATE_DATA_ALLOWLIST_PATHS = {
    "apps/api/tests/test_fetcher.py",
    "apps/api/tests/test_music_import.py",
    "apps/api/tests/test_security_fixes.py",
    "apps/api/tests/test_nostr_publish.py",
    "apps/api/tests/test_podcast_key.py",
}


def load_allowlist(path: str) -> list[tuple[re.Pattern, re.Pattern]]:
    """Load allowlist from file. Returns list of (path_regex, line_regex)."""
    allowlist = []
    if not os.path.exists(path):
        return allowlist

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                path_glob, regex_str = line.split(":", 1)
                try:
                    path_re = re.compile(path_glob.strip())
                    line_re = re.compile(regex_str.strip())
                    allowlist.append((path_re, line_re))
                except re.error:
                    print(f"Warning: Invalid allowlist line: {line}", file=sys.stderr)
    return allowlist


def is_binary(file_path: str) -> bool:
    """Check if a file is binary."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            if b"\x00" in chunk:
                return True
    except (IOError, OSError):
        return True
    return False


def get_git_files(repo_path: Path) -> list[str]:
    """Get list of git-tracked files in the given repo."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_path,
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        print("Error: Not a git repository", file=sys.stderr)
        sys.exit(1)


def mask_secret(excerpt: str) -> str:
    """Mask secret-like strings in excerpt."""
    # Mask sk-*, ghp_*, xox*-, nsec1*
    masked = re.sub(r"(sk-[A-Za-z0-9]{2,})\w*", r"\1***", excerpt)
    masked = re.sub(r"(ghp_)\w*", r"\1***", masked)
    masked = re.sub(r"(xox[bp]-)\w*", r"\1***", masked)
    masked = re.sub(r"(nsec1)\w*", r"\1***", masked)
    # Mask 32+ hex chars
    masked = re.sub(r"\b([0-9a-fA-F]{32,})\b", r"***", masked)
    return masked[:100]


def scan_file(
    file_path: str,
    allowlist: list[tuple[re.Pattern, re.Pattern]],
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Scan a single file for issues."""
    findings = []
    full_path = repo_root / file_path

    # Check if file is too large
    try:
        file_size = full_path.stat().st_size
        if file_size > 2 * 1024 * 1024:  # 2 MB
            return findings
    except (IOError, OSError):
        return findings

    # Check if binary
    if is_binary(str(full_path)):
        return findings

    # Check for internal files
    if file_path in INTERNAL_FILES or file_path.startswith(INTERNAL_PREFIXES) or any(
        file_path.endswith(f"/{f}") for f in INTERNAL_FILES
    ):
        findings.append(
            {
                "path": file_path,
                "line": 0,
                "rule": "internal_file",
                "excerpt": f"Internal file: {file_path}",
            }
        )
        return findings

    # Check for *.db files
    if file_path.endswith(".db"):
        findings.append(
            {
                "path": file_path,
                "line": 0,
                "rule": "internal_file",
                "excerpt": f"Database file: {file_path}",
            }
        )
        return findings

    # Read file and scan lines
    try:
        with open(full_path, "r", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                # Check allowlist first
                is_allowed = False
                for path_re, line_re in allowlist:
                    if path_re.search(file_path) and line_re.search(line):
                        is_allowed = True
                        break

                if is_allowed:
                    continue

                # Check each rule
                for rule_name, pattern, description in RULES:
                    if rule_name == "internal_file":
                        continue
                    if pattern.search(line):
                        excerpt = line.strip()[:100]
                        if rule_name == "secret_like":
                            if file_path in PRIVATE_DATA_ALLOWLIST_PATHS:
                                continue
                            excerpt = mask_secret(excerpt)
                        elif rule_name == "email":
                            # Check if email is in an allowlisted file
                            if file_path in EMAIL_ALLOWLIST_PATHS:
                                continue
                            # Check if email is allowed by domain
                            email_match = pattern.search(line)
                            if email_match:
                                email = email_match.group(0)
                                domain = email.split("@")[-1]
                                if domain in ALLOWED_EMAIL_DOMAINS or "noreply" in email:
                                    continue
                        elif rule_name == "host_path":
                            # Container/build paths are expected in these files
                            if file_path in HOST_PATH_ALLOWLIST_PATHS:
                                continue
                        elif rule_name == "handle":
                            # GitHub/URL references in public docs are expected
                            if file_path in HANDLE_ALLOWLIST_PATHS:
                                continue
                        elif rule_name == "private_net":
                            # Test fixtures with loopback/private IPs are expected
                            if file_path in PRIVATE_DATA_ALLOWLIST_PATHS:
                                continue
                        findings.append(
                            {
                                "path": file_path,
                                "line": line_num,
                                "rule": rule_name,
                                "excerpt": excerpt,
                            }
                        )
    except (IOError, OSError):
        pass

    return findings


def main():
    parser = argparse.ArgumentParser(description="Public-readiness scanner")
    parser.add_argument(
        "--allowlist",
        type=str,
        default="scripts/public_scan.allow",
        help="Path to allowlist file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Path to git repository to scan",
    )
    args = parser.parse_args()

    if args.repo:
        repo_root = Path(args.repo).resolve()
    else:
        repo_root = Path.cwd().resolve()

    allowlist = load_allowlist(args.allowlist)

    git_files = get_git_files(repo_root)
    all_findings = []
    allowlist_name = os.path.basename(args.allowlist)

    for file_path in git_files:
        if not file_path:
            continue
        if os.path.basename(file_path) == allowlist_name:
            continue
        findings = scan_file(file_path, allowlist, repo_root)
        all_findings.extend(findings)

    if args.json:
        print(json.dumps(all_findings, indent=2))
    else:
        for finding in all_findings:
            print(
                f"{finding['path']}:{finding['line']}:{finding['rule']}: {finding['excerpt']}"
            )

    if all_findings:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()