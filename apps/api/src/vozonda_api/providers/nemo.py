"""NVIDIA Nemo TTS provider with access token gate and pay-per-job billing support.

This provider uses Nemo's TTS capabilities with billing and access token validation.
"""

import asyncio
from pathlib import Path
from typing import Any

from ..billing import InsufficientBalanceError, TokenValidationError, charge_job, confirm_charge, validate_token
from ..env import env
from ..plugins.types import Permission, PluginKind, PluginMeta

META = PluginMeta(
    id="nemo",
    kind=PluginKind.TTS_ENGINE,
    label="nemo (NVIDIA FastPitch + HiFiGAN)",
    permissions=frozenset({Permission.GPU}),
    supports_instructions=False,
    supports_emotion_instructions=False,
    supports_paralinguistic_tags=False,
    ui_badge="local GPU",
    ui_fix_hint="pip install nemo_toolkit",
    license="NVIDIA NeMo (Apache-2.0)",
)


async def render_audio(
    script: list[dict[str, Any]],
    workdir: Path,
    timbre_profile: dict[str, Any] | None = None,
    access_token: str | None = None,
    job_id: str | None = None,
) -> Path:
    """Render audio using NVIDIA Nemo TTS with billing integration.

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
            charge = charge_job(job_id, user_id, "nemo", job_type)
            print(f"Nemo: charged {charge['amount_sats']} sats to user {user_id} for job {job_id}")
        except InsufficientBalanceError as e:
            raise InsufficientBalanceError(f"Cannot render: {e}") from e

    # Import Nemo
    try:
        import torch
        from nemo.collections.tts.models import FastPitch, HiFiGAN
    except ImportError:
        raise RuntimeError("nemo_toolkit not installed. Run: pip install nemo_toolkit")

    output_path = workdir / "speech.mp3"

    try:
        # Load models (using pretrained models from Nemo)
        spec_gen = FastPitch.from_pretrained("tts_en_fastpitch")
        vocoder = HiFiGAN.from_pretrained("tts_en_hifigan")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        spec_gen = spec_gen.to(device)
        vocoder = vocoder.to(device)

        # Combine script lines into single text
        full_text = " ".join([line.get("text", "").strip() for line in script if line.get("text")])

        if not full_text.strip():
            raise ValueError("No text to render")

        # Generate spectrogram
        with torch.no_grad():
            spec = spec_gen.forward(tokens=spec_gen.text_to_tokens(full_text))

        # Generate audio from spectrogram
        with torch.no_grad():
            audio = vocoder.forward(spec)

        # Save audio
        from scipy.io import wavfile

        audio_np = audio.squeeze().cpu().numpy()
        sample_rate = 22050
        wavfile.write(str(workdir / "speech.wav"), sample_rate, audio_np)

        # Convert WAV to MP3 using ffmpeg
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(workdir / "speech.wav"),
            "-q:a",
            "5",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        if proc.returncode != 0 or not output_path.exists():
            raise RuntimeError("FFmpeg conversion failed")

        # Mark charge as confirmed on success
        if user_id and job_id and env("ENABLE_BILLING", "false").lower() == "true":
            confirm_charge(job_id)

        return output_path

    except Exception as e:
        raise RuntimeError(f"Nemo TTS failed: {e}") from e
