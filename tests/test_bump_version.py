"""Tests for scripts/bump_version.py auto bump functionality."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts directory to path so we can import bump_version
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import bump_version


class TestAutoBump:
    """Tests for auto bump version detection from CHANGELOG.md."""

    def test_auto_minor_with_added(self, monkeypatch):
        """Auto bump picks minor when Unreleased has ### Added."""
        changelog = """# Changelog

## [Unreleased]

### Added
- New feature

### Fixed
- Bug fix
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text(changelog)

            # Monkeypatch the module's CHANGELOG_PATH
            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            bump_type, reason = bump_version.determine_auto_bump("0.7.5")
            assert bump_type == "minor"
            assert "Added" in reason

    def test_auto_patch_with_only_fixed(self, monkeypatch):
        """Auto bump picks patch when Unreleased has only ### Fixed."""
        changelog = """# Changelog

## [Unreleased]

### Fixed
- Bug fix
- Another fix
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text(changelog)

            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            bump_type, reason = bump_version.determine_auto_bump("0.7.5")
            assert bump_type == "patch"
            assert "Fixed" in reason
            assert "Added" not in reason

    def test_auto_patch_with_only_security(self, monkeypatch):
        """Auto bump picks patch when Unreleased has only ### Security."""
        changelog = """# Changelog

## [Unreleased]

### Security
- Security fix
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text(changelog)

            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            bump_type, reason = bump_version.determine_auto_bump("0.7.5")
            assert bump_type == "patch"
            assert "Security" in reason

    def test_auto_minor_with_breaking_at_zero_major(self, monkeypatch):
        """Auto bump picks minor for BREAKING at 0.x."""
        changelog = """# Changelog

## [Unreleased]

### Added
- New feature

BREAKING: API changed
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text(changelog)

            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            bump_type, reason = bump_version.determine_auto_bump("0.7.5")
            assert bump_type == "minor"
            assert "BREAKING" in reason
            assert "0.x" in reason

    def test_auto_major_with_breaking_at_one_major(self, monkeypatch):
        """Auto bump picks major for BREAKING at 1.x+."""
        changelog = """# Changelog

## [Unreleased]

### Fixed
- Bug fix

BREAKING: Major API change
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text(changelog)

            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            bump_type, reason = bump_version.determine_auto_bump("1.2.3")
            assert bump_type == "major"
            assert "BREAKING" in reason
            assert "1.x" in reason

    def test_auto_minor_with_changed_or_removed(self, monkeypatch):
        """Auto bump picks minor for ### Changed or ### Removed."""
        for heading in ["### Changed", "### Removed"]:
            changelog = f"""# Changelog

## [Unreleased]

{heading}
- Something changed
"""
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                changelog_path = tmp_path / "CHANGELOG.md"
                changelog_path.write_text(changelog)

                monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

                bump_type, _ = bump_version.determine_auto_bump("0.7.5")
                assert bump_type == "minor", f"Failed for {heading}"

    def test_auto_exit_on_empty_unreleased(self, monkeypatch):
        """Auto bump exits with error when Unreleased is empty."""
        changelog = """# Changelog

## [Unreleased]

## [0.7.5] - 2026-10-15

### Fixed
- Old fix
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text(changelog)

            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            with pytest.raises(SystemExit) as exc:
                bump_version.determine_auto_bump("0.7.5")
            assert "nothing to release" in str(exc.value).lower()

    def test_auto_exit_on_no_unreleased_section(self, monkeypatch):
        """Auto bump exits with error when no Unreleased section exists."""
        changelog = """# Changelog

## [0.7.5] - 2026-10-15

### Fixed
- Old fix
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text(changelog)

            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            with pytest.raises(SystemExit) as exc:
                bump_version.determine_auto_bump("0.7.5")
            assert "unreleased" in str(exc.value).lower()


