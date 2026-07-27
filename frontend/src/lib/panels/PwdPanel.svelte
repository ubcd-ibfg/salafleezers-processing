<script lang="ts">
  import uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import RunButton from '../ui/RunButton.svelte'
  import { api } from '../api'
  import { session } from '../stores/session.svelte'
  import { theme } from '../stores/theme.svelte'
  import { seriesColor, seriesFill } from '../theme/plot'
  import { useRun } from '../ui/useRun.svelte'
  import type { PWDResult } from '../types'

  let { channel, tStart, tEnd }: { channel: string; tStart: number; tEnd: number } = $props()

  let bins = $state(200)
  let binCenters = $state<number[]>([])
  let pwdCounts = $state<number[]>([])
  let stepSizes = $state<number[]>([])
  let peakHeights = $state<number[]>([])

  const runState = useRun<PWDResult>()

  const barsPath = uPlot.paths.bars!({ size: [0.9, 100] })

  async function run() {
    const file = session.activeFile
    if (!file) return
    const r = await runState.run((signal) =>
      api.pwd(
        { session_id: session.sessionId!, file_id: file.file_id, channel, bins, t_start: tStart, t_end: tEnd },
        { signal },
      ),
    )
    if (r) {
      binCenters = r.bin_centers
      pwdCounts = r.pwd_counts
      stepSizes = r.step_sizes
      peakHeights = r.peak_heights
    }
  }

  let plotData = $derived.by((): uPlot.AlignedData => [binCenters, pwdCounts] as uPlot.AlignedData)
  let plotSeries = $derived.by((): uPlot.Series[] => {
    theme.current
    return [
      {},
      { label: 'pairwise distance', stroke: seriesColor(2), fill: seriesFill(2), paths: barsPath, points: { show: false } },
    ]
  })
</script>

<div class="row">
  <label>
    Bins
    <input type="number" min="10" bind:value={bins} style="width: 80px" />
  </label>
  <RunButton state={runState} label="Run PWD" onRun={run} />
</div>

{#if binCenters.length}
  <div style="margin-top: 8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
  {#if stepSizes.length}
    <p class="dim" style="margin-top: 6px; font-size: var(--text-sm);">
      Peaks: {stepSizes.map((s, i) => `${s.toFixed(2)} nm (h=${peakHeights[i]?.toFixed(1)})`).join(', ')}
    </p>
  {/if}
{/if}
