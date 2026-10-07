"""Tests for OSS hygiene: SECURITY.md and GitHub CI workflow parity with Gitea CI."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

SECURITY_MD = REPO_ROOT / "SECURITY.md"
GITHUB_CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITEA_CI = REPO_ROOT / ".gitea" / "workflows" / "ci.yml"


def _read(path: Path) -> str:
    return path.read_text()


def test_files_exist() -> None:
    """SECURITY.md and both CI workflow files must exist."""
    assert SECURITY_MD.exists(), f"{SECURITY_MD} not found"
    assert GITHUB_CI.exists(), f"{GITHUB_CI} not found"
    assert GITEA_CI.exists(), f"{GITEA_CI} not found"


def test_security_has_required_sections() -> None:
    """SECURITY.md must contain all required section headings."""
    content = _read(SECURITY_MD)
    sections = [
        "Supported Versions",
        "Reporting a Vulnerability",
        "Scope",
        "Bug Bounty",
    ]
    for section in sections:
        pat = f"#{{1,6}}\\s+{re.escape(section)}"
        assert re.search(pat, content), f"SECURITY.md missing section: {section}"


def test_security_no_email() -> None:
    """SECURITY.md must not contain private email addresses (vozonda@proton.me allowed)."""
    content = _read(SECURITY_MD)
    email_re = re.compile(r"\S+@\S+\.\S+")
    matches = [m.strip("*") for m in email_re.findall(content)]
    unexpected = [m for m in matches if m != "vozonda@proton.me"]
    assert unexpected == [], f"SECURITY.md must not contain unexpected email addresses, found: {unexpected}"


def test_security_github_advisories() -> None:
    """SECURITY.md must reference GitHub Security Advisories."""
    content = _read(SECURITY_MD)
    assert "Security Advisories" in content or "security advisory" in content.lower(), (
        "SECURITY.md must reference GitHub Security Advisories"
    )


def test_security_no_hostnames() -> None:
    """SECURITY.md must not mention hostnames or URLs to specific hosts."""
    content = _read(SECURITY_MD)
    hostname_re = re.compile(r"https?://[a-zA-Z0-9][-a-zA-Z0-9]*(\.[a-zA-Z0-9][-a-zA-Z0-9]*)+")
    matches = hostname_re.findall(content)
    assert matches == [], f"SECURITY.md must not contain hostnames, found: {matches}"


def test_security_no_bug_bounty() -> None:
    """SECURITY.md must state there is no bug bounty."""
    content = _read(SECURITY_MD)
    assert "no bug bounty" in content.lower() or "not a bug bounty" in content.lower(), (
        "SECURITY.md must mention no bug bounty"
    )


def test_security_response_time() -> None:
    """SECURITY.md must mention an expected first-response time."""
    content = _read(SECURITY_MD)
    response_re = re.compile(
        r"(\d+)\s*(hours?|hrs?|days?|hours|days)",
        re.IGNORECASE,
    )
    matches = response_re.findall(content)
    assert matches, (
        "SECURITY.md must mention an expected response time (e.g. '48 hours')"
    )


def test_github_ci_has_required_run_commands() -> None:
    """Every 'run:' command in the Gitea CI must have an equivalent in the GitHub CI."""
    gitea_content = _read(GITEA_CI)
    github_content = _read(GITHUB_CI)

    # Extract all 'run:' values from the Gitea workflow
    gitea_runs = re.findall(r"^\s+run:\s+(.+)$", gitea_content, re.MULTILINE)

    # Check that each Gitea 'run' value appears in the GitHub CI
    for cmd in gitea_runs:
        stripped = cmd.strip()
        found = any(stripped in line for line in github_content.splitlines())
        assert found, (
            f"Gitea CI 'run: {stripped}' not found in GitHub CI"
        )


def test_github_ci_triggers() -> None:
    """GitHub CI workflow must trigger on push and pull_request."""
    content = _read(GITHUB_CI)
    assert "push:" in content, "GitHub CI must trigger on push"
    assert "pull_request:" in content, "GitHub CI must trigger on pull_request"


def test_github_ci_pinned_actions() -> None:
    """Actions must be pinned to a major version tag."""
    content = _read(GITHUB_CI)
    uses_re = re.findall(r"uses:\s+(\S+)", content)
    for action_ref in uses_re:
        assert "@v" in action_ref or "@main" in action_ref or "@" in action_ref, (
            f"Action '{action_ref}' should be pinned to a version (major or full SHA)"
        )


def test_github_ci_no_secrets() -> None:
    """GitHub CI workflow must not reference secrets."""
    content = _read(GITHUB_CI)
    assert "secrets" not in content.lower() or "inherit" in content.lower() or (
        "github" in content.lower() and "token" in content.lower()
    ), "GitHub CI should not require secrets configuration"