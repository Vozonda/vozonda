"""Per-engine speaker tables, kept as plain data on purpose.

The api process must be able to list the choices without importing torch
or any tts stack; each renderer adapter validates against its table here.
A new engine adds one entry to SPEAKER_TABLES and stays fully decoupled.
"""

from pathlib import Path

from .env import env

QWEN_SPEAKERS = [
    {"id": "aiden", "label": "Aiden (m)", "native": "English"},
    {"id": "ryan", "label": "Ryan (m)", "native": "English"},
    {"id": "sohee", "label": "Sohee (f)", "native": "Korean"},
    {"id": "serena", "label": "Serena (f)", "native": "Chinese"},
    {"id": "vivian", "label": "Vivian (f)", "native": "Chinese"},
    {"id": "ono_anna", "label": "Ono Anna (f)", "native": "Japanese"},
    {"id": "dylan", "label": "Dylan (m)", "native": "Chinese"},
    {"id": "eric", "label": "Eric (m)", "native": "Chinese"},
    {"id": "uncle_fu", "label": "Uncle Fu (m)", "native": "Chinese"},
]

VOXTRAL_SPEAKERS = [
    {"id": "leopold", "label": "Leopold (m)", "native": "German"},
    {"id": "hannah", "label": "Hannah (f)", "native": "German"},
    {"id": "ludwig", "label": "Ludwig (m)", "native": "German"},
    {"id": "florian", "label": "Florian (m)", "native": "German"},
    {"id": "charlotte", "label": "Charlotte (f)", "native": "French"},
    {"id": "gabriel", "label": "Gabriel (m)", "native": "French"},
    {"id": "aurelie", "label": "Aurélie (f)", "native": "French"},
    {"id": "mathis", "label": "Mathis (m)", "native": "French"},
    {"id": "celeste", "label": "Céleste (f)", "native": "French"},
    {"id": "mateo", "label": "Mateo (m)", "native": "Spanish"},
    {"id": "lucia", "label": "Lucía (f)", "native": "Spanish"},
    {"id": "alessio", "label": "Alessio (m)", "native": "Italian"},
    {"id": "giulia", "label": "Giulia (f)", "native": "Italian"},
    {"id": "tiago", "label": "Tiago (m)", "native": "Portuguese"},
    {"id": "clara", "label": "Clara (f)", "native": "Portuguese"},
    {"id": "oliver", "label": "Oliver (m)", "native": "English"},
    {"id": "emma", "label": "Emma (f)", "native": "English"},
]

PIPER_SPEAKERS = [
    {"id": "thorsten", "label": "Thorsten (m)", "native": "German"},
    {"id": "kerstin", "label": "Kerstin (f)", "native": "German"},
    {"id": "ramona", "label": "Ramona (f)", "native": "German"},
    {"id": "alan", "label": "Alan (m)", "native": "English (GB)"},
    {"id": "cori", "label": "Cori (f)", "native": "English (GB)"},
    {"id": "ryan", "label": "Ryan (m)", "native": "English (US)"},
    {"id": "amy", "label": "Amy (f)", "native": "English (US)"},
    {"id": "siwis", "label": "Siwis (f)", "native": "French"},
    {"id": "gilles", "label": "Gilles (m)", "native": "French"},
    {"id": "carlfm", "label": "Carlfm (m)", "native": "Spanish"},
    {"id": "davefx", "label": "Davefx (m)", "native": "Spanish"},
    {"id": "riccardo", "label": "Riccardo (m)", "native": "Italian"},
    {"id": "paola", "label": "Paola (f)", "native": "Italian"},
]

KOKORO_SPEAKERS = [
    {"id": "af_bella", "label": "Bella (f)", "native": "English (US)"},
    {"id": "af_sarah", "label": "Sarah (f)", "native": "English (US)"},
    {"id": "af_nicole", "label": "Nicole (f)", "native": "English (US)"},
    {"id": "af_sky", "label": "Sky (f)", "native": "English (US)"},
    {"id": "am_adam", "label": "Adam (m)", "native": "English (US)"},
    {"id": "am_michael", "label": "Michael (m)", "native": "English (US)"},
    {"id": "am_eric", "label": "Eric (m)", "native": "English (US)"},
    {"id": "bf_emma", "label": "Emma (f)", "native": "English (GB)"},
    {"id": "bf_isabella", "label": "Isabella (f)", "native": "English (GB)"},
    {"id": "bm_george", "label": "George (m)", "native": "English (GB)"},
    {"id": "bm_lewis", "label": "Lewis (m)", "native": "English (GB)"},
]

