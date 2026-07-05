<script lang="ts">
  import type uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import { api, ApiError } from '../api'
  import { session } from '../stores/session.svelte'
  import type { ViolinGroup } from '../types'

  const PALETTE = ['#7c3aed', '#059669', '#d97706', '#dc2626', '#2563eb', '#0891b2']
  const GRID_POINTS = 256

  let selectedFiles = $state<string[]>([])
  let channel = $state('extension')
  let bandwidth = $state('scott')
  let running = $state(false)
  let error = $state('')
  let groups = $state<ViolinGroup[]>([])

  $effect(() => {
    if (session.activeFileId && !selectedFiles.length) {
      selectedFiles = [session.activeFileId]
    }
  })

  function toggleFile(fileId: string) {
    selectedFiles = selectedFiles.includes(fileId)
      ? selectedFiles.filter((id) => id !== fileId)
      : [...selectedFiles, fileId]
  }

  async function run() {
    if (!selectedFiles.length) {
      error = 'Select at least one file'
      return
    }
    running = true
    error = ''
    try {
      const bwValue = bandwidth === 'scott' || bandwidth === 'silverman' ? bandwidth : Number(bandwidth)
      const r = await api.violin({
        session_id: session.sessionId!,
        file_ids: selectedFiles,
        channel,
        bandwidth: bwValue,
      })
      groups = r.groups
    } catch (e) {
      error = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)
    } finally {
      running = false
    }
  }

  function interpOrZero(xq: number, xs: number[], ys: number[]): number {
    const n = xs.length
    if (n === 0 || xq < xs[0] || xq > xs[n - 1]) return 0
    let lo = 0
    let hi = n - 1
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1
      if (xs[mid] <= xq) lo = mid
      else hi = mid
    }
    const x0 = xs[lo]
    const x1 = xs[hi]
    const y0 = ys[lo]
    const y1 = ys[hi]
    if (x1 === x0) return y0
    return y0 + ((y1 - y0) * (xq - x0)) / (x1 - x0)
  }

  let sharedX = $derived.by((): number[] => {
    if (!groups.length) return []
    const min = Math.min(...groups.map((g) => g.x[0]))
    const max = Math.max(...groups.map((g) => g.x[g.x.length - 1]))
    return Array.from({ length: GRID_POINTS }, (_, i) => min + ((max - min) * i) / (GRID_POINTS - 1))
  })

  let plotData = $derived.by((): uPlot.AlignedData => {
    const x = sharedX
    return [x, ...groups.map((g) => x.map((xq) => interpOrZero(xq, g.x, g.density)))] as uPlot.AlignedData
  })

  let plotSeries = $derived.by((): uPlot.Series[] => [
    {},
    ...groups.map((g, i) => ({ label: g.label, stroke: PALETTE[i % PALETTE.length], width: 1.5, points: { show: false } })),
  ])
</script>

<div class="row">
  <div>
    <span class="muted" style="display:block; font-size:12px;">Files (one density curve each)</span>
    <div class="row" style="gap:6px;">
      {#each session.files as f (f.file_id)}
        <label style="flex-direction: row; align-items: center; gap: 4px;">
          <input type="checkbox" checked={selectedFiles.includes(f.file_id)} onchange={() => toggleFile(f.file_id)} />
          {f.filename}
        </label>
      {/each}
    </div>
  </div>
  <label>
    Channel
    <select bind:value={channel}>
      {#each session.activeFile?.channels ?? [] as ch (ch)}
        <option value={ch}>{ch}</option>
      {/each}
    </select>
  </label>
  <label>
    Bandwidth
    <select bind:value={bandwidth}>
      <option value="scott">Scott</option>
      <option value="silverman">Silverman</option>
    </select>
  </label>
  <button class="primary" onclick={run} disabled={running}>{running ? 'Running…' : 'Compare distributions'}</button>
  {#if error}<span style="color: var(--danger)">{error}</span>{/if}
</div>

{#if groups.length}
  <div style="margin-top:8px;">
    <Plot data={plotData} series={plotSeries} height={240} cursor={false} />
  </div>
  <table class="mono" style="margin-top:8px; width:100%; border-collapse: collapse; font-size:12px;">
    <thead>
      <tr>
        <th style="text-align:left;">file</th>
        <th>n</th>
        <th>median</th>
        <th>Q25</th>
        <th>Q75</th>
        <th>whisker lo</th>
        <th>whisker hi</th>
      </tr>
    </thead>
    <tbody>
      {#each groups as g (g.label)}
        <tr>
          <td>{g.label}</td>
          <td>{g.n}</td>
          <td>{g.median.toFixed(3)}</td>
          <td>{g.quartile_25.toFixed(3)}</td>
          <td>{g.quartile_75.toFixed(3)}</td>
          <td>{g.whisker_lo.toFixed(3)}</td>
          <td>{g.whisker_hi.toFixed(3)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<style>
  th,
  td {
    padding: 3px 8px;
    border-bottom: 1px solid var(--border);
    text-align: right;
  }
</style>
