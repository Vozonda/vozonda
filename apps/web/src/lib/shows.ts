// Show catalog: the single source for the compose show picker and the
// watchlist template tiles. Values apply to ONE episode (the job's voice
// profile); a show never changes global settings such as the TTS engine.

export interface TemplateVoices {
  a?: string
  b?: string
  c?: string
  solo?: string
  a_emotion?: string
  b_emotion?: string
  c_emotion?: string
  solo_emotion?: string
}

export interface TemplateValues {
  style: string
  format: 'dialog' | 'narration'
  hosts: number
  explicit: boolean
  voices?: TemplateVoices
  // advanced presets (#122 follow-up): setting key -> value, written
  // instant-save on pick. curation over mass: 2-3 keys per persona max
  advanced?: Record<string, string>
}

export interface TemplateItem {
  id: string
  label: string
  teaserTitle: string
  teaserDuration: string
  icon: string
  engineName: 'voxtral' | 'qwen' | 'piper' | 'kokoro'
  summary: string
  details: string
  values: TemplateValues
  engineVoices?: {
    qwen_tts: TemplateVoices
    voxtral: TemplateVoices
    piper: TemplateVoices
    kokoro?: TemplateVoices
  }
}

export const TEMPLATES: TemplateItem[] = [
  {
    id: 'morning_dispatch',
    label: 'morning dispatch',
    teaserTitle: 'sample · news',
    teaserDuration: '27s',
    icon: 'serious',
    engineName: 'voxtral',
    summary: 'conversation · 2 hosts · crisp pace',
    details: '2 hosts (m/f · serious + calm) · serious · direct research · 1.05x · 300ms gap',
    values: {
      style: 'serious',
      format: 'dialog',
      hosts: 2,
      explicit: false,
      advanced: { 'voice.speed': '1.05', 'voice.gap_ms': '300', 'tts.engine': 'voxtral', 'source.research_depth': 'direct' }
    },
    engineVoices: {
      qwen_tts: { a: 'dylan', b: 'sohee', a_emotion: 'serious', b_emotion: 'calm' },
      voxtral: { a: 'oliver', b: 'emma', a_emotion: 'serious', b_emotion: 'calm' },
      piper: { a: 'ryan', b: 'amy', a_emotion: 'serious', b_emotion: 'calm' },
      kokoro: { a: 'af_sarah', b: 'am_adam', a_emotion: 'serious', b_emotion: 'calm' }
    }
  },
  {
    id: 'feature_story',
    label: 'feature story',
    teaserTitle: 'sample · story',
    teaserDuration: '60s',
    icon: 'balanced',
    engineName: 'qwen',
    summary: 'conversation · 2 hosts · natural pace',
    details: '2 hosts (m/f · neutral + warm) · balanced · deep-page research · 1.00x · 380ms gap',
    values: {
      style: 'balanced',
      format: 'dialog',
      hosts: 2,
      explicit: false,
      advanced: { 'voice.speed': '1.0', 'voice.gap_ms': '380', 'tts.engine': 'qwen_tts', 'source.research_depth': 'deep-page' }
    },
    engineVoices: {
      qwen_tts: { a: 'dylan', b: 'sohee', a_emotion: 'neutral', b_emotion: 'warm' },
      voxtral: { a: 'oliver', b: 'emma', a_emotion: 'neutral', b_emotion: 'warm' },
      piper: { a: 'ryan', b: 'amy', a_emotion: 'neutral', b_emotion: 'warm' },
      kokoro: { a: 'af_bella', b: 'am_eric', a_emotion: 'neutral', b_emotion: 'warm' }
    }
  },
  {
    id: 'trio_roundtable',
    label: 'trio roundtable',
    teaserTitle: 'sample · 3-way',
    teaserDuration: '30s',
    icon: 'clash',
    engineName: 'kokoro',
    summary: 'roundtable panel · 3 hosts · lively debate',
    details: '3 hosts (2m/1f · energetic + dramatic + serious) · clash · contrast research · 1.02x · 280ms gap',
    values: {
      style: 'clash',
      format: 'dialog',
      hosts: 3,
      explicit: false,
      advanced: { 'voice.speed': '1.02', 'voice.gap_ms': '280', 'tts.engine': 'kokoro', 'source.research_depth': 'contrast' }
    },
    engineVoices: {
      qwen_tts: { a: 'dylan', b: 'sohee', c: 'uncle_fu', a_emotion: 'energetic', b_emotion: 'dramatic', c_emotion: 'serious' },
      voxtral: { a: 'oliver', b: 'emma', c: 'leopold', a_emotion: 'energetic', b_emotion: 'dramatic', c_emotion: 'serious' },
      piper: { a: 'ryan', b: 'amy', c: 'alan', a_emotion: 'energetic', b_emotion: 'dramatic', c_emotion: 'serious' },
      kokoro: { a: 'af_bella', b: 'am_michael', c: 'bf_emma', a_emotion: 'energetic', b_emotion: 'dramatic', c_emotion: 'serious' }
    }
  },
  {
    id: 'tech_roast',
    label: 'tech roast',
    teaserTitle: 'sample · roast',
    teaserDuration: '21s',
    icon: 'witty',
    engineName: 'kokoro',
    summary: 'conversation · 2 hosts · fast banter',
    details: '2 hosts (m/f · cheerful + energetic) · tech roast · direct research · 1.08x · 220ms gap',
    values: {
      style: 'tech_roast',
      format: 'dialog',
      hosts: 2,
      explicit: false,
      advanced: { 'voice.speed': '1.08', 'voice.gap_ms': '220', 'tts.engine': 'kokoro', 'source.research_depth': 'direct' }
    },
    engineVoices: {
      qwen_tts: { a: 'dylan', b: 'sohee', a_emotion: 'cheerful', b_emotion: 'energetic' },
      voxtral: { a: 'oliver', b: 'emma', a_emotion: 'cheerful', b_emotion: 'energetic' },
      piper: { a: 'ryan', b: 'amy', a_emotion: 'cheerful', b_emotion: 'energetic' },
      kokoro: { a: 'am_adam', b: 'af_sarah', a_emotion: 'cheerful', b_emotion: 'energetic' }
    }
  },
  {
    id: 'true_crime_dossier',
    label: 'true crime dossier',
    teaserTitle: 'sample · crime',
    teaserDuration: '33s',
    icon: 'storyteller',
    engineName: 'voxtral',
    summary: 'conversation · 2 hosts · dramatic pace',
    details: '2 hosts (m/f · dramatic + serious) · true crime · fact-check research · 0.95x · 450ms gap',
    values: {
      style: 'true_crime',
      format: 'dialog',
      hosts: 2,
      explicit: false,
      advanced: { 'voice.speed': '0.95', 'voice.gap_ms': '450', 'tts.engine': 'voxtral', 'source.research_depth': 'fact-check' }
    },
    engineVoices: {
      qwen_tts: { a: 'dylan', b: 'sohee', a_emotion: 'dramatic', b_emotion: 'serious' },
      voxtral: { a: 'oliver', b: 'emma', a_emotion: 'dramatic', b_emotion: 'serious' },
      piper: { a: 'ryan', b: 'amy', a_emotion: 'dramatic', b_emotion: 'serious' },
      kokoro: { a: 'af_nicole', b: 'bm_george', a_emotion: 'dramatic', b_emotion: 'serious' }
    }
  },
  {
    id: 'explainer_lab',
    label: 'explainer lab',
    teaserTitle: 'sample · eli5',
    teaserDuration: '37s',
    icon: 'eli5',
    engineName: 'qwen',
    summary: 'conversation · 2 hosts · clear analogies',
    details: '2 hosts (m/f · cheerful + warm) · eli5 · deep-page research · 0.98x · 340ms gap',
    values: {
      style: 'eli5',
      format: 'dialog',
      hosts: 2,
      explicit: false,
      advanced: { 'voice.speed': '0.98', 'voice.gap_ms': '340', 'tts.engine': 'qwen_tts', 'source.research_depth': 'deep-page' }
    },
    engineVoices: {
      qwen_tts: { a: 'dylan', b: 'sohee', a_emotion: 'cheerful', b_emotion: 'warm' },
      voxtral: { a: 'oliver', b: 'emma', a_emotion: 'cheerful', b_emotion: 'warm' },
      piper: { a: 'ryan', b: 'amy', a_emotion: 'cheerful', b_emotion: 'warm' },
      kokoro: { a: 'af_sky', b: 'am_adam', a_emotion: 'cheerful', b_emotion: 'warm' }
    }
  },
  {
    id: 'socratic_dialogue',
    label: 'socratic dialogue',
    teaserTitle: 'sample · inquiry',
    teaserDuration: '31s',
    icon: 'socrates',
    engineName: 'voxtral',
    summary: 'conversation · 2 hosts · deep inquiry',
    details: '2 hosts (m/f · serious + calm) · socrates · contrast research · 0.92x · 480ms gap',
    values: {
      style: 'socrates',
      format: 'dialog',
      hosts: 2,
      explicit: false,
      advanced: { 'voice.speed': '0.92', 'voice.gap_ms': '480', 'tts.engine': 'voxtral', 'source.research_depth': 'contrast' }
    },
    engineVoices: {
      qwen_tts: { a: 'dylan', b: 'sohee', a_emotion: 'serious', b_emotion: 'calm' },
      voxtral: { a: 'oliver', b: 'emma', a_emotion: 'serious', b_emotion: 'calm' },
      piper: { a: 'ryan', b: 'amy', a_emotion: 'serious', b_emotion: 'calm' },
      kokoro: { a: 'af_bella', b: 'bf_isabella', a_emotion: 'serious', b_emotion: 'calm' }
    }
  },
  {
    id: 'solo_audio_essay',
    label: 'solo audio essay',
    teaserTitle: 'sample · essay',
    teaserDuration: '17s',
    icon: 'balanced',
    engineName: 'piper',
    summary: 'read aloud · 1 host · steady pace',
    details: '1 host (f · calm) · balanced · deep-page research · 0.95x · 400ms gap',
    values: {
      style: 'balanced',
      format: 'narration',
      hosts: 1,
      explicit: false,
      advanced: { 'voice.speed': '0.95', 'voice.gap_ms': '400', 'tts.engine': 'piper', 'source.research_depth': 'deep-page' }
    },
    engineVoices: {
      qwen_tts: { solo: 'sohee', solo_emotion: 'calm' },
      voxtral: { solo: 'emma', solo_emotion: 'calm' },
      piper: { solo: 'amy', solo_emotion: 'calm' },
      kokoro: { solo: 'af_nicole', solo_emotion: 'calm' }
    }
  },
  {
    id: 'zen_meditation',
    label: 'zen meditation',
    teaserTitle: 'sample · zen',
    teaserDuration: '22s',
    icon: 'meditation',
    engineName: 'piper',
    summary: 'read aloud · 1 host · soothing pace',
    details: '1 host (f · calm) · meditation · direct research · 0.85x · 600ms gap',
    values: {
      style: 'meditation',
      format: 'narration',
      hosts: 1,
      explicit: false,
      advanced: { 'voice.speed': '0.85', 'voice.gap_ms': '600', 'tts.engine': 'piper', 'source.research_depth': 'direct' }
    },
    engineVoices: {
      qwen_tts: { solo: 'sohee', solo_emotion: 'calm' },
      voxtral: { solo: 'emma', solo_emotion: 'calm' },
      piper: { solo: 'amy', solo_emotion: 'calm' },
      kokoro: { solo: 'bf_emma', solo_emotion: 'calm' }
    }
  }
]

