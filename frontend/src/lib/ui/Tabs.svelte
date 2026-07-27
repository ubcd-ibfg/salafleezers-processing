<script lang="ts" generics="T extends string">
  let {
    tabs,
    active,
    onSelect,
  }: {
    tabs: { id: T; label: string }[]
    active: T
    onSelect: (id: T) => void
  } = $props()
</script>

<div class="tabs">
  {#each tabs as t (t.id)}
    <button class:active={active === t.id} onclick={() => onSelect(t.id)}>{t.label}</button>
  {/each}
</div>
