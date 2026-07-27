<script lang="ts">
  let {
    error,
    onSubmit,
  }: {
    error?: string | null
    onSubmit: (token: string) => void
  } = $props()

  let value = $state('')
</script>

<div class="card auth-gate">
  <p class="label" style="margin: 0 0 var(--s-1);">Authentication required</p>
  <p class="dim" style="font-size: var(--text-sm); margin: 0 0 var(--s-3);">
    This server requires a bearer token. Ask whoever runs it for the shared token.
  </p>
  <form
    class="row-center"
    onsubmit={(e) => {
      e.preventDefault()
      onSubmit(value)
    }}
  >
    <input type="password" placeholder="token" bind:value autocomplete="off" style="flex: 1;" />
    <button class="primary" type="submit" disabled={!value.trim()}>Connect</button>
  </form>
  {#if error}<p class="text-danger" style="font-size: var(--text-sm); margin-top: var(--s-2);">{error}</p>{/if}
</div>

<style>
  .auth-gate {
    width: min(380px, 90vw);
  }
</style>
