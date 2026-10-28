<script lang="ts">
  import Icon from './Icon.svelte'
  import {
    getPronunciations,
    savePronunciations,
    getShowPronunciations,
    saveShowPronunciations,
    type PronunciationEntry
  } from '../api'

  interface LocalEntry {
    id: string
    term: string
    say: string
    match_case: boolean
  }

  let {
    slug,
    inShow = false
  }: {
    slug?: string
    inShow?: boolean
  } = $props()

  let nextId = 0
  function makeEntry(e?: Partial<PronunciationEntry>): LocalEntry {
    nextId += 1
    return {
      id: `pe-${nextId}`,
      term: e?.term ?? '',
      say: e?.say ?? '',
      match_case: Boolean(e?.match_case)
    }
  }

  let entries = $state<LocalEntry[]>([])
  let loading = $state(false)
  let saving = $state(false)
  let savedFlash = $state(false)
  let saveError = $state('')
  let loadError = $state('')
  let savedTimer: ReturnType<typeof setTimeout> | undefined

  const uid = $derived(slug ? `pron-${slug.replace(/[^a-zA-Z0-9_-]/g, '-')}` : 'pron-global')
  const helpText = $derived(
    inShow
      ? 'Applied after the global list.'
      : 'Changes only how the voice says a word; the transcript keeps your spelling.'
  )

  async function loadData(targetSlug?: string) {
    loading = true
    loadError = ''
    try {
      const data = targetSlug
        ? await getShowPronunciations(targetSlug)
        : await getPronunciations()
      entries = data.map((d) => makeEntry(d))
    } catch (err: unknown) {
      loadError = err instanceof Error ? err.message.toLowerCase() : 'could not load pronunciations'
    } finally {
      loading = false
    }
  }

  $effect(() => {
    const s = slug
    void loadData(s)
  })

  $effect(() => {
    return () => {
      if (savedTimer) {
        clearTimeout(savedTimer)
      }
    }
  })

  function addWord() {
    entries = [...entries, makeEntry()]
    saveError = ''
    savedFlash = false
  }

  function removeWord(index: number) {
    entries = entries.filter((_, i) => i !== index)
    saveError = ''
    savedFlash = false
  }

  async function doSave() {
    saveError = ''
    savedFlash = false

    const cleaned: PronunciationEntry[] = []
    for (const [i, entry] of entries.entries()) {
      const term = entry.term.trim()
      const say = entry.say.trim()

      // Skip completely empty rows
      if (!term && !say) {
        continue
      }
      if (!term) {
        saveError = `row ${i + 1}: write field cannot be empty`
        return
      }
      if (!say) {
        saveError = `row ${i + 1}: say as field cannot be empty`
        return
      }
      if (term.length > 100) {
        saveError = `row ${i + 1}: write cannot exceed 100 characters`
        return
      }
      if (say.length > 100) {
        saveError = `row ${i + 1}: say as cannot exceed 100 characters`
        return
      }
      cleaned.push({
        term,
        say,
        match_case: Boolean(entry.match_case)
      })
    }

    saving = true
    try {
      const res = slug
        ? await saveShowPronunciations(slug, cleaned)
        : await savePronunciations(cleaned)
      entries = res.map((d) => makeEntry(d))
      savedFlash = true
      if (savedTimer) {
        clearTimeout(savedTimer)
      }
      savedTimer = setTimeout(() => {
        savedFlash = false
      }, 2000)
    } catch (err: unknown) {
      saveError = err instanceof Error ? err.message.toLowerCase() : 'could not save'
    } finally {
      saving = false
    }
  }
</script>

