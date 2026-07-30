import { api } from '../api'
import { SessionSocket } from '../ws'
import type { FileOpenRequest, TracePreview } from '../types'

export interface LoadedFile {
  file_id: string
  filename: string
  channels: string[]
  n_samples: number
  sampling_rate_hz: number
  duration_s: number
}

export type FileRef = { path: string } | { datasetId: string; relativePath: string }

class SessionStore {
  sessionId = $state<string | null>(null)
  files = $state<LoadedFile[]>([])
  activeFileId = $state<string | null>(null)
  status = $state<'idle' | 'connecting' | 'ready' | 'error'>('idle')
  errorMessage = $state<string | null>(null)
  socket: SessionSocket | null = null

  get activeFile(): LoadedFile | undefined {
    return this.files.find((f) => f.file_id === this.activeFileId)
  }

  async init() {
    this.status = 'connecting'
    try {
      const saved = localStorage.getItem('sfz.sessionId')
      if (saved) {
        try {
          await api.getSession(saved)
          this.sessionId = saved
        } catch {
          this.sessionId = null
        }
      }
      if (!this.sessionId) {
        const info = await api.createSession()
        this.sessionId = info.session_id
        localStorage.setItem('sfz.sessionId', info.session_id)
      }
      this.socket = new SessionSocket(this.sessionId)
      this.status = 'ready'
    } catch (e) {
      this.status = 'error'
      this.errorMessage = e instanceof Error ? e.message : String(e)
    }
  }

  private addFile(preview: TracePreview) {
    const entry: LoadedFile = {
      file_id: preview.file_id,
      filename: preview.filename,
      channels: Object.keys(preview.channels),
      n_samples: preview.n_original,
      sampling_rate_hz: preview.sampling_rate_hz,
      duration_s: preview.time.length ? preview.time[preview.time.length - 1] : 0,
    }
    this.files = [...this.files.filter((f) => f.file_id !== entry.file_id), entry]
    this.activeFileId = entry.file_id
  }

  /**
   * Mirror a preview the server already opened into this session (e.g. the
   * force/extension trace `POST /api/process` produces and opens as a side
   * effect) into the client-side file list, without a redundant
   * `POST /api/files/open` round-trip.
   */
  registerOpenedFile(preview: TracePreview) {
    this.addFile(preview)
  }

  /**
   * Open a file either by an uploaded-dataset reference or (legacy,
   * server-path) reference. The UI only ever constructs the dataset form —
   * `{path}` exists for completeness/testing, not as a user-facing input.
   */
  async openFile(ref: FileRef): Promise<TracePreview> {
    if (!this.sessionId) throw new Error('Session not initialized')
    const body: FileOpenRequest =
      'path' in ref
        ? { path: ref.path, session_id: this.sessionId }
        : { dataset_id: ref.datasetId, relative_path: ref.relativePath, session_id: this.sessionId }
    const preview = await api.openFile(body)
    this.addFile(preview)
    return preview
  }

  async saveSession() {
    if (!this.sessionId) return
    return api.saveSession(this.sessionId)
  }

  async newSession() {
    const info = await api.createSession()
    this.sessionId = info.session_id
    localStorage.setItem('sfz.sessionId', info.session_id)
    this.files = []
    this.activeFileId = null
    this.socket?.close()
    this.socket = new SessionSocket(info.session_id)
  }
}

export const session = new SessionStore()
