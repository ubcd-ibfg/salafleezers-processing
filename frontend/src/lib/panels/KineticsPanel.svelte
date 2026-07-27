<script lang="ts">
  import uPlot from 'uplot'
  import Plot from '../Plot.svelte'
  import RunButton from '../ui/RunButton.svelte'
  import { api } from '../api'
  import { session } from '../stores/session.svelte'
  import { theme } from '../stores/theme.svelte'
  import { seriesColor, seriesFill, dangerColor } from '../theme/plot'
  import { useRun } from '../ui/useRun.svelte'
  import type { KineticsModel, KineticsResult, StepFindResult } from '../types'

  let { stepResult }: { stepResult: StepFindResult | null } = $props()

  let model = $state<KineticsModel>('exponential')
  let nComponents = $state(1)
  let nRestarts = $state(3)
  let manualDwellTimes = $state('')

  const runState = useRun<KineticsResult>()
  let result = $state<KineticsResult | null>(null)

  function dwellTimesFromSteps(r: StepFindResult): number[] {
    const t = r.step_times
    const out: number[] = []
    for (let i = 1; i < t.length; i++) out.push(t[i] - t[i - 1])
    return out
  }

  let dwellTimes = $derived.by((): number[] => {
    if (manualDwellTimes.trim()) {
      return manualDwellTimes
        .split(/[\s,]+/)
        .map(Number)
        .filter((v) => Number.isFinite(v) && v > 0)
    }
    return stepResult ? dwellTimesFromSteps(stepResult) : []
  })

  function histogram(values: number[], nBins = 20): { centers: number[]; counts: number[] } {
    if (!values.length) return { centers: [], counts: [] }
    const min = Math.min(...values)
    const max = Math.max(...values)
    const width = (max - min || 1) / nBins
    const counts = new Array(nBins).fill(0)
    for (const v of values) {
      const idx = Math.min(nBins - 1, Math.max(0, Math.floor((v - min) / width)))
      counts[idx]++
    }
    const centers = counts.map((_, i) => min + width * (i + 0.5))
    return { centers, counts }
  }

  async function run() {
    const file = session.activeFile
    if (!file) return
    if (!dwellTimes.length && !stepResult) {
      runState.error = 'Run step-find above, or paste dwell times manually'
      return
    }
    const r = await runState.run((signal) =>
      api.kineticsFit(
        {
          session_id: session.sessionId!,
          file_id: file.file_id,
          dwell_times: manualDwellTimes.trim() ? dwellTimes : undefined,
          step_result_id: !manualDwellTimes.trim() ? stepResult?.result_id : undefined,
          model,
          n_components: nComponents,
          n_restarts: nRestarts,
        },
        { signal },
      ),
    )
    if (r) result = r
  }

  const barsPath = uPlot.paths.bars!({ size: [0.9, 100] })

  let hist = $derived.by(() => histogram(dwellTimes))

  let plotData = $derived.by((): uPlot.AlignedData => {
    const { centers, counts } = hist
    if (result && result.model === 'exponential' && result.rates && result.amplitudes) {
      const n = dwellTimes.length
      const binWidth = centers.length > 1 ? centers[1] - centers[0] : 1
      const pdf = centers.map((t) => {
        let p = 0
        for (let i = 0; i < result!.rates!.length; i++) {
          p += result!.amplitudes![i] * result!.rates![i] * Math.exp(-result!.rates![i] * t)
        }
        return p * n * binWidth
      })
      return [centers, counts, pdf] as uPlot.AlignedData
    }
    return [centers, counts] as uPlot.AlignedData
  })

  let plotSeries = $derived.by((): uPlot.Series[] => {
    theme.current
    const s: uPlot.Series[] = [
      {},
      { label: 'dwell times', stroke: seriesColor(0), fill: seriesFill(0), paths: barsPath, points: { show: false } },
    ]
    if (result && result.model === 'exponential') {
      s.push({ label: 'fit (scaled)', stroke: dangerColor(), width: 2, points: { show: false } })
    }
    return s
  })
</script>

<div class="row">
  <label>
    Model
    <select bind:value={model}>
      <option value="exponential">n-exponential</option>
      <option value="gamma">n-gamma</option>
    </select>
  </label>
  <label>
    Components
    <input type="number" min="1" max="4" bind:value={nComponents} style="width: 70px" />
  </label>
  <label>
    Restarts
    <input type="number" min="1" bind:value={nRestarts} style="width: 70px" />
  </label>
  <RunButton state={runState} label="Fit dwell times" onRun={run} />
</div>

<label style="margin-top: 6px;">
  Manual dwell times (overrides step-find result if non-empty)
  <input type="text" bind:value={manualDwellTimes} placeholder="0.5, 1.2, 0.8, …" style="width: 100%" />
</label>

{#if !stepResult && !manualDwellTimes.trim()}
  <p class="muted">Run step-find above (or paste dwell times) to enable fitting.</p>
{/if}

{#if dwellTimes.length}
  <div style="margin-top: 8px;">
    <Plot data={plotData} series={plotSeries} height={220} cursor={false} />
  </div>
{/if}

{#if result}
  <div class="row" style="margin-top: 8px;">
    {#if result.model === 'exponential'}
      <span class="mono">rates = [{result.rates?.map((r) => r.toFixed(3)).join(', ')}] s⁻¹</span>
      <span class="mono">amplitudes = [{result.amplitudes?.map((a) => a.toFixed(3)).join(', ')}]</span>
    {:else}
      <span class="mono">shapes = [{result.shapes?.map((s) => s.toFixed(3)).join(', ')}]</span>
      <span class="mono">scales = [{result.scales?.map((s) => s.toFixed(3)).join(', ')}]</span>
      <span class="mono">amplitudes = [{result.amplitudes?.map((a) => a.toFixed(3)).join(', ')}]</span>
    {/if}
    <span class="dim mono">AIC {result.aic.toFixed(2)} · BIC {result.bic.toFixed(2)}</span>
  </div>
{/if}
