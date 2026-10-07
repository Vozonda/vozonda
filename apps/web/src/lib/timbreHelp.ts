// single source for voice temperament hints, shared by compose and
// watchlist voice pickers. deliberately web-side, english-only:
// i18n stays deferred until the UI ever goes multilingual (issue #109).
export const TIMBRE_HELP: Record<string, string> = {
  aiden: 'confident host',
  sohee: 'bright and quick',
  serena: 'soft narrator',
  vivian: 'lively storyteller',
  ono_anna: 'calm and gentle',
  ryan: 'laid-back co-host',
  dylan: 'young energy',
  eric: 'deep gravitas',
  uncle_fu: 'big character voice'
}

export function timbreLabel(
  id: string,
  timbres: { id: string; label: string; native?: string }[]
): string {
  const t = timbres.find((x) => x.id === id)
  if (!t) return id
  const h = TIMBRE_HELP[id]
  return h ? `${t.label} · ${h} · native ${t.native}` : `${t.label} · native ${t.native}`
}
