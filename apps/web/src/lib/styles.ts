// Style catalogue for the web app, driven by GET /meta style_meta.
//
// The backend registry (apps/api/src/vozonda_api/style_registry.py) is the
// single source of truth. These helpers build the style groups, icons and
// docs from the /meta payload; FALLBACK_STYLE_META below is only used while
// /meta is unreachable (offline). A backend test pins the fallback to the
// registry (ids, group, icon, doc) so it cannot drift.

export interface StyleMeta {
  id: string
  doc: string
  group: string
  icon: string
  hosts?: string
}

export interface StyleGroup {
  key: string
  label: string
  styles: string[]
}

/** Group order shown in the UI. Same order as before. */
export const STYLE_GROUP_ORDER = ['learn', 'mood', 'drama', 'play', 'custom'] as const

/**
 * Chip order within each group. Same order as the old hardcoded copies (the
 * backend registry ships energy-axis order, which differs). Style ids the
 * backend adds later sort after these, by id.
 */
const GROUP_STYLE_ORDER: Record<string, string[]> = {
  learn: ['balanced', 'eli5', 'serious', 'socrates'],
  mood: ['asmr', 'meditation', 'slang', 'noir'],
  drama: ['sensational', 'storyteller', 'debate', 'courtroom', 'clash', 'conspiracy', 'true_crime', 'crisis_room'],
  play: ['futbol', 'dude', 'tech_roast', 'trivia']
}

/**
 * Offline fallback. Mirrors the backend registry exactly; used only when
 * /meta fails. Do not edit by hand: apps/api/tests/test_style_ui_from_meta.py
 * checks every entry against style_registry.py.
 */
export const FALLBACK_STYLE_META: StyleMeta[] = [
  { id: 'balanced', doc: 'Balanced tour: curious host, expert guest.', group: 'learn', icon: 'balanced' },
  { id: 'serious', doc: 'Precise and evidence-first, no jokes.', group: 'learn', icon: 'serious' },
  { id: 'sensational', doc: 'High energy and stakes, zero fabrication.', group: 'drama', icon: 'sensational' },
  { id: 'eli5', doc: 'A five-year-old gets it wrong in creative ways; B fixes the picture, not the kid.', group: 'learn', icon: 'eli5' },
  { id: 'slang', doc: 'Two friends after hours in the casual register of your language. Cool, not cringe.', group: 'mood', icon: 'slang' },
  { id: 'debate', doc: 'Sharp pro/contra from the same source; ends in shared ground.', group: 'drama', icon: 'debate' },
  { id: 'storyteller', doc: 'Three named chapters, cliffhanger cuts; B lives inside the story.', group: 'drama', icon: 'storyteller' },
  { id: 'clash', doc: 'A heated on-air fight over ideas: interruptions, challenges, no fake peace at the end.', group: 'drama', icon: 'clash' },
  { id: 'asmr', doc: 'Whisper session: max twelve words per turn; the silences carry it.', group: 'mood', icon: 'asmr' },
  { id: 'meditation', doc: 'Gentle ASMR soothing narration, slow tempo and guided presence.', group: 'mood', icon: 'meditation' },
  { id: 'futbol', doc: 'Latin American football-commentator energy: every point gets the goal call.', group: 'play', icon: 'futbol' },
  { id: 'conspiracy', doc: 'B connects every dot: each fact becomes evidence, every turn ends with a question.', group: 'drama', icon: 'conspiracy' },
  { id: 'socrates', doc: 'A asks only questions and dismantles every answer; B starts confident and slowly unravels.', group: 'learn', icon: 'socrates' },
  { id: 'dude', doc: 'Big Lebowski energy: A abides lazily through the article, B erupts over principles, C drifts in late.', group: 'play', icon: 'dude' },
  { id: 'true_crime', doc: 'Atmospheric tension, deep suspense, dramatic pauses.', group: 'drama', icon: 'storyteller' },
  { id: 'tech_roast', doc: 'Sharp witty debate, fast paced banter, sarcastic tone.', group: 'play', icon: 'witty' },
  { id: 'noir', doc: '1940s hardboiled cyber-noir: rain on neon, fatalistic cynicism, trenchcoat metaphors.', group: 'mood', icon: 'storyteller' },
  { id: 'trivia', doc: 'High-stakes game show: three structured quiz rounds, rapid buzzer reactions.', group: 'play', icon: 'witty' },
  { id: 'courtroom', doc: 'Legal cross-examination: prosecution vs defense, exhibits, objections, jury verdict.', group: 'drama', icon: 'balanced' },
  { id: 'crisis_room', doc: '03:00 AM situation room: SitRep timestamps, incident commander and triage specialist.', group: 'drama', icon: 'pulse' }
]

export interface MetaWithStyles {
  style_meta?: StyleMeta[] | null
  style_docs?: Record<string, string> | null
}

/** Entries from /meta when present, else the offline fallback. */
export function styleMetaList(meta?: MetaWithStyles | null): StyleMeta[] {
  const list = meta?.style_meta
  if (list && list.length > 0) return list
  return FALLBACK_STYLE_META
}

/** Groups in UI order, each holding the style ids of that group. */
export function buildStyleGroups(meta?: MetaWithStyles | null): StyleGroup[] {
  const entries = styleMetaList(meta)
  return STYLE_GROUP_ORDER.map((key) => {
    const ids = entries.filter((e) => e.group === key).map((e) => e.id)
    const order = GROUP_STYLE_ORDER[key] ?? []
    ids.sort((a, b) => {
      const ia = order.indexOf(a)
      const ib = order.indexOf(b)
      if (ia === -1 && ib === -1) return a < b ? -1 : a > b ? 1 : 0
      if (ia === -1) return 1
      if (ib === -1) return -1
      return ia - ib
    })
    return { key, label: key, styles: ids }
  }).filter((g) => g.styles.length > 0)
}

/** Icon name per style id. */
export function buildStyleIcons(meta?: MetaWithStyles | null): Record<string, string> {
  const out: Record<string, string> = {}
  for (const e of styleMetaList(meta)) out[e.id] = e.icon
  return out
}

/**
 * Doc line per style id. A live style_docs entry from /meta wins over the
 * style_meta doc so server-side custom docs keep working.
 */
export function buildStyleDocs(meta?: MetaWithStyles | null): Record<string, string> {
  const out: Record<string, string> = {}
  for (const e of styleMetaList(meta)) out[e.id] = e.doc
  const overrides = meta?.style_docs
  if (overrides) {
    for (const [k, v] of Object.entries(overrides)) out[k] = v
  }
  return out
}

/** Single doc line for one style id. */
export function styleDocFor(style: string, meta?: MetaWithStyles | null): string {
  return buildStyleDocs(meta)[style] ?? ''
}

/** Icon name for one style id. */
export function styleIconFor(style: string, meta?: MetaWithStyles | null): string {
  return buildStyleIcons(meta)[style] ?? 'balanced'
}

/** Group key ('learn' | 'mood' | 'drama' | 'play') for one style id. */
export function categoryOf(style: string, meta?: MetaWithStyles | null): string {
  const found = styleMetaList(meta).find((e) => e.id === style)
  return found?.group ?? 'learn'
}
