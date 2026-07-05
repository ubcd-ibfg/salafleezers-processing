<script lang="ts">
  import type uPlot from 'uplot'
  import { onMount, onDestroy } from 'svelte'
  import Plot from './Plot.svelte'
  import AnalysisPanels from './panels/AnalysisPanels.svelte'
  import { api } from './api'
  import { session } from './stores/session.svelte'
  import type { MeasurementResult, StepFindAlgorithm, StepFindResult } from './types'

  const TARGET_POINTS = 4000
  const PALETTE = ['#7c3aed', '#059669', '#d97706', '#dc2626', '#2563eb', '#0891b2']

  let plotRef: Plot | undefined = $state()
  let primaryChannel = $state<string>('')
  let overlayChannels = $state<string[]>([])

  let mainTime = $state<number[]>([])
  let primaryData = $state<number[]>([])
  let overlayData = $state<Record<string, number[]>>({})
  let loading = $state(false)
  let loadError = $state('')

  // view window (null = full trace)
  let viewStart = $state<number | null>(null)
  let viewEnd = $state<number | null>(null)
  let selection = $state<{ start: number; end: number } | null>(null)

  let filterHalfWidth = $state(0)
  let filteredData = $state<number[] | null>(null)

  let algorithm = $state<StepFindAlgorithm>('kv')
  let penFactor = $state(2.0)
  let nStates = $state(2)
  let stepResult = $state<StepFindResult | null>(null)
  let stepRunning = $state(false)

  let measurement = $state<MeasurementResult | null>(null)
  let measuring = $state(false)

  let comment = $state('')

  // Reset per-file state when the active file changes.
  let lastFileId: string | null = null
  $effect(() => {
    const file = session.activeFile
    if (!file) return
    if (file.file_id !== lastFileId) {
      lastFileId = file.file_id
      primaryChannel = file.channels[0] ?? ''
      overlayChannels = []
      viewStart = null
      viewEnd = null
      selection = null
      filterHalfWidth = 0
      filteredData = null
      stepResult = null
      measurement = null
      comment = ''
      viewHistory = []
      redoHistory = []
    }
  })

  function decimateFor(durationS: number): number {
    const fs = session.activeFile?.sampling_rate_hz ?? 1
    const nPts = Math.max(1, durationS * fs)
    return Math.max(1, Math.floor(nPts / TARGET_POINTS))
  }

  async function fetchChannel(channel: string): Promise<{ time: number[]; data: number[] }> {
    const file = session.activeFile!
    const duration = viewStart != null && viewEnd != null ? viewEnd - viewStart : file.duration_s
    const decimate = decimateFor(duration || file.duration_s)
    const seg = await api.getTrace(file.file_id, {
      session_id: session.sessionId!,
      channel,
      decimate,
      t_start: viewStart,
      t_end: viewEnd,
    })
    return { time: seg.time, data: seg.data }
  }

  async function reload() {
    const file = session.activeFile
    if (!file || !primaryChannel) return
    loading = true
    loadError = ''
    filteredData = null
    stepResult = null
    try {
      const main = await fetchChannel(primaryChannel)
      mainTime = main.time
      primaryData = main.data
      const overlays: Record<string, number[]> = {}
      for (const ch of overlayChannels) {
        const seg = await fetchChannel(ch)
        overlays[ch] = seg.data
      }
      overlayData = overlays
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e)
    } finally {
      loading = false
    }
  }

  $effect(() => {
    // dependencies: active file, primary channel, overlay set, view window
    session.activeFileId
    primaryChannel
    overlayChannels
    viewStart
    viewEnd
    reload()
  })

  function toggleOverlay(ch: string) {
    overlayChannels = overlayChannels.includes(ch)
      ? overlayChannels.filter((c) => c !== ch)
      : [...overlayChannels, ch]
  }

  function applyFilter() {
    const file = session.activeFile
    if (!file || !session.socket) return
    if (filterHalfWidth <= 0) {
      filteredData = null
      return
    }
    const unsub = session.socket.onMessage((msg) => {
      if (msg.type === 'trace' && msg.channel === primaryChannel) {
        filteredData = msg.data
        unsub()
      }
    })
    const duration = viewStart != null && viewEnd != null ? viewEnd - viewStart : file.duration_s
    session.socket.filter(file.file_id, primaryChannel, filterHalfWidth, decimateFor(duration))
  }

  type ViewWindow = { start: number | null; end: number | null }
  let viewHistory = $state<ViewWindow[]>([])
  let redoHistory = $state<ViewWindow[]>([])

  function pushHistory() {
    viewHistory = [...viewHistory, { start: viewStart, end: viewEnd }]
    redoHistory = []
  }

  function undoView() {
    if (!viewHistory.length) return
    const prev = viewHistory[viewHistory.length - 1]
    viewHistory = viewHistory.slice(0, -1)
    redoHistory = [...redoHistory, { start: viewStart, end: viewEnd }]
    viewStart = prev.start
    viewEnd = prev.end
    selection = null
  }

  function redoView() {
    if (!redoHistory.length) return
    const next = redoHistory[redoHistory.length - 1]
    redoHistory = redoHistory.slice(0, -1)
    viewHistory = [...viewHistory, { start: viewStart, end: viewEnd }]
    viewStart = next.start
    viewEnd = next.end
    selection = null
  }

  function zoomToSelection() {
    if (!selection) return
    pushHistory()
    viewStart = selection.start
    viewEnd = selection.end
    selection = null
  }

  function resetZoom() {
    if (viewStart == null && viewEnd == null) return
    pushHistory()
    viewStart = null
    viewEnd = null
    selection = null
  }

  async function applyCrop() {
    if (!selection || !session.socket || !session.activeFile) return
    const file = session.activeFile
    pushHistory()
    session.socket.crop(file.file_id, selection.start, selection.end, [primaryChannel, ...overlayChannels], 1)
    viewStart = selection.start
    viewEnd = selection.end
    selection = null
  }

  function measureSelection() {
    if (!selection || !session.socket || !session.activeFile) return
    measuring = true
    const unsub = session.socket.onMessage((msg) => {
      if (msg.type === 'measurement') {
        measurement = msg
        measuring = false
        unsub()
      } else if (msg.type === 'error') {
        measuring = false
        unsub()
      }
    })
    session.socket.measure(session.activeFile.file_id, primaryChannel, selection.start, selection.end)
  }

  async function runStepFind() {
    const file = session.activeFile
    if (!file) return
    stepRunning = true
    try {
      stepResult = await api.stepFind({
        session_id: session.sessionId!,
        file_id: file.file_id,
        channel: primaryChannel,
        algorithm,
        pen_factor: penFactor,
        n_states: nStates,
        t_start: viewStart,
        t_end: viewEnd,
      })
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e)
    } finally {
      stepRunning = false
    }
  }

  function resampleSteps(result: StepFindResult, time: number[]): number[] {
    const times = result.step_times
    const levels = result.levels
    if (!times.length || !levels.length) return time.map(() => NaN)
    const out = new Array(time.length)
    let idx = 0
    for (let i = 0; i < time.length; i++) {
      while (idx < times.length - 1 && times[idx + 1] <= time[i]) idx++
      out[i] = levels[Math.min(idx, levels.length - 1)]
    }
    return out
  }

  let plotSeries = $derived.by((): uPlot.Series[] => {
    const s: uPlot.Series[] = [
      {},
      { label: primaryChannel, stroke: PALETTE[0], width: 1.5 },
    ]
    if (filteredData) s.push({ label: `${primaryChannel} (filtered)`, stroke: PALETTE[3], width: 1.5 })
    if (stepResult) s.push({ label: `${stepResult.algorithm} steps`, stroke: PALETTE[2], width: 2 })
    overlayChannels.forEach((ch, i) => {
      s.push({ label: ch, stroke: PALETTE[(i + 2) % PALETTE.length], width: 1.2 })
    })
    return s
  })

  let plotData = $derived.by((): uPlot.AlignedData => {
    const arr: number[][] = [mainTime, primaryData]
    if (filteredData) arr.push(filteredData)
    if (stepResult) arr.push(resampleSteps(stepResult, mainTime))
    for (const ch of overlayChannels) arr.push(overlayData[ch] ?? mainTime.map(() => NaN))
    return arr as uPlot.AlignedData
  })

  function exportCsv() {
    if (!mainTime.length) return
    const header = ['time', primaryChannel, ...overlayChannels].join(',')
    const lines = mainTime.map((t, i) =>
      [t, primaryData[i], ...overlayChannels.map((ch) => overlayData[ch]?.[i])].join(','),
    )
    const blob = new Blob([header + '\n' + lines.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${session.activeFile?.filename ?? 'trace'}_${primaryChannel}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  function isTyping(target: EventTarget | null): boolean {
    const el = target as HTMLElement | null
    return !!el && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
  }

  function handleKeydown(e: KeyboardEvent) {
    if (isTyping(e.target)) return
    const mod = e.ctrlKey || e.metaKey
    if (mod && e.key.toLowerCase() === 'z') {
      e.preventDefault()
      if (e.shiftKey) redoView()
      else undoView()
      return
    }
    switch (e.key) {
      case 'z':
        zoomToSelection()
        break
      case 'c':
        applyCrop()
        break
      case 'm':
        measureSelection()
        break
      case '0':
        resetZoom()
        break
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleKeydown)
  })
  onDestroy(() => {
    window.removeEventListener('keydown', handleKeydown)
  })
</script>

{#if !session.activeFile}
  <p class="muted">Open a file above to view its traces.</p>
{:else}
  <div class="toolbar card row">
    <label>
      Channel
      <select bind:value={primaryChannel}>
        {#each session.activeFile.channels as ch (ch)}
          <option value={ch}>{ch}</option>
        {/each}
      </select>
    </label>

    <div>
      <span class="muted" style="display:block; font-size:12px;">Overlay</span>
      <div class="row" style="gap:6px;">
        {#each session.activeFile.channels.filter((c) => c !== primaryChannel) as ch (ch)}
          <label style="flex-direction: row; align-items: center; gap: 4px;">
            <input
              type="checkbox"
              checked={overlayChannels.includes(ch)}
              onchange={() => toggleOverlay(ch)}
            />
            {ch}
          </label>
        {/each}
      </div>
    </div>

    <label>
      Filter half-width
      <input type="number" min="0" bind:value={filterHalfWidth} onchange={applyFilter} style="width:80px" />
    </label>

    <button onclick={exportCsv} disabled={!mainTime.length}>Export CSV</button>
  </div>

  <div class="card" style="margin-top:8px;">
    {#if loading}<p class="muted">Loading…</p>{/if}
    {#if loadError}<p style="color: var(--danger)">{loadError}</p>{/if}
    <Plot
      bind:this={plotRef}
      data={plotData}
      series={plotSeries}
      height={340}
      onZoom={() => {}}
      onSelect={(min, max) => (selection = { start: min, end: max })}
    />
    <div class="row" style="margin-top:8px;">
      <button disabled={!selection} onclick={zoomToSelection} title="z">Zoom to selection</button>
      <button disabled={!selection} onclick={applyCrop} title="c">Apply crop</button>
      <button disabled={!selection || measuring} onclick={measureSelection} title="m">Measure selection</button>
      <button disabled={viewStart == null} onclick={resetZoom} title="0">Reset view</button>
      <button disabled={!viewHistory.length} onclick={undoView} title="Ctrl+Z">Undo</button>
      <button disabled={!redoHistory.length} onclick={redoView} title="Ctrl+Shift+Z">Redo</button>
      <button onclick={() => plotRef?.exportPng(`${session.activeFile?.filename ?? 'trace'}_${primaryChannel}.png`)}>
        Export PNG
      </button>
      {#if selection}
        <span class="muted mono">
          [{selection.start.toFixed(3)}, {selection.end.toFixed(3)}] s
        </span>
      {/if}
    </div>
  </div>

  {#if measurement}
    <div class="card" style="margin-top:8px;">
      <strong>Measurement</strong>
      <div class="row mono">
        <span>mean {measurement.mean.toFixed(4)}</span>
        <span>std {measurement.std.toFixed(4)}</span>
        <span>median {measurement.median.toFixed(4)}</span>
        <span>min {measurement.min.toFixed(4)}</span>
        <span>max {measurement.max.toFixed(4)}</span>
        <span>n {measurement.n_pts}</span>
        <span>duration {measurement.duration.toFixed(4)} s</span>
      </div>
    </div>
  {/if}

  <div class="card row" style="margin-top:8px;">
    <label>
      Algorithm
      <select bind:value={algorithm}>
        <option value="kv">Kalafut-Visscher</option>
        <option value="hmm">HMM</option>
      </select>
    </label>
    {#if algorithm === 'kv'}
      <label>
        Penalty factor
        <input type="number" step="0.1" bind:value={penFactor} style="width:80px" />
      </label>
    {:else}
      <label>
        N states
        <input type="number" min="2" bind:value={nStates} style="width:80px" />
      </label>
    {/if}
    <button class="primary" onclick={runStepFind} disabled={stepRunning}>
      {stepRunning ? 'Running…' : 'Run step-find'}
    </button>
    {#if stepResult}
      <span class="muted">
        {stepResult.n_steps} steps found{stepResult.chi2 != null ? `, χ² = ${stepResult.chi2.toFixed(2)}` : ''}
      </span>
    {/if}
  </div>

  <AnalysisPanels channel={primaryChannel} tStart={viewStart} tEnd={viewEnd} {stepResult} />

  <div class="card" style="margin-top:8px;">
    <label>
      Comment (local to this session)
      <textarea bind:value={comment} rows="2" style="width:100%"></textarea>
    </label>
  </div>
{/if}

<style>
  .toolbar {
    align-items: start;
  }
</style>
