<script lang="ts">
  import type uPlot from 'uplot'
  import Plot from './Plot.svelte'
  import RunButton from './ui/RunButton.svelte'
  import { api } from './api'
  import { datasets } from './data/datasets.svelte'
  import { session } from './stores/session.svelte'
  import { theme } from './stores/theme.svelte'
  import { seriesColor, dangerColor, themedAxes } from './theme/plot'
  import { useRun } from './ui/useRun.svelte'
  import type { CalibrationAxisResult, CalibrationResultOut, ProcessRunResult } from './types'

  let { onNavigate }: { onNavigate: (view: 'trace' | 'force-ext') => void } = $props()

  const NONE_OFFSET = '__none__'
  const USE_FIT = '__fit__'

  // ---------------------------------------------------------------------
  // Section A -- fit calibration from the currently open trace
  // ---------------------------------------------------------------------

  let beadRadiusA = $state(500.0)
  let beadRadiusB = $state(500.0)
  let fMin = $state(100.0)
  let fMax = $state<number | null>(null)
  let nBin = $state(1563)
  let nAlias = $state(20)
  let normalize = $state(true)
  let showAdvanced = $state(false)

  const calRun = useRun<CalibrationResultOut>()
  let calResult = $state<CalibrationResultOut | null>(null)

  let lastFileId: string | null = null
  $effect(() => {
    const file = session.activeFile
    if (!file) return
    if (file.file_id !== lastFileId) {
      lastFileId = file.file_id
      calResult = null
    }
  })

  async function runCalibrate() {
    const file = session.activeFile
    if (!file) return
    const r = await calRun.run((signal) =>
      api.calibrate(
        {
          session_id: session.sessionId!,
          file_id: file.file_id,
          bead_radius_a_nm: beadRadiusA,
          bead_radius_b_nm: beadRadiusB,
          f_min_hz: fMin,
          f_max_hz: fMax,
          n_bin: nBin,
          n_alias: nAlias,
          normalize,
        },
        { signal },
      ),
    )
    if (r) calResult = r
  }

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

  // uPlot's log scale can't render non-positive values, and every series in
  // one AlignedData must share a single x-grid -- so the fitted model
  // (evaluated on its own geomspace) is resampled onto the binned PSD's
  // frequency grid, same technique ForceExtensionViewer uses to overlay a
  // WLC model on measured force/extension points.
  function axisPlotData(axis: CalibrationAxisResult): uPlot.AlignedData {
    const f: number[] = []
    const p: number[] = []
    for (let i = 0; i < axis.f_binned.length; i++) {
      if (axis.psd_binned[i] > 0) {
        f.push(axis.f_binned[i])
        p.push(axis.psd_binned[i])
      }
    }
    const model = f.map((fq) => interp(fq, axis.f_model, axis.psd_model))
    return [f, p, model] as uPlot.AlignedData
  }

  function axisPlotSeries(): uPlot.Series[] {
    theme.current
    return [
      {},
      { label: 'PSD', stroke: seriesColor(0), paths: () => null, points: { show: true, size: 2 } },
      { label: 'fit', stroke: dangerColor(), width: 2, points: { show: false } },
    ]
  }

  // `time: false` is required on the x scale -- uPlot's x scale defaults to
  // treating series[0] as UNIX timestamps, which (combined with a log
  // distribution) produced garbled overlapping "12am 1/1/70" tick labels
  // for what is actually a frequency axis, not a time axis.
  const psdScales: uPlot.Scales = { x: { time: false, distr: 3 }, y: { distr: 3 } }

  // PSD values span several orders of magnitude (~1e-3 down to ~1e-9), so
  // the default tick formatter (a handful of decimal places) rounds every
  // y-tick below 0.001 to a useless "0". Exponential notation keeps ticks
  // distinguishable across the whole log-scaled range.
  function formatLogTick(v: number | null): string {
    // uPlot passes `null` for split positions it doesn't want labeled.
    if (v === null) return ''
    if (v === 0) return '0'
    const abs = Math.abs(v)
    return abs >= 1000 || abs < 0.01 ? v.toExponential(0) : String(v)
  }

  function psdAxes(): uPlot.Axis[] {
    theme.current
    const [xAxis, yAxis] = themedAxes()
    return [
      { ...xAxis, label: 'Frequency (Hz)', labelSize: 22 },
      { ...yAxis, label: 'PSD (V²/Hz)', labelSize: 34, values: (_u, splits) => splits.map(formatLogTick) },
    ]
  }

  // ---------------------------------------------------------------------
  // Section B -- apply a calibration to a data+offset pair
  // ---------------------------------------------------------------------

  interface TraceOption {
    key: string // "datasetId::relativePath"
    label: string
    isCalibration: boolean
  }

  let traceOptions = $derived.by((): TraceOption[] => {
    const opts: TraceOption[] = []
    for (const ds of datasets.datasets) {
      for (const e of ds.entries) {
        if (e.kind === 'trace' && e.relative_path.toLowerCase().endsWith('.dat')) {
          opts.push({
            key: `${ds.dataset_id}::${e.relative_path}`,
            label: `${ds.name}/${e.relative_path}`,
            isCalibration: e.datatype === 1,
          })
        }
      }
    }
    return opts
  })

  function refOf(key: string): { dataset_id: string; relative_path: string } {
    const [dataset_id, ...rest] = key.split('::')
    return { dataset_id, relative_path: rest.join('::') }
  }

  let dataKey = $state('')
  let offsetKey = $state(NONE_OFFSET)
  let calSource = $state(USE_FIT)

  let procBeadRadiusA = $state(500.0)
  let procBeadRadiusB = $state(500.0)
  let procFMin = $state(100.0)
  let procFMax = $state<number | null>(null)
  let procNBin = $state(1563)
  let procNAlias = $state(20)
  let procNormalize = $state(true)
  let procShowAdvanced = $state(false)

  const processRun = useRun<ProcessRunResult>()
  let processResult = $state<ProcessRunResult | null>(null)

  let fittingFreshCalibration = $derived(calSource !== USE_FIT)

  async function runProcess() {
    if (!session.sessionId || !dataKey) return
    if (calSource === USE_FIT && !calResult) {
      processRun.error = 'Run a calibration fit above first, or pick a calibration file.'
      return
    }
    processResult = null
    const r = await processRun.run(
      (signal) =>
        api.process(
          {
            session_id: session.sessionId!,
            data: refOf(dataKey),
            offset: offsetKey === NONE_OFFSET ? null : refOf(offsetKey),
            calibration: calSource === USE_FIT ? null : refOf(calSource),
            calibration_result_id: calSource === USE_FIT ? calResult!.result_id : null,
            bead_radius_a_nm: procBeadRadiusA,
            bead_radius_b_nm: procBeadRadiusB,
            f_min_hz: procFMin,
            f_max_hz: procFMax,
            n_bin: procNBin,
            n_alias: procNAlias,
            normalize: procNormalize,
          },
          { signal },
        ),
      600_000,
    )
    if (r) {
      processResult = r
      session.registerOpenedFile(r.preview)
      datasets.refresh()
    }
  }
