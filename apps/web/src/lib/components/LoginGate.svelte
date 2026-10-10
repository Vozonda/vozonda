<script lang="ts">
  // Sign-in for a Vozonda reached from outside the host (through a reverse proxy, a VPN or the LAN), or one
  // with VOZONDA_TOKEN set. The token is exchanged once for an HttpOnly session cookie (POST /auth/session),
  // which the browser then sends with every request, the audio player and live updates included.
  // Local use without a token never shows this (GHSA-crq5-73gf-fv2h).
  import { onMount } from 'svelte'

  let open = $state(false)
  let token = $state('')
  let error = $state('')
  let busy = $state(false)
  let configured = $state(true)

  async function check() {
    try {
      const res = await fetch('/auth/session', { cache: 'no-store' })
      if (!res.ok) return
      const s = await res.json()
      configured = !!s.token_configured
      open = !!s.required && !s.authenticated
    } catch {
      /* API not reachable: the app shows its own error */
    }
  }

  async function signIn(event: SubmitEvent) {
    event.preventDefault()
    if (!token.trim()) return
    busy = true
    error = ''
    try {
      const res = await fetch('/auth/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token.trim() })
      })
      if (res.ok) {
        location.reload()
        return
      }
      error = res.status === 401 ? 'That token is not right.' : 'Sign-in failed; is the API running?'
    } catch {
      error = 'Sign-in failed; is the API running?'
    } finally {
      busy = false
    }
  }

  onMount(() => {
    check()
    // main.ts signals a 401 from any request (for example after VOZONDA_TOKEN changed)
    const onSignin = () => { open = true }
    window.addEventListener('vozonda:signin', onSignin)
    return () => window.removeEventListener('vozonda:signin', onSignin)
  })
</script>

{#if open}
  <div class="gate" role="dialog" aria-modal="true" aria-labelledby="gate-title">
    <form class="card" onsubmit={signIn}>
      <h2 id="gate-title">Sign in to Vozonda</h2>
      {#if configured}
        <p>This Vozonda is reached from outside its host, so it asks for its token
          (<code>VOZONDA_TOKEN</code> in <code>.env</code>). The browser remembers it for 30 days.</p>
        <label for="gate-token">Token</label>
        <!-- svelte-ignore a11y_autofocus -->
        <input id="gate-token" type="password" autocomplete="current-password" bind:value={token} autofocus />
        {#if error}<p class="err" role="alert">{error}</p>{/if}
        <button type="submit" disabled={busy || !token.trim()}>{busy ? 'Signing in…' : 'Sign in'}</button>
      {:else}
        <p>This Vozonda is reached from outside its host but has no token, so it stays locked.
          Set <code>VOZONDA_TOKEN</code> in <code>.env</code>, restart it (<code>docker compose up -d</code>)
          and reload this page.</p>
      {/if}
    </form>
  </div>
{/if}

<style>
  .gate {
    position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: var(--space-4);
    background: color-mix(in srgb, var(--paper) 88%, transparent); backdrop-filter: blur(4px);
  }
  .card {
    width: min(440px, 100%); display: grid; gap: var(--space-3); padding: var(--space-5);
    background: var(--paper); color: var(--ink); border: 1px solid var(--line); border-radius: var(--radius);
  }
  h2 { margin: 0; font-size: 1.25rem; }
  p { margin: 0; color: var(--ink-soft); line-height: 1.5; }
  label { font: 600 var(--ui-size) var(--font-mono); }
  input {
    font: var(--ui-size) var(--font-mono); padding: var(--space-2) var(--space-3); color: var(--ink);
    background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius);
  }
  button {
    justify-self: start; font: 600 var(--ui-size) var(--font-mono); padding: var(--space-2) var(--space-4);
    color: var(--paper); background: var(--ink); border: 0; border-radius: var(--radius); cursor: pointer;
  }
  button:disabled { opacity: 0.5; cursor: default; }
  .err { color: var(--red, #b42318); }
  code { font-family: var(--font-mono); }
</style>