// ---------------------------------------------------------------------------
// Compose show picker: the four NotebookLM classics first, then the curated
// shows. A show sets style, hosts and, per engine, voices plus pacing for ONE
// episode. It never switches the TTS engine or writes global settings.

export type ShowCategory = 'learn' | 'mood' | 'drama' | 'play'

export interface Show {
  id: string
  label: string
  icon: string
  desc: string
  category: ShowCategory | null
  style: string
  format: 'dialog' | 'narration'
  hosts: number
  explicit: boolean
  speed?: number
  gapMs?: number
  engineVoices?: Partial<Record<string, TemplateVoices>>
  // pre-rendered teaser; its voices only match when engine === the active one
  sample?: { url: string; engine: string }
}

const CLASSICS: Show[] = [
  { id: 'deep_dive', label: 'deep dive', icon: 'balanced', desc: 'thorough conversation, full context', category: null, style: 'balanced', format: 'dialog', hosts: 2, explicit: false },
  { id: 'brief', label: 'brief', icon: 'serious', desc: 'short and precise, just the facts', category: null, style: 'serious', format: 'dialog', hosts: 2, explicit: false },
  { id: 'debate', label: 'debate', icon: 'debate', desc: 'pro and contra, sharp but fair', category: null, style: 'debate', format: 'dialog', hosts: 2, explicit: false },
  { id: 'critique', label: 'critique', icon: 'socrates', desc: 'questions that take the argument apart', category: null, style: 'socrates', format: 'dialog', hosts: 2, explicit: false }
]

