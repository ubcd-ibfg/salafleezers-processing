<script lang="ts">
  import VelocityPanel from './VelocityPanel.svelte'
  import PwdPanel from './PwdPanel.svelte'
  import KineticsPanel from './KineticsPanel.svelte'
  import KdePanel from './KdePanel.svelte'
  import ViolinPanel from './ViolinPanel.svelte'
  import MsdPanel from './MsdPanel.svelte'
  import type { StepFindResult } from '../types'

  let {
    channel,
    tStart,
    tEnd,
    stepResult,
  }: {
    channel: string
    tStart: number | null
    tEnd: number | null
    stepResult: StepFindResult | null
  } = $props()

  type Tab = 'velocity' | 'pwd' | 'kinetics' | 'kde' | 'violin' | 'msd'
  let tab = $state<Tab>('velocity')

  const tabs: { id: Tab; label: string }[] = [
    { id: 'velocity', label: 'Velocity' },
    { id: 'pwd', label: 'Pairwise distance' },
    { id: 'kinetics', label: 'Dwell times' },
    { id: 'kde', label: 'Kernel density' },
    { id: 'violin', label: 'Distributions' },
    { id: 'msd', label: 'MSD' },
  ]
</script>

<div class="card" style="margin-top:8px;">
  <div class="row" style="gap:4px; margin-bottom:8px;">
    {#each tabs as t (t.id)}
      <button class:active={tab === t.id} onclick={() => (tab = t.id)}>{t.label}</button>
    {/each}
  </div>

  {#if tab === 'velocity'}
    <VelocityPanel {channel} />
  {:else if tab === 'pwd'}
    <PwdPanel {channel} {tStart} {tEnd} />
  {:else if tab === 'kinetics'}
    <KineticsPanel {stepResult} />
  {:else if tab === 'kde'}
    <KdePanel {channel} {tStart} {tEnd} />
  {:else if tab === 'violin'}
    <ViolinPanel />
  {:else if tab === 'msd'}
    <MsdPanel {channel} {tStart} {tEnd} />
  {/if}
</div>

<style>
  button.active {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }
</style>
