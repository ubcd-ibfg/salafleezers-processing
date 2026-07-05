<script lang="ts">
  import type uPlot from 'uplot'
  import Plot from './Plot.svelte'
  import { api, ApiError } from './api'
  import { session } from './stores/session.svelte'
  import type { WLCFitResult, WLCMethod } from './types'

  const TARGET_POINTS = 4000

  let plotRef: Plot | undefined = $state()
  let fChannel = $state('force')
  let xChannel = $state('extension')

  let sortedX = $state<number[]>([])
  let sortedF = $state<number[]>([])
  let loading = $state(false)
  let loadError = $state('')

  let method = $state<WLCMethod>('basic')
  let P0 = $state(50.0)
  let S0 = $state(900.0)
  let fitOffsets = $state(true)
  let fitting = $state(false)
  let fitError = $state('')
  let fitResult = $state<WLCFitResult | null>(null)

  let lastFileId: string | null = null
  $effect(() => {
    const file = session.activeFile
    if (!file) return
    if (file.file_id !== lastFileId) {
      lastFileId = file.file_id
      fChannel = file.channels.includes('force') ? 'force' : (file.channels[0] ?? '')
      xChannel = file.channels.includes('extension') ? 'extension' : (file.channels[1] ?? file.channels[0] ?? '')
      fitResult = null
    }
  })

  function interp(xq: number, xs: number[], ys: number[]): number {
    const n = xs.length
    if (n === 0) return NaN
    if (xq <= xs[0]) return ys[0]
    if (xq >= xs[n - 1]) return ys[n - 1]
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

  async function reload() {
    const file = session.activeFile
    if (!file || !fChannel || !xChannel) return
    loading = true
    loadError = ''
    fitResult = null
    try {
      const decimate = Math.max(1, Math.floor(file.n_samples / TARGET_POINTS))
      const [fSeg, xSeg] = await Promise.all([
        api.getTrace(file.file_id, { session_id: session.sessionId!, channel: fChannel, decimate }),
        api.getTrace(file.file_id, { session_id: session.sessionId!, channel: xChannel, decimate }),
      ])
      const pairs = xSeg.data.map((x, i) => [x, fSeg.data[i]] as const)
      pairs.sort((a, b) => a[0] - b[0])
      sortedX = pairs.map((p) => p[0])
      sortedF = pairs.map((p) => p[1])
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e)
    } finally {
      loading = false
    }
  }

  $effect(() => {
    session.activeFileId
    fChannel
    xChannel
    reload()
  })

  async function runFit() {
    const file = session.activeFile
    if (!file) return
    fitting = true
    fitError = ''
    try {
      fitResult = await api.wlcFit({
        session_id: session.sessionId!,
        file_id: file.file_id,
        F_channel: fChannel,
        x_channel: xChannel,
        method,
        P0,
        S0,
        fit_offsets: fitOffsets,
      })
    } catch (e) {
      fitError = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e)
    } finally {
      fitting = false
    }
  }

  let modelOnData = $derived.by((): number[] => {
    if (!fitResult) return []
    return sortedX.map((x) => interp(x, fitResult!.x_model, fitResult!.F_model))
  })

  let residuals = $derived.by((): number[] => {
    if (!fitResult) return []
    return sortedF.map((F, i) => F - modelOnData[i])
  })

  let plotSeries = $derived.by((): uPlot.Series[] => {
    const s: uPlot.Series[] = [
      {},
      { label: `${fChannel} (data)`, stroke: '#7c3aed', paths: () => null, points: { show: true, size: 3 } },
    ]
    if (fitResult) s.push({ label: `WLC fit (${fitResult.method})`, stroke: '#dc2626', width: 2, points: { show: false } })
    return s
  })

  let plotData = $derived.by((): uPlot.AlignedData => {
    const arr: number[][] = [sortedX, sortedF]
    if (fitResult) arr.push(modelOnData)
    return arr as uPlot.AlignedData
  })

  let residualSeries: uPlot.Series[] = [{}, { label: 'residual', stroke: '#059669', paths: () => null, points: { show: true, size: 3 } }]
  let residualData = $derived.by((): uPlot.AlignedData => [sortedX, residuals] as uPlot.AlignedData)
</script>

{#if !session.activeFile}
  <p class="muted">Open a file above to view its force-extension curve.</p>
{:else}
  <div class="card row">
    <label>
      Force channel
      <select bind:value={fChannel}>
        {#each session.activeFile.channels as ch (ch)}
          <option value={ch}>{ch}</option>
        {/each}
      </select>
    </label>
    <label>
      Extension channel
      <select bind:value={xChannel}>
        {#each session.activeFile.channels as ch (ch)}
          <option value={ch}>{ch}</option>
        {/each}
      </select>
    </label>
  </div>

  <div class="card" style="margin-top:8px;">
    {#if loading}<p class="muted">Loading…</p>{/if}
    {#if loadError}<p style="color: var(--danger)">{loadError}</p>{/if}
    <Plot bind:this={plotRef} data={plotData} series={plotSeries} height={340} cursor={false} />
    <div class="row" style="margin-top:8px;">
      <button onclick={() => plotRef?.exportPng(`${session.activeFile?.filename ?? 'force_ext'}_wlc.png`)}>
        Export PNG
      </button>
    </div>
  </div>

  <div class="card row" style="margin-top:8px;">
    <label>
      Method
      <select bind:value={method}>
        <option value="basic">Basic</option>
        <option value="marko_siggia">Marko-Siggia</option>
        <option value="bouchiat">Bouchiat</option>
      </select>
    </label>
    <label>
      P0 (nm)
      <input type="number" step="1" bind:value={P0} style="width:80px" />
    </label>
    <label>
      S0 (pN)
      <input type="number" step="10" bind:value={S0} style="width:90px" />
    </label>
    <label style="flex-direction: row; align-items: center; gap: 4px;">
      <input type="checkbox" bind:checked={fitOffsets} />
      Fit offsets
    </label>
    <button class="primary" onclick={runFit} disabled={fitting}>{fitting ? 'Fitting…' : 'Fit WLC'}</button>
    {#if fitError}<span style="color: var(--danger)">{fitError}</span>{/if}
  </div>

  {#if fitResult}
    <div class="card row" style="margin-top:8px;">
      <span class="mono">P = {fitResult.P_nm.toFixed(2)} nm</span>
      <span class="mono">Lc = {fitResult.Lc_nm.toFixed(1)} nm</span>
      <span class="mono">S = {fitResult.S_pN.toFixed(0)} pN</span>
      <span class="mono">x offset = {fitResult.x_offset_nm.toFixed(2)} nm</span>
      <span class="mono">F offset = {fitResult.F_offset_pN.toFixed(3)} pN</span>
      <span class="mono">χ² = {fitResult.chi2.toFixed(4)}</span>
    </div>

    <div class="card" style="margin-top:8px;">
      <strong class="muted" style="font-size:12px;">Residuals (data − model)</strong>
      <Plot data={residualData} series={residualSeries} height={140} cursor={false} />
    </div>
  {/if}
{/if}
