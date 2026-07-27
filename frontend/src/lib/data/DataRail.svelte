<script lang="ts">
  import { onMount } from 'svelte'
  import Dropzone from './Dropzone.svelte'
  import UploadProgress from './UploadProgress.svelte'
  import { datasets } from './datasets.svelte'
  import { session } from '../stores/session.svelte'
  import { formatBytes } from '../format'
  import type { Dataset, UploadEntry } from '../types'

  const ROWS_PER_PAGE = 100

  let collapsed = $state<Set<string>>(new Set())
  let selected = $state<Set<string>>(new Set())
  let visibleCount = $state<Record<string, number>>({})
  let opening = $state<string | null>(null)
  let openError = $state('')

  onMount(() => {
    datasets.refresh()
  })

  function toggleCollapsed(id: string) {
    const s = new Set(collapsed)
    s.has(id) ? s.delete(id) : s.add(id)
    collapsed = s
  }

  function key(datasetId: string, relativePath: string): string {
    return `${datasetId}::${relativePath}`
  }

  function toggleSelected(k: string) {
    const s = new Set(selected)
    s.has(k) ? s.delete(k) : s.add(k)
    selected = s
  }

  function traces(ds: Dataset): UploadEntry[] {
    return ds.entries.filter((e) => e.kind === 'trace')
  }

  function sidecarBadges(entry: UploadEntry): string[] {
    const badges: string[] = []
    for (const s of entry.sidecars) {
      const stem = s.replace(/\.dat$/i, '')
      if (stem.endsWith('_pos')) badges.push('pos')
      else if (stem.endsWith('_fl')) badges.push('fl')
      else if (stem.endsWith('_grn')) badges.push('grn')
    }
    return badges
  }

  function baseName(path: string): string {
    return path.split('/').pop() ?? path
  }

  async function openTrace(ds: Dataset, entry: UploadEntry) {
    opening = key(ds.dataset_id, entry.relative_path)
    openError = ''
    try {
      await session.openFile({ datasetId: ds.dataset_id, relativePath: entry.relative_path })
    } catch (e) {
      openError = e instanceof Error ? e.message : String(e)
    } finally {
      opening = null
    }
  }

  async function openSelected() {
    openError = ''
    for (const k of Array.from(selected)) {
      const [datasetId, ...rest] = k.split('::')
      const relativePath = rest.join('::')
      opening = k
      try {
        await session.openFile({ datasetId, relativePath })
      } catch (e) {
        openError = e instanceof Error ? e.message : String(e)
      }
    }
    opening = null
    selected = new Set()
  }

  async function removeDataset(id: string) {
    await datasets.remove(id)
  }

  function shownEntries(ds: Dataset): UploadEntry[] {
    const all = traces(ds)
    const n = visibleCount[ds.dataset_id] ?? ROWS_PER_PAGE
    return all.slice(0, n)
  }

  function showMore(id: string, total: number) {
    visibleCount = { ...visibleCount, [id]: Math.min(total, (visibleCount[id] ?? ROWS_PER_PAGE) + ROWS_PER_PAGE) }
  }
</script>

