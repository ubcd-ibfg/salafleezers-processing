<script lang="ts">
  import uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import RunButton from '../ui/RunButton.svelte'
  import { api } from '../api'
  import { session } from '../stores/session.svelte'
  import { theme } from '../stores/theme.svelte'
  import { seriesColor, seriesFill } from '../theme/plot'
  import { useRun } from '../ui/useRun.svelte'
  import type { VelocityMethod, VelocityResult } from '../types'

  let { channel, tStart, tEnd }: { channel: string; tStart: number; tEnd: number } = $props()

  let method = $state<VelocityMethod>('savgol')
  let window_ = $state(21)
  let polyorder = $state(2)
  let vCenters = $state<number[]>([])
  let counts = $state<number[]>([])
  let meanVelocity = $state<number | null>(null)

  const runState = useRun<VelocityResult>()

  const barsPath = uPlot.paths.bars!({ size: [0.7, 100] })

  async function run() {
    const file = session.activeFile
    if (!file) return
    const r = await runState.run((signal) =>
      api.velocity(
        {
          session_id: session.sessionId!,
          file_id: file.file_id,
          channel,
          method,
          window: window_,
          polyorder,
          t_start: tStart,
          t_end: tEnd,
        },
        { signal },
      ),
    )
    if (r) {
      vCenters = r.v_centers
      counts = r.counts
      meanVelocity = r.mean_velocity_nm_s
    }
  }

  let plotData = $derived.by((): uPlot.AlignedData => [vCenters, counts] as uPlot.AlignedData)
  let plotSeries = $derived.by((): uPlot.Series[] => {
    theme.current
    return [{}, { label: 'count', stroke: seriesColor(5), fill: seriesFill(5), paths: barsPath, points: { show: false } }]
  })
</script>

<div class="row">
  <label>
    Method
    <select bind:value={method}>
      <option value="savgol">Savitzky-Golay</option>
      <option value="steps">From steps</option>
    </select>
  </label>
  <label>
    Window
    <input type="number" min="5" step="2" bind:value={window_} style="width: 70px" />
  </label>
  <label>
    Polyorder
    <input type="number" min="1" bind:value={polyorder} style="width: 70px" />
  </label>
  <RunButton state={runState} label="Run velocity" onRun={run} />
  {#if meanVelocity != null}
    <span class="dim mono">mean |v| = {meanVelocity.toFixed(3)} nm/s</span>
  {/if}
</div>

{#if vCenters.length}
  <div style="margin-top: 8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
{/if}
