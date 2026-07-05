<script lang="ts">
  import uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import { api, ApiError } from '../api'
  import { session } from '../stores/session.svelte'
  import type { VelocityMethod } from '../types'

  let { channel }: { channel: string } = $props()

  let method = $state<VelocityMethod>('savgol')
  let window_ = $state(21)
  let polyorder = $state(2)
  let running = $state(false)
  let error = $state('')
  let vCenters = $state<number[]>([])
  let counts = $state<number[]>([])
  let meanVelocity = $state<number | null>(null)

  const barsPath = uPlot.paths.bars!({ size: [0.7, 100] })

  async function run() {
    const file = session.activeFile
    if (!file) return
    running = true
    error = ''
    try {
      const r = await api.velocity({
        session_id: session.sessionId!,
        file_id: file.file_id,
        channel,
        method,
        window: window_,
        polyorder,
      })
      vCenters = r.v_centers
      counts = r.counts
      meanVelocity = r.mean_velocity_nm_s
    } catch (e) {
      error = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)
    } finally {
      running = false
    }
  }

  let plotData = $derived.by((): uPlot.AlignedData => [vCenters, counts] as uPlot.AlignedData)
  let plotSeries: uPlot.Series[] = [
    {},
    { label: 'count', stroke: '#2563eb', fill: 'rgba(37,99,235,0.35)', paths: barsPath, points: { show: false } },
  ]
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
    <input type="number" min="5" step="2" bind:value={window_} style="width:70px" />
  </label>
  <label>
    Polyorder
    <input type="number" min="1" bind:value={polyorder} style="width:70px" />
  </label>
  <button class="primary" onclick={run} disabled={running}>{running ? 'Running…' : 'Run velocity'}</button>
  {#if meanVelocity != null}
    <span class="muted mono">mean |v| = {meanVelocity.toFixed(3)} nm/s</span>
  {/if}
  {#if error}<span style="color: var(--danger)">{error}</span>{/if}
</div>

{#if vCenters.length}
  <div style="margin-top:8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
{/if}
