"""Protocol interfaces for vozonda plugin system.

Each plugin kind has a Protocol that conforming modules or classes can
satisfy. All Protocols use runtime_checkable so the registry can verify
conformance, but heavy module bodies are never imported until the
Protocol methods are actually called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import PluginMeta


@runtime_checkable
class HasMeta(Protocol):
    """Minimal contract: every plugin module must expose META."""

    META: PluginMeta


@runtime_checkable
class TTSPlugin(Protocol):
    """Text-to-speech engine plugin."""

    META: PluginMeta

    async def render_audio(
        self,
        lines: list[dict[str, str]],
        workdir: Path,
        voices: dict[str, dict[str, str | None]],
        *,
        language: str = "en",
        gap_ms: int = 380,
    ) -> Path:
        """Render dialogue lines to a WAV file. Returns path to output."""
        ...

    async def probe(self) -> bool:
        """Fast health check. Must not import heavy deps."""
        ...

    def speakers(self) -> list[dict[str, str]]:
        """Return speaker table as plain data (no torch import)."""
        ...


@runtime_checkable
class ScriptEnginePlugin(Protocol):
    """LLM dialogue script generation plugin."""

    META: PluginMeta

    async def generate_script(
        self,
        prompt: str,
        *,
        model: str = "",
        max_tokens: int = 8192,
        temperature: float = 0.7,
        timeout: float = 600.0,
    ) -> tuple[list[dict[str, str]], str]:
        """Generate dialogue lines from prompt.

        Returns (lines, description).
        """
        ...

    async def probe(self) -> bool:
        """Fast health check."""
        ...


@runtime_checkable
class IngestorPlugin(Protocol):
    """Content ingestion plugin (URL to text)."""

    META: PluginMeta

    def can_handle(self, url: str) -> bool:
        """Return True if this ingestor accepts the URL scheme/domain."""
        ...

    async def fetch(
        self,
        url: str,
        *,
        max_bytes: int = 2_000_000,
    ) -> tuple[str, str, str | None]:
        """Fetch and extract content.

        Returns (title, body, og_image_url or None).
        """
        ...


@runtime_checkable
class AudioFilterPlugin(Protocol):
    """Audio post-processing filter plugin."""

    META: PluginMeta

    async def process(
        self,
        input_path: Path,
        output_path: Path,
        *,
        params: dict[str, str | float | int | bool] | None = None,
    ) -> Path:
        """Transform audio file. Returns path to output."""
        ...

    async def probe(self) -> bool:
        """Fast health check."""
        ...
