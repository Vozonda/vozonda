<script lang="ts">
  import Icon from './Icon.svelte'

  let {
    onAddUrl,
    onAddNote,
    onUploadFile,
    onSubmitReady,
    canSubmit = false,
    disabled = false,
    busy = false,
    flash = false,
    inputEl = $bindable(null)
  }: {
    onAddUrl: (url: string) => Promise<void>
    onAddNote: (text: string) => Promise<void>
    onUploadFile: (file: File) => Promise<void>
    onSubmitReady: () => void
    canSubmit?: boolean
    disabled?: boolean
    busy?: boolean
    flash?: boolean
    inputEl?: HTMLTextAreaElement | null
  } = $props()

  let rawInput = $state('')
  let isDragging = $state(false)
  let fileInputEl = $state<HTMLInputElement | null>(null)
  let isProcessing = $state(false)

  const trimmed = $derived(rawInput.trim())
  const hasText = $derived(trimmed.length > 0)
  // the primary action also takes what is still in the field (plan decision 8)
  const launchReady = $derived(!busy && !isProcessing && (canSubmit || hasText))

  // grow with the text; field-sizing: content does it natively where supported
  $effect(() => {
    void rawInput
    const el = inputEl
    if (!el || (typeof CSS !== 'undefined' && CSS.supports?.('field-sizing', 'content'))) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  })

  // Enter adds, Enter on empty field starts
  async function handleKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (hasText) {
        await processInput()
      } else if (canSubmit && !disabled) {
        onSubmitReady()
      }
    }
  }

  async function processInput() {
    const text = trimmed
    if (!text || isProcessing || disabled) return
    isProcessing = true
    try {
      // Check if input is one or multiple URLs (one per line)
      const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
      const firstLine = lines[0] ?? ''
      const isAllUrls = lines.length > 0 && lines.every((l) => /^https?:\/\//i.test(l) || /^www\./i.test(l))
      const isSingleUrlLike = lines.length === 1 && (/^https?:\/\//i.test(firstLine) || /^[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(\/.*)?$/.test(firstLine))

      if (isAllUrls) {
        rawInput = ''
        for (const line of lines) {
          const norm = /^https?:\/\//i.test(line) ? line : `https://${line}`
          await onAddUrl(norm)
        }
      } else if (isSingleUrlLike) {
        rawInput = ''
        const norm = /^https?:\/\//i.test(firstLine) ? firstLine : `https://${firstLine}`
        await onAddUrl(norm)
      } else {
        // Plain text note
        rawInput = ''
        await onAddNote(text)
      }
    } finally {
      isProcessing = false
      inputEl?.focus()
    }
  }

  function handleFileSelect(e: Event) {
    const target = e.target as HTMLInputElement
    const files = target.files
    if (!files || files.length === 0) return
    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      if (file) void onUploadFile(file)
    }
    target.value = ''
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    isDragging = false
    if (disabled || isProcessing) return
    const files = e.dataTransfer?.files
    if (files && files.length > 0) {
      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        if (file) void onUploadFile(file)
      }
    } else {
      const droppedText = e.dataTransfer?.getData('text')
      if (droppedText) {
        rawInput = (rawInput ? rawInput + '\n' : '') + droppedText
      }
    }
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault()
    if (!disabled && !isProcessing) {
      isDragging = true
    }
  }

  function handleDragLeave(e: DragEvent) {
    e.preventDefault()
    isDragging = false
  }

  // Public method for external callers (e.g. submit button taking leftover input)
  export async function flushRemaining(): Promise<void> {
    if (hasText) {
      await processInput()
    }
  }
</script>

<!-- One box like a chat composer: the field has no frame of its own and grows with
     its text; every action sits in the bar inside the box. -->
<div
  class="composer"
  class:dragging={isDragging}
  class:busy={isProcessing}
  ondragover={handleDragOver}
  ondragleave={handleDragLeave}
  ondrop={handleDrop}
  role="region"
  aria-label="Source drop zone"
