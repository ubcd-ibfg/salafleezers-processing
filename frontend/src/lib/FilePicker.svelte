<script lang="ts">
  import { session } from './stores/session.svelte'
  import { ApiError } from './api'

  let path = $state('')
  let opening = $state(false)
  let error = $state('')

  async function open() {
    if (!path.trim()) return
    opening = true
    error = ''
    try {
      await session.openFile(path.trim())
      path = ''
    } catch (e) {
      error = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)
    } finally {
      opening = false
    }
  }
</script>

<div class="card row">
  <label style="flex: 1; min-width: 240px;">
    File path (on server filesystem)
    <input
      type="text"
      bind:value={path}
      placeholder="/path/to/trace.dat"
      onkeydown={(e) => e.key === 'Enter' && open()}
    />
  </label>
  <button class="primary" onclick={open} disabled={opening || !path.trim()}>
    {opening ? 'Opening…' : 'Open file'}
  </button>

  {#if session.files.length}
    <label style="min-width: 220px;">
      Active file
      <select bind:value={session.activeFileId}>
        {#each session.files as f (f.file_id)}
          <option value={f.file_id}>{f.filename}</option>
        {/each}
      </select>
    </label>
  {/if}

  {#if error}<span class="muted" style="color: var(--danger)">{error}</span>{/if}
</div>