// order after the classics; the first four fill the visible 4x2 grid
const CURATED_ORDER = [
  'morning_dispatch', 'feature_story', 'explainer_lab', 'trio_roundtable',
  'tech_roast', 'true_crime_dossier', 'socratic_dialogue', 'solo_audio_essay', 'zen_meditation'
]

const CURATED_COPY: Record<string, { desc: string; category: ShowCategory }> = {
  morning_dispatch: { desc: 'the news of your link, crisp and to the point', category: 'learn' },
  feature_story: { desc: 'a narrative arc with chapters and a twist', category: 'drama' },
  explainer_lab: { desc: 'a curious host and an expert who makes it click', category: 'learn' },
  trio_roundtable: { desc: 'three voices, three angles, one table', category: 'play' },
  tech_roast: { desc: 'sharp, witty and allergic to hype', category: 'play' },
  true_crime_dossier: { desc: 'slow suspense, evidence first', category: 'drama' },
  socratic_dialogue: { desc: 'one asks, one answers, both think harder', category: 'learn' },
  solo_audio_essay: { desc: 'one calm voice reads it to you', category: 'mood' },
  zen_meditation: { desc: 'slow, soft and soothing', category: 'mood' }
}

const ENGINE_ID: Record<TemplateItem['engineName'], string> = {
  qwen: 'qwen_tts', voxtral: 'voxtral', piper: 'piper', kokoro: 'kokoro'
}

