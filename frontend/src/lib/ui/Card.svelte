<script lang="ts">
  import type { Snippet } from 'svelte'

  let {
    title,
    meta,
    children,
  }: {
    title?: string
    meta?: Snippet
    children?: Snippet
  } = $props()
</script>

<div class="card">
  {#if title || meta}
    <div class="card-head">
      {#if title}<span class="label">{title}</span>{/if}
      {#if meta}<span class="dim mono" style="font-size: var(--text-xs);">{@render meta()}</span>{/if}
    </div>
  {/if}
  {@render children?.()}
</div>

<style>
  .card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--s-2);
  }
</style>
