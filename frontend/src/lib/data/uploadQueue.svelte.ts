// The upload engine backing Dropzone.svelte: one HTTP request per file (not
// one multipart request carrying all of them), which is what gives per-file
// progress, bounded memory, real parallelism, and the ability to retry a
// single failed file out of a 700-file folder drop without redoing the
// whole thing.

import { api } from '../api'
import { datasets } from './datasets.svelte'
import type { Dataset } from '../types'

const CONCURRENCY = 3

export type UploadItemStatus = 'queued' | 'uploading' | 'done' | 'error'

export interface UploadItem {
  file: File
  relativePath: string
  status: UploadItemStatus
  loaded: number
  error?: string
}

class UploadQueue {
  items = $state<UploadItem[]>([])
  datasetId = $state<string | null>(null)
  active = $state(false)
  finalizing = $state(false)
  finalizedDataset = $state<Dataset | null>(null)
  error = $state('')

  private controller: AbortController | null = null

  get total(): number {
    return this.items.length
  }
  get doneCount(): number {
    return this.items.filter((i) => i.status === 'done').length
  }
  get errorCount(): number {
    return this.items.filter((i) => i.status === 'error').length
  }
  get totalBytes(): number {
    return this.items.reduce((s, i) => s + i.file.size, 0)
  }
  get loadedBytes(): number {
    return this.items.reduce((s, i) => s + i.loaded, 0)
  }
  get progress(): number {
    return this.totalBytes ? this.loadedBytes / this.totalBytes : 0
  }

  async start(files: { file: File; relativePath: string }[], name: string): Promise<void> {
    this.items = files.map((f) => ({ file: f.file, relativePath: f.relativePath, status: 'queued', loaded: 0 }))
    this.datasetId = null
    this.finalizedDataset = null
    this.error = ''
    this.active = true
    this.controller = new AbortController()

    try {
      const ds = await api.createDataset(name)
      this.datasetId = ds.dataset_id
      await this.runQueue()
      if (this.controller.signal.aborted) return

      this.finalizing = true
      const finalized = await api.finalizeDataset(ds.dataset_id)
      this.finalizedDataset = finalized
      datasets.upsert(finalized)
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e)
    } finally {
      this.active = false
      this.finalizing = false
    }
  }

  private async runQueue(): Promise<void> {
    const signal = this.controller!.signal
    let cursor = 0
    const worker = async () => {
      while (cursor < this.items.length) {
        if (signal.aborted) return
        const item = this.items[cursor++]
        item.status = 'uploading'
        try {
          await api.uploadFile(this.datasetId!, item.relativePath, item.file, {
            onProgress: (loaded) => {
              item.loaded = loaded
            },
            signal,
          })
          item.status = 'done'
          item.loaded = item.file.size
        } catch (e) {
          if (signal.aborted) return
          item.status = 'error'
          item.error = e instanceof Error ? e.message : String(e)
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, this.items.length || 1) }, worker))
  }

  /** Retry a single failed item without redoing the rest of the batch. */
  async retry(index: number): Promise<void> {
    if (!this.datasetId) return
    const item = this.items[index]
    if (!item || item.status !== 'error') return
    item.status = 'uploading'
    item.error = undefined
    item.loaded = 0
    try {
      await api.uploadFile(this.datasetId, item.relativePath, item.file, {
        onProgress: (loaded) => {
          item.loaded = loaded
        },
      })
      item.status = 'done'
      item.loaded = item.file.size
    } catch (e) {
      item.status = 'error'
      item.error = e instanceof Error ? e.message : String(e)
    }
  }

  cancel(): void {
    this.controller?.abort()
    this.active = false
  }

  dismiss(): void {
    this.items = []
    this.datasetId = null
    this.finalizedDataset = null
    this.error = ''
  }
}

export const uploadQueue = new UploadQueue()
