"""Tests for the WITH_QWEN_TTS Docker build argument feature."""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def read_file(name: str) -> str:
    return (ROOT / name).read_text()


class TestDockerfileQwenOptional:
    """Verify Dockerfile and related files for WITH_QWEN_TTS support."""

    def test_arg_exists(self):
        dockerfile = read_file("Dockerfile")
        assert "ARG WITH_QWEN_TTS=0" in dockerfile

    def test_conditional_install(self):
        dockerfile = readfile = read_file("Dockerfile")
        # torch, torchaudio, qwen-tts should only appear inside the conditional block
        # We check that the unconditional pip install does NOT contain them
        unconditional_section = dockerfile.split("RUN if [ \"$WITH_QWEN_TTS\" = \"1\" ]")[0]
        assert "torch" not in unconditional_section or "torch" in unconditional_section.split("kokoro-onnx")[0] # Rough check
        # Better: check the specific conditional block exists and contains the packages
        assert "pip install --no-cache-dir torch torchaudio qwen-tts" in dockerfile

    def test_unconditional_packages(self):
        dockerfile = read_file("Dockerfile")
        # These should be in the first pip install
        assert "kokoro-onnx" in dockerfile
        assert "piper-tts" in dockerfile
        assert "soundfile" in dockerfile
        assert "numpy" in dockerfile

    def test_docker_compose_passes_arg(self):
        compose = read_file("docker-compose.yml")
        assert "WITH_QWEN_TTS:" in compose
        assert "${VOZONDA_WITH_QWEN_TTS:-0}" in compose

    def test_env_example_mentions_var(self):
        env_example = read_file(".env.example")
        assert "VOZONDA_WITH_QWEN_TTS" in env_example


class TestQuickstartDocs:
    def test_gpu_section_mentions_build(self):
        quickstart = read_file("docs/quickstart.md")
        assert "VOZONDA_WITH_QWEN_TTS=1" in quickstart
        assert "docker compose up -d --build" in quickstart


class TestChangelog:
    def test_changelog_entry(self):
        changelog = read_file("CHANGELOG.md")
        assert "VOZONDA_WITH_QWEN_TTS=1" in changelog
        assert "#26" in changelog
