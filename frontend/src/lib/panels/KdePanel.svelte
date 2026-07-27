<script lang="ts">
  import type uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import RunButton from '../ui/RunButton.svelte'
  import { api } from '../api'
  import { session } from '../stores/session.svelte'
  import { theme } from '../stores/theme.svelte'
  import { seriesColor } from '../theme/plot'
  import { useRun } from '../ui/useRun.svelte'
  import type { KDEResult } from '../types'

  let { channel, tStart, tEnd }: { channel: string; tStart: number; tEnd: number } = $props()

  let nPoints = $state(256)
  let bandwidth = $state('scott')
  let x = $state<number[]>([])
  let density = $state<number[]>([])
  let effectiveBandwidth = $state<number | null>(null)

  const runState = useRun<KDEResult>()

  async function run() {
    const file = session.activeFile
    if (!file) return
    const bwValue = bandwidth === 'scott' || bandwidth === 'silverman' ? bandwidth : Number(bandwidth)
    const r = await runState.run((signal) =>
      api.kde(
        {
          session_id: session.sessionId!,
          file_id: file.file_id,
          channel,
          n_points: nPoints,
          bandwidth: bwValue,
          t_start: tStart,
          t_end: tEnd,
        },
        { signal },
      ),
    )
    if (r) {
      x = r.x
      density = r.density
      effectiveBandwidth = r.bandwidth
    }
  }

  let plotData = $derived.by((): uPlot.AlignedData => [x, density] as uPlot.AlignedData)
  let plotSeries = $derived.by((): uPlot.Series[] => {
    theme.current
    return [{}, { label: 'density', stroke: seriesColor(4), width: 1.5, points: { show: false } }]
  })
</script>

<div class="row">
  <label>
    N points
    <input type="number" min="32" bind:value={nPoints} style="width: 80px" />
  </label>
  <label>
    Bandwidth
    <select bind:value={bandwidth}>
      <option value="scott">Scott</option>
      <option value="silverman">Silverman</option>
      <option value="0.1">0.1 (fixed)</option>
      <option value="0.5">0.5 (fixed)</option>
      <option value="1.0">1.0 (fixed)</option>
    </select>
  </label>
  <RunButton state={runState} label="Run KDE" onRun={run} />
  {#if effectiveBandwidth != null}<span class="dim mono">bw = {effectiveBandwidth.toFixed(4)}</span>{/if}
</div>

{#if x.length}
  <div style="margin-top: 8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
{/if}
