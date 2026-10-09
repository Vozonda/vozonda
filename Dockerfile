# vozonda-api - Python / FastAPI orchestrator + TTS voice engines (Kokoro CPU default, Piper fallback, Qwen3-TTS GPU opt-in)
FROM python:3.11-slim-bookworm

# Prevent python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# System dependencies: ffmpeg (audio mastering), libsndfile (audio I/O), poppler-utils
# (pdftotext: PDF sources), curl (healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    poppler-utils \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install wheel/build tooling
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install PyTorch + Audio + TTS dependencies
# PyPI torch wheels include CPU support and CUDA support when NVIDIA runtime is present
# kokoro-onnx (Apache-2.0) is the CPU quickstart engine; piper-tts (GPL-3.0)
# renders the languages kokoro lacks. Both install side by side.
RUN pip install --no-cache-dir \
    torch \
    torchaudio \
    soundfile \
    numpy \
    qwen-tts \
    kokoro-onnx \
    piper-tts \
    faster-whisper

# Copy API package metadata and install dependencies
COPY apps/api /app/apps/api
RUN pip install --no-cache-dir /app/apps/api

# Create default directories for SQLite database, media artifacts, HF model cache, and TTS voice caches
RUN mkdir -p /app/data /app/media /root/.cache/vozonda/hf /root/.local/share/piper /root/.local/share/kokoro

# Default environment configuration (kokoro renders English and 7 more
# languages; piper covers German and the rest; models download on first use)
ENV VOZONDA_HOST=0.0.0.0 \
    VOZONDA_PORT=8787 \
    VOZONDA_DB=/app/data/jobs.db \
    VOZONDA_MEDIA=/app/media \
    VOZONDA_HF_HOME=/root/.cache/vozonda/hf \
    VOZONDA_TTS_PY=/usr/local/bin/python \
    VOZONDA_TTS_ENGINE=kokoro \
    VOZONDA_TTS_SCRIPT=/app/apps/api/src/vozonda_api/render_kokoro.py

EXPOSE 8787

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8787/health || exit 1

CMD ["uvicorn", "vozonda_api.main:app", "--host", "0.0.0.0", "--port", "8787"]