<aside class="rail stack">
  <Dropzone compact={datasets.datasets.length > 0} />
  <UploadProgress />

  {#if openError}<p class="text-danger" style="margin: 0; font-size: var(--text-xs);">{openError}</p>{/if}

  {#if selected.size}
    <button class="primary" onclick={openSelected} disabled={opening != null}>
      Open {selected.size} selected
    </button>
  {/if}

  {#if datasets.error}
    <p class="text-danger" style="font-size: var(--text-xs);">{datasets.error}</p>
  {/if}

  {#each datasets.datasets as ds (ds.dataset_id)}
    {@const entries = traces(ds)}
    {@const shown = shownEntries(ds)}
    <div class="dataset">
      <button class="dataset-head" onclick={() => toggleCollapsed(ds.dataset_id)}>
        <span class="disclosure">{collapsed.has(ds.dataset_id) ? '▸' : '▾'}</span>
        <span class="dataset-name">{ds.name}</span>
        <span class="dim mono" style="font-size: var(--text-2xs);">{formatBytes(ds.total_bytes)}</span>
      </button>
      {#if !collapsed.has(ds.dataset_id)}
        <div class="dataset-body">
          {#each shown as entry (entry.relative_path)}
            {@const k = key(ds.dataset_id, entry.relative_path)}
            <div class="entry-row" class:opening={opening === k}>
              <input
                type="checkbox"
                checked={selected.has(k)}
                onchange={() => toggleSelected(k)}
                aria-label={`Select ${entry.relative_path}`}
              />
              <button class="entry-open" onclick={() => openTrace(ds, entry)} disabled={opening === k}>
                <span class="mono entry-name">{baseName(entry.relative_path)}</span>
                <span class="dim mono" style="font-size: var(--text-2xs);">{formatBytes(entry.size_bytes)}</span>
                {#each sidecarBadges(entry) as b (b)}
                  <span class="badge">{b}</span>
                {/each}
                {#if entry.missing_sidecars.length}
                  <span class="warn-dot" title={entry.warning ?? ''}>●</span>
                {/if}
              </button>
            </div>
          {/each}
          {#if shown.length < entries.length}
            <button class="ghost show-more" onclick={() => showMore(ds.dataset_id, entries.length)}>
              Show {Math.min(ROWS_PER_PAGE, entries.length - shown.length)} more ({entries.length - shown.length} left)
            </button>
          {/if}
          {#if entries.length === 0}
            <p class="dim" style="font-size: var(--text-xs); padding: var(--s-1) var(--s-2);">
              No openable traces in this upload.
            </p>
          {/if}
          <button class="ghost delete-dataset" onclick={() => removeDataset(ds.dataset_id)}>Delete dataset</button>
        </div>
      {/if}
    </div>
  {/each}
</aside>

<style>
  .rail {
    width: var(--rail-width);
    flex: 0 0 var(--rail-width);
    overflow-y: auto;
  }

  @media (max-width: 1000px) {
    .rail {
      width: 100%;
      flex: 0 0 auto;
      max-height: 300px;
    }
  }

  .dataset {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg-elev);
  }

  .dataset-head {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--s-2);
    background: transparent;
    border: none;
    border-radius: var(--radius);
    padding: var(--s-2);
    text-align: left;
  }

  .disclosure {
    color: var(--text-dim);
    width: 1em;
  }

  .dataset-name {
    flex: 1;
    font-weight: 600;
    font-size: var(--text-sm);
    color: var(--text-h);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .dataset-body {
    border-top: 1px solid var(--border);
    padding: var(--s-1);
    /* Skip layout/paint for offscreen rows -- the cheap alternative to a
       hand-rolled virtual scroller for a folder drop of hundreds of files. */
    content-visibility: auto;
    contain-intrinsic-size: 28px;
  }

  .entry-row {
    display: flex;
    align-items: center;
    gap: var(--s-1);
    padding: 2px 0;
  }

  .entry-row.opening {
    opacity: 0.6;
  }

  .entry-open {
    flex: 1;
    display: flex;
    align-items: center;
    gap: var(--s-1);
    background: transparent;
    border: none;
    padding: 3px 4px;
    border-radius: var(--radius-sm);
    text-align: left;
    min-width: 0;
  }

  .entry-open:hover {
    background: var(--bg-panel);
    border-color: transparent;
  }

  .entry-name {
    flex: 1;
    font-size: var(--text-xs);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .badge {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 1px 4px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-strong);
    color: var(--text-dim);
  }

  .warn-dot {
    color: var(--warn);
    font-size: 10px;
    cursor: help;
  }

  .show-more,
  .delete-dataset {
    display: block;
    width: 100%;
    text-align: left;
    font-size: var(--text-2xs);
    color: var(--text-dim);
    margin-top: 2px;
  }
</style>
