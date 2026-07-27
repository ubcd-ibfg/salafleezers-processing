<script lang="ts">
  import type { RunState } from './useRun.svelte'

  let {
    state,
    label,
    onRun,
    disabled = false,
  }: {
    state: RunState<unknown>
    label: string
    onRun: () => void
    disabled?: boolean
  } = $props()
</script>

<span class="row-center">
  <button
    class={state.running ? '' : 'primary'}
    onclick={() => (state.running ? state.stopWaiting() : onRun())}
    disabled={disabled && !state.running}
  >
    {state.running ? `Stop waiting  ${(state.elapsedMs / 1000).toFixed(1)}s` : label}
  </button>
  {#if state.error}<span class="text-danger">{state.error}</span>{/if}
</span>