function fromTemplate(t: TemplateItem): Show {
  const adv = t.values.advanced ?? {}
  const copy = CURATED_COPY[t.id] ?? { desc: t.summary, category: 'learn' as ShowCategory }
  return {
    id: t.id,
    label: t.label,
    icon: t.icon,
    desc: copy.desc,
    category: copy.category,
    style: t.values.style,
    format: t.values.format,
    hosts: t.values.hosts,
    explicit: t.values.explicit,
    speed: adv['voice.speed'] ? Number(adv['voice.speed']) : undefined,
    gapMs: adv['voice.gap_ms'] ? Number(adv['voice.gap_ms']) : undefined,
    engineVoices: t.engineVoices,
    sample: { url: `/media/samples/templates/${t.id}.mp3`, engine: ENGINE_ID[t.engineName] }
  }
}

// With 2+ sources compose makes ONE conversation; this show asks for the
// per-source digest instead (one story per source, chapters, transitions).
export const DIGEST_SHOW: Show = {
  id: 'digest', label: 'digest', icon: 'history', desc: 'one story per source, with chapters',
  category: 'learn', style: 'balanced', format: 'dialog', hosts: 2, explicit: false
}

export const SHOWS: Show[] = [
  ...CLASSICS,
  ...CURATED_ORDER.map((id) => TEMPLATES.find((t) => t.id === id)).filter((t): t is TemplateItem => !!t).map(fromTemplate),
  DIGEST_SHOW
]

// cards visible before "show all": fills 4x2 on wide screens and 2x4 on phones
export const SHOWS_VISIBLE = 8

/** Per-episode voice profile patch for a show on the given engine. */
export function showVoicePatch(show: Show, engine: string): Record<string, string | number> {
  const patch: Record<string, string | number> = {}
  const v = show.engineVoices?.[engine]
  if (v) {
    const keys: [keyof TemplateVoices, string][] = [
      ['a', 'a.timbre'], ['b', 'b.timbre'], ['c', 'c.timbre'], ['solo', 'solo.timbre'],
      ['a_emotion', 'a.emotion'], ['b_emotion', 'b.emotion'], ['c_emotion', 'c.emotion'], ['solo_emotion', 'solo.emotion']
    ]
    for (const [from, to] of keys) {
      const val = v[from]
      if (val) patch[to] = val
    }
  }
  if (show.speed !== undefined) patch.speed = show.speed
  if (show.gapMs !== undefined) patch.gap_ms = show.gapMs
  return patch
}

/** Human pace word for a speed factor. */
export function paceWord(speed: number | undefined): string {
  if (speed === undefined || Number.isNaN(speed)) return 'natural pace'
  if (speed < 0.9) return 'slow, calm pace'
  if (speed < 0.97) return 'relaxed pace'
  if (speed > 1.04) return 'brisk pace'
  return 'natural pace'
}
