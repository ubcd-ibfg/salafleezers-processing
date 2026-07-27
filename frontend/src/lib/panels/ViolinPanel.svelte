<script lang="ts">
  import type uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import RunButton from '../ui/RunButton.svelte'
  import { api } from '../api'
  import { session } from '../stores/session.svelte'
  import { theme } from '../stores/theme.svelte'
  import { seriesColor } from '../theme/plot'
  import { useRun } from '../ui/useRun.svelte'
  import type { ViolinGroup, ViolinResult } from '../types'

  let { tStart, tEnd }: { tStart: number; tEnd: number } = $props()

  const GRID_POINTS = 256

  let selectedFiles = $state<string[]>([])
  let channel = $state('extension')
  let bandwidth = $state('scott')
  let groups = $state<ViolinGroup[]>([])

  const runState = useRun<ViolinResult>()

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
      runState.error = 'Select at least one file'
      return
    }
    const bwValue = bandwidth === 'scott' || bandwidth === 'silverman' ? bandwidth : Number(bandwidth)
    const r = await runState.run((signal) =>
      api.violin(
        {
          session_id: session.sessionId!,
          file_ids: selectedFiles,
          channel,
          bandwidth: bwValue,
          t_start: tStart,
          t_end: tEnd,
        },
        { signal },
      ),
    )
    if (r) groups = r.groups
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

  let plotSeries = $derived.by((): uPlot.Series[] => {
    theme.current
    return [
      {},
      ...groups.map((g, i) => ({ label: g.label, stroke: seriesColor(i), width: 1.5, points: { show: false } })),
    ]
  })
</script>

<div class="row">
  <div>
    <span class="label">Files (one density curve each)</span>
    <div class="row-center" style="margin-top: 4px;">
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
  <RunButton state={runState} label="Compare distributions" onRun={run} />
</div>

{#if groups.length}
  <div style="margin-top: 8px;">
    <Plot data={plotData} series={plotSeries} height={240} cursor={false} />
  </div>
  <table class="mono" style="margin-top: 8px; width: 100%; border-collapse: collapse; font-size: var(--text-xs);">
    <thead>
      <tr>
        <th style="text-align: left;">file</th>
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
