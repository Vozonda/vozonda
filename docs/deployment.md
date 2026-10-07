# Vozonda Deployment Guide

This guide covers deploying Vozonda on any modern Linux server (Ubuntu 24.04 LTS, Debian 12, or equivalent).

---

## 1. System Requirements

### Hardware Specs

- **Minimum (Cloud TTS / Lightweight CPU):**
  - 2 CPU cores
  - 4 GB RAM
  - 10 GB disk space

- **Recommended (Local Qwen3-TTS with NVIDIA GPU):**
  - 4+ CPU cores
  - 16 GB RAM
  - NVIDIA GPU with 8 GB+ VRAM (e.g. RTX 3060, RTX 4070, A100, etc.)
  - 25 GB disk space (for model weights and rendered audio)

- **DGX Spark "sparki" (Sovereign Grid Reference):**
  - GB10 Blackwell, 121 GB Unified Memory, SM 12.1
  - Qwen3.6-35B via vLLM :30001 (49.2 tok/s, 67 GB mem)
  - Mutex: only one inference service at a time (Qwen vLLM OR Mistral SGLang)

- **CPU Fallback for Local TTS:**
  - Works on any x86_64 or ARM64 Linux system without a dedicated GPU. Note that CPU synthesis takes longer per turn than GPU synthesis.

---

## 2. Docker Compose Deployment (Recommended)

Docker Compose is the fastest and most reliable way to run Vozonda in production.

### Step 1: Install Docker and Docker Compose

On Ubuntu 24.04:

```bash
# Update package index and install prerequisites
sudo apt update
sudo apt install -y curl ca-certificates gnupg

# Add Docker official GPG key and repository
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow current user to run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

### Step 2 (Optional): Enable NVIDIA GPU Support

If your server has an NVIDIA GPU:

```bash
# Install NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Then uncomment the `deploy.resources.reservations.devices` block in `docker-compose.yml`.

### Step 3: Clone Repository and Configure

```bash
git clone https://github.com/Vozonda/vozonda.git /opt/vozonda
cd /opt/vozonda

# Copy sample configuration
cp .env.example .env
```

Edit `.env` to match your infrastructure:

```bash
nano .env
```

#### Example 1: Local Ollama on Host + Local Qwen3-TTS

```bash
VOZONDA_LLM_BASE=http://host.docker.internal:11434/v1
VOZONDA_LLM_MODEL=qwen2.5:latest
VOZONDA_RENDERER=qwen_tts
```

#### Example 2: Cloud OpenAI LLM + OpenAI TTS (Zero Local GPU Needed)

```bash
VOZONDA_LLM_BASE=https://api.openai.com/v1
VOZONDA_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-proj-your-openai-key

VOZONDA_TTS_FALLBACKS='[{"name":"openai_tts","model":"gpt-4o-mini-tts","voices":{"A":"onyx","B":"nova"},"key_env":"OPENAI_API_KEY"}]'
```

### Step 4: Build and Start Containers

```bash
cd /opt/vozonda
docker compose up -d
```

Check logs and health status:

```bash
docker compose logs -f
curl http://localhost:8787/doctor
```

---

## 3. Native / Bare-Metal Deployment (systemd user units)

This is the production deployment used on the DGX Spark "sparki"  -  no Docker, systemd user services for API and Web.

### Step 1: Install System Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg nodejs npm curl git build-essential libsndfile1 sox libsox-fmt-all
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### Step 2: Set Up Backend

```bash
cd ~/vozonda/apps/api
uv venv
source .venv/bin/activate
uv pip install -e .
uv pip install torch soundfile numpy qwen-tts
```

### Step 3: Set Up Frontend

```bash
cd ~/vozonda/apps/web
npm ci
npm run build
```

### Step 4: systemd User Service Units

Create `~/.config/systemd/user/vozonda-api.service`:

```ini
[Unit]
Description=Vozonda API Orchestrator
After=network.target

[Service]
Type=simple
WorkingDirectory=~/vozonda
EnvironmentFile=~/vozonda/.env
ExecStart=~/vozonda/apps/api/.venv/bin/uvicorn vozonda_api.main:app --host 127.0.0.1 --port 8787
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Create `~/.config/systemd/user/vozonda-web.service`:

```ini
[Unit]
Description=Vozonda Web Preview (Vite)
After=network.target

[Service]
Type=simple
WorkingDirectory=~/vozonda/apps/web
ExecStart=/usr/bin/npm run preview -- --host 0.0.0.0 --port 4173
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Enable and start services:

```bash
systemctl --user daemon-reload
systemctl --user enable --now vozonda-api vozonda-web
systemctl --user status vozonda-api vozonda-web
```

Enable lingering for boot-time start (run once as the deploying user):

```bash
sudo loginctl enable-linger $(whoami)
```

### Step 5: Reverse Proxy (Caddy)

Install Caddy and configure `/etc/caddy/Caddyfile`:

```caddy
vozonda.example.com {
    reverse_proxy localhost:4173
}
```

Share pages, OG tags and clip links use the address each request comes in on;
Caddy passes the original host through, so this works without configuration.
If your proxy rewrites the host, set `VOZONDA_PUBLIC_URL=https://vozonda.example.com`.

---

## 4. Environment Configuration (.env)

Copy `.env.example` to `.env` and adjust. Key variables:

