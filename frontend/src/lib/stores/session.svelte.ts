import { api } from '../api'
import { SessionSocket } from '../ws'
import type { TracePreview } from '../types'

export interface LoadedFile {
  file_id: string
  filename: string
  channels: string[]
  n_samples: number
  sampling_rate_hz: number
  duration_s: number
}

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

  async openFile(path: string): Promise<TracePreview> {
    if (!this.sessionId) throw new Error('Session not initialized')
    const preview = await api.openFile({ path, session_id: this.sessionId })
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