</script>

<div class="card stack">
  <p class="label">Fit calibration</p>
  {#if !session.activeFile}
    <p class="muted">
      Open a calibration <span class="mono">.dat</span> from the data rail to fit trap stiffness.
    </p>
  {:else}
    <div class="row">
      <label>
        Bead radius A (nm)
        <input type="number" step="10" bind:value={beadRadiusA} style="width: 90px" />
      </label>
      <label>
        Bead radius B (nm)
        <input type="number" step="10" bind:value={beadRadiusB} style="width: 90px" />
      </label>
      <RunButton state={calRun} label="Run calibration" onRun={runCalibrate} />
    </div>

    <button class="ghost" style="align-self: flex-start;" onclick={() => (showAdvanced = !showAdvanced)}>
      {showAdvanced ? 'Hide' : 'Show'} advanced fit parameters
    </button>
    {#if showAdvanced}
      <div class="row">
        <label>
          f min (Hz)
          <input type="number" step="10" bind:value={fMin} style="width: 90px" />
        </label>
        <label>
          f max (Hz)
          <input type="number" step="100" bind:value={fMax} placeholder="Nyquist" style="width: 100px" />
        </label>
        <label>
          Points/bin
          <input type="number" step="1" min="1" bind:value={nBin} style="width: 90px" />
        </label>
        <label>
          Aliasing order
          <input type="number" step="1" min="0" bind:value={nAlias} style="width: 90px" />
        </label>
        <label style="flex-direction: row; align-items: center; gap: 4px;">
          <input type="checkbox" bind:checked={normalize} />
          Normalize by QPD sum
        </label>
      </div>
    {/if}

    {#if calResult}
      <span class="dim mono" style="font-size: var(--text-xs);">{session.activeFile.filename}</span>
      {#if calResult.skipped.length}
        <p class="dim">Skipped (channel not present): {calResult.skipped.join(', ')}</p>
      {/if}
      <div class="calib-grid">
        {#each calResult.axes as axis (axis.detector)}
          <div class="card stack">
            <div class="row-center" style="justify-content: space-between;">
              <span class="label">{axis.detector}</span>
              {#if !axis.converged}<span class="text-warn">fit did not converge</span>{/if}
            </div>
            <Plot
              data={axisPlotData(axis)}
              series={axisPlotSeries()}
              scales={psdScales}
              axes={psdAxes()}
              height={200}
              cursor={false}
            />
            <div class="row-center mono" style="font-size: var(--text-xs); flex-wrap: wrap;">
              <span>fc = {axis.fc_hz.toFixed(1)} Hz</span>
              <span>α = {axis.alpha_nm_v.toFixed(2)} nm/V</span>
              <span>κ = {axis.kappa_pn_nm.toFixed(4)} pN/nm</span>
              <span>χ² = {axis.chi2.toFixed(3)}</span>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<div class="card stack" style="margin-top: 8px;">
  <p class="label">Apply &rarr; force/extension</p>

  <div class="row">
    <label>
      Data file
      <select bind:value={dataKey} style="min-width: 220px">
        <option value="">Select a .dat file&hellip;</option>
        {#each traceOptions as opt (opt.key)}
          <option value={opt.key}>{opt.label}</option>
        {/each}
      </select>
    </label>
    <label>
      Offset file
      <select bind:value={offsetKey} style="min-width: 220px">
        <option value={NONE_OFFSET}>(none)</option>
        {#each traceOptions as opt (opt.key)}
          <option value={opt.key}>{opt.label}</option>
        {/each}
      </select>
    </label>
    <label>
      Calibration
      <select bind:value={calSource} style="min-width: 220px">
        <option value={USE_FIT} disabled={!calResult}>
          {calResult ? 'Use fit above' : 'Use fit above (run a fit first)'}
        </option>
        {#each traceOptions as opt (opt.key)}
          <option value={opt.key}>{opt.label}{opt.isCalibration ? ' (calibration)' : ''}</option>
        {/each}
      </select>
    </label>
  </div>

  <div class="row">
    <label>
      Bead radius A (nm)
      <input type="number" step="10" bind:value={procBeadRadiusA} style="width: 90px" />
    </label>
    <label>
      Bead radius B (nm)
      <input type="number" step="10" bind:value={procBeadRadiusB} style="width: 90px" />
    </label>
    <RunButton state={processRun} label="Process" onRun={runProcess} disabled={!dataKey} />
  </div>

  {#if fittingFreshCalibration}
    <button class="ghost" style="align-self: flex-start;" onclick={() => (procShowAdvanced = !procShowAdvanced)}>
      {procShowAdvanced ? 'Hide' : 'Show'} advanced fit parameters
    </button>
    {#if procShowAdvanced}
      <div class="row">
        <label>
          f min (Hz)
          <input type="number" step="10" bind:value={procFMin} style="width: 90px" />
        </label>
        <label>
          f max (Hz)
          <input type="number" step="100" bind:value={procFMax} placeholder="Nyquist" style="width: 100px" />
        </label>
        <label>
          Points/bin
          <input type="number" step="1" min="1" bind:value={procNBin} style="width: 90px" />
        </label>
        <label>
          Aliasing order
          <input type="number" step="1" min="0" bind:value={procNAlias} style="width: 90px" />
        </label>
        <label style="flex-direction: row; align-items: center; gap: 4px;">
          <input type="checkbox" bind:checked={procNormalize} />
          Normalize by QPD sum
        </label>
      </div>
    {/if}
  {/if}

  {#if processResult}
    {#each processResult.warnings as w}
      <p class="text-warn">{w}</p>
    {/each}
    <div class="row-center mono" style="font-size: var(--text-xs); flex-wrap: wrap;">
      {#each processResult.calibration.axes as axis (axis.detector)}
        <span>{axis.detector}: α={axis.alpha_nm_v.toFixed(2)} κ={axis.kappa_pn_nm.toFixed(4)}</span>
      {/each}
    </div>
    <div class="row-center" style="justify-content: space-between;">
      <span class="dim">Wrote <span class="mono">{processResult.relative_path}</span></span>
      <button class="primary" onclick={() => onNavigate('trace')}>Open in Trace Viewer &rarr;</button>
    </div>
  {/if}
</div>

<style>
  .calib-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: var(--s-3);
    margin-top: var(--s-2);
  }

  @media (max-width: 760px) {
    .calib-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
