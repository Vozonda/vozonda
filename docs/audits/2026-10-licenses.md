# Vozonda License Audit: Dependencies, TTS Models, and Bundled Assets

Date: 2026-10-01
Scope: Repository license compliance audit for MIT open-source launch on GitHub
Target License: MIT License (https://opensource.org/license/mit)

---

## 1. Executive Summary and Verdict

Vozonda is architected as an audio-overview application that orchestrates multi-voice dialogues from text, URLs, and RSS feeds. The application code is licensed under the MIT License.

This audit evaluates every direct dependency, every supported TTS/ASR provider model and service, and all bundled assets to determine readiness for an MIT launch on GitHub.

### Short Verdict
Vozonda is structurally ready for an MIT launch, with three specific blockers that must be resolved:
1. **GPL-3.0 Dependency Flag**: The Python package `piper-tts>=1.2.0` in `apps/api/pyproject.toml` is licensed under GPL-3.0-or-later. To preserve vozonda's pure MIT status, `piper-tts` must remain strictly isolated behind the existing CLI subprocess seam (`render_piper.py`), must not be imported in-process, and should be isolated into a standalone optional plugin rather than bundled in the primary `tts` extra.
2. **Non-Commercial Voice Model in Piper**: The curated voice table in `render_piper.py` includes `lessac` (`en_US-lessac-medium`), which was trained on the Lessac Blizzard 2013 dataset carrying an explicit non-commercial restriction. It must be flagged or replaced with a permissive alternative before a commercial-ready release.
3. **Third-Party Notices**: A formal `THIRD_PARTY_NOTICES.md` document must accompany the repository to satisfy attribution obligations for Apache-2.0, BSD, MIT, ISC, and OFL-1.1 components.

---

## 2. Direct Dependencies Audit

The tables below list every direct dependency specified in `apps/api/pyproject.toml` and `apps/web/package.json`. Each entry includes its declared license, compatibility with an MIT-licensed distribution, primary source URL verified on 2026-10-01, and compliance flags.

### 2.1 Backend Dependencies (`apps/api/pyproject.toml`)

| Package | Version Spec | License | MIT Compatible | Flag | Primary Source URL |
|---|---|---|---|---|---|
| `fastapi` | `>=0.115` | MIT | Yes | None | https://pypi.org/project/fastapi/ |
| `uvicorn[standard]` | `>=0.34` | BSD-3-Clause | Yes | None | https://pypi.org/project/uvicorn/ |
| `httpx` | `>=0.28` | BSD-3-Clause | Yes | None | https://pypi.org/project/httpx/ |
| `pydantic` | `>=2.10` | MIT | Yes | None | https://pypi.org/project/pydantic/ |
| `readability-lxml` | `>=0.8.4.1` | Apache-2.0 | Yes | Apache-2.0 (Notice) | https://pypi.org/project/readability-lxml/ |
| `lxml_html_clean` | `>=0.4` | BSD-3-Clause | Yes | None | https://pypi.org/project/lxml-html-clean/ |
| `torch` (optional: tts-qwen) | `>=2.2.0` | Modified BSD | Yes | None | https://pypi.org/project/torch/ |
| `soundfile` (optional: tts-qwen) | `>=0.12.0` | BSD-3-Clause | Yes | None | https://pypi.org/project/soundfile/ |
| `numpy` (optional: tts-qwen) | `>=1.26.0` | BSD-3-Clause | Yes | None | https://pypi.org/project/numpy/ |
| `qwen-tts` (optional: tts-qwen) | `>=0.1.0` | Apache-2.0 | Yes | Apache-2.0 (Notice) | https://pypi.org/project/qwen-tts/ |
| `piper-tts` (optional: tts-piper) | `>=1.2.0` | GPL-3.0-or-later | Conditional | **GPL-3.0-or-later** | https://pypi.org/project/piper-tts/ |
| `mcp` (optional: mcp) | `>=1.9` | MIT | Yes | None | https://pypi.org/project/mcp/ |
| `hatchling` (build-system) | build requirement | MIT | Yes | Build tool | https://pypi.org/project/hatchling/ |
| `mypy` (dev) | `>=2.3.1` | MIT | Yes | Dev only | https://pypi.org/project/mypy/ |
| `pytest` (dev) | `>=9.1.1` | MIT | Yes | Dev only | https://pypi.org/project/pytest/ |
| `pytest-asyncio` (dev) | `>=0.24.0` | Apache-2.0 | Yes | Dev only | https://pypi.org/project/pytest-asyncio/ |
| `pytest-xdist` (dev) | `>=3.5.0` | MIT | Yes | Dev only | https://pypi.org/project/pytest-xdist/ |
| `ruff` (dev) | `>=0.16.4` | MIT / Apache-2.0 | Yes | Dev only | https://pypi.org/project/ruff/ |

### 2.2 Frontend Dependencies (`apps/web/package.json`)

| Package | Version Spec | License | MIT Compatible | Flag | Primary Source URL |
|---|---|---|---|---|---|
| `@fontsource-variable/jetbrains-mono` | `^5.3.0` | OFL-1.1 | Yes | OFL-1.1 (Notice) | https://www.npmjs.com/package/@fontsource-variable/jetbrains-mono |
| `@fontsource-variable/source-serif-4` | `^5.3.0` | OFL-1.1 | Yes | OFL-1.1 (Notice) | https://www.npmjs.com/package/@fontsource-variable/source-serif-4 |
| `axe-core` | `^4.13.0` | MPL-2.0 | Yes | MPL-2.0 (Weak copyleft) | https://www.npmjs.com/package/axe-core |
| `playwright` | `^1.62.1` | Apache-2.0 | Yes | Test dependency | https://www.npmjs.com/package/playwright |
| `@sveltejs/vite-plugin-svelte` (dev) | `^5.0.3` | MIT | Yes | Dev only | https://www.npmjs.com/package/@sveltejs/vite-plugin-svelte |
| `@tsconfig/svelte` (dev) | `^5.0.4` | MIT | Yes | Dev only | https://www.npmjs.com/package/@tsconfig/svelte |
| `svelte` (dev) | `^5.19.0` | MIT | Yes | Dev only | https://www.npmjs.com/package/svelte |
| `svelte-check` (dev) | `^4.1.4` | MIT | Yes | Dev only | https://www.npmjs.com/package/svelte-check |
| `typescript` (dev) | `^5.7.3` | Apache-2.0 | Yes | Dev only | https://www.npmjs.com/package/typescript |
| `vite` (dev) | `^6.0.11` | MIT | Yes | Dev only | https://www.npmjs.com/package/vite |

---

## 3. Analysis of Flagged Dependencies

### 3.1 `piper-tts` (GPL-3.0-or-later)
- **Fact**: `piper-tts` on PyPI (current release 1.8.0, homepage http://github.com/OHF-voice/piper1-gpl) is explicitly licensed under `GPL-3.0-or-later`.
- **Assessment**: The GNU General Public License version 3 (GPL-3.0) contains strong copyleft provisions. If a project links or imports GPL-3.0 code directly in-process, the entire combined work must be licensed under GPL-3.0. In vozonda, `render_piper.py` executes as an independent Python script in a separate subprocess via `subprocess.run`. The main `vozonda_api` service communicates with it strictly through command-line arguments and JSON files. This loose coupling at arm's length prevents license infection of the parent API under standard copyright doctrine.
- **Action Required**: 
  1. Do not import `piper` or `piper_tts` inside any module in `src/vozonda_api/`.
  2. In `pyproject.toml`, decouple `piper-tts` from the combined `tts = ["vozonda-api[tts-qwen]", "vozonda-api[tts-piper]"]` extra so that a standard developer installation does not inadvertently pull in GPL-3.0 packages.
  3. Clearly document in `THIRD_PARTY_NOTICES.md` that Piper is an optional, external subprocess integration.

### 3.2 `axe-core` (MPL-2.0)
- **Fact**: `axe-core` is licensed under Mozilla Public License 2.0 (MPL-2.0).
- **Assessment**: MPL-2.0 is a file-level weak copyleft license. It requires that modifications to `axe-core` source files remain under MPL-2.0, but allows bundling with proprietary or MIT-licensed software in a larger work without relicensing the larger work. Furthermore, `axe-core` is only used by the testing harness (`apps/web/scripts/audit.cjs`) and is not executed in client production builds.
- **Action Required**: Move `axe-core` and `playwright` from `"dependencies"` to `"devDependencies"` in `apps/web/package.json` to prevent automated SBOM scanners from flagging runtime copyleft concerns.

### 3.3 Apache-2.0 Dependencies (`qwen-tts`, `readability-lxml`, `playwright`, `typescript`, `pytest-asyncio`)
- **Fact**: These packages are licensed under Apache License 2.0.
- **Assessment**: Apache-2.0 is fully compatible with distributing a downstream project under MIT. The only condition is preserving the copyright notices, license text, and any upstream `NOTICE` files in `THIRD_PARTY_NOTICES.md`.

---

## 4. TTS and ASR Models, Services, and Weight Licenses

Vozonda integrates 12 distinct TTS and ASR models/services across its provider seams. Below is the verified audit for each system, covering both code and model weights.

### 4.1 Chatterbox (Resemble AI)
- **Code License**: MIT (https://github.com/resemble-ai/chatterbox)
- **Weights License**: MIT (https://huggingface.co/ResembleAI/Chatterbox)
- **Commercial Use**: Allowed. Resemble AI explicitly permits commercial usage, fine-tuning, and self-hosting.
- **Attribution Required**: Yes, standard MIT license text and copyright notice.
- **Usage Restrictions**: Generated audio embeds Resemble AI's PerTh (Perceptual Threshold) neural watermark for synthetic speech provenance and attribution. Tampering with the watermark violates intended use terms.

### 4.2 Dia (Nari Labs 1.6B)
- **Code License**: Apache-2.0 (https://github.com/nari-labs/dia)
- **Weights License**: Apache-2.0 (https://huggingface.co/nari-labs/Dia-1.6B-0626)
- **Commercial Use**: Allowed under Apache-2.0.
- **Attribution Required**: Yes, Apache-2.0 notices must be retained.
- **Usage Restrictions**: Designed for two-speaker dialogue synthesis using `[S1]` and `[S2]` tokens with nonverbal acoustic cues. English only.

### 4.3 Dia2 (Nari Labs 2B)
- **Code License**: Apache-2.0 (https://github.com/nari-labs/dia2)
- **Weights License**: Apache-2.0 (https://huggingface.co/nari-labs/Dia2-2B)
- **Commercial Use**: Allowed under Apache-2.0.
- **Attribution Required**: Yes, Apache-2.0 notices must be retained.
- **Usage Restrictions**: English only. Optimized for low-latency streaming and dialogue stability via reference prefix conditioning.

### 4.4 Higgs Audio v2 / Higgs TTS 2 (Boson AI)
- **Code License**: Apache-2.0 in `boson-ai/higgs-audio` repository (https://github.com/boson-ai/higgs-audio).
- **Weights License**: Boson Community License / Boson Research License (https://huggingface.co/bosonai/higgs-audio-v2-generation-3B-base and https://huggingface.co/bosonai/higgs-tts-2-3b-base).
- **Commercial Use**: **Not Allowed** without an explicit commercial license agreement from Boson AI. Free use is restricted to non-commercial research and personal evaluation. A Creator Use Grant permits individual creator content with attribution, but commercial SaaS hosting or enterprise embedding is prohibited.
- **Attribution Required**: Yes, mandatory credit to Boson AI.
- **Usage Restrictions**: Reference voice cloning up to 4 speakers. Non-commercial research only. Vozonda correctly sets `commercial_use=False` in `providers/higgs.py`.

### 4.5 Kokoro-82M (hexgrad)
- **Code License**: Apache-2.0 (https://github.com/hexgrad/kokoro)
- **Weights License**: Apache-2.0 (https://huggingface.co/hexgrad/Kokoro-82M)
- **Commercial Use**: Allowed under Apache-2.0.
- **Attribution Required**: Yes, Apache-2.0 copyright notice.
- **Usage Restrictions**: Compact 82M parameter model. Uses 11 curated English voices (American and British blends). No proprietary voice-cloning restrictions.

### 4.6 Piper Voices (Rhasspy / Open Home Foundation)
- **Code License**: GPL-3.0-or-later for active engine `OHF-voice/piper1-gpl` (https://github.com/OHF-voice/piper1-gpl); legacy archive was MIT (https://github.com/rhasspy/piper).
- **Weights License**: Heterogeneous per-voice dataset licenses (https://huggingface.co/rhasspy/piper-voices).
  - `de_DE-thorsten`: CC0-1.0 (Public Domain Dedication, commercial use allowed).
  - `en_US-amy`: Permissive open dataset.
  - `en_US-lessac`: Trained on Lessac Blizzard 2013 corpus, which carries an **explicit non-commercial restriction**.
  - Other voices in catalog: Mix of CC-BY-4.0, CC-BY-SA, and CC-BY-NC.
- **Commercial Use**: **Mixed / Voice-Dependent**. Permissive voices (Thorsten, Amy) allow commercial use. Lessac prohibits commercial use.
- **Attribution Required**: Yes, required for all CC-BY based voice models.
- **Usage Restrictions**: Single-speaker ONNX checkpoints. Downstream users must verify individual `MODEL_CARD` files before commercial deployment.

### 4.7 Qwen3-TTS (Alibaba Cloud Qwen Team)
- **Code License**: Apache-2.0 (https://github.com/QwenLM/Qwen3-TTS)
- **Weights License**: Apache-2.0 (https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- **Commercial Use**: Allowed. Both code and model weights are published under Apache-2.0.
- **Attribution Required**: Yes, Apache-2.0 notice.
- **Usage Restrictions**: Covers 10 languages (Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian). 9 built-in timbres. Natural-language instruction control.

### 4.8 VibeVoice-1.5B (Microsoft)
- **Code License**: MIT (https://github.com/microsoft/VibeVoice)
- **Weights License**: MIT (https://huggingface.co/microsoft/VibeVoice-1.5B or `vibevoice/VibeVoice-1.5B-hf`)
- **Commercial Use**: Allowed under MIT License.
- **Attribution Required**: Yes, MIT notice.
- **Usage Restrictions**: Supports multi-speaker long-form audio generation (up to 4 voices) using reference WAV audio prompts on speaker turns.

### 4.9 NVIDIA NeMo TTS (FastPitch + HiFiGAN)
- **Code License**: Apache-2.0 (https://github.com/NVIDIA/NeMo)
- **Weights License**: CC-BY-4.0 on Hugging Face (https://huggingface.co/nvidia/tts_en_fastpitch, https://huggingface.co/nvidia/tts_en_hifigan); NVIDIA NGC Terms of Use on NGC Catalog.
- **Commercial Use**: Allowed under CC-BY-4.0 and Apache-2.0.
- **Attribution Required**: Yes, CC-BY-4.0 attribution to NVIDIA and Apache-2.0 notices.
- **Usage Restrictions**: Standard acoustic spectrogram generator and neural vocoder. Single-speaker English.

### 4.10 NVIDIA Magpie TTS Multilingual (357M / NVIDIA NIM)
- **Code License**: Apache-2.0 for NeMo client libraries (https://github.com/NVIDIA/NeMo).
- **Weights License**: NVIDIA Open Model License (https://huggingface.co/nvidia/magpie_tts_multilingual_357m).
- **Hosted API Terms**: NVIDIA Developer Trial Terms of Service (`grpc.nvcf.nvidia.com`).
- **Commercial Use**: 
  - Open Weights: Allowed under NVIDIA Open Model License with mandatory attribution.
  - Hosted NIM Trial API: **Not Allowed**. Free developer trial keys are restricted to evaluation, prototyping, and testing only.
- **Attribution Required**: Yes. When distributing models or derivatives, a notice stating "Licensed by NVIDIA Corporation under the NVIDIA Open Model License" is required.
- **Usage Restrictions**: 12 languages. Hosted NIM access is non-commercial in vozonda; `providers/magpie.py` enforces `commercial_use=False`.

### 4.11 Voxtral (Mistral AI)
- **Client SDK License**: Apache-2.0 (https://github.com/mistralai/client-python).
- **Weights License**: **CC BY-NC 4.0** for open weights (https://huggingface.co/mistralai).
- **Hosted API Terms**: Mistral Commercial Terms of Service (https://mistral.ai/terms/).
- **Commercial Use**:
  - Open Weights: **Not Allowed** (strictly non-commercial under CC BY-NC 4.0).
  - Hosted API (`https://api.mistral.ai/v1/audio/speech`): Allowed for paid API customers according to Mistral API terms.
- **Attribution Required**: Yes, attribution to Mistral AI.
- **Usage Restrictions**: Multimodal voice foundation model with European multilingual accents and paralinguistic tag execution (`[laughs]`, `[sighs]`).

### 4.12 Whisper (OpenAI)
- **Code License**: MIT (https://github.com/openai/whisper)
- **Weights License**: MIT (https://github.com/openai/whisper/blob/main/LICENSE, https://huggingface.co/openai/whisper-large-v3)
- **Commercial Use**: Allowed under MIT License.
- **Attribution Required**: Yes, MIT notice.
- **Usage Restrictions**: Speech-to-text (ASR) foundation model. No synthesis or voice cloning restrictions.

---

### 4.13 TTS / ASR Provider Summary Matrix

| Engine | Code License | Weights License | Commercial Use Allowed | Attribution Required | Usage / Voice Cloning Restrictions |
|---|---|---|---|---|---|
| **Chatterbox** | MIT | MIT | Yes | MIT Notice | Embedded PerTh neural watermark for provenance |
| **Dia** | Apache-2.0 | Apache-2.0 | Yes | Apache Notice | English only; dialogue tags `[S1]`, `[S2]` |
| **Dia2** | Apache-2.0 | Apache-2.0 | Yes | Apache Notice | English only; 2-speaker streaming dialogue |
| **Higgs Audio v2** | Apache-2.0 | Boson Non-Commercial | **No** (Research Only) | Yes (Boson AI) | Non-commercial research only; 4 speakers max |
| **Kokoro-82M** | Apache-2.0 | Apache-2.0 | Yes | Apache Notice | 82M style diffusion; preset English voice blends |
| **Piper Voices** | GPL-3.0-or-later | Varies (CC0 / CC-BY / CC-NC) | **Varies** | Yes (Model card) | Single speaker; `lessac` voice is non-commercial |
| **Qwen3-TTS** | Apache-2.0 | Apache-2.0 | Yes | Apache Notice | 10 languages; 9 curated voices; natural instruct |
| **VibeVoice** | MIT | MIT | Yes | MIT Notice | Multi-speaker dialogue via reference WAV prompts |
| **NeMo (FastPitch)** | Apache-2.0 | CC-BY-4.0 | Yes | CC-BY Notice | Single speaker English synthesis |
| **Magpie** | Apache-2.0 | NVIDIA Open Model | Weights: Yes / API: **No** | NVIDIA Notice | Hosted NIM trial is testing/prototyping only |
| **Voxtral** | Apache-2.0 | CC BY-NC 4.0 | Weights: **No** / API: Yes | Yes (Mistral) | Open weights are non-commercial; API is paid |
| **Whisper** | MIT | MIT | Yes | MIT Notice | ASR transcription only; no voice cloning |

---

## 5. Bundled Assets Audit

### 5.1 Typography and Fonts
1. **JetBrains Mono Variable (`JetBrains Mono Variable`)**:
   - Location: `apps/web/node_modules/@fontsource-variable/jetbrains-mono`
   - Origin: Designed by Philipp Nurullin and Konstantin Bulenkov at JetBrains.
   - License: SIL Open Font License 1.1 (OFL-1.1).
   - Commercial Use: Allowed. Bundling font files with software is explicitly permitted under OFL Clause 2, provided font files are not sold standalone and copyright notices are preserved.
2. **Source Serif 4 Variable (`Source Serif 4 Variable`)**:
   - Location: `apps/web/node_modules/@fontsource-variable/source-serif-4`
   - Origin: Designed by Frank Grießhammer at Adobe Systems Incorporated.
   - License: SIL Open Font License 1.1 (OFL-1.1).
   - Commercial Use: Allowed under OFL-1.1.

### 5.2 Icons and Graphic Design
1. **Inline SVG Icon System**:
   - Location: `apps/web/src/lib/components/Icon.svelte`
   - Origin: SVG stroke path data derived from the Lucide Icon project (https://lucide.dev), originally based on Feather Icons by Cole Bemis.
   - License: ISC License (https://github.com/lucide-icons/lucide/blob/main/LICENSE).
   - Commercial Use: Allowed. The ISC license is fully permissive and compatible with MIT.
2. **Favicon (`favicon.svg`)**:
   - Location: `apps/web/public/favicon.svg`
   - Origin: Original vector artwork created specifically for Vozonda (green rounded rectangular emblem with letter 'H').
   - License: MIT (Project license).
3. **App Icons (`icon-192.png`, `icon-512.png`)**:
   - Location: `apps/web/public/icon-192.png`, `apps/web/public/icon-512.png`
   - Origin: Rasterized renderings of Vozonda's original favicon vector graphic.
   - License: MIT (Project license).

### 5.3 Static Images
1. **Social Preview Image (`og-default.png`)**:
   - Location: `apps/web/public/og-default.png`
   - Origin: Clean editorial screenshot/mockup of Vozonda's Calm Grid interface, generated using Vozonda's typography and color tokens.
   - License: MIT (Project license).

### 5.4 Audio Assets and Music Beds
1. **Procedural Jingle Generators**:
   - Location: `apps/api/src/vozonda_api/music.py` (`generate_jingle()`, `mix_music_beds()`)
   - Origin: Original mathematical harmonic synthesis implemented in pure Python/NumPy (sine waveforms with musical overtones, raised-cosine ducking envelopes, and analog tanh saturation).
   - License: MIT (Project license).
2. **Package Music Assets (`assets/music/`)**:
   - Location: Checked against `apps/api/src/vozonda_api/assets/music/`.
   - Origin / Status: No static audio files are bundled inside the python package directory. Custom stems are imported dynamically at runtime by the user via SSRF-guarded URL import (`music_store.py`) into user data storage.
3. **Template Audio Showcases**:
   - Location: `apps/web/public/media/samples/templates/*.mp3` (9 files: `morning_dispatch.mp3`, `feature_story.mp3`, `trio_roundtable.mp3`, `tech_roast.mp3`, `true_crime_dossier.mp3`, `explainer_lab.mp3`, `socratic_dialogue.mp3`, `solo_audio_essay.mp3`, `zen_meditation.mp3`).
   - Origin: Synthesized audio clips generated via `scripts/render_crafted_template_showcases.py` using local and cloud TTS backends:
     - `feature_story.mp3` & `explainer_lab.mp3`: Qwen3-TTS (Apache-2.0).
     - `trio_roundtable.mp3` & `tech_roast.mp3`: Kokoro-82M (Apache-2.0).
     - `solo_audio_essay.mp3` & `zen_meditation.mp3`: Piper (`en_US-amy-medium`).
     - `morning_dispatch.mp3`, `true_crime_dossier.mp3`, `socratic_dialogue.mp3`: Voxtral (Mistral API).
   - Assessment: The text scripts and synthesis pipelines are original project work. Output generated from Mistral's hosted API is permitted under paid customer terms, but redistributing proprietary voice audio in a public GitHub repository can create copyright ambiguity.
   - Recommendation: Re-render the three Voxtral showcase samples with local Apache-2.0 engines (Qwen3-TTS or Kokoro) prior to public GitHub release to make all bundled audio 100% libre.

---

## 6. Actionable Blockers for an MIT GitHub Launch

Before publishing the repository publicly under the MIT license on GitHub, the following items must be resolved:

1. **Decouple `piper-tts` from Default Extras in `pyproject.toml`**:
   - *Problem*: `piper-tts` is licensed under GPL-3.0-or-later. Including it in the unified `tts` optional extra encourages installations that mix GPL-3.0 and MIT in the same Python environment.
   - *Fix*: Keep `piper-tts` isolated in `[project.optional-dependencies] tts-piper = ["piper-tts>=1.2.0"]` and do not include it in `tts = ["vozonda-api[tts-qwen]"]`. Maintain clear subprocess separation via `render_piper.py`.
2. **Audit Piper Voice Curated Selection in `render_piper.py`**:
   - *Problem*: `render_piper.py` includes `lessac` (`en_US-lessac-medium`), which is restricted to non-commercial research by the Blizzard 2013 Lessac corpus license.
   - *Fix*: Remove `lessac` from default commercial offerings or explicitly gate it behind non-commercial warnings, replacing the default English voice selection with permissive alternatives (`alan`, `amy`, `ryan`).
3. **Move Dev Tools out of Web Runtime Dependencies in `package.json`**:
   - *Problem*: `axe-core` (MPL-2.0) and `playwright` (Apache-2.0) are listed in `"dependencies"` in `apps/web/package.json`.
   - *Fix*: Move both to `"devDependencies"`. They are only used by `audit.cjs` and browser testing.
4. **Publish `THIRD_PARTY_NOTICES.md` at Repository Root**:
   - *Problem*: An MIT project incorporating or interfacing with Apache-2.0, BSD-3-Clause, ISC, and OFL-1.1 components must provide license and copyright attributions.
   - *Fix*: Create and maintain `THIRD_PARTY_NOTICES.md` at the repo root.
5. **Re-render Voxtral Template Teasers with Open Local Models**:
   - *Problem*: `morning_dispatch.mp3`, `true_crime_dossier.mp3`, and `socratic_dialogue.mp3` contain voice audio from Mistral's hosted Voxtral service.
   - *Fix*: Re-render all template audio teasers with Apache-2.0 engines (Qwen3-TTS and Kokoro-82M) so that every audio asset in `apps/web/public/` is completely libre.

---

## 7. Audit Conclusion

Vozonda's core orchestrator, Calm Grid web application, and custom pipeline mastering are 100% original work cleanly released under the MIT license. By resolving the five blockers listed above, the repository will achieve complete licensing integrity and can be released on GitHub without risk of copyleft contamination or upstream license violations.