SPEAKER_TABLES = {
    "qwen_tts": QWEN_SPEAKERS,
    "voxtral": VOXTRAL_SPEAKERS,
    "piper": PIPER_SPEAKERS,
    "kokoro": KOKORO_SPEAKERS,
}


def _web_public_dir() -> Path:
    """Return the web public directory where samples are served from."""
    raw = env("WEB_PUBLIC",
        str(Path(__file__).resolve().parents[4] / "apps" / "web" / "public"),
    )
    return Path(raw)


def sample_url(engine_id: str, voice_id: str) -> str | None:
    """Return the URL path to a voice sample MP3, or None if it does not exist.

    The sample path is: /media/samples/voices/<engine>_<voice>.mp3
    relative to the web public dir.
    """
    sample_path = (
        _web_public_dir()
        / "media"
        / "samples"
        / "voices"
        / f"{engine_id}_{voice_id}.mp3"
    )
    if sample_path.exists() and sample_path.stat().st_size > 0:
        return f"/media/samples/voices/{engine_id}_{voice_id}.mp3"
    return None


def _enrich_speaker(speaker: dict, engine_id: str) -> dict:
    """Add sample_url to a speaker entry."""
    out = dict(speaker)
    out["sample_url"] = sample_url(engine_id, speaker["id"])
    return out


def speakers_for(engine_id: str, enrich: bool = False) -> list[dict]:
    """Speaker table of an engine: the curated tables first, then the provider
    module's own SPEAKERS, so a new engine ships its voices with itself.

    If enrich=True the returned dicts carry an extra 'sample_url' key.
    """
    if engine_id in SPEAKER_TABLES:
        base = SPEAKER_TABLES[engine_id]
    else:
        try:
            from .plugins import registry
            from .providers import tts_engines

            # The registry fills on first discovery; before that every plugin
            # engine (dia, dia2, chatterbox, vibevoice) looked voiceless.
            tts_engines()
            base = list(getattr(registry.get(engine_id), "SPEAKERS", []) or [])
        except Exception:
            base = []
    if enrich:
        return [_enrich_speaker(s, engine_id) for s in base]
    return list(base)


def all_speaker_tables() -> dict[str, list[dict]]:
    from .providers import engine_ids
    return {
        eid: speakers_for(eid, enrich=True)
        for eid in sorted(engine_ids() | set(SPEAKER_TABLES))
    }


VALID_TIMBRES = {s["id"] for table in SPEAKER_TABLES.values() for s in table}

# Per-language default timbres for qwen_tts renderer, per role (a, b, c, solo).
# Rating-5 timbres (no accent on German) from voice-accent-probe.md:
#   sohee (KO), ono_anna (JA), dylan (ZH), uncle_fu (ZH)
# German gets the differentiated rating-5 cast (the maintainer's ear review). Other
# languages reuse their best-known voice for every role until a
# per-language probe exists.
# Every language gets distinct A/B/C voices: until 2026-09-23 "en" and most
# others used one voice for every role, so a two-host episode was one voice
# talking to itself. en: Ryan + Serena (the probe found Serena strongly
# American-sounding, a flaw in German and a fit in English) + Aiden.
_MIXED = {"a": "dylan", "b": "sohee", "c": "uncle_fu", "solo": "sohee"}

DEFAULT_TIMBRE_FOR = {
    "de": dict(_MIXED),
    "en": {"a": "ryan", "b": "serena", "c": "aiden", "solo": "ryan"},
    "es": dict(_MIXED),
    "fr": dict(_MIXED),
    "it": dict(_MIXED),
    "pt": dict(_MIXED),
    "ru": dict(_MIXED),
    "zh": {"a": "dylan", "b": "serena", "c": "uncle_fu", "solo": "serena"},
    "ja": {"a": "dylan", "b": "ono_anna", "c": "uncle_fu", "solo": "ono_anna"},
    "ko": dict(_MIXED),
    "auto": {"a": "ryan", "b": "serena", "c": "aiden", "solo": "ryan"},
}

# Kokoro default timbres: expressive American voices for the 82M engine.
# af_bella = versatile expressive female, af_sarah = bright female,
# am_adam = warm male, bf_emma = British female.
_KOKORO_MIXED = {"a": "af_bella", "b": "am_adam", "c": "bf_emma", "solo": "af_bella"}