<div class="opt pronunciation-card" class:in-show={inShow} aria-labelledby={inShow ? `${uid}-heading` : undefined}>
  {#if inShow}
    <div class="ctl-row">
      <span id={`${uid}-heading`} class="lab mono pron-show-label">pronunciation</span>
    </div>
  {/if}

  <p class="help">{helpText}</p>

  {#if loading}
    <p class="mono help">// loading...</p>
  {:else}
    {#if entries.length === 0}
      <p class="help empty-help">no pronunciation rules yet. click "add word" to add one.</p>
    {:else}
      <div class="pron-list">
        {#each entries as entry, i (entry.id)}
          <div class="pron-row">
            <div class="pron-field">
              <label class="lab mono" for={`${uid}-write-${entry.id}`}>write</label>
              <input
                id={`${uid}-write-${entry.id}`}
                class="mono text-in"
                type="text"
                maxlength="100"
                spellcheck="false"
                placeholder="e.g. SQL"
                bind:value={entry.term}
                oninput={() => { saveError = '' }}
              />
            </div>
            <div class="pron-field">
              <label class="lab mono" for={`${uid}-say-${entry.id}`}>say as</label>
              <input
                id={`${uid}-say-${entry.id}`}
                class="mono text-in"
                type="text"
                maxlength="100"
                spellcheck="false"
                placeholder="e.g. sequel"
                bind:value={entry.say}
                oninput={() => { saveError = '' }}
              />
            </div>
            <div class="pron-controls">
              <label class="toggle-label mono" for={`${uid}-case-${entry.id}`}>
                <input
                  id={`${uid}-case-${entry.id}`}
                  type="checkbox"
                  bind:checked={entry.match_case}
                  onchange={() => { saveError = '' }}
                />
                <span>match case</span>
              </label>
              <button
                type="button"
                class="link mono remove-btn"
                aria-label={`remove pronunciation for ${entry.term.trim() || 'row ' + (i + 1)}`}
                onclick={() => removeWord(i)}
              >
                <Icon name="trash" size={13} />
                <span>remove</span>
              </button>
            </div>
          </div>
        {/each}
      </div>
    {/if}

    <div class="pron-actions">
      <button type="button" class="link mono add-btn" onclick={addWord}>
        <Icon name="plus" size={13} />
        <span>add word</span>
      </button>

      <div class="save-group">
        {#if savedFlash}
          <span class="mono save-note ok" role="status" aria-live="polite">// saved</span>
        {/if}
        <button
          type="button"
          class="mono btn-save"
          onclick={doSave}
          disabled={saving}
        >
          {saving ? 'saving...' : 'save'}
        </button>
      </div>
    </div>
  {/if}

  {#if saveError}
    <p class="mono help err" role="alert">// error: {saveError}</p>
  {/if}
  {#if loadError}
    <p class="mono help err" role="alert">// error: {loadError}</p>
  {/if}
</div>

<style>
  .pronunciation-card {
    display: grid;
    gap: var(--space-3);
  }

  .pronunciation-card.in-show {
    margin-top: var(--space-3);
    padding-top: var(--space-3);
    border-top: 1px solid color-mix(in srgb, var(--line) 30%, transparent);
  }

  .ctl-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--space-2);
  }

  .lab {
    color: var(--ink-soft);
    font-size: var(--ui-size);
  }

  .pron-show-label {
    color: var(--ink);
    font-weight: 600;
  }

  .help {
    color: var(--ink-soft);
    font-size: var(--ui-size);
    line-height: 1.45;
    margin: 0;
  }

  .help.err {
    color: var(--danger);
  }

  .empty-help {
    font-style: italic;
  }

  .pron-list {
    display: grid;
    gap: var(--space-2);
  }

  .pron-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
    align-items: flex-end;
    gap: var(--space-2);
    padding: var(--space-2);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
  }

  .pron-field {
    display: grid;
    gap: var(--space-1);
    min-width: 0;
  }

  .text-in {
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    background-color: var(--paper);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-1) var(--space-2);
    max-width: 100%;
    width: 100%;
    min-height: 36px;
    box-sizing: border-box;
    transition: border-color var(--dur-fast) ease-out, background-color var(--dur-fast) ease-out;
  }

  .text-in:hover {
    border-color: var(--ink-soft);
    background-color: color-mix(in srgb, var(--ink) 2%, var(--paper));
  }

  .text-in:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 1px;
  }

  .text-in::placeholder {
    color: color-mix(in srgb, var(--ink-soft) 60%, transparent);
  }

  .pron-controls {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 36px;
  }

  .toggle-label {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: var(--ui-size);
    color: var(--ink);
    cursor: pointer;
    white-space: nowrap;
    user-select: none;
  }

  .toggle-label input[type='checkbox'] {
    accent-color: var(--green);
    width: 16px;
    height: 16px;
    cursor: pointer;
    margin: 0;
  }

  .link {
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
    min-height: 28px;
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    text-decoration: underline;
    text-decoration-color: var(--line);
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    transition: color var(--dur-fast) ease-out;
  }

  .link:hover {
    color: var(--green);
  }

  .remove-btn:hover {
    color: var(--danger);
  }

  .pron-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-3);
    margin-top: var(--space-1);
  }

  .save-group {
    display: inline-flex;
    align-items: center;
    gap: var(--space-3);
    margin-left: auto;
  }

  .btn-save {
    font: 600 var(--ui-size) var(--font-mono);
    padding: 0 var(--space-3);
    color: var(--paper);
    background: var(--ink);
    border: 0;
    border-radius: var(--radius);
    cursor: pointer;
    min-height: 36px;
    transition: opacity var(--dur-fast) ease-out;
  }

  .btn-save:hover:not(:disabled) {
    opacity: 0.85;
  }

  .btn-save:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .save-note {
    font-size: var(--ui-size);
    margin: 0;
  }

  .save-note.ok {
    color: var(--green);
  }

  @media (max-width: 600px) {
    .pron-row {
      grid-template-columns: 1fr;
      gap: var(--space-2);
    }

    .pron-controls {
      justify-content: space-between;
      width: 100%;
      padding-top: var(--space-1);
      border-top: 1px dashed color-mix(in srgb, var(--line) 40%, transparent);
    }
  }
</style>
