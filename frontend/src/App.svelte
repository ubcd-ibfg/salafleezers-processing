<script lang="ts">
  import { onMount } from 'svelte'
  import Nav from './lib/Nav.svelte'
  import FilePicker from './lib/FilePicker.svelte'
  import TraceViewer from './lib/TraceViewer.svelte'
  import ForceExtensionViewer from './lib/ForceExtensionViewer.svelte'
  import { session } from './lib/stores/session.svelte'
  import { theme } from './lib/stores/theme.svelte'

  let view = $state<'trace' | 'force-ext'>('trace')

  function isTyping(target: EventTarget | null): boolean {
    const el = target as HTMLElement | null
    return !!el && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
  }

  function handleKeydown(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault()
      session.saveSession()
      return
    }
    if (isTyping(e.target)) return
    if (e.key === 't') theme.toggle()
    else if (e.key === '1') view = 'trace'
    else if (e.key === '2') view = 'force-ext'
  }

  onMount(() => {
    theme.apply()
    session.init()
    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  })
</script>

<Nav bind:view />

<main>
  {#if session.status === 'connecting'}
    <p class="muted">Connecting…</p>
  {:else if session.status === 'error'}
    <p style="color: var(--danger)">{session.errorMessage}</p>
  {:else}
    <FilePicker />
    <div style="margin-top: 12px;">
      {#if view === 'trace'}
        <TraceViewer />
      {:else}
        <ForceExtensionViewer />
      {/if}
    </div>
  {/if}
</main>

<style>
  main {
    flex: 1;
    padding: 16px;
    max-width: 1200px;
    width: 100%;
    margin: 0 auto;
    box-sizing: border-box;
  }
</style>