```bash
# LLM
VOZONDA_LLM_BASE=http://host.docker.internal:11434/v1
VOZONDA_LLM_MODEL=qwen2.5:latest

# TTS (kokoro = CPU default, piper renders the languages kokoro lacks, qwen_tts = GPU)
VOZONDA_TTS_ENGINE=kokoro
VOZONDA_TTS_FALLBACKS='[]'

# Public address for share pages and clip links (empty = request host)
VOZONDA_PUBLIC_URL=

# Database & Media
VOZONDA_DB=data/jobs.db
VOZONDA_MEDIA=media

# Watchlist
VOZONDA_WATCHLIST_INTERVAL=600
VOZONDA_WATCHLIST_MAX_NEW=3

# Auth: required as soon as VOZONDA_HOST is not a loopback address
VOZONDA_TOKEN=
```

Full list in `.env.example` (18/20 vars documented, see #142).

---

## 5. Health Diagnostics & Doctor Endpoint

### Run Doctor Diagnostic

```bash
curl http://localhost:8787/doctor
```

With fresh probes (bypasses 60s cache):

```bash
curl "http://localhost:8787/doctor?refresh=1"
```

The response returns a checklist verifying:
- `script_llm`: Reachability of primary LLM and fallbacks
- `voice_engine`: Availability of Python and TTS packages
- `voice_renderable`: Qwen3-TTS can synthesize
- `master_ffmpeg`: FFmpeg binary in PATH
- `media_dir`: Writable media storage directory
- `model_cache`: Hugging Face cache accessible
- `engine_qwen_tts`: Qwen3-TTS installed and available
- `engine_piper`: Piper TTS status (optional)

### View Real-Time Logs

```bash
# systemd user services
journalctl --user -u vozonda-api -f
journalctl --user -u vozonda-web -f

# Docker
docker compose logs -f api
docker compose logs -f web
```

---

## 6. QA Audit Flow & Seed Script

### Full Audit

```bash
cd ~/vozonda/apps/web
node scripts/audit.cjs
```

Runs 42 checks against `http://localhost:4173` (web preview proxying to API). All 42 must pass.

### Seed Script (CI / Manual QA)

```bash
cd ~/vozonda
./scripts/seed-qa.sh
```

Creates a demo episode via API (text paste, ~2 min render). Usage documented in `audit.cjs` header.

Environment overrides:
```bash
SEED_TEXT="custom text" SEED_STYLE=balanced SEED_FORMAT=dialog ./scripts/seed-qa.sh
SEED_URL="https://example.com" ./scripts/seed-qa.sh
```

### verify.sh (Pre-commit / CI Gate)

```bash
cd ~/vozonda
./scripts/verify.sh
```

Runs: ruff -> pytest -> svelte-check -> build. All must pass.

---

## 7. Restart Guard

**Never** restart API with bare `systemctl restart vozonda-api` while jobs are rendering.

Use the guard script:

```bash
./scripts/restart-api.sh
```

- Refuses to restart if jobs are running (`queued` or `rendering`)
- Override with `--force` (honest admission you are killing renders)
- Logs to `systemd` journal

---

## 8. Backups & Maintenance

### Persistent Data

All state is stored in three locations:
1. **SQLite Database:** `data/jobs.db` (job history, watchlist, settings)
2. **Audio Media:** `media/` (rendered MP3 files, peaks.json, chapters)
3. **Model Cache:** `~/.cache/vozonda/hf` (Qwen3-TTS weights)

### Backup Command

```bash
# Snapshot the database and media folder
cd ~/vozonda
tar -czvf vozonda-backup-$(date +%Y%m%d).tar.gz data/jobs.db media/
```

### Updating Vozonda (systemd user)

```bash
cd ~/vozonda
git pull
cd apps/api && source .venv/bin/activate && uv pip install -e .
cd ../web && npm ci && npm run build
systemctl --user restart vozonda-api vozonda-web
```

### Updating Vozonda (Docker)

```bash
cd /opt/vozonda
git pull
docker compose build
docker compose up -d
```

---

## 9. Current Feature Set

See the [Changelog](https://vozonda.com/changelog/) for current releases and updates.

- **Compose:** Paste URL or text → select style/format/voices/language → render
- **Digest Mode (Phase 1):** Per-feed digest toggle, count select (2-5), "render digest now" button, chapter list on listen view, digest badge in library
- **Watchlist:** Add RSS feeds, check feeds, per-feed voice settings, digest controls
- **Listen:** Static `/e/{id}` page + SPA `#e={id}` with waveform player, karaoke transcript, chapter seek, j/k navigation, space toggle
- **Library:** Search, filter (style/language), sort, delete
- **Feed.xml:** RSS 2.0 with Podcasting 2.0 extensions (`podcast:value`, chapters, enclosures)
- **Engine Switch:** Runtime TTS engine selection (GET/PUT `/tts/engine`)
- **Settings:** Advanced settings screen with live doctor card

---

## 10. Troubleshooting

- **First job takes several minutes:** Initial run downloads Qwen3-TTS model weights (~4 GB) to HF cache. Subsequent runs instant.
- **LLM Connection Refused:** Ensure host LLM (Ollama/vLLM) listens on `0.0.0.0` or use `http://host.docker.internal:11434/v1` in Docker.
- **Settings screen "stuck on loading":** API may be cold-starting; audit now polls up to 6s (#143).
- **Job queue stuck:** Use `./scripts/restart-api.sh --force` to clear (kills in-flight renders).
- **Audio range requests 404:** Job ID in audit was stale; audit now uses newest done episode dynamically.