<script lang="ts">
  import Icon from './Icon.svelte'

  interface Props {
    onback: () => void
  }

  let { onback }: Props = $props()

  let viewMode = $state<'all' | 'people' | 'agents'>('all')
  let copiedId = $state<string | null>(null)
  let copyTimer: ReturnType<typeof setTimeout> | null = null

  async function copySnippet(id: string, text: string) {
    try {
      await navigator.clipboard.writeText(text)
      if (copyTimer) clearTimeout(copyTimer)
      copiedId = id
      copyTimer = setTimeout(() => {
        copiedId = null
      }, 2000)
    } catch {
      // clipboard access might be unavailable
    }
  }

  const claudeCodeCmd =
    'claude mcp add vozonda -e VOZONDA_API=http://127.0.0.1:8787 -- /path/to/vozonda/apps/api/.venv/bin/python -m vozonda_api.mcp_server'

  const claudeDesktopSnippet = JSON.stringify(
    {
      mcpServers: {
        vozonda: {
          command: '/path/to/vozonda/apps/api/.venv/bin/python',
          args: ['-m', 'vozonda_api.mcp_server'],
          env: {
            VOZONDA_API: 'http://127.0.0.1:8787',
            VOZONDA_TOKEN: ''
          }
        }
      }
    },
    null,
    2
  )

  const httpStartCmd = 'python -m vozonda_api.mcp_server --http --port 8790 --host 127.0.0.1'

  const httpClientSnippet = JSON.stringify(
    {
      mcpServers: {
        vozonda: {
          url: 'http://127.0.0.1:8790/mcp'
        }
      }
    },
    null,
    2
  )

  const prompt1 = 'make a 10-minute episode from https://example.com/article'
  const prompt2 =
    'combine these three links into one episode: https://example.com/part1, https://example.com/part2, https://example.com/part3'
  const prompt3 = 'what did you make today?'
  const prompt4 =
    'watch https://example.com/feed.xml and make me a morning digest every weekday at 7, Berlin time'
</script>

