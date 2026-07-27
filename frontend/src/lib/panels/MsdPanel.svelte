<script lang="ts">
  import type uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import RunButton from '../ui/RunButton.svelte'
  import { api } from '../api'
  import { session } from '../stores/session.svelte'
  import { theme } from '../stores/theme.svelte'
  import { seriesColor } from '../theme/plot'
  import { useRun } from '../ui/useRun.svelte'
  import type { MSDResult } from '../types'

  let { channel, tStart, tEnd }: { channel: string; tStart: number; tEnd: number } = $props()

  let maxLag = $state<number | null>(null)
  let lags = $state<number[]>([])
  let msd = $state<number[]>([])

  const runState = useRun<MSDResult>()

  async function run() {
    const file = session.activeFile
    if (!file) return
    const r = await runState.run((signal) =>
      api.msd(
        { session_id: session.sessionId!, file_id: file.file_id, channel, max_lag: maxLag, t_start: tStart, t_end: tEnd },
        { signal },
      ),
    )
    if (r) {
      lags = r.lags_s
      msd = r.msd
    }
  }

  let plotData = $derived.by((): uPlot.AlignedData => [lags, msd] as uPlot.AlignedData)
  let plotSeries = $derived.by((): uPlot.Series[] => {
    theme.current
    return [{}, { label: 'MSD', stroke: seriesColor(5), width: 1.5, points: { show: false } }]
  })
</script>

<div class="row">
  <label>
    Max lag (samples, blank = N/2)
    <input type="number" min="1" bind:value={maxLag} style="width: 120px" placeholder="auto" />
  </label>
  <RunButton state={runState} label="Run MSD" onRun={run} />
</div>

{#if lags.length}
  <div style="margin-top: 8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
{/if}
