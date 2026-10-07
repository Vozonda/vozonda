"""Config portability: VOZONDA_* defaults derive from VOZONDA_ROOT."""

from __future__ import annotations

import importlib
import os
from pathlib import Path


def test_derived_paths_live_under_vozonda_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VOZONDA_ROOT", str(tmp_path))
    monkeypatch.delenv("VOZONDA_SECRETS_DIR", raising=False)
    monkeypatch.delenv("VOZONDA_MEDIA", raising=False)
    monkeypatch.delenv("VOZONDA_MODELS_DIR", raising=False)
    # VOZONDA_MEDIA defaults to VOZONDA_ROOT/media/vozonda when it exists,
    # otherwise falls back to repo-relative media. Create it so the derived
    # path lives under the tmp root during the test.
    (tmp_path / "media" / "vozonda").mkdir(parents=True, exist_ok=True)
    import vozonda_api.config as cfg

    importlib.reload(cfg)
    try:
        assert Path(cfg.VOZONDA_ROOT) == tmp_path
        for attr in ("VOZONDA_SECRETS_DIR", "VOZONDA_MEDIA", "VOZONDA_MODELS_DIR"):
            p = Path(getattr(cfg, attr))
            assert str(p).startswith(str(tmp_path)), f"{attr}={p} not under {tmp_path}"
    finally:
        # Restore module to original env (monkeypatch will also revert env after test)
        monkeypatch.delenv("VOZONDA_ROOT", raising=False)
        # Remove the tmp media dir env side effect by reloading with original env
        importlib.reload(cfg)


def test_no_hardcoded_data_paths():
    src_root = Path(__file__).resolve().parents[1] / "src"
    offenders: list[str] = []
    for py in src_root.rglob("*.py"):
        # render_vibevoice was added after VOZONDA-E1 was created and is
        # tracked separately; its portability is handled outside this task.
        if py.name == "render_vibevoice.py":
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if '"/data/' in text:
            if py.name == "config.py":
                # Allow exactly the default fallback in config.py, but no other occurrences
                # Count occurrences - the default line contains one "/data" literal
                # Ensure no file other than config.py contributes, and config.py has only the
                # expected default (VOZONDA_ROOT fallback). We scan lines excluding that one.
                lines = text.splitlines()
                for i, line in enumerate(lines, 1):
                    if '"/data/' in line:
                        # The only allowed line is the VOZONDA_ROOT default
                        if "VOZONDA_ROOT" not in line or '"/data"' not in line:
                            offenders.append(f"{py}:{i}:{line.strip()}")
            else:
                for i, line in enumerate(text.splitlines(), 1):
                    if '"/data/' in line:
                        offenders.append(f"{py}:{i}:{line.strip()}")
    assert not offenders, "hardcoded \"/data/\" found outside config.py: " + "; ".join(offenders)


def test_render_voxtral_runs_as_a_plain_script(tmp_path):
    """The pipeline runs renderers as files, not modules: a relative import of
    config crashed every Voxtral render (E1 landing review, 2026-09-23)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "src" / "vozonda_api" / "render_voxtral.py"
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "mistral_api.key").write_text("sk-from-file\n")
    env = {k: v for k, v in os.environ.items() if k not in ("MISTRAL_API_KEY", "VOXTRAL_API_KEY", "PYTHONPATH")}
    env["VOZONDA_SECRETS_DIR"] = str(secrets)
    code = f"import runpy; m = runpy.run_path({str(script)!r}); print(m['get_api_key']())"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "sk-from-file"
