# Third-Party Software and Asset Notices

Vozonda is licensed under the MIT License (see [LICENSE](LICENSE)).

This document contains third-party software, asset, and model notices and license attributions for components integrated, bundled, or interfaced by Vozonda.

For the comprehensive licensing audit and compliance assessment, see [docs/audits/2026-10-licenses.md](docs/audits/2026-10-licenses.md).

---

## 1. Table of Contents

1. [Overview and Launch Notice](#overview-and-launch-notice)
2. [Bundled Typography and Fonts](#bundled-typography-and-fonts)
3. [Bundled Icons and Visual Assets](#bundled-icons-and-visual-assets)
4. [AI Model and Voice Engine Attributions](#ai-model-and-voice-engine-attributions)
5. [External Subprocess Engines (Kokoro ONNX and Piper TTS)](#external-subprocess-engines-kokoro-onnx-and-piper-tts)
6. [Core Direct Dependencies](#core-direct-dependencies)
7. [License Texts](#license-texts)

---

## 2. Overview and Launch Notice

Vozonda combines original application code with open-source software libraries, open-weights machine learning models, and permissive fonts/assets.

### Key Compliance Rules for Downstream Users
- **Permissive Core**: The core Vozonda application (backend API and Calm Grid frontend) is released under the MIT License.
- **Arm's-Length Seams**: Providers that run external binaries or scripts (such as Piper TTS) operate across an arm's-length subprocess boundary and are not linked into the core Python process.
- **Model Weight Terms**: Different TTS engines have different model weight licenses. While Qwen3-TTS, Kokoro-82M, Chatterbox, and Dia/Dia2 are permissible for commercial deployment, others such as Higgs Audio v2 and Voxtral open weights are restricted to non-commercial research. Users should consult the model notices below before commercial hosting.

---

## 3. Bundled Typography and Fonts

### JetBrains Mono Variable
- **Files**: Embedded via `@fontsource-variable/jetbrains-mono`
- **Copyright**: Copyright (c) 2020 JetBrains s.r.o.
- **License**: SIL Open Font License 1.1 (OFL-1.1)
- **Source**: https://github.com/JetBrains/JetBrainsMono
- **Notice**: JetBrains Mono is a trademark of JetBrains s.r.o.

### Source Serif 4 Variable
- **Files**: Embedded via `@fontsource-variable/source-serif-4`
- **Copyright**: Copyright (c) 2014, 2021 Adobe Systems Incorporated (https://www.adobe.com/)
- **License**: SIL Open Font License 1.1 (OFL-1.1)
- **Source**: https://github.com/adobe-fonts/source-serif

---

## 4. Bundled Icons and Visual Assets

### Lucide Icons
- **Files**: Vector paths in `apps/web/src/lib/components/Icon.svelte`
- **Copyright**: Copyright (c) Lucide Contributors (https://lucide.dev)
- **Original Work**: Feather Icons, Copyright (c) 2013-2017 Cole Bemis
- **License**: ISC License
- **Source**: https://github.com/lucide-icons/lucide

---

## 5. AI Model and Voice Engine Attributions

Vozonda interfaces with several speech synthesis and transcription models. The models and weights carry the following acknowledgments:

### Qwen3-TTS
- **Provider**: Alibaba Cloud Qwen Team
- **Code & Weights License**: Apache License 2.0
- **Repositories**:
  - Code: https://github.com/QwenLM/Qwen3-TTS
  - Weights: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice

### Kokoro-82M
- **Provider**: hexgrad
- **Code & Weights License**: Apache License 2.0
- **Repositories**:
  - Code: https://github.com/hexgrad/kokoro
  - Weights: https://huggingface.co/hexgrad/Kokoro-82M

### Chatterbox
- **Provider**: Resemble AI
- **Code & Weights License**: MIT License
- **Repositories**:
  - Code: https://github.com/resemble-ai/chatterbox
  - Weights: https://huggingface.co/ResembleAI/Chatterbox
- **Notice**: Resemble AI Chatterbox incorporates PerTh neural watermarking in generated audio to ensure synthetic speech provenance.

### Dia and Dia2
- **Provider**: Nari Labs
- **Code & Weights License**: Apache License 2.0
- **Repositories**:
  - Dia Code: https://github.com/nari-labs/dia
  - Dia Weights: https://huggingface.co/nari-labs/Dia-1.6B-0626
  - Dia2 Code: https://github.com/nari-labs/dia2
  - Dia2 Weights: https://huggingface.co/nari-labs/Dia2-2B

### VibeVoice-1.5B
- **Provider**: Microsoft Corporation
- **Code & Weights License**: MIT License
- **Repositories**:
  - Code: https://github.com/microsoft/VibeVoice
  - Weights: https://huggingface.co/microsoft/VibeVoice-1.5B

### NVIDIA NeMo (FastPitch + HiFi-GAN)
- **Provider**: NVIDIA Corporation
- **Code License**: Apache License 2.0
- **Weights License**: Creative Commons Attribution 4.0 International (CC-BY-4.0)
- **Repositories**:
  - Code: https://github.com/NVIDIA/NeMo
  - Weights: https://huggingface.co/nvidia/tts_en_fastpitch, https://huggingface.co/nvidia/tts_en_hifigan
- **Notice**: Portions of NeMo TTS models are licensed by NVIDIA Corporation under CC-BY-4.0.

### NVIDIA Magpie TTS Multilingual
- **Provider**: NVIDIA Corporation
- **Code License**: Apache License 2.0
- **Weights License**: NVIDIA Open Model License
- **Repositories**:
  - Weights: https://huggingface.co/nvidia/magpie_tts_multilingual_357m
- **Notice**: Magpie open weights are licensed by NVIDIA Corporation under the NVIDIA Open Model License. The hosted NVIDIA NIM preview API is limited to development, testing, and evaluation.

### OpenAI Whisper
- **Provider**: OpenAI
- **Code & Weights License**: MIT License
- **Repositories**:
  - Code: https://github.com/openai/whisper
  - Weights: https://huggingface.co/openai/whisper-large-v3

### Higgs Audio v2 (Boson AI)
- **Provider**: Boson AI
- **Code License**: Apache License 2.0
- **Weights License**: Boson Research License (Non-Commercial)
- **Notice**: Higgs Audio v2 weights are restricted to non-commercial research, education, and personal evaluation.

### Voxtral (Mistral AI)
- **Provider**: Mistral AI
- **Client SDK License**: Apache License 2.0
- **Weights License**: Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)
- **Notice**: Open weights for Voxtral are non-commercial. Commercial use requires accessing Mistral AI's paid cloud API endpoints.

---

## 6. External Subprocess Engines (Kokoro ONNX and Piper TTS)

Vozonda provides optional external integrations for Kokoro-82M (`render_kokoro.py`)
and Piper TTS (`render_piper.py`). The vozonda code itself stays MIT-licensed;
the GPL components below are separate packages installed alongside it, never
linked into the core API process.

- **Engine Package**: `kokoro-onnx` (https://github.com/thewh1teagle/kokoro-onnx)
- **License**: Apache License 2.0 (code and Kokoro-82M weights)
- **Notice**: `kokoro-onnx` pulls in `phonemizer` (GNU General Public License
  version 3 or later, GPL-3.0-or-later) and `espeakng-loader` (which bundles
  `espeak-ng`, GPL-3.0-or-later) for grapheme-to-phoneme conversion. These run
  in the renderer subprocess, at arm's length from the MIT-licensed vozonda code.
- **Engine Package**: `piper-tts` (https://github.com/OHF-voice/piper1-gpl)
- **License**: GNU General Public License version 3 or later (GPL-3.0-or-later)
- **Dependency**: `piper-tts` uses `espeak-ng` (GPL-3.0-or-later) for phonemization.
- **Architecture Notice**: Kokoro and Piper are not linked into the Vozonda API server process. They are executed as external stand-alone scripts via command-line arguments and standard input/output streams. The Vozonda API code and the renderer scripts communicate at arm's length. Users who build combined distribution images or binary installers containing these packages must adhere to the distribution terms of GPL-3.0 for those packages.
- **Voice Weights Notice**: Voices downloaded by Piper come from heterogeneous sources. For example, `de_DE-thorsten` is CC0-1.0, while `en_US-lessac-medium` is derived from the Blizzard 2013 dataset with explicit non-commercial restrictions. Consult individual voice card metadata before commercial deployment.

---

## 7. Core Direct Dependencies

The following list acknowledges direct dependencies utilized across the backend and web frontend services:

### Backend Libraries (`apps/api/pyproject.toml`)
- **FastAPI**: MIT License, Copyright (c) 2018 Sebastian Ramirez
- **Uvicorn**: BSD-3-Clause License, Copyright (c) 2017-present, Encode OSS Ltd
- **HTTPX**: BSD-3-Clause License, Copyright (c) 2019-present, Encode OSS Ltd
- **Pydantic**: MIT License, Copyright (c) 2017-2024 Samuel Colvin and Pydantic Services Inc
- **readability-lxml**: Apache License 2.0, Copyright (c) The Readability Authors / Yuri Baburov
- **lxml-html-clean**: BSD-3-Clause License, Copyright (c) The lxml-html-clean Developers
- **PyTorch**: Modified BSD License, Copyright (c) 2016-present Facebook, Inc / PyTorch Contributors
- **SoundFile**: BSD-3-Clause License, Copyright (c) 2013-2024 Bastian Bechtold
- **NumPy**: BSD-3-Clause License, Copyright (c) 2005-2024 NumPy Developers
- **Qwen-TTS**: Apache License 2.0, Copyright (c) Alibaba Group
- **kokoro-onnx**: Apache License 2.0 (ships Kokoro-82M weights under Apache-2.0)
- **phonemizer**: GNU General Public License version 3 or later (GPL-3.0-or-later, kokoro-onnx dependency)
- **espeak-ng (via espeakng-loader)**: GNU General Public License version 3 or later (GPL-3.0-or-later, used by kokoro-onnx and piper-tts)
- **piper-tts**: GNU General Public License version 3 or later (GPL-3.0-or-later)
- **coincurve**: MIT OR Apache-2.0, Copyright (c) Ofek Lev; bundles libsecp256k1 (MIT, Copyright (c) Pieter Wuille and the Bitcoin Core developers). Signs the per-show Nostr podcast events (BIP-340)
- **Model Context Protocol (mcp)**: MIT License, Copyright (c) 2024 Anthropic PBC

### Frontend Libraries (`apps/web/package.json`)
- **Svelte**: MIT License, Copyright (c) 2016-2025 Svelte Contributors
- **Vite**: MIT License, Copyright (c) 2019-present Evan You & Vite Contributors
- **axe-core**: Mozilla Public License 2.0 (MPL-2.0), Copyright (c) 2015-present Deque Systems, Inc. (used for accessibility audit testing)
- **Playwright**: Apache License 2.0, Copyright (c) Microsoft Corporation (used for end-to-end testing)
- **TypeScript**: Apache License 2.0, Copyright (c) Microsoft Corporation

---

## 8. License Texts

### MIT License

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### ISC License

```
Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

### BSD 3-Clause License

```
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE OTHERWISE) ARISING IN ANY WAY OUT
OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### SIL Open Font License 1.1 (OFL-1.1)

```
PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded, 
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless prominent written permission is granted by the
corresponding Copyright Holder. This restriction only applies to the
primary font name as presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

### Apache License Version 2.0 (Summary Notice)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at:

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
