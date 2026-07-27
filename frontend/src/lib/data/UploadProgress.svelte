<script lang="ts">
  import { uploadQueue } from './uploadQueue.svelte'
  import { formatBytes } from '../format'
</script>

{#if uploadQueue.items.length}
  <div class="card">
    <div class="row-center" style="justify-content: space-between;">
      <span class="label">
        {#if uploadQueue.active}Uploading…{:else if uploadQueue.finalizing}Finalizing…{:else}Upload complete{/if}
      </span>
      {#if uploadQueue.active}
        <button class="ghost" onclick={() => uploadQueue.cancel()}>Cancel</button>
      {:else}
        <button class="ghost" onclick={() => uploadQueue.dismiss()}>Dismiss</button>
      {/if}
    </div>
    <div class="stack">
      <div class="progress-track">
        <div class="progress-fill" style="width: {(uploadQueue.progress * 100).toFixed(1)}%"></div>
      </div>
      <p class="dim mono" style="font-size: var(--text-xs); margin: 0;">
        {uploadQueue.doneCount} / {uploadQueue.total} files · {formatBytes(uploadQueue.loadedBytes)} / {formatBytes(
          uploadQueue.totalBytes,
        )}
        {#if uploadQueue.errorCount}
          · <span class="text-danger">{uploadQueue.errorCount} failed</span>
        {/if}
      </p>
      {#if uploadQueue.error}<p class="text-danger" style="margin: 0;">{uploadQueue.error}</p>{/if}
      {#each uploadQueue.items as item, i (item.relativePath)}
        {#if item.status === 'error'}
          <div class="row-center" style="font-size: var(--text-xs);">
            <span class="mono">{item.relativePath}</span>
            <span class="text-danger">{item.error}</span>
            <button class="ghost" onclick={() => uploadQueue.retry(i)}>Retry</button>
          </div>
        {/if}
      {/each}
    </div>
  </div>
{/if}

<style>
  .progress-track {
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: var(--accent);
    transition: width 120ms ease-out;
  }
</style>
