# Quickstart: From Zero to Your First Episode in 10 Minutes

Vozonda turns web articles, newsletters, and documents into multi-voice podcast
episodes published directly to your personal RSS feed.

By default, Vozonda runs entirely on your CPU using Kokoro TTS, with Piper as
the fallback for German and other languages Kokoro lacks (no NVIDIA GPU or
CUDA required). You only need Docker and an LLM endpoint (local Ollama or any
OpenAI-compatible cloud API).

---

## Prerequisites

1. **Docker and Docker Compose** (Compose v2):
   - Verify with `docker compose version`.
2. **Language Model (LLM)** for script composition:
   - **Option A (Recommended for 100% local, free inference):**
     Install [Ollama](https://ollama.com/) on your host machine and pull a model:
     ```bash
     ollama pull qwen2.5:latest
     ```
     (Or use `llama3.2`, `mistral`, or any other instruction-tuned model.)
   - **Option B (Cloud API):**
     Any OpenAI-compatible API key (OpenAI, OpenRouter, Groq, Together, Mistral).

---

## The Three Commands

Open your terminal and run:

```bash
# 1. Clone the repository
git clone https://github.com/Vozonda/vozonda.git && cd vozonda

# 2. Copy the example configuration
cp .env.example .env

# 3. Launch the containers
docker compose up -d
```

The first build downloads PyTorch and takes several minutes (around 3 to 8 minutes
depending on your network); subsequent starts take only seconds.

> **Port note:** The default ports are 8787 (API) and 4173 (web). If either port
> is already in use on your machine, edit `.env` before running `docker compose up -d`
> and change `VOZONDA_PORT` and `VOZONDA_WEB_PORT` to unused values (e.g. 9787 and 5173).

Both ports are published on `127.0.0.1` only, so Vozonda is reachable from this
machine and nobody else on your network. That is also why the web UI works without
a password. To reach it from other devices, publish the ports on another address in
`docker-compose.yml`, remove `VOZONDA_PUBLISHED_ON=loopback` and set `VOZONDA_TOKEN`
in `.env`; the API then refuses writes without that token.

> **Note for Cloud LLMs:**
> If you are using a cloud API instead of local Ollama, edit `.env` before running
> `docker compose up -d`:
> ```bash
> VOZONDA_LLM_BASE=https://api.openai.com/v1
> VOZONDA_LLM_MODEL=gpt-4o-mini
> OPENAI_API_KEY=your-api-key-here
> ```

---

## Open the Web UI

Once the containers are running, navigate to:

- **Web UI:** [http://localhost:4173](http://localhost:4173)
- **API Health:** [http://localhost:8787/health](http://localhost:8787/health)
- **System Doctor:** [http://localhost:8787/doctor](http://localhost:8787/doctor)

---

## Make Your First Episode from a URL

1. Open [http://localhost:4173](http://localhost:4173) in your browser.
2. In the input box, paste a link to an article, blog post, or essay.
3. Choose a dialogue style (for example, `balanced` for thoughtful discussion,
   `tech_roast` for witty banter, or `eli5` for simple explanations).
4. Click **make it talk** (or **go**).
5. Watch the real-time stage progress:
   - `extract`: Fetches the clean article text and metadata.
   - `script`: Prompts your LLM to write an engaging multi-host script.
   - `voice`: Synthesizes speech turn-by-turn with the CPU voice engine (Kokoro by default, Piper for German and other languages Kokoro lacks).
   - `master`: Normalizes loudness (EBU R128), mixes music beds, and builds MP3.
6. The browser player will appear automatically with interactive waveform,
   karaoke transcript, chapters, and key takeaways.

---

## Audio Sources

Audio files (mp3, m4a, wav, ogg, opus) and podcast episode enclosures are accepted as sources.
They are transcribed locally using faster-whisper (included in the Docker image; for a native
install run `uv sync --extra stt` in `apps/api`). Punctuation is restored by the local LLM in
chunks with a word-for-word check so the raw text is preserved when the LLM changes words. Two
environment variables control transcription: `VOZONDA_WHISPER_MODEL` picks the Whisper model
(default `base`) and `VOZONDA_AUDIO_MAX_BYTES` caps the download size (default 300 MB). A larger
Whisper model is slower but more accurate. A feed item that already carries a `<podcast:transcript>`
tag uses that transcript instead of transcribing.

---

## Where the RSS Feed Lives

Every generated episode is added to your personal podcast feed:

- **Personal Podcast Feed:** [http://localhost:8787/feed.xml](http://localhost:8787/feed.xml)

Add this URL to your preferred podcast player (such as AntennaPod, Pocket Casts,
Apple Podcasts, or Overcast) to receive new episodes on your mobile device as
soon as they are rendered.

---

## Troubleshooting

### 1. LLM Unreachable (`no LLM server on http://host.docker.internal:11434/v1`)
- Verify Ollama is running on your host machine:
  ```bash
  curl http://localhost:11434/v1/models
  ```
- The container reaches your host LLM via `host.docker.internal:11434` (Docker's
  special hostname for reaching services on the host machine).
- On Linux, Ollama may bind only to `127.0.0.1` by default. Allow container access
  by setting `OLLAMA_HOST=0.0.0.0:11434` when launching Ollama:
  ```bash
  OLLAMA_HOST=0.0.0.0:11434 ollama serve
  ```
- If your host IP is static, you can also set `VOZONDA_LLM_BASE=http://<host-ip>:11434/v1`
  in your `.env` file.

### 2. Model Not Found
- If the logs report that the requested model does not exist:
  ```bash
  ollama pull qwen2.5:latest
  ```
  Or change `VOZONDA_LLM_MODEL` in `.env` to match a model you have already pulled
  (run `ollama list` to see installed models).

### 3. Port Already Allocated
- If `docker compose up` reports that port 8787 or 4173 is already in use:
  Edit `.env` and change `VOZONDA_PORT` and `VOZONDA_WEB_PORT` to unused values:
  ```bash
  VOZONDA_PORT=9787
  VOZONDA_WEB_PORT=5173
  ```
  Then run `docker compose up -d` again.

### 4. Check System Doctor
Run the built-in diagnostic tool to identify failing components:
```bash
curl -s http://localhost:8787/doctor | python3 -m json.tool
```

### 5. Viewing Logs
View real-time API logs:
```bash
docker compose logs -f api
```

---

## GPU Acceleration (Optional)

If you have an NVIDIA GPU and wish to use the heavier Qwen3-TTS engine instead
of CPU Kokoro:

1. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
2. Set `VOZONDA_WITH_QWEN_TTS=1` in your `.env` file to include the Qwen3-TTS
   engine (torch, ~2GB) in the Docker image. You must rebuild the image:
   ```bash
   docker compose up -d --build
   ```
3. Create a `docker-compose.override.yml` file in the repository root:
   ```yaml
   services:
     api:
       environment:
         - VOZONDA_TTS_ENGINE=qwen_tts
         - VOZONDA_TTS_SCRIPT=/app/apps/api/src/vozonda_api/render_vozonda.py
       deploy:
         resources:
           reservations:
             devices:
               - driver: nvidia
                 count: all
                 capabilities: [gpu]
   ```
4. Restart Docker Compose:
   ```bash
   docker compose up -d
   ```
5. On the first render with Qwen3-TTS, model weights (~4GB) will download
   automatically to the persistent `vozonda-hf-cache` Docker volume.
