import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
QUICKSTART_PATH = REPO_ROOT / "docs" / "quickstart.md"
README_PATH = REPO_ROOT / "README.md"

CPU_TTS_ENGINES = {"piper", "kokoro"}
CPU_TTS_SCRIPTS = {"render_piper.py", "render_kokoro.py"}


def _parse_env_example(text: str) -> dict[str, str]:
    """Parse key-value definitions from .env.example lines."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(?:#\s*)?([A-Za-z0-9_]+)\s*=(.*)$", line)
        if m:
            key = m.group(1).strip()
            raw_val = m.group(2).strip()
            # Strip trailing inline comments if present
            if " #" in raw_val:
                raw_val = raw_val.split(" #", 1)[0].rstrip()
            result[key] = raw_val
    return result


def _extract_compose_env_vars(compose_text: str) -> set[str]:
    """Extract all ${VAR} or ${VAR:-default} variable names from compose text."""
    matches = re.findall(r"\$\{([A-Za-z0-9_]+)", compose_text)
    return set(matches)


def _get_compose_service_env(compose_data: dict, service_name: str) -> dict[str, str]:
    """Extract environment mapping for a service from parsed compose data."""
    service = compose_data.get("services", {}).get(service_name, {})
    env = service.get("environment", {})
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    if isinstance(env, list):
        out = {}
        for item in env:
            if isinstance(item, str) and "=" in item:
                k, v = item.split("=", 1)
                out[k.strip()] = v.strip()
        return out
    return {}


def test_compose_variables_documented_in_env_example():
    """Verify that every variable referenced in docker-compose.yml is documented in .env.example."""
    assert COMPOSE_PATH.exists(), f"Missing docker-compose.yml at {COMPOSE_PATH}"
    assert ENV_EXAMPLE_PATH.exists(), f"Missing .env.example at {ENV_EXAMPLE_PATH}"

    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
    env_example_text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    compose_vars = _extract_compose_env_vars(compose_text)
    assert compose_vars, "No environment variables found in docker-compose.yml"

    env_dict = _parse_env_example(env_example_text)
    env_keys = set(env_dict.keys())

    missing = compose_vars - env_keys
    assert not missing, (
        f"Variables referenced in docker-compose.yml are missing from .env.example: {sorted(missing)}"
    )


def test_default_tts_engine_is_cpu():
    """Verify that docker-compose.yml and Dockerfile default to a CPU engine (e.g. piper)."""
    assert COMPOSE_PATH.exists()
    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
    compose_data = yaml.safe_load(compose_text)

    api_env = _get_compose_service_env(compose_data, "api")

    # Check VOZONDA_TTS_ENGINE default
    engine_val = api_env.get("VOZONDA_TTS_ENGINE", "")
    engine_match = re.search(r":-([a-zA-Z0-9_]+)", engine_val)
    default_engine = engine_match.group(1) if engine_match else engine_val
    assert default_engine in CPU_TTS_ENGINES, (
        f"Expected compose default TTS engine to be one of {CPU_TTS_ENGINES}, got {default_engine!r}"
    )

    # Check VOZONDA_TTS_SCRIPT default
    script_val = api_env.get("VOZONDA_TTS_SCRIPT", "")
    assert any(s in script_val for s in CPU_TTS_SCRIPTS), (
        f"Expected compose default TTS script to reference a CPU renderer ({CPU_TTS_SCRIPTS}), got {script_val!r}"
    )
    assert "render_vozonda.py" not in script_val, (
        "docker-compose.yml should not default to GPU script render_vozonda.py"
    )

    # Check Dockerfile defaults
    assert DOCKERFILE_PATH.exists()
    dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert any(s in dockerfile_text for s in CPU_TTS_SCRIPTS), (
        "Dockerfile should configure a CPU TTS renderer script by default"
    )
    assert "piper-tts" in dockerfile_text, "Dockerfile should install piper-tts for CPU voice synthesis"


def test_no_secrets_in_env_example():
    """Verify that .env.example contains only placeholders and no real secrets or API keys."""
    assert ENV_EXAMPLE_PATH.exists()
    env_text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    env_dict = _parse_env_example(env_text)

    sensitive_keys = {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ELEVENLABS_API_KEY",
        "VOZONDA_TOKEN",
    }

    for key, val in env_dict.items():
        # Keys must not contain real OpenAI keys (sk-...)
        assert not val.startswith("sk-"), f"Found potential OpenAI API key in .env.example for {key}: {val}"
        # Keys must not contain Slack tokens (xoxb-...)
        assert not val.startswith("xoxb-"), f"Found potential Slack token in .env.example for {key}: {val}"
        # Keys must not contain long hex strings (>= 32 chars)
        hex_match = re.search(r"\b[0-9a-fA-F]{32,}\b", val)
        assert not hex_match, f"Found long hex string in .env.example for {key}: {val}"

        # Sensitive keys should be empty placeholders
        if key in sensitive_keys:
            assert val == "" or "your_" in val or "placeholder" in val, (
                f"Sensitive key {key} must have an empty value or safe placeholder, got: {val!r}"
            )


def test_quickstart_docs_and_readme_link():
    """Verify that docs/quickstart.md exists, has required sections, and is linked near the top of README.md."""
    assert QUICKSTART_PATH.exists(), f"Missing docs/quickstart.md at {QUICKSTART_PATH}"
    doc_text = QUICKSTART_PATH.read_text(encoding="utf-8")

    assert len(doc_text) > 200, "docs/quickstart.md is too short"
    assert "docker compose up" in doc_text.lower(), "quickstart.md should mention docker compose command"
    assert "4173" in doc_text, "quickstart.md should mention web UI port 4173"
    assert "feed.xml" in doc_text, "quickstart.md should explain RSS feed location"
    assert "gpu" in doc_text.lower(), "quickstart.md should have a GPU section"
    assert "docker-compose.override.yml" in doc_text, "quickstart.md should document GPU override file"

    # Check README.md links to quickstart.md near the top
    assert README_PATH.exists()
    readme_lines = README_PATH.read_text(encoding="utf-8").splitlines()
    first_screen = "\n".join(readme_lines[:50])
    assert "docs/quickstart.md" in first_screen, (
        "README.md must link to docs/quickstart.md near the top (within the first 50 lines)"
    )


def test_docker_compose_config_parses():
    """Verify that docker-compose.yml parses as valid compose configuration."""
    assert COMPOSE_PATH.exists(), f"Missing docker-compose.yml at {COMPOSE_PATH}"
    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(compose_text)
    assert isinstance(data, dict), "docker-compose.yml must parse to a dictionary"
    assert "services" in data, "docker-compose.yml must define services"
    services = data["services"]
    assert "api" in services, "docker-compose.yml must define api service"
    assert "web" in services, "docker-compose.yml must define web service"

    api_ports = services["api"].get("ports", [])
    assert any("8787" in str(p) for p in api_ports), "api service must expose port 8787"
    web_ports = services["web"].get("ports", [])
    assert any("4173" in str(p) or "80" in str(p) for p in web_ports), "web service must expose port"

    api_volumes = services["api"].get("volumes", [])
    assert len(api_volumes) >= 2, "api service must define volumes"


def test_no_operator_host_paths_in_public_configs_and_docs():
    """Verify that public docs and configuration contain no operator host paths."""
    public_files = [
        REPO_ROOT / "docs" / "deployment.md",
        REPO_ROOT / "docs" / "architecture.md",
        DOCKERFILE_PATH,
        COMPOSE_PATH,
        ENV_EXAMPLE_PATH,
    ]
    # an absolute /data/... path, not a container path such as /app/data/
    pattern = re.compile(r"(?<![\w.~])/data/|/home/cipherfox")
    for file_path in public_files:
        assert file_path.exists(), f"File {file_path} not found"
        for line_num, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
            match = pattern.search(line)
            assert not match, (
                f"Forbidden operator host path in {file_path.name}:{line_num}: {line.strip()}"
            )


def test_no_em_dashes_in_quickstart_artifacts():
    """Verify that none of the files modified for quickstart contain em-dashes (hard rule 5)."""
    checked_files = [
        COMPOSE_PATH,
        DOCKERFILE_PATH,
        ENV_EXAMPLE_PATH,
        QUICKSTART_PATH,
        README_PATH,
        REPO_ROOT / "docs" / "deployment.md",
        REPO_ROOT / "docs" / "architecture.md",
        Path(__file__),
    ]
    em_dash = chr(8212)
    for file_path in checked_files:
        assert file_path.exists(), f"File {file_path} not found"
        content = file_path.read_text(encoding="utf-8")
        assert em_dash not in content, f"Found em-dash in {file_path.name}"


def test_compose_publishes_on_loopback_and_persists_the_db():
    """The quickstart UI sends no token: that is only safe while the ports stay on loopback."""
    services = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))["services"]
    for name in ("api", "web"):
        for port in services[name]["ports"]:
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} beyond loopback"
    env = services["api"]["environment"]
    assert "VOZONDA_PUBLISHED_ON=loopback" in env
    # without it jobs.db lands in site-packages, outside the volume, and is lost on recreate
    assert "VOZONDA_DB=/app/data/jobs.db" in env
    assert any(str(v).endswith(":/app/data") for v in services["api"]["volumes"])
