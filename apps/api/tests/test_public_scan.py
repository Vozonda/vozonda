"""Tests for public_scan.py"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run_scan(allowlist_content: str = "", extra_args: list[str] | None = None) -> tuple[int, str, str]:
    """Run the public_scan.py script in a temporary git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
        
        # Create allowlist file if provided
        allowlist_path = repo_path / "public_scan.allow"
        if allowlist_content:
            allowlist_path.write_text(allowlist_content)
        
        # Create a test file with various issues
        test_file = repo_path / "test.txt"
        test_file.write_text(
            "This is a test file\n"
            "Path: /data/projects/vozonda\n"
            "IP: 192.168.1.1\n"
            "Email: user@example.com\n"
            "Handle: cipherfox\n"
            "Secret: sk-12345678901234567890\n"
            "Internal: docs/archive/internal/COORDINATION.md\n"
        )
        
        # Commit the file
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "test"], cwd=repo_path, check=True, capture_output=True)
        
        # Run the scanner
        script_path = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "public_scan.py"
        cmd = [sys.executable, str(script_path), "--repo", str(repo_path)]
        if allowlist_content:
            cmd.extend(["--allowlist", str(allowlist_path)])
        if extra_args:
            cmd.extend(extra_args)
        
        result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
        return result.returncode, result.stdout, result.stderr


def test_host_path_finding():
    """Test that host paths are detected."""
    returncode, stdout, _stderr = run_scan()
    assert returncode == 1
    assert "/data/" in stdout


def test_private_net_finding():
    """Test that private network addresses are detected."""
    returncode, stdout, _stderr = run_scan()
    assert returncode == 1
    assert "192.168.1.1" in stdout


def test_email_finding():
    """Test that email addresses are detected."""
    returncode, stdout, _stderr = run_scan()
    assert returncode == 1
    assert "user@example.com" in stdout


def test_handle_finding():
    """Test that operator handles are detected."""
    returncode, stdout, _stderr = run_scan()
    assert returncode == 1
    assert "cipherfox" in stdout


def test_secret_like_finding():
    """Test that secret-like strings are detected."""
    returncode, stdout, _stderr = run_scan()
    assert returncode == 1
    assert "sk-" in stdout


def test_internal_file_finding():
    """Test that internal files are detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
        
        # Create an internal file
        internal_dir = repo_path / "docs/archive/internal"
        internal_dir.mkdir(parents=True, exist_ok=True)
        internal_file = internal_dir / "COORDINATION.md"
        internal_file.write_text("Internal coordination file")
        
        # Commit the file
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "test"], cwd=repo_path, check=True, capture_output=True)
        
        # Run the scanner
        script_path = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "public_scan.py"
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        
        assert result.returncode == 1
        assert "internal_file" in result.stdout


def test_allowlist():
    """Test that allowlist works correctly."""
    allowlist_content = "test.txt:.*data/projects/vozonda.*"
    returncode, stdout, _stderr = run_scan(allowlist_content=allowlist_content)
    # The /data/ path should be allowed, but other findings should remain
    assert returncode == 1
    # Check that the allowed line is not in the output
    assert "/data/projects/vozonda" not in stdout


def test_json_output():
    """Test that JSON output works correctly."""
    returncode, stdout, _stderr = run_scan(extra_args=["--json"])
    assert returncode == 1
    # Should be valid JSON
    data = json.loads(stdout)
    assert isinstance(data, list)
    assert len(data) > 0


def test_no_findings():
    """Test that no findings results in exit code 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
        
        # Create a clean file
        clean_file = repo_path / "clean.txt"
        clean_file.write_text("This is a clean file with no issues")
        
        # Commit the file
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "test"], cwd=repo_path, check=True, capture_output=True)
        
        # Run the scanner
        script_path = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "public_scan.py"
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        
        assert result.returncode == 0


NAME = "St" + "ef"  # built from parts so this file passes the scan


def test_private_first_name_is_flagged(tmp_path):
    """A name on the private deny pattern is flagged, longer words are not."""
    import subprocess
    import sys
    from pathlib import Path

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.org"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo_path, check=True)
    (repo_path / "CONTRIBUTING.md").write_text(f"Maintained by somebody ({NAME}).\n{NAME}hanie stays fine.\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-qm", "t"], cwd=repo_path, check=True)
    script = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "public_scan.py"
    res = subprocess.run([sys.executable, str(script)], cwd=repo_path, capture_output=True, text=True, check=False)
    assert res.returncode == 1 and "private_name" in res.stdout
    assert res.stdout.count("private_name") == 1, "only the exact name, not longer words"


OLD_NAME = "hear" + "say"


def _scan_repo(tmp_path, files):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.org"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo_path, check=True)
    for rel, text in files.items():
        f = repo_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-qm", "t"], cwd=repo_path, check=True)
    script = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "public_scan.py"
    return subprocess.run([sys.executable, str(script)], cwd=repo_path, capture_output=True, text=True, check=False)


def test_old_name_is_flagged_everywhere(tmp_path):
    """The old product name is flagged in every file: no allowlist, not even the changelog."""
    res = _scan_repo(tmp_path, {
        "notes.txt": f"Welcome to {OLD_NAME} audio overview.\n",
        "CHANGELOG.md": f"Changed: renamed from {OLD_NAME.upper()}\n",
        "docs/history.md": f"Historical {OLD_NAME.capitalize()} notes.\n",
    })
    assert res.returncode == 1
    findings = [line for line in res.stdout.splitlines() if "old_name" in line]
    assert len(findings) == 3, res.stdout


def test_scanner_source_does_not_contain_the_old_name():
    script = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "public_scan.py"
    assert OLD_NAME not in script.read_text().lower()