>
  <textarea
    bind:this={inputEl}
    bind:value={rawInput}
    class="mono smart-input"
    rows="2"
    placeholder="paste a link, text, or drop files"
    aria-label="Paste a link, text, or drop files"
    disabled={disabled || isProcessing}
    onkeydown={handleKeyDown}
  ></textarea>

  <div class="composer-bar mono">
    <button
      type="button"
      class="icon-btn"
      onclick={() => fileInputEl?.click()}
      disabled={disabled || isProcessing}
      title="upload a pdf, image or text file"
      aria-label="Upload file"
    >
      <Icon name="upload" size={16} />
    </button>

    <span class="hint" aria-live="polite">
      {#if isDragging}
        drop to add
      {:else if isProcessing}
        <Icon name="pulse" size={12} /> reading…
      {:else if hasText}
        enter adds · shift+enter new line
      {:else if canSubmit}
        or press enter
      {:else}
        articles, pdf, images, audio, youtube, notes
      {/if}
    </span>

    <span class="bar-actions">
      {#if hasText}
        <button
          type="button"
          class="add-btn mono"
          onclick={() => void processInput()}
          disabled={disabled || isProcessing}
          aria-label="Add source"
        >
          <Icon name="plus" size={14} />
          <span>add</span>
        </button>
      {/if}
      <button
        type="button"
        class="launch-btn mono"
        class:ready={launchReady}
        class:flash
        disabled={!launchReady}
        onclick={() => onSubmitReady()}
        aria-label="Make it talk: generate the episode"
      >
        <Icon name="playtri" size={14} />
        <span>{busy ? 'starting…' : 'make it talk'}</span>
      </button>
    </span>
  </div>

  <input
    bind:this={fileInputEl}
    type="file"
    onchange={handleFileSelect}
    multiple
    accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.mp3,.m4a,.wav,.ogg,.opus"
    hidden
    aria-hidden="true"
  />
</div>

<style>
  .composer {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
    padding: var(--space-2);
    background: color-mix(in srgb, var(--ink) 3%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    transition: border-color var(--dur-fast) ease-out, box-shadow var(--dur-fast) ease-out;
  }

  .composer:focus-within {
    border-color: color-mix(in srgb, var(--green) 55%, var(--line));
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--green) 14%, transparent);
  }

  .composer.dragging {
    border-style: dashed;
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 6%, var(--paper));
  }

  /* the field itself has no frame, no handle and no visible scrollbar until it is long */
  .smart-input {
    display: block;
    width: 100%;
    box-sizing: border-box;
    min-height: calc(var(--ui-size) * 3.2);
    max-height: 40vh;
    padding: var(--space-1) var(--space-2);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    line-height: 1.55;
    color: var(--ink);
    background: transparent;
    border: none;
    outline: none;
    resize: none;
    overflow-y: auto;
    scrollbar-width: thin;
    field-sizing: content;
  }

  .smart-input::placeholder {
    color: color-mix(in srgb, var(--ink-soft) 80%, transparent);
  }

  .smart-input:disabled {
    cursor: progress;
  }

  .composer-bar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .icon-btn {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    padding: 0;
    color: var(--ink-soft);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius);
    cursor: pointer;
    transition: color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }

  .icon-btn:hover:not(:disabled) {
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 7%, transparent);
  }

  .icon-btn:focus-visible,
  .add-btn:focus-visible,
  .launch-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .hint {
    flex: 1 1 10rem;
    min-width: 0;
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: calc(var(--ui-size) * 0.85);
    color: var(--ink-soft);
  }

  .bar-actions {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }

  .add-btn,
  .launch-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 36px;
    padding: 0 var(--space-3);
    font-family: var(--font-mono);
    font-size: var(--ui-size);
    font-weight: 500;
    white-space: nowrap;
    border-radius: var(--radius);
    transition: background var(--dur-fast) ease-out, color var(--dur-fast) ease-out,
      border-color var(--dur-fast) ease-out;
  }

  .add-btn {
    color: var(--ink);
    background: transparent;
    border: 1px solid var(--line);
    cursor: pointer;
  }

  .add-btn:hover:not(:disabled) {
    border-color: var(--ink-soft);
  }

  /* the one primary action of the page: an outline while nothing can start,
     solid ink once it can (a disabled solid button read as broken grey) */
  .launch-btn {
    color: var(--ink-soft);
    background: transparent;
    border: 1px solid var(--line);
    cursor: not-allowed;
  }

  .launch-btn.ready {
    color: var(--paper);
    background: var(--ink);
    border-color: var(--ink);
    cursor: pointer;
  }

  .launch-btn.ready:hover {
    background: var(--green);
    border-color: var(--green);
  }

  .launch-btn.flash {
    animation: launch-pulse var(--dur-slow) ease-out 2;
  }

  @keyframes launch-pulse {
    50% {
      background: var(--green);
      border-color: var(--green);
    }
  }

  @media (max-width: 600px) {
    .hint {
      display: none;
    }

    .bar-actions {
      flex: 1 1 auto;
    }

    .launch-btn {
      flex: 1 1 auto;
      justify-content: center;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .composer,
    .launch-btn {
      transition: none;
    }

    .launch-btn.flash {
      animation: none;
    }
  }
</style>