KOKORO_DEFAULTS = {
    "de": dict(_KOKORO_MIXED),
    "en": dict(_KOKORO_MIXED),
    "es": dict(_KOKORO_MIXED),
    "fr": {"a": "bf_emma", "b": "am_adam", "c": "af_bella", "solo": "bf_emma"},
    "it": dict(_KOKORO_MIXED),
    "pt": dict(_KOKORO_MIXED),
    "ru": dict(_KOKORO_MIXED),
    "zh": dict(_KOKORO_MIXED),
    "ja": dict(_KOKORO_MIXED),
    "ko": dict(_KOKORO_MIXED),
    "auto": dict(_KOKORO_MIXED),
}

VOICE_PROFILE_KEYS = (
    "engine", "a.timbre", "b.timbre", "c.timbre", "solo.timbre",
    "solo.name", "a.name", "b.name", "c.name", "count",
    "emotion", "a.emotion", "b.emotion", "c.emotion", "solo.emotion",
    "speed", "gap_ms"
)


def normalize_voice(v: dict | None) -> dict:
    """Validate a per-job/per-feed voice profile (DUE-078).

    Unknown keys are dropped, values are clamped to the same ranges the
    settings layer enforces. Returns a clean dict safe to store and to
    hand to the pipeline reader chain job profile > global > default.
    """
    out: dict = {}
    if not isinstance(v, dict):
        return out
    for key in VOICE_PROFILE_KEYS:
        if key not in v:
            continue
        val = v[key]
        if key == "engine":
            from .providers import engine_ids
            if isinstance(val, str) and val in engine_ids():
                out[key] = val
        elif key.endswith(".timbre"):
            if isinstance(val, str) and val in VALID_TIMBRES:
                out[key] = val
        elif key in ("a.name", "b.name", "c.name", "solo.name"):
            if isinstance(val, str) and val.strip():
                out[key] = val.strip()[:24]
        elif key == "count":
            try:
                out[key] = max(1, min(3, int(val)))
            except (TypeError, ValueError):
                pass
        elif key in ("emotion", "a.emotion", "b.emotion", "c.emotion", "solo.emotion"):
            if isinstance(val, str) and len(val) <= 24:
                out[key] = val.strip()
        elif key == "speed":
            try:
                out[key] = max(0.5, min(2.0, float(val)))
            except (TypeError, ValueError):
                pass
        elif key == "gap_ms":
            try:
                out[key] = max(50, min(1200, int(float(val))))
            except (TypeError, ValueError):
                pass
    return out


def default_cast_for(engine: str) -> dict[str, dict[str, str]]:
    """Per-language default cast (a, b, c, solo) for a TTS engine.

    qwen_tts and kokoro have curated tables; any other engine is cast from its
    own speaker list (first male A, first female B, next voice C) so the ids
    always exist for that engine. Until 2026-09-23 every engine got the
    qwen table, and KOKORO_DEFAULTS was never used.
    """
    if engine == "kokoro":
        return KOKORO_DEFAULTS
    if engine in ("qwen_tts", ""):
        return DEFAULT_TIMBRE_FOR
    speakers = speakers_for(engine)
    if not speakers:
        return DEFAULT_TIMBRE_FOR

    def gender(s: dict) -> str:
        g = str(s.get("gender") or "").lower()
        if g in ("m", "f"):
            return g
        label = str(s.get("label") or "").lower()
        return "m" if "(m" in label else "f" if "(f" in label else ""

    def cast_from(pool: list[dict]) -> dict[str, str]:
        males = [s["id"] for s in pool if gender(s) == "m"]
        females = [s["id"] for s in pool if gender(s) == "f"]
        ordered = [s["id"] for s in pool]
        a = (males or ordered)[0]
        b = next((x for x in females + ordered if x != a), a)
        c = next((x for x in males[1:] + females[1:] + ordered if x not in (a, b)), b)
        return {"a": a, "b": b, "c": c, "solo": b}

    # Engines whose voices are single-language (piper: thorsten is German) are
    # cast per language from the voices native to it; until 2026-09-25 English
    # piper episodes got the German thorsten + kerstin.
    fallback = cast_from(speakers)
    out = {}
    for lang in DEFAULT_TIMBRE_FOR:
        name = _LANG_NAMES.get(lang, "")
        native = [s for s in speakers if name and str(s.get("native") or "").startswith(name)]
        out[lang] = cast_from(native) if native else dict(fallback)
    return out


_LANG_NAMES = {
    "en": "English", "de": "German", "es": "Spanish", "fr": "French", "it": "Italian",
    "pt": "Portuguese", "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
}
