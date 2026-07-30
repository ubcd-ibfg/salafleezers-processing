<script lang="ts">
  import DataRail from './data/DataRail.svelte'
  import Home from './Home.svelte'
  import TraceViewer from './TraceViewer.svelte'
  import CalibrationViewer from './CalibrationViewer.svelte'
  import ForceExtensionViewer from './ForceExtensionViewer.svelte'
  import { session } from './stores/session.svelte'
  import { theme } from './stores/theme.svelte'
  import { BASE_PATH } from './api'

  let { view = $bindable() }: { view: 'home' | 'trace' | 'calibrate' | 'force-ext' } = $props()

  let saveMsg = $state('')
  let showShortcuts = $state(false)

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

<header class="topbar">
  <button class="brand" onclick={() => (view = 'home')} title="Home (`)">
    <img src="{BASE_PATH}/logo.png" alt="SalaFleezer logo" class="brand-logo" />
    SalaFleezer
  </button>

  <div class="tabs">
    <button class:active={view === 'home'} onclick={() => (view = 'home')}>Home</button>
    <button class:active={view === 'trace'} onclick={() => (view = 'trace')}>Trace Viewer</button>
    <button class:active={view === 'calibrate'} onclick={() => (view = 'calibrate')}>Calibration</button>
    <button class:active={view === 'force-ext'} onclick={() => (view = 'force-ext')}>Force-Extension</button>
  </div>

  <div class="spacer"></div>

  {#if session.sessionId}
    <span class="dim mono" style="font-size: var(--text-xs);" title={session.sessionId}>
      session {session.sessionId.slice(0, 8)}
    </span>
  {/if}
  <button onclick={handleSave} disabled={!session.sessionId}>Save session</button>
  {#if saveMsg}<span class="dim" style="font-size: var(--text-xs);">{saveMsg}</span>{/if}
  <button class="ghost" onclick={() => theme.toggle()} title="Toggle theme (t)">
    {theme.current === 'dark' ? '☀' : '☾'}
  </button>
  <button class="ghost" onclick={() => (showShortcuts = !showShortcuts)} title="Keyboard shortcuts">?</button>
</header>

{#if showShortcuts}
  <div
    class="shortcuts-backdrop"
    role="presentation"
    onclick={() => (showShortcuts = false)}
    onkeydown={(e) => e.key === 'Escape' && (showShortcuts = false)}
  >
    <div
      class="card shortcuts-panel"
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      tabindex="-1"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.key === 'Escape' && (showShortcuts = false)}
    >
      <div class="row-center" style="justify-content: space-between;">
        <span class="label">Keyboard shortcuts</span>
        <button class="ghost" onclick={() => (showShortcuts = false)}>Close</button>
      </div>
      <dl class="stack mono" style="font-size: var(--text-sm); margin-top: var(--s-2);">
        <div class="shortcut-row"><dt>`</dt><dd>home</dd></div>
        <div class="shortcut-row"><dt>1 / 2 / 3</dt><dd>switch view</dd></div>
        <div class="shortcut-row"><dt>t</dt><dd>toggle theme</dd></div>
        <div class="shortcut-row"><dt>⌘/Ctrl + S</dt><dd>save session</dd></div>
        <div class="shortcut-row"><dt>drag</dt><dd>select a range on the trace plot</dd></div>
        <div class="shortcut-row"><dt>z</dt><dd>zoom to selection</dd></div>
        <div class="shortcut-row"><dt>c</dt><dd>crop to selection</dd></div>
        <div class="shortcut-row"><dt>m</dt><dd>measure selection</dd></div>
        <div class="shortcut-row"><dt>0</dt><dd>reset view</dd></div>
        <div class="shortcut-row"><dt>⌘/Ctrl + Z</dt><dd>undo view</dd></div>
        <div class="shortcut-row"><dt>⌘/Ctrl + Shift + Z</dt><dd>redo view</dd></div>
      </dl>
    </div>
  </div>
{/if}

{#if view === 'home'}
  <Home onNavigate={(v) => (view = v)} />
{:else}
  <div class="body">
    <DataRail />
    <main class="canvas">
      {#if view === 'trace'}
        <TraceViewer />
      {:else if view === 'calibrate'}
        <CalibrationViewer onNavigate={(v) => (view = v)} />
      {:else}
        <ForceExtensionViewer />
      {/if}
    </main>
  </div>
{/if}

<style>
  .topbar {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    padding: var(--s-2) var(--s-4);
    border-bottom: 1px solid var(--border);
    background: var(--bg-elev);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: var(--s-2);
    font-weight: 600;
    color: var(--text-h);
    white-space: nowrap;
    background: transparent;
    border: 1px solid transparent;
    padding: var(--s-1) var(--s-2);
  }
  .brand:hover {
    border-color: var(--border);
  }
  .brand-logo {
    width: 22px;
    height: 22px;
    border-radius: var(--radius-sm);
  }
  .spacer {
    flex: 1;
  }

  .body {
    flex: 1;
    display: flex;
    gap: var(--s-3);
    padding: var(--s-3) var(--s-4);
    min-height: 0;
    align-items: start;
  }
  .canvas {
    flex: 1;
    min-width: 0;
  }

  .shortcuts-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
  }
  .shortcuts-panel {
    width: min(420px, 90vw);
  }
  .shortcut-row {
    display: flex;
    justify-content: space-between;
    gap: var(--s-3);
  }
  .shortcut-row dt {
    color: var(--text-h);
  }
  .shortcut-row dd {
    margin: 0;
    color: var(--text-dim);
  }

  @media (max-width: 1000px) {
    .body {
      flex-direction: column;
    }
  }
</style>
