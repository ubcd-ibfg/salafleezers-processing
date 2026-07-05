<script lang="ts">
  import uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import { api, ApiError } from '../api'
  import { session } from '../stores/session.svelte'

  let { channel, tStart, tEnd }: { channel: string; tStart: number | null; tEnd: number | null } = $props()

  let bins = $state(200)
  let running = $state(false)
  let error = $state('')
  let binCenters = $state<number[]>([])
  let pwdCounts = $state<number[]>([])
  let stepSizes = $state<number[]>([])
  let peakHeights = $state<number[]>([])

  const barsPath = uPlot.paths.bars!({ size: [0.9, 100] })

  async function run() {
    const file = session.activeFile
    if (!file) return
    running = true
    error = ''
    try {
      const r = await api.pwd({
        session_id: session.sessionId!,
        file_id: file.file_id,
        channel,
        bins,
        t_start: tStart,
        t_end: tEnd,
      })
      binCenters = r.bin_centers
      pwdCounts = r.pwd_counts
      stepSizes = r.step_sizes
      peakHeights = r.peak_heights
    } catch (e) {
      error = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)
    } finally {
      running = false
    }
  }

  let plotData = $derived.by((): uPlot.AlignedData => [binCenters, pwdCounts] as uPlot.AlignedData)
  let plotSeries: uPlot.Series[] = [
    {},
    { label: 'pairwise distance', stroke: '#d97706', fill: 'rgba(217,119,6,0.3)', paths: barsPath, points: { show: false } },
  ]
</script>

<div class="row">
  <label>
    Bins
    <input type="number" min="10" bind:value={bins} style="width:80px" />
  </label>
  <button class="primary" onclick={run} disabled={running}>{running ? 'Running…' : 'Run PWD'}</button>
  {#if error}<span style="color: var(--danger)">{error}</span>{/if}
</div>

{#if binCenters.length}
  <div style="margin-top:8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
  {#if stepSizes.length}
    <p class="muted" style="margin-top:6px;">
      Peaks: {stepSizes.map((s, i) => `${s.toFixed(2)} nm (h=${peakHeights[i]?.toFixed(1)})`).join(', ')}
    </p>
  {/if}
{/if}
