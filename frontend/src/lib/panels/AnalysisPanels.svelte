<script lang="ts">
  import Tabs from '../ui/Tabs.svelte'
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
    tStart: number
    tEnd: number
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

<div class="card" style="margin-top: 8px;">
  <Tabs {tabs} active={tab} onSelect={(id) => (tab = id)} />

  <div style="margin-top: var(--s-2);">
    {#if tab === 'velocity'}
      <VelocityPanel {channel} {tStart} {tEnd} />
    {:else if tab === 'pwd'}
      <PwdPanel {channel} {tStart} {tEnd} />
    {:else if tab === 'kinetics'}
      <KineticsPanel {stepResult} />
    {:else if tab === 'kde'}
      <KdePanel {channel} {tStart} {tEnd} />
    {:else if tab === 'violin'}
      <ViolinPanel {tStart} {tEnd} />
    {:else if tab === 'msd'}
      <MsdPanel {channel} {tStart} {tEnd} />
    {/if}
  </div>
</div>
