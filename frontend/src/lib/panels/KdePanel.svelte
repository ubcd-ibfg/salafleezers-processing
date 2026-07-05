<script lang="ts">
  import type uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import { api, ApiError } from '../api'
  import { session } from '../stores/session.svelte'

  let { channel, tStart, tEnd }: { channel: string; tStart: number | null; tEnd: number | null } = $props()

  let nPoints = $state(256)
  let bandwidth = $state('scott')
  let running = $state(false)
  let error = $state('')
  let x = $state<number[]>([])
  let density = $state<number[]>([])
  let effectiveBandwidth = $state<number | null>(null)

  async function run() {
    const file = session.activeFile
    if (!file) return
    running = true
    error = ''
    try {
      const bwValue = bandwidth === 'scott' || bandwidth === 'silverman' ? bandwidth : Number(bandwidth)
      const r = await api.kde({
        session_id: session.sessionId!,
        file_id: file.file_id,
        channel,
        n_points: nPoints,
        bandwidth: bwValue,
        t_start: tStart,
        t_end: tEnd,
      })
      x = r.x
      density = r.density
      effectiveBandwidth = r.bandwidth
    } catch (e) {
      error = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)
    } finally {
      running = false
    }
  }

  let plotData = $derived.by((): uPlot.AlignedData => [x, density] as uPlot.AlignedData)
  let plotSeries: uPlot.Series[] = [{}, { label: 'density', stroke: '#059669', width: 1.5, points: { show: false } }]
</script>

<div class="row">
  <label>
    N points
    <input type="number" min="32" bind:value={nPoints} style="width:80px" />
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
  <button class="primary" onclick={run} disabled={running}>{running ? 'Running…' : 'Run KDE'}</button>
  {#if effectiveBandwidth != null}<span class="muted mono">bw = {effectiveBandwidth.toFixed(4)}</span>{/if}
  {#if error}<span style="color: var(--danger)">{error}</span>{/if}
</div>

{#if x.length}
  <div style="margin-top:8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
{/if}
