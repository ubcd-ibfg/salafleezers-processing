// Single source of truth for chart color. Previously a 6-hex PALETTE array
// was copy-pasted between TraceViewer and ViolinPanel, with more literals
// scattered across every analysis panel -- none of it read CSS variables,
// so dark mode themed the shell but left every chart in light colors.
//
// Canvas 2D (what uPlot draws on) can't resolve `var(--x)` the way DOM/SVG
// can, so colors have to be resolved to concrete strings via
// getComputedStyle before reaching uPlot options. These are plain functions,
// not reactive on their own -- callers that build series/axes from them
// need to depend on `theme.current` (see stores/theme.svelte.ts) so Svelte
// re-invokes them when the theme changes.

import type uPlot from 'uplot'

function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

const SERIES_VARS = [
  '--series-1',
  '--series-2',
  '--series-3',
  '--series-4',
  '--series-5',
  '--series-6',
] as const

/** The i-th qualitative series color, wrapping after 6. */
export function seriesColor(i: number): string {
  return cssVar(SERIES_VARS[i % SERIES_VARS.length], '#7c3aed')
}

/** A translucent fill for the same series color, for bar/area charts. */
export function seriesFill(i: number, alphaHex = '4d'): string {
  return `${seriesColor(i)}${alphaHex}`
}

export function textColor(): string {
  return cssVar('--text', '#3a3742')
}

export function borderColor(): string {
  return cssVar('--border', '#e5e4e7')
}

export function dangerColor(): string {
  return cssVar('--danger', '#dc2626')
}

export function accentColor(): string {
  return cssVar('--accent', '#7c3aed')
}

export function fontStack(): string {
  return cssVar('--sans', 'system-ui, sans-serif')
}

/** Default themed x/y axes: canvas-drawn, so this is the only way to theme them. */
export function themedAxes(): uPlot.Axis[] {
  const font = `12px ${fontStack()}`
  const stroke = textColor()
  const grid = { stroke: borderColor(), width: 1 }
  const ticks = { stroke: borderColor(), width: 1 }
  return [
    { stroke, grid, ticks, font },
    { stroke, grid, ticks, font },
  ]
}
