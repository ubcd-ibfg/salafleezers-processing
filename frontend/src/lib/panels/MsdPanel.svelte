<script lang="ts">
  import type uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import { api, ApiError } from '../api'
  import { session } from '../stores/session.svelte'

  let { channel, tStart, tEnd }: { channel: string; tStart: number | null; tEnd: number | null } = $props()

  let maxLag = $state<number | null>(null)
  let running = $state(false)
  let error = $state('')
  let lags = $state<number[]>([])
  let msd = $state<number[]>([])

  async function run() {
    const file = session.activeFile
    if (!file) return
    running = true
    error = ''
    try {
      const r = await api.msd({
        session_id: session.sessionId!,
        file_id: file.file_id,
        channel,
        max_lag: maxLag,
        t_start: tStart,
        t_end: tEnd,
      })
      lags = r.lags_s
      msd = r.msd
    } catch (e) {
      error = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)
    } finally {
      running = false
    }
  }

  let plotData = $derived.by((): uPlot.AlignedData => [lags, msd] as uPlot.AlignedData)
  let plotSeries: uPlot.Series[] = [{}, { label: 'MSD', stroke: '#2563eb', width: 1.5, points: { show: false } }]
</script>

<div class="row">
  <label>
    Max lag (samples, blank = N/2)
    <input type="number" min="1" bind:value={maxLag} style="width:120px" placeholder="auto" />
  </label>
  <button class="primary" onclick={run} disabled={running}>{running ? 'Running…' : 'Run MSD'}</button>
  {#if error}<span style="color: var(--danger)">{error}</span>{/if}
</div>

{#if lags.length}
  <div style="margin-top:8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
{/if}
