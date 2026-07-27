<script lang="ts">
  import { uploadQueue } from './uploadQueue.svelte'
  import { filesFromDataTransfer, filesFromFileList, inferDatasetName, type FlatFile } from './fileTraversal'

  let { compact = false }: { compact?: boolean } = $props()

  let dragOver = $state(false)
  let fileInput: HTMLInputElement
  let dirInput: HTMLInputElement

  function startUpload(files: FlatFile[]) {
    if (!files.length) return
    uploadQueue.start(files, inferDatasetName(files))
  }

  async function handleDrop(e: DragEvent) {
    e.preventDefault()
    dragOver = false
    if (!e.dataTransfer) return
    startUpload(await filesFromDataTransfer(e.dataTransfer))
  }

  function handlePick(e: Event) {
    const input = e.target as HTMLInputElement
    const files = filesFromFileList(input.files ?? new FileList())
    input.value = ''
    startUpload(files)
  }
</script>

<div
  class="dropzone card"
  class:compact
  class:drag-over={dragOver}
  role="group"
  aria-label="Upload data"
  ondragover={(e) => {
    e.preventDefault()
    dragOver = true
  }}
  ondragleave={() => (dragOver = false)}
  ondrop={handleDrop}
>
  {#if !compact}
    <p class="label" style="margin: 0 0 var(--s-1);">Data</p>
    <p class="dim" style="margin: 0 0 var(--s-2); font-size: var(--text-sm);">
      Drag files or a folder here — sidecars (<code class="mono">_pos</code>,
      <code class="mono">_fl</code>) are kept alongside their trace automatically.
    </p>
  {/if}
  <div class="row-center">
    <button onclick={() => fileInput.click()}>{compact ? '+ Upload' : 'Choose files'}</button>
    {#if !compact}
      <button onclick={() => dirInput.click()}>Choose folder</button>
    {/if}
  </div>
  <input bind:this={fileInput} type="file" multiple hidden onchange={handlePick} />
  <input bind:this={dirInput} type="file" webkitdirectory multiple hidden onchange={handlePick} />
</div>

<style>
  .dropzone {
    border-style: dashed;
    border-color: var(--border-strong);
    text-align: center;
  }
  .dropzone.compact {
    padding: var(--s-2);
    text-align: left;
  }
  .dropzone.drag-over {
    border-color: var(--accent);
    background: var(--accent-bg);
  }
</style>
