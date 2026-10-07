#!/usr/bin/env python3
"""Render handcrafted, representative 20-35s peak excerpt showcases for Vozonda templates.

Each template showcases an authentic, characterful peak moment:
- Instant immersion into the style (witty roasts, breaking flashes, philosophical inquiry, eerie noir)
- Recommended TTS engine per template (Voxtral, Kokoro, Qwen3-TTS, Piper)
- Distinctive voice pairings and register contrasts
- Vozonda audio pipeline mastering: raised-cosine ducked musical beds + EBU R128 (-16 LUFS)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_SRC = REPO_ROOT / "apps/api/src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from vozonda_api.music import apply_music_beds_to_file, style_to_jingle_preset  # noqa: E402

MEDIA_DIR = Path("/data/media/vozonda/template_craft")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

TARGET_DIR = REPO_ROOT / "apps/web/public/media/samples/templates"
TARGET_DIR.mkdir(parents=True, exist_ok=True)

VENV_PY = REPO_ROOT / "apps/api/.venv/bin/python"

SHOWCASES = [
    {
        "id": "morning_dispatch",
        "title": "voxtral · news pulse",
        "engine": "voxtral",
        "renderer": "render_voxtral.py",
        "style": "serious",
        "speed": 1.05,
        "gap_ms": 280,
        "voices": {"a": "oliver", "b": "emma"},
        "segments": [
            {
                "speaker": "a",
                "text": "Flash update: European sovereign nodes just absorbed forty terabytes of redirected compute in under sixty milliseconds."
            },
            {
                "speaker": "b",
                "text": "Zero packet loss across the alpine relays. Centralized providers are scrambling to explain why their multi-region SLAs just got beaten by local clusters."
            },
            {
                "speaker": "a",
                "text": "The unit economics speak for themselves: independence is no longer a luxury, it is the performance baseline."
            }
        ]
    },
    {
        "id": "feature_story",
        "title": "qwen · deep story",
        "engine": "qwen_tts",
        "renderer": "render_vozonda.py",
        "style": "balanced",
        "speed": 1.00,
        "gap_ms": 360,
        "voices": {"a": "dylan", "b": "sohee"},
        "segments": [
            {
                "speaker": "a",
                "text": "Down in the server cavern, the temperature never rises above four degrees. There are no fans screaming, just the soft click of relay switches in total darkness."
            },
            {
                "speaker": "b",
                "text": "When Elena first plugged her hard drive into the rack, she expected a firewall prompt. Instead, the terminal simply printed: Welcome home. We kept your seat warm."
            },
            {
                "speaker": "a",
                "text": "Ten years of memories, preserved offline, safe from the algorithmic churn of the open web."
            }
        ]
    },
    {
        "id": "trio_roundtable",
        "title": "kokoro · 3-way clash",
        "engine": "kokoro",
        "renderer": "render_kokoro.py",
        "style": "clash",
        "speed": 1.02,
        "gap_ms": 260,
        "voices": {"a": "af_bella", "b": "am_michael", "c": "bf_emma"},
        "segments": [
            {
                "speaker": "a",
                "text": "Michael, you cannot just tell enterprise compliance teams to ditch cloud APIs and run everything on a refurbished gaming rig!"
            },
            {
                "speaker": "b",
                "text": "Why not? The model weights fit in VRAM, the data never leaves the building, and you aren't paying twenty cents a prompt to rent your own thoughts!"
            },
            {
                "speaker": "c",
                "text": "Until someone needs real-time multimodal search across five million PDFs, Michael! Then your gaming rig catches fire."
            },
            {
                "speaker": "b",
                "text": "Then buy two gaming rigs, Emma! Still cheaper than a single enterprise contract."
            }
        ]
    },
    {
        "id": "tech_roast",
        "title": "kokoro · roast duel",
        "engine": "kokoro",
        "renderer": "render_kokoro.py",
        "style": "tech_roast",
        "speed": 1.08,
        "gap_ms": 200,
        "voices": {"a": "am_adam", "b": "af_sarah"},
        "segments": [
            {
                "speaker": "a",
                "text": "Wait, so they took an open source model, changed the CSS hex code to corporate navy, and billed the client two hundred thousand dollars?"
            },
            {
                "speaker": "b",
                "text": "Worse. They added an AI disclaimer in the footer that says: results may vary based on quantum alignment."
            },
            {
                "speaker": "a",
                "text": "Quantum alignment! That is not machine learning, that is astrology for venture capitalists!"
            },
            {
                "speaker": "b",
                "text": "And the board gave them a standing ovation."
            }
        ]
    },
    {
        "id": "true_crime_dossier",
        "title": "voxtral · crime noir",
        "engine": "voxtral",
        "renderer": "render_voxtral.py",
        "style": "true_crime",
        "speed": 0.95,
        "gap_ms": 420,
        "voices": {"a": "oliver", "b": "emma"},
        "segments": [
            {
                "speaker": "a",
                "text": "The investigator looked at the forensic dump. The cryptographic signature wasn't signed from a remote IP."
            },
            {
                "speaker": "b",
                "text": "It was signed from inside the bank's own air-gapped terminal. At three in the morning, while the building was locked from the outside."
            },
            {
                "speaker": "a",
                "text": "And the security guard on duty? He hadn't worked there for six months."
            },
            {
                "speaker": "b",
                "text": "Yet his badge swiped through the vault doors eleven times that night."
            }
        ]
    },
    {
        "id": "explainer_lab",
        "title": "qwen · eli5 lab",
        "engine": "qwen_tts",
        "renderer": "render_vozonda.py",
        "style": "eli5",
        "speed": 0.98,
        "gap_ms": 320,
        "voices": {"a": "dylan", "b": "sohee"},
        "segments": [
            {
                "speaker": "a",
                "text": "So how does Alice convince Bob she knows the secret without telling him what it is?"
            },
            {
                "speaker": "b",
                "text": "Imagine Alice is colorblind, and Bob has two identical balls, one red, one green. Bob hides them behind his back, switches them or doesn't, and asks: did I switch them?"
            },
            {
                "speaker": "a",
                "text": "If she is guessing, she is wrong half the time. But after twenty rounds..."
            },
            {
                "speaker": "b",
                "text": "She is right every single time. Probability of faking it? One in a million. Truth proven, zero information leaked."
            }
        ]
    },
    {
        "id": "socratic_dialogue",
        "title": "voxtral · inquiry",
        "engine": "voxtral",
        "renderer": "render_voxtral.py",
        "style": "socrates",
        "speed": 0.92,
        "gap_ms": 460,
        "voices": {"a": "oliver", "b": "emma"},
        "segments": [
            {
                "speaker": "a",
                "text": "If you cannot inspect the weights that shape your judgment, tell me, friend: who is doing the thinking?"
            },
            {
                "speaker": "b",
                "text": "Surely I am. I pose the inquiry and I decide whether to act upon the answer."
            },
            {
                "speaker": "a",
                "text": "And when a river carves a valley, does the stone decide where the water flows, or does the contour of the river dictate the path?"
            },
            {
                "speaker": "b",
                "text": "Then... he who shapes the model shapes the riverbed of the mind."
            }
        ]
    },
    {
        "id": "solo_audio_essay",
        "title": "piper · calm essay",
        "engine": "piper",
        "renderer": "render_piper.py",
        "style": "balanced",
        "speed": 0.95,
        "gap_ms": 380,
        "voices": {"solo": "amy"},
        "segments": [
            {
                "speaker": "solo",
                "text": "We were told that convenience required surrender: surrender of our data, our infrastructure, our quiet attention. But convenience without agency is simply a velvet cage. When you take the friction back, you also take back the dignity of ownership."
            }
        ]
    },
    {
        "id": "zen_meditation",
        "title": "piper · zen calm",
        "engine": "piper",
        "renderer": "render_piper.py",
        "style": "meditation",
        "speed": 0.85,
        "gap_ms": 2000,
        "voices": {"solo": "amy"},
        "segments": [
            {
                "speaker": "solo",
                "text": "Notice the brief, quiet pause between the end of the in-breath and the beginning of the exhale.",
                "gap_ms": 2200
            },
            {
                "speaker": "solo",
                "text": "In that still space, the mind has no obligations.",
                "gap_ms": 2000
            },
            {
                "speaker": "solo",
                "text": "Breathe out slowly. Soften your shoulders, and simply be.",
                "gap_ms": 600
            }
        ]
    }
]


def render_showcase(item: dict, force: bool = False) -> bool:
    item_id = item["id"]
    title = item["title"]
    engine = item["engine"]
    renderer_name = item["renderer"]
    style = item["style"]
    speed = item["speed"]
    gap_ms = item["gap_ms"]
    voices = item["voices"]
    segments = item["segments"]

    print(f"\n=======================================================")
    print(f"Rendering Peak Excerpt: {item_id} ({title})")
    print(f"Engine: {engine} | Style: {style} | Speed: {speed}x | Gap: {gap_ms}ms")
    print(f"Voices: {voices}")
    print(f"=======================================================")

    t0 = time.time()
    work_wav = MEDIA_DIR / f"{item_id}.raw.wav"
    cfg_path = MEDIA_DIR / f"{item_id}.cfg.json"

    cfg = {
        "segments": segments,
        "voices": voices,
        "gap_ms": gap_ms,
        "language": "English",
        "out": str(work_wav),
    }
    cfg_path.write_text(json.dumps(cfg, indent=2))

    renderer_script = API_SRC / "vozonda_api" / renderer_name
    hf_home = os.environ.get("HF_HOME", "/ai/models")

    if not force and work_wav.exists() and work_wav.stat().st_size > 1000:
        print(f"Reusing existing clean raw speech WAV ({work_wav.name})...")
    else:
        # Step 1: Synthesize speech via engine renderer
        cmd = [
            str(VENV_PY),
            str(renderer_script),
            "--config",
            str(cfg_path),
        ]

        print(f"Running TTS synthesis ({renderer_name})...")
        env = {**os.environ, "HF_HOME": hf_home}
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if res.returncode != 0 or not work_wav.exists():
            print(f"ERROR: Synthesis failed for {item_id}:", file=sys.stderr)
            print(res.stderr, file=sys.stderr)
            return False

        print(f"TTS synthesis completed in {time.time() - t0:.1f}s.")

    # Step 2: Read turn durations for music bed alignment
    timing_file = work_wav.parent / f"{work_wav.stem}.timing.json"
    turn_durations = None
    if timing_file.exists():
        try:
            turn_durations = json.loads(timing_file.read_text())
        except Exception:
            pass

    # Step 3: Final mastering with ffmpeg (speed + loudnorm EBU R128 + smooth head/tail fades)
    final_mp3 = TARGET_DIR / f"{item_id}.mp3"
    filters = []
    if abs(speed - 1.0) > 0.01:
        filters.append(f"atempo={max(0.5, min(2.0, speed))}")
    filters.append("afade=t=in:st=0:d=0.04")
    filters.append("loudnorm=I=-16:LRA=11:TP=-1.5")

    master_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(work_wav),
        "-af",
        ",".join(filters),
        "-b:a",
        "128k",
        str(final_mp3),
    ]

    print(f"Mastering clean voice with EBU R128 to {final_mp3.name}...")
    m_res = subprocess.run(master_cmd, capture_output=True, text=True)
    if m_res.returncode != 0 or not final_mp3.exists():
        print(f"ERROR: Mastering failed for {item_id}:", file=sys.stderr)
        print(m_res.stderr, file=sys.stderr)
        return False

    # Step 5: Probe duration
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(final_mp3),
    ]
    p_res = subprocess.run(probe_cmd, capture_output=True, text=True)
    dur = float(p_res.stdout.strip() or "0")
    size_kb = round(final_mp3.stat().st_size / 1024, 1)

    print(f"SUCCESS: {final_mp3.name} created! Duration: {dur:.1f}s, Size: {size_kb} KB in {time.time() - t0:.1f}s")
    return True


def main():
    parser = argparse.ArgumentParser(description="Render crafted template showcases")
    parser.add_argument("--template", choices=[s["id"] for s in SHOWCASES], help="Render a specific template")
    parser.add_argument("--force", action="store_true", help="Force re-synthesis even if raw WAV exists")
    args = parser.parse_args()

    to_render = [s for s in SHOWCASES if args.template is None or s["id"] == args.template]

    print(f"Rendering {len(to_render)} handcrafted template showcases (force={args.force})...")
    results = {}
    for item in to_render:
        ok = render_showcase(item, force=args.force)
        results[item["id"]] = ok

    print("\n=======================================================")
    print("Summary of Template Showcases:")
    print("=======================================================")
    all_ok = True
    for item in to_render:
        status = "OK" if results.get(item["id"]) else "FAILED"
        if not results.get(item["id"]):
            all_ok = False
        mp3 = TARGET_DIR / f"{item['id']}.mp3"
        dur_str = "N/A"
        if mp3.exists():
            probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(mp3)]
            p_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            dur_str = f"{float(p_res.stdout.strip() or 0):.1f}s"
        print(f"  {item['id']:<20} [{item['engine']:<9}] {status:<6} -> {dur_str}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
