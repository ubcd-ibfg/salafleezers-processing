import { api } from '../api'
import type { Dataset } from '../types'

class DatasetStore {
  datasets = $state<Dataset[]>([])
  loading = $state(false)
  error = $state('')

  async refresh() {
    this.loading = true
    this.error = ''
    try {
      this.datasets = await api.listDatasets()
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e)
    } finally {
      this.loading = false
    }
  }

  upsert(ds: Dataset) {
    this.datasets = [...this.datasets.filter((d) => d.dataset_id !== ds.dataset_id), ds]
  }

  async remove(datasetId: string) {
    await api.deleteDataset(datasetId)
    this.datasets = this.datasets.filter((d) => d.dataset_id !== datasetId)
  }

  /** Delete a single file or a whole subfolder within a dataset. */
  async removeEntry(datasetId: string, relativePath: string): Promise<Dataset> {
    const updated = await api.deleteEntry(datasetId, relativePath)
    this.upsert(updated)
    return updated
  }
}

export const datasets = new DatasetStore()
