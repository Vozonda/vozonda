"""Qwen TTS provider with access token gate and pay-per-job billing support.

This provider wraps the local qwen_tts renderer and applies billing logic
and access token validation before rendering.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ..billing import InsufficientBalanceError, TokenValidationError, charge_job, confirm_charge, validate_token
from ..env import env
from ..plugins.types import Permission, PluginKind, PluginMeta

META = PluginMeta(
    id="qwen_tts",
    kind=PluginKind.TTS_ENGINE,
    label="qwen3_tts (local GPU, studio quality)",
    permissions=frozenset({Permission.GPU, Permission.SUBPROCESS}),
    supports_instructions=True,
    supports_emotion_instructions=True,
    supports_paralinguistic_tags=False,
    ui_badge="local GPU",
    ui_fix_hint="uv sync --extra tts-qwen",
    renderer="render_vozonda.py",
    license="Apache-2.0",
)


async def render_audio(
    script: list[dict[str, Any]],
    workdir: Path,
    timbre_profile: dict[str, Any] | None = None,
    access_token: str | None = None,
    job_id: str | None = None,
) -> Path:
    """Render audio using Qwen TTS with billing integration.

    Args:
        script: dialogue lines with speaker and text
        workdir: output directory
        timbre_profile: voice profiles for speakers
        access_token: access token for gated access
        job_id: job ID for billing

    Returns:
        Path to rendered MP3 file

    Raises:
        TokenValidationError: if access token is invalid/inactive
        InsufficientBalanceError: if user balance insufficient
    """
    # Validate access token if provided
    user_id = None
    if access_token:
        try:
            token_info = validate_token(access_token)
            user_id = token_info["user_id"]
        except TokenValidationError as e:
            raise TokenValidationError(f"Access denied: {e}") from e

    # Charge user if enabled and access token provided
    if user_id and job_id and env("ENABLE_BILLING", "false").lower() == "true":
        try:
            job_type = "digest" if len(script) > 20 else "standard"
            charge = charge_job(job_id, user_id, "qwen", job_type)
            print(f"Qwen: charged {charge['amount_sats']} sats to user {user_id} for job {job_id}")
        except InsufficientBalanceError as e:
            raise InsufficientBalanceError(f"Cannot render: {e}") from e

    # Import and call the actual qwen renderer
    try:
        import torch
        from qwen_tts import Qwen3TTSModel
    except ImportError:
        raise RuntimeError("qwen_tts not installed. Run: uv sync --extra tts-qwen")

    # Use environment-configured Python for subprocess rendering if needed
    tts_py = env("TTS_PY", sys.executable)
    tts_script = env(
        "TTS_SCRIPT",
        str(Path(__file__).resolve().parent.parent / "render_vozonda.py"),
    )

    if not Path(tts_script).exists():
        # Fallback to direct rendering
        model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-1B")
        output_path = workdir / "speech.mp3"

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)

        for line in script:
            text = line.get("text", "").strip()
            if text:
                # Simple direct rendering
                with torch.no_grad():
                    audio = model.forward(text)
                    audio.save(str(output_path))
                break

        if user_id and job_id and env("ENABLE_BILLING", "false").lower() == "true":
            confirm_charge(job_id)

        return output_path

    # Use subprocess renderer
    script_json = json.dumps(script)
    profile_json = json.dumps(timbre_profile or {})

    try:
        proc = await asyncio.create_subprocess_exec(
            tts_py,
            tts_script,
            script_json,
            str(workdir),
            profile_json,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode() if stderr else "unknown error"
            raise RuntimeError(f"Qwen renderer failed: {error_msg}")

        output_path = workdir / "speech.mp3"
        if not output_path.exists():
            raise RuntimeError("Qwen renderer did not produce output")

        # Mark charge as confirmed on success
        if user_id and job_id and env("ENABLE_BILLING", "false").lower() == "true":
            confirm_charge(job_id)

        return output_path

    except Exception as e:
        raise RuntimeError(f"Qwen TTS failed: {e}") from e
