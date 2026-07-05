<script lang="ts">
  import uPlot from 'uplot'
  import { onMount, onDestroy } from 'svelte'

  let {
    data,
    series,
    height = 300,
    scales,
    onZoom,
    onSelect,
    cursor = true,
    selectDrag = 'x',
  }: {
    data: uPlot.AlignedData
    series: uPlot.Series[]
    height?: number
    scales?: uPlot.Scales
    onZoom?: (min: number, max: number) => void
    onSelect?: (min: number, max: number) => void
    cursor?: boolean
    selectDrag?: 'x' | 'xy' | 'none'
  } = $props()

  let container: HTMLDivElement
  let plot: uPlot | null = null

  function build() {
    if (!container) return
    const width = container.clientWidth || 600
    const opts: uPlot.Options = {
      width,
      height,
      series,
      scales,
      cursor: cursor
        ? {
            drag: {
              x: selectDrag === 'x' || selectDrag === 'xy',
              y: selectDrag === 'xy',
            },
          }
        : { show: false },
      hooks: {
        setScale: [
          (u, key) => {
            if (key === 'x' && onZoom) {
              const { min, max } = u.scales.x
              if (min != null && max != null) onZoom(min, max)
            }
          },
        ],
        setSelect: onSelect
          ? [
              (u) => {
                if (u.select.width <= 0) return
                const min = u.posToVal(u.select.left, 'x')
                const max = u.posToVal(u.select.left + u.select.width, 'x')
                onSelect(Math.min(min, max), Math.max(min, max))
              },
            ]
          : [],
      },
    }
    plot = new uPlot(opts, data, container)
  }

  function destroy() {
    plot?.destroy()
    plot = null
  }

  onMount(() => {
    build()
    const ro = new ResizeObserver(() => {
      if (plot && container) plot.setSize({ width: container.clientWidth, height })
    })
    ro.observe(container)
    return () => ro.disconnect()
  })

  // Rebuild whenever the series definition changes (e.g. channel selection).
  $effect(() => {
    series
    if (container) {
      destroy()
      build()
    }
  })

  // Push new data into the existing plot instance without rebuilding axes/cursor.
  $effect(() => {
    if (plot) plot.setData(data)
  })

  onDestroy(destroy)

  export function exportPng(filename = 'plot.png') {
    if (!plot) return
    const url = plot.ctx.canvas.toDataURL('image/png')
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
  }
</script>

<div bind:this={container} class="plot-container"></div>

<style>
  .plot-container {
    width: 100%;
  }
</style>
