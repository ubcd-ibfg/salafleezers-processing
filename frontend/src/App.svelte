<script lang="ts">
  import { onMount } from 'svelte'
  import AppShell from './lib/AppShell.svelte'
  import AuthGate from './lib/AuthGate.svelte'
  import { api } from './lib/api'
  import { auth } from './lib/stores/auth.svelte'
  import { session } from './lib/stores/session.svelte'
  import { theme } from './lib/stores/theme.svelte'

  let view = $state<'home' | 'trace' | 'calibrate' | 'force-ext'>('home')

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
    else if (e.key === '`') view = 'home'
    else if (e.key === '1') view = 'trace'
    else if (e.key === '2') view = 'calibrate'
    else if (e.key === '3') view = 'force-ext'
  }

  async function boot() {
    try {
      const health = await api.health()
      auth.required = health.auth_required
    } catch {
      // Health check itself failed (server unreachable) -- session.init()
      // below makes the same call and surfaces a real error message.
    }
    if (!auth.required || auth.token) {
      await session.init()
    }
  }

  function connectWithToken(token: string) {
    auth.setToken(token)
    session.init()
  }

  onMount(() => {
    theme.apply()
    boot()
    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  })
</script>

{#if auth.required && !auth.token}
  <main class="gate">
    <AuthGate onSubmit={connectWithToken} />
  </main>
{:else if session.status === 'idle' || session.status === 'connecting'}
  <main class="gate"><p class="muted">Connecting…</p></main>
{:else if session.status === 'error'}
  <main class="gate">
    {#if auth.required}
      <AuthGate error={session.errorMessage} onSubmit={connectWithToken} />
    {:else}
      <p style="color: var(--danger)">{session.errorMessage}</p>
    {/if}
  </main>
{:else}
  <AppShell bind:view />
{/if}

<style>
  .gate {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--s-4);
  }
</style>
