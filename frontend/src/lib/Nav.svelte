<script lang="ts">
  import { session } from './stores/session.svelte'
  import { theme } from './stores/theme.svelte'

  let { view = $bindable() }: { view: 'trace' | 'force-ext' } = $props()

  let saveMsg = $state('')

  async function handleSave() {
    saveMsg = 'saving…'
    try {
      const res = await session.saveSession()
      saveMsg = res ? `saved to ${res.saved_to}` : ''
    } catch (e) {
      saveMsg = e instanceof Error ? e.message : String(e)
    }
    setTimeout(() => (saveMsg = ''), 4000)
  }
</script>

<nav>
  <div class="brand">
    <img src="/logo.png" alt="SalaFleezer logo" class="brand-logo" />
    SalaFleezer
  </div>

  <div class="tabs">
    <button class:active={view === 'trace'} onclick={() => (view = 'trace')}>Trace Viewer</button>
    <button class:active={view === 'force-ext'} onclick={() => (view = 'force-ext')}>
      Force-Extension
    </button>
  </div>

  <div class="spacer"></div>

  {#if session.sessionId}
    <span class="session-id mono muted" title={session.sessionId}>
      session {session.sessionId.slice(0, 8)}
    </span>
  {/if}
  <button onclick={handleSave} disabled={!session.sessionId}>Save session</button>
  {#if saveMsg}<span class="muted">{saveMsg}</span>{/if}
  <button onclick={() => theme.toggle()} title="Toggle theme (t)">
    {theme.current === 'dark' ? '☀' : '☾'}
  </button>
  <span
    class="muted shortcuts"
    title="1/2 switch view · t theme · ⌘/Ctrl+S save session · in Trace Viewer: drag to select, z zoom, c crop, m measure, 0 reset, ⌘/Ctrl+Z undo, ⌘/Ctrl+Shift+Z redo"
  >
    ⌨
  </span>
</nav>

<style>
  nav {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-panel);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    color: var(--text-h);
  }
  .brand-logo {
    width: 24px;
    height: 24px;
    border-radius: 4px;
  }
  .tabs {
    display: flex;
    gap: 4px;
  }
  .tabs button.active {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }
  .spacer {
    flex: 1;
  }
  .session-id {
    font-size: 12px;
  }
  .shortcuts {
    cursor: help;
    font-size: 16px;
  }
</style>