<div class="agents-page">
  <div class="top-nav">
    <button type="button" class="link mono back-link" onclick={onback}>
      <Icon name="back" size={13} />
      <span>back to compose</span>
    </button>

    <div class="seg-wrap" role="group" aria-label="section filter">
      <div class="seg">
        <button
          type="button"
          class:sel={viewMode === 'all'}
          onclick={() => (viewMode = 'all')}
        >
          all
        </button>
        <button
          type="button"
          class:sel={viewMode === 'people'}
          onclick={() => (viewMode = 'people')}
        >
          for people
        </button>
        <button
          type="button"
          class:sel={viewMode === 'agents'}
          onclick={() => (viewMode = 'agents')}
        >
          for agents
        </button>
      </div>
    </div>
  </div>

  <div class="scope-banner mono">
    <span class="scope-tag">// self-hosted scope</span>
    <p class="scope-text">
      vozonda runs on your own machine or private tailnet. there is no hosted public endpoint yet.
      your documents, transcripts, and audio files remain strictly on your hardware.
    </p>
  </div>

  {#if viewMode === 'all' || viewMode === 'people'}
    <section class="part-sec" id="for-people" aria-labelledby="h-for-people">
      <div class="sec-header">
        <h2 id="h-for-people" class="mono sec-title">for people</h2>
        <span class="mono sec-tag">// your assistant makes the podcast</span>
      </div>

      <p class="lede-copy">
        your assistant turns links into episodes that land in your podcast feed. vozonda reads the sources,
        writes balanced dialogue, performs every turn with local voices, and publishes the finished audio straight
        to your library and personal rss feed.
      </p>

      <div class="sub-block">
        <h3 class="mono sub-title">how to connect</h3>
        <p class="sub-help mono">
          choose your assistant or client below. make sure the vozonda api service is running (default port 8787).
        </p>

        <div class="client-tabs">
          <div class="code-box">
            <div class="code-head">
              <span class="code-label mono">claude code (cli)</span>
              <button
                type="button"
                class="copy-btn mono"
                onclick={() => copySnippet('claude-code', claudeCodeCmd)}
                aria-label="copy claude code configuration command"
              >
                {#if copiedId === 'claude-code'}
                  <Icon name="check" size={13} />
                  <span>copied</span>
                {:else}
                  <Icon name="copy" size={13} />
                  <span>copy</span>
                {/if}
              </button>
            </div>
            <pre><code>{claudeCodeCmd}</code></pre>
          </div>

          <div class="code-box">
            <div class="code-head">
              <span class="code-label mono">claude desktop & json mcp clients</span>
              <button
                type="button"
                class="copy-btn mono"
                onclick={() => copySnippet('claude-desktop', claudeDesktopSnippet)}
                aria-label="copy claude desktop json snippet"
              >
                {#if copiedId === 'claude-desktop'}
                  <Icon name="check" size={13} />
                  <span>copied</span>
                {:else}
                  <Icon name="copy" size={13} />
                  <span>copy</span>
                {/if}
              </button>
            </div>
            <pre><code>{claudeDesktopSnippet}</code></pre>
          </div>

          <div class="code-box">
            <div class="code-head">
              <span class="code-label mono">streamable http transport (start server)</span>
              <button
                type="button"
                class="copy-btn mono"
                onclick={() => copySnippet('http-start', httpStartCmd)}
                aria-label="copy streamable http start command"
              >
                {#if copiedId === 'http-start'}
                  <Icon name="check" size={13} />
                  <span>copied</span>
                {:else}
                  <Icon name="copy" size={13} />
                  <span>copy</span>
                {/if}
              </button>
            </div>
            <pre><code>{httpStartCmd}</code></pre>
          </div>

          <div class="code-box">
            <div class="code-head">
              <span class="code-label mono">streamable http client config (endpoint: /mcp)</span>
              <button
                type="button"
                class="copy-btn mono"
                onclick={() => copySnippet('http-client', httpClientSnippet)}
                aria-label="copy streamable http client configuration snippet"
              >
                {#if copiedId === 'http-client'}
                  <Icon name="check" size={13} />
                  <span>copied</span>
                {:else}
                  <Icon name="copy" size={13} />
                  <span>copy</span>
                {/if}
              </button>
            </div>
            <pre><code>{httpClientSnippet}</code></pre>
          </div>
        </div>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">example prompts to try</h3>
        <p class="sub-help mono">
          once connected, talk to your assistant naturally. here are four common workflows:
        </p>

        <div class="prompt-grid">
          <div class="prompt-card">
            <div class="prompt-body">
              <span class="prompt-label mono">// single article</span>
              <p class="prompt-text mono">{prompt1}</p>
            </div>
            <button
              type="button"
              class="copy-btn mono"
              onclick={() => copySnippet('p1', prompt1)}
              aria-label="copy single article prompt"
            >
              {#if copiedId === 'p1'}
                <Icon name="check" size={13} />
                <span>copied</span>
              {:else}
                <Icon name="copy" size={13} />
                <span>copy</span>
              {/if}
            </button>
          </div>

          <div class="prompt-card">
            <div class="prompt-body">
              <span class="prompt-label mono">// multi-source synthesis</span>
              <p class="prompt-text mono">{prompt2}</p>
            </div>
            <button
              type="button"
              class="copy-btn mono"
              onclick={() => copySnippet('p2', prompt2)}
              aria-label="copy multi-source prompt"
            >
              {#if copiedId === 'p2'}
                <Icon name="check" size={13} />
                <span>copied</span>
              {:else}
                <Icon name="copy" size={13} />
                <span>copy</span>
              {/if}
            </button>
          </div>

          <div class="prompt-card">
            <div class="prompt-body">
              <span class="prompt-label mono">// query recent creations</span>
              <p class="prompt-text mono">{prompt3}</p>
            </div>
            <button
              type="button"
              class="copy-btn mono"
              onclick={() => copySnippet('p3', prompt3)}
              aria-label="copy query creations prompt"
            >
              {#if copiedId === 'p3'}
                <Icon name="check" size={13} />
                <span>copied</span>
              {:else}
                <Icon name="copy" size={13} />
                <span>copy</span>
              {/if}
            </button>
          </div>

          <div class="prompt-card">
            <div class="prompt-body">
              <span class="prompt-label mono">// a feed that becomes a podcast</span>
              <p class="prompt-text mono">{prompt4}</p>
            </div>
            <button
              type="button"
              class="copy-btn mono"
              onclick={() => copySnippet('p4', prompt4)}
              aria-label="copy watchlist prompt"
            >
              {#if copiedId === 'p4'}
                <Icon name="check" size={13} />
                <span>copied</span>
              {:else}
                <Icon name="copy" size={13} />
                <span>copy</span>
              {/if}
            </button>
          </div>
        </div>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">where episodes appear</h3>
        <p class="fact-body">
          every episode completed by an agent immediately lands in your vozonda <a href="#library" class="link mono">library</a>
          with its full transcript and playback controls. it also automatically appears in your personal podcast feed at
          <code>/feed.xml</code>. add the feed to pocket casts, overcast, apple podcasts, antenna pod, or any podcatcher
          to listen during your commute.
        </p>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">sovereign & private</h3>
        <p class="fact-body">
          runs on your own machine. local speech models synthesize audio without sending text to third-party cloud tts
          providers. no tracking, no external accounts, and no data leaves your control.
        </p>
      </div>
    </section>
  {/if}

  {#if viewMode === 'all' || viewMode === 'agents'}
    <section class="part-sec" id="for-agents" aria-labelledby="h-for-agents">
      <div class="sec-header">
        <h2 id="h-for-agents" class="mono sec-title">for agents</h2>
        <span class="mono sec-tag">// deterministic tools & http contract</span>
      </div>

      <p class="lede-copy">
        plain structure and deterministic specifications for ai agents invoking vozonda tools or calling the http api directly.
      </p>

      <div class="sub-block">
        <h3 class="mono sub-title">configuration by environment</h3>
        <p class="sub-help mono">the mcp server reads configuration exclusively from environment variables:</p>
        <dl class="mono spec-dl">
          <div>
            <dt>VOZONDA_API</dt>
            <dd>http api base url (default: <code>http://127.0.0.1:8787</code>)</dd>
          </div>
          <div>
            <dt>VOZONDA_TOKEN</dt>
            <dd>bearer auth token. sent in authorization header on write requests when the api enforces write auth</dd>
          </div>
        </dl>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">mcp tool list</h3>
        <div class="tools-grid">
          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">create_episode</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">create a new podcast episode from one or more urls or raw pasted text.</p>
            <div class="param-group mono">
              <span class="param-title">// arguments:</span>
              <ul class="param-list">
                <li><code>sources: list[str] | null</code>: 1 url creates a single-source episode; 2+ urls create a combined conversation.</li>
                <li><code>text: str | null</code>: pasted article text (min 150 chars). provide either sources or text.</li>
                <li><code>minutes: float | null</code>: target episode length in minutes (1 to 60).</li>
                <li><code>style: str</code>: dialogue style id (default "balanced"). query list_styles for choices.</li>
                <li><code>language: str</code>: output language code (default "auto" for source language detection).</li>
                <li><code>focus: str | null</code>: steer emphasis without adding ungrounded facts.</li>
              </ul>
            </div>
            <div class="param-group mono">
              <span class="param-title">// returns:</span>
              <pre><code>{`{
  "id": "2026-09-25-example-id",
  "state": "queued",
  "status_hint": "call get_episode(id) until state is done"
}`}</code></pre>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">get_episode</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">get episode status, metadata, duration, and audio url when done.</p>
            <div class="param-group mono">
              <span class="param-title">// arguments:</span>
              <ul class="param-list">
                <li><code>job_id: str</code>: unique job identifier returned by create_episode.</li>
              </ul>
            </div>
            <div class="param-group mono">
              <span class="param-title">// returns:</span>
              <pre><code>{`{
  "id": "2026-09-25-example-id",
  "state": "done",
  "title": "Why Compilers Matter",
  "duration_ms": 482000,
  "error": "",
  "audio_url": "http://127.0.0.1:8787/audio/2026-09-25-example-id.mp3"
}`}</code></pre>
            </div>
            <p class="sub-help mono">note: audio_url is only present when state equals "done".</p>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">list_episodes</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">list recent episodes with id, title, state, and created_at timestamp.</p>
            <div class="param-group mono">
              <span class="param-title">// arguments:</span>
              <ul class="param-list">
                <li><code>limit: int</code>: maximum episodes to return (default 10).</li>
              </ul>
            </div>
            <div class="param-group mono">
              <span class="param-title">// returns:</span>
              <pre><code>{`[
  {
    "id": "2026-09-25-example-id",
    "title": "Why Compilers Matter",
    "state": "done",
    "created_at": 1790322600
  }
]`}</code></pre>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">list_styles</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">list available dialogue styles with a one-line description each.</p>
            <div class="param-group mono">
              <span class="param-title">// returns:</span>
              <pre><code>{`[
  {"id": "balanced", "description": "Balanced tour: curious host, expert guest."},
  {"id": "debate", "description": "Sharp pro/contra from the same source; ends in shared ground."},
  {"id": "eli5", "description": "A five-year-old gets it wrong in creative ways; B fixes the picture, not the kid."}
]`}</code></pre>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">get_feed_url</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">get the rss podcast feed url containing all completed episodes.</p>
            <div class="param-group mono">
              <span class="param-title">// returns:</span>
              <pre><code>"http://127.0.0.1:8787/feed.xml"</code></pre>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">list_watchlists</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">list every watched feed with its schedule and status; use it to find a watchlist id.</p>
            <div class="param-group mono">
              <span class="param-title">// returns:</span>
              <pre><code>[&#123; id, feed_url, style, language, schedule, schedule_tz, enabled, last_checked &#125;]</code></pre>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">create_watchlist</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">watch an rss or atom feed so new articles become episodes on their own, one per article or bundled into a digest.</p>
            <div class="param-group mono">
              <span class="param-title">// arguments:</span>
              <ul class="param-list">
                <li><code>feed_url: str</code>: the feed to watch.</li>
                <li><code>style: str</code>: a style id from list_styles; default 'balanced'.</li>
                <li><code>language: str</code>: 'auto' or a language code.</li>
                <li><code>digest_mode / digest_count: int | null</code>: bundle entries into one digest episode and how many.</li>
                <li><code>schedule: str | null</code>: 'daily@HH:MM' or 'weekly@mon..sun@HH:MM'; none renders new entries as they arrive.</li>
                <li><code>schedule_tz: str</code>: IANA timezone, e.g. 'Europe/Berlin'; default 'UTC'.</li>
              </ul>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">set_watchlist_schedule</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">set or clear when a watched feed renders its digest episode.</p>
            <div class="param-group mono">
              <span class="param-title">// arguments:</span>
              <ul class="param-list">
                <li><code>watchlist_id: str</code>: id from list_watchlists or create_watchlist.</li>
                <li><code>schedule: str | null</code>: 'daily@HH:MM' or 'weekly@mon..sun@HH:MM'; none renders new entries as they arrive.</li>
                <li><code>schedule_tz: str</code>: IANA timezone, e.g. 'Europe/Berlin'; default 'UTC'.</li>
              </ul>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">check_watchlist</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">poll a watched feed right now and render new entries.</p>
            <div class="param-group mono">
              <span class="param-title">// arguments:</span>
              <ul class="param-list">
                <li><code>watchlist_id: str</code>: id from list_watchlists or create_watchlist.</li>
              </ul>
            </div>
            <div class="param-group mono">
              <span class="param-title">// returns:</span>
              <pre><code>&#123; checked: watchlist_id, created: [job_id, ...], error?: str &#125;</code></pre>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">render_digest</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">bundle the newest fresh entries of a feed into one episode now; needs at least two fresh entries (422 otherwise).</p>
            <div class="param-group mono">
              <span class="param-title">// arguments:</span>
              <ul class="param-list">
                <li><code>watchlist_id: str</code>: id from list_watchlists or create_watchlist.</li>
              </ul>
            </div>
          </div>

          <div class="tool-card">
            <div class="tool-head mono">
              <span class="tool-name">delete_watchlist</span>
              <span class="tool-kind">tool</span>
            </div>
            <p class="tool-desc">stop watching a feed; episodes already made stay.</p>
            <div class="param-group mono">
              <span class="param-title">// arguments:</span>
              <ul class="param-list">
                <li><code>watchlist_id: str</code>: id from list_watchlists or create_watchlist.</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">agent lifecycle flow</h3>
        <ol class="flow-steps mono">
          <li>
            <span class="step-num">1. create</span>
            <span class="step-desc">call <code>create_episode(...)</code> with url(s) or text. receive job id and state "queued".</span>
          </li>
          <li>
            <span class="step-num">2. poll</span>
            <span class="step-desc">poll <code>get_episode(job_id)</code> every 5-10s. states transition: queued → running → done (or failed).</span>
          </li>
          <li>
            <span class="step-num">3. audio</span>
            <span class="step-desc">once state is "done", extract <code>audio_url</code> for mp3 playback or download.</span>
          </li>
        </ol>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">webhook notifications (no polling)</h3>
        <p class="fact-body">
          agents invoking <code>POST /jobs</code> directly can provide a <code>callback_url</code>.
          upon completion (state "done" or "failed"), vozonda sends a POST to the callback url with the job json payload.
        </p>
        <p class="fact-body">
          when <code>VOZONDA_WEBHOOK_SECRET</code> is configured on the api server, the webhook request includes the
          header <code>X-Vozonda-Signature: sha256=&lt;hmac&gt;</code> computed using HMAC-SHA256 over the raw request body.
        </p>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">idempotency</h3>
        <p class="fact-body">
          on <code>POST /jobs</code>, include the <code>Idempotency-Key: &lt;unique-key&gt;</code> header (up to 200 characters).
          requests reusing the same key within 24 hours return the previously created job immediately, avoiding duplicate
          synthesis and duplicate billing deductions.
        </p>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">error codes</h3>
        <dl class="mono spec-dl">
          <div>
            <dt>402 Payment Required</dt>
            <dd>billing is enabled (VOZONDA_ENABLE_BILLING=true) and token is invalid or has insufficient funds. detail contains estimated price.</dd>
          </div>
          <div>
            <dt>422 Unprocessable Entity</dt>
            <dd>input validation failure: text under 20 chars, unreadable url, unknown style id, invalid format, or callback_url exceeding 2048 chars.</dd>
          </div>
          <div>
            <dt>404 Not Found</dt>
            <dd>requested job id does not exist in the database.</dd>
          </div>
        </dl>
      </div>

      <div class="sub-block">
        <h3 class="mono sub-title">machine-readable api references</h3>
        <p class="fact-body">
          agents can inspect endpoints directly via standard specification files:
        </p>
        <div class="links-row mono">
          <a href="/llms.txt" class="doc-link">
            <Icon name="file-text" size={14} />
            <span>/llms.txt (plain text documentation)</span>
          </a>
          <a href="/openapi.json" class="doc-link">
            <Icon name="link" size={14} />
            <span>/openapi.json (openapi 3.1 specification)</span>
          </a>
        </div>
      </div>
    </section>
  {/if}

  <div class="bottom-bar">
    <button type="button" class="link mono" onclick={onback}>
      <Icon name="back" size={13} />
      <span>back to compose</span>
    </button>
  </div>
</div>

<style>
  .agents-page {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
  }

  .top-nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-3);
    flex-wrap: wrap;
  }

  .back-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
  }

  .seg-wrap {
    display: inline-flex;
  }

  .seg {
    display: inline-flex;
    gap: 2px;
    align-items: center;
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid color-mix(in srgb, var(--ink) 14%, var(--line));
    border-radius: var(--radius);
    padding: 2px;
  }

  .seg button {
    background: transparent;
    border: 1px solid transparent;
    border-radius: calc(var(--radius) - 1px);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.88);
    font-weight: 500;
    min-height: 32px;
    padding: 3px var(--space-3);
    cursor: pointer;
    text-transform: lowercase;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: color var(--dur-fast) ease-out, background var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .seg button:hover:not(.sel):not([aria-checked="true"]) {
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 8%, var(--paper));
  }

  .seg button.sel {
    background: var(--green);
    color: var(--paper);
    border: 1px solid var(--green);
    font-weight: 600;
  }

  .scope-banner {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3) var(--space-4);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
    font-size: calc(var(--ui-size) * 0.85);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .scope-tag {
    color: var(--ink-soft);
  }

  .scope-text {
    margin: 0;
    color: var(--ink);
    line-height: 1.5;
  }

  .part-sec {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-5);
    background: color-mix(in srgb, var(--paper) 4%, transparent);
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    min-width: 0;
  }

  .sec-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-2);
    border-bottom: 1px solid var(--line);
    padding-bottom: var(--space-2);
    flex-wrap: wrap;
  }

  .sec-title {
    margin: 0;
    font-size: var(--h2-size);
    font-weight: var(--h2-weight);
    color: var(--ink);
    text-transform: lowercase;
  }

  .sec-tag {
    font-size: calc(var(--ui-size) * 0.82);
    color: var(--ink-soft);
  }

  .lede-copy {
    margin: 0;
    font-size: var(--lede-size);
    color: var(--ink);
    line-height: 1.6;
  }

  .sub-block {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }

  .sub-title {
    margin: 0;
    font-size: var(--ui-size);
    color: var(--ink);
    text-transform: lowercase;
    font-weight: 600;
  }

  .sub-help {
    margin: 0;
    font-size: calc(var(--ui-size) * 0.82);
    color: var(--ink-soft);
    line-height: 1.5;
  }

  .fact-body {
    margin: 0;
    font-size: calc(var(--ui-size) * 0.95);
    color: var(--ink);
    line-height: 1.6;
  }

  .client-tabs {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin-top: var(--space-1);
    min-width: 0;
  }

  .code-box {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    overflow: hidden;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
  }

  .code-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-1) var(--space-3);
    border-bottom: 1px solid var(--line);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    min-height: 36px;
    gap: var(--space-2);
  }

  .code-label {
    font-size: calc(var(--ui-size) * 0.8);
    color: var(--ink-soft);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .code-box pre {
    margin: 0;
    padding: var(--space-3);
    overflow-x: auto;
    max-width: 100%;
    box-sizing: border-box;
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.85);
    line-height: 1.45;
    color: var(--ink);
    white-space: pre;
  }

  .copy-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink-soft);
    font-family: var(--font-mono);
    font-size: calc(var(--ui-size) * 0.78);
    padding: 2px 8px;
    min-height: 28px;
    cursor: pointer;
    white-space: nowrap;
    transition: color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out, background var(--dur-fast) ease-out;
  }

  .copy-btn:hover {
    color: var(--green);
    border-color: var(--green);
    background: color-mix(in srgb, var(--green) 6%, transparent);
  }

  .copy-btn:focus-visible {
    outline: 2px solid var(--green);
    outline-offset: 2px;
  }

  .prompt-grid {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-top: var(--space-1);
  }

  .prompt-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    box-sizing: border-box;
  }

  .prompt-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .prompt-label {
    font-size: calc(var(--ui-size) * 0.75);
    color: var(--ink-soft);
  }

  .prompt-text {
    margin: 0;
    font-size: calc(var(--ui-size) * 0.88);
    color: var(--ink);
    word-break: break-word;
  }

  .tools-grid {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin-top: var(--space-1);
    min-width: 0;
  }

  .tool-card {
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: var(--space-3);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    box-sizing: border-box;
  }

  .tool-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-2);
    border-bottom: 1px solid color-mix(in srgb, var(--line) 60%, transparent);
    padding-bottom: 4px;
  }

  .tool-name {
    font-weight: 600;
    font-size: var(--ui-size);
    color: var(--green);
  }

  .tool-kind {
    font-size: calc(var(--ui-size) * 0.75);
    color: var(--ink-soft);
  }

  .tool-desc {
    margin: 0;
    font-size: calc(var(--ui-size) * 0.9);
    color: var(--ink);
    line-height: 1.5;
  }

  .param-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 2px;
    min-width: 0;
  }

  .param-title {
    font-size: calc(var(--ui-size) * 0.78);
    color: var(--ink-soft);
  }

  .param-list {
    margin: 0;
    padding-left: var(--space-3);
    font-size: calc(var(--ui-size) * 0.82);
    color: var(--ink);
    line-height: 1.5;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .param-list code {
    color: var(--ink);
    background: color-mix(in srgb, var(--ink) 6%, var(--paper));
    padding: 1px 4px;
    border-radius: var(--radius);
  }

  .tool-card pre {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    background: color-mix(in srgb, var(--ink) 4%, var(--paper));
    border: 1px solid var(--line);
    border-radius: var(--radius);
    overflow-x: auto;
    max-width: 100%;
    box-sizing: border-box;
    font-size: calc(var(--ui-size) * 0.82);
    color: var(--ink);
    line-height: 1.4;
  }

  .flow-steps {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .flow-steps li {
    display: flex;
    gap: var(--space-3);
    align-items: baseline;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
  }

  .step-num {
    color: var(--green);
    font-weight: 600;
    min-width: 5.5em;
    flex: none;
    font-size: calc(var(--ui-size) * 0.88);
  }

  .step-desc {
    color: var(--ink);
    font-size: calc(var(--ui-size) * 0.85);
    line-height: 1.5;
  }

  .spec-dl {
    margin: 0;
    display: grid;
    gap: var(--space-2);
  }

  .spec-dl div {
    display: flex;
    gap: var(--space-3);
    align-items: baseline;
  }

  .spec-dl dt {
    min-width: 13em;
    flex: none;
    color: var(--ink-soft);
    font-size: calc(var(--ui-size) * 0.85);
  }

  .spec-dl dd {
    margin: 0;
    color: var(--ink);
    font-size: calc(var(--ui-size) * 0.85);
    line-height: 1.5;
  }

  .spec-dl code {
    background: color-mix(in srgb, var(--ink) 6%, var(--paper));
    padding: 1px 4px;
    border-radius: var(--radius);
  }

  .links-row {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
    margin-top: var(--space-1);
  }

  .doc-link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    color: var(--ink);
    text-decoration: none;
    font-size: calc(var(--ui-size) * 0.85);
    background: color-mix(in srgb, var(--ink) 2%, var(--paper));
    transition: color var(--dur-fast) ease-out, border-color var(--dur-fast) ease-out;
  }

  .doc-link:hover {
    color: var(--green);
    border-color: var(--green);
  }

  .bottom-bar {
    padding-top: var(--space-3);
    border-top: 1px solid var(--line);
    display: flex;
    justify-content: flex-start;
  }

  .link {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: var(--ink-soft);
    text-decoration: underline;
    text-decoration-color: var(--line);
  }

  .link:hover {
    color: var(--green);
  }

  @media (max-width: 600px) {
    .part-sec {
      padding: var(--space-3);
      gap: var(--space-4);
    }
    .spec-dl div {
      flex-direction: column;
      gap: 2px;
      align-items: flex-start;
    }
    .spec-dl dt {
      min-width: 0;
    }
    .flow-steps li {
      flex-direction: column;
      gap: 4px;
    }
    .prompt-card {
      flex-direction: column;
      align-items: flex-start;
      gap: var(--space-2);
    }
    .prompt-card .copy-btn {
      align-self: flex-end;
    }
  }
</style>
