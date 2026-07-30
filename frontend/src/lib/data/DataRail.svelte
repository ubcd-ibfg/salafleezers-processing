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
  let collapsedFolders = $state<Set<string>>(new Set())
  let selected = $state<Set<string>>(new Set())
  let visibleCount = $state<Record<string, number>>({})
  let opening = $state<string | null>(null)
  let openError = $state('')
  let deleting = $state<string | null>(null)
  let deleteError = $state('')

  onMount(() => {
    datasets.refresh()
  })

  function toggleCollapsed(id: string) {
    const s = new Set(collapsed)
    s.has(id) ? s.delete(id) : s.add(id)
    collapsed = s
  }

  function toggleFolderCollapsed(k: string) {
    const s = new Set(collapsedFolders)
    s.has(k) ? s.delete(k) : s.add(k)
    collapsedFolders = s
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

  interface FolderGroup {
    folder: string   // '' for entries at the dataset's top level
    entries: UploadEntry[]
  }

  function folderOf(relativePath: string): string {
    const idx = relativePath.lastIndexOf('/')
    return idx === -1 ? '' : relativePath.slice(0, idx)
  }

  /** Groups a dataset's traces by their parent subfolder, top level first. */
  function folderGroups(ds: Dataset): FolderGroup[] {
    const order: string[] = []
    const byFolder = new Map<string, UploadEntry[]>()
    for (const entry of traces(ds)) {
      const folder = folderOf(entry.relative_path)
      if (!byFolder.has(folder)) {
        byFolder.set(folder, [])
        order.push(folder)
      }
      byFolder.get(folder)!.push(entry)
    }
    order.sort((a, b) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b)))
    return order.map((folder) => ({ folder, entries: byFolder.get(folder)! }))
  }

  function groupBytes(group: FolderGroup): number {
    return group.entries.reduce((s, e) => s + e.size_bytes, 0)
  }

  /** Removes stale selection/pagination state for a dataset after an entry is deleted. */
  function pruneAfterDelete(ds: Dataset) {
    const valid = new Set(ds.entries.map((e) => key(ds.dataset_id, e.relative_path)))
    selected = new Set(
      Array.from(selected).filter((k) => !k.startsWith(`${ds.dataset_id}::`) || valid.has(k)),
    )
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

  async function removeEntry(ds: Dataset, entry: UploadEntry) {
    if (!confirm(`Delete "${baseName(entry.relative_path)}"?`)) return
    const k = key(ds.dataset_id, entry.relative_path)
    deleteError = ''
    deleting = k
    try {
      const updated = await datasets.removeEntry(ds.dataset_id, entry.relative_path)
      pruneAfterDelete(updated)
    } catch (e) {
      deleteError = e instanceof Error ? e.message : String(e)
    } finally {
      deleting = null
    }
  }

  async function removeFolder(ds: Dataset, folder: string) {
    if (!confirm(`Delete folder "${folder}" and everything inside it?`)) return
    const k = key(ds.dataset_id, folder)
    deleteError = ''
    deleting = k
    try {
      const updated = await datasets.removeEntry(ds.dataset_id, folder)
      pruneAfterDelete(updated)
    } catch (e) {
      deleteError = e instanceof Error ? e.message : String(e)
    } finally {
      deleting = null
    }
  }

  function shownEntries(ds: Dataset, group: FolderGroup): UploadEntry[] {
    const n = visibleCount[key(ds.dataset_id, group.folder)] ?? ROWS_PER_PAGE
    return group.entries.slice(0, n)
  }

  function showMore(ds: Dataset, group: FolderGroup) {
    const k = key(ds.dataset_id, group.folder)
    visibleCount = {
      ...visibleCount,
      [k]: Math.min(group.entries.length, (visibleCount[k] ?? ROWS_PER_PAGE) + ROWS_PER_PAGE),
    }
  }
</script>

<aside class="rail stack">
  <Dropzone compact={datasets.datasets.length > 0} />
  <UploadProgress />

  {#if openError}<p class="text-danger" style="margin: 0; font-size: var(--text-xs);">{openError}</p>{/if}
  {#if deleteError}<p class="text-danger" style="margin: 0; font-size: var(--text-xs);">{deleteError}</p>{/if}

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
    {@const groups = folderGroups(ds)}
    <div class="dataset">
      <button class="dataset-head" onclick={() => toggleCollapsed(ds.dataset_id)}>
        <span class="disclosure">{collapsed.has(ds.dataset_id) ? '▸' : '▾'}</span>
        <span class="dataset-name">{ds.name}</span>
        <span class="dim mono" style="font-size: var(--text-2xs);">{formatBytes(ds.total_bytes)}</span>
      </button>
      {#if !collapsed.has(ds.dataset_id)}
        <div class="dataset-body">
          {#each groups as group (group.folder)}
            {@const fk = key(ds.dataset_id, group.folder)}
            {@const shown = shownEntries(ds, group)}
            {#if group.folder}
              <div class="folder-head">
                <button class="folder-disclosure" onclick={() => toggleFolderCollapsed(fk)}>
                  <span class="disclosure">{collapsedFolders.has(fk) ? '▸' : '▾'}</span>
                  <span class="mono folder-name" title={group.folder}>{baseName(group.folder)}</span>
                  <span class="dim mono" style="font-size: var(--text-2xs);">{formatBytes(groupBytes(group))}</span>
                </button>
                <button
                  class="ghost folder-delete"
                  onclick={() => removeFolder(ds, group.folder)}
                  disabled={deleting === fk}
                  aria-label={`Delete folder ${group.folder}`}
                  title="Delete folder"
                >✕</button>
              </div>
            {/if}
            {#if !group.folder || !collapsedFolders.has(fk)}
              <div class="folder-body" class:indented={!!group.folder}>
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
                    <button
                      class="ghost entry-delete"
                      onclick={() => removeEntry(ds, entry)}
                      disabled={deleting === k}
                      aria-label={`Delete ${entry.relative_path}`}
                      title="Delete file"
                    >✕</button>
                  </div>
                {/each}
                {#if shown.length < group.entries.length}
                  <button class="ghost show-more" onclick={() => showMore(ds, group)}>
                    Show {Math.min(ROWS_PER_PAGE, group.entries.length - shown.length)} more ({group.entries.length - shown.length} left)
                  </button>
                {/if}
              </div>
            {/if}
          {/each}
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

  .entry-delete,
  .folder-delete {
    flex: 0 0 auto;
    background: transparent;
    border: none;
    padding: 3px 6px;
    font-size: var(--text-2xs);
    color: var(--text-dim);
    border-radius: var(--radius-sm);
  }

  .entry-delete:hover,
  .folder-delete:hover {
    color: var(--danger);
    background: var(--bg-panel);
  }

  .folder-head {
    display: flex;
    align-items: center;
    gap: var(--s-1);
    margin-top: 2px;
  }

  .folder-disclosure {
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

  .folder-disclosure:hover {
    background: var(--bg-panel);
    border-color: transparent;
  }

  .folder-name {
    flex: 1;
    font-size: var(--text-xs);
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .folder-body.indented {
    padding-left: var(--s-3);
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