class TestDryRun:
    """Tests for --dry-run behavior."""

    def test_dry_run_writes_nothing(self, monkeypatch, capsys):
        """Dry run prints preview but writes no files."""
        changelog = """# Changelog

## [Unreleased]

### Added
- New feature
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            # Create all the files the script touches
            pyproject = tmp_path / "pyproject.toml"
            pyproject.write_text('version = "0.7.5"\n')
            
            version_py = tmp_path / "version.py"
            version_py.write_text('BASE_VERSION = "0.7.5"\n')
            
            web_pkg = tmp_path / "package.json"
            web_pkg.write_text('{"version": "0.7.5"}\n')
            
            npm_pkg = tmp_path / "package-npm.json"
            npm_pkg.write_text('{"version": "0.7.5"}\n')
            
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text(changelog)

            monkeypatch.setattr(bump_version, "PYPROJECT_PATH", pyproject)
            monkeypatch.setattr(bump_version, "VERSION_PY_PATH", version_py)
            monkeypatch.setattr(bump_version, "WEB_PACKAGE_JSON", web_pkg)
            monkeypatch.setattr(bump_version, "NPM_PACKAGE_JSON", npm_pkg)
            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            # Run main with auto and --dry-run
            original_argv = sys.argv
            sys.argv = ["bump_version.py", "auto", "--dry-run"]
            try:
                bump_version.main()
            finally:
                sys.argv = original_argv

            # Verify files unchanged
            assert pyproject.read_text() == 'version = "0.7.5"\n'
            assert version_py.read_text() == 'BASE_VERSION = "0.7.5"\n'
            assert web_pkg.read_text() == '{"version": "0.7.5"}\n'
            assert npm_pkg.read_text() == '{"version": "0.7.5"}\n'
            assert changelog_path.read_text() == changelog

            # Verify output mentions dry-run
            out = capsys.readouterr().out
            assert "dry-run" in out.lower()


class TestExplicitBumps:
    """Tests that explicit patch/minor/major still work."""

    def test_explicit_patch(self, monkeypatch):
        """Explicit 'patch' argument still computes correct version."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text("# Changelog\n\n## [Unreleased]\n\n### Fixed\n- fix\n")
            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            new_ver = bump_version.compute_next_version("0.7.5", "patch")
            assert new_ver == "0.7.6"

    def test_explicit_minor(self, monkeypatch):
        """Explicit 'minor' argument still computes correct version."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text("# Changelog\n\n## [Unreleased]\n\n### Fixed\n- fix\n")
            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            new_ver = bump_version.compute_next_version("0.7.5", "minor")
            assert new_ver == "0.8.0"

    def test_explicit_major(self, monkeypatch):
        """Explicit 'major' argument still computes correct version."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text("# Changelog\n\n## [Unreleased]\n\n### Fixed\n- fix\n")
            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            new_ver = bump_version.compute_next_version("0.7.5", "major")
            assert new_ver == "1.0.0"

    def test_explicit_version_string(self, monkeypatch):
        """Explicit version string still works."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            changelog_path = tmp_path / "CHANGELOG.md"
            changelog_path.write_text("# Changelog\n\n## [Unreleased]\n\n### Fixed\n- fix\n")
            monkeypatch.setattr(bump_version, "CHANGELOG_PATH", changelog_path)

            new_ver = bump_version.compute_next_version("0.7.5", "1.2.3")
            assert new_ver == "1.2.3"


class TestComputeNextVersion:
    """Tests for compute_next_version function."""

    def test_invalid_keyword_raises(self):
        """Invalid keyword raises ValueError."""
        with pytest.raises(ValueError):
            bump_version.compute_next_version("0.7.5", "invalid")

    def test_invalid_version_format_raises(self):
        """Invalid version format raises ValueError."""
        with pytest.raises(ValueError):
            bump_version.compute_next_version("0.7.5", "1.2")

    def test_non_semver_current_raises(self):
        """Non-semver current version raises for keyword bumps."""
        with pytest.raises(ValueError):
            bump_version.compute_next_version("0.7", "patch")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])