import { auth } from './stores/auth.svelte'
import type {
  Dataset,
  FileOpenRequest,
  HealthInfo,
  KDERequest,
  KDEResult,
  KineticsRequest,
  KineticsResult,
  MSDRequest,
  MSDResult,
  PWDRequest,
  PWDResult,
  SessionInfo,
  StepFindRequest,
  StepFindResult,
  TraceMetadata,
  TracePreview,
  TraceSegment,
  UploadedFileInfo,
  VelocityRequest,
  VelocityResult,
  ViolinRequest,
  ViolinResult,
  WLCFitRequest,
  WLCFitResult,
  WsTicket,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const DEFAULT_TIMEOUT_MS = 60_000

async function request<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal; timeoutMs?: number },
): Promise<T> {
  const { signal: callerSignal, timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = init ?? {}
  // A hung network connection or a server-side stall must not leave a
  // RunButton spinning forever, so every request carries a default timeout
  // in addition to whatever cancellation the caller wired up. See useRun.svelte.ts.
  const timeoutSignal = AbortSignal.timeout(timeoutMs)
  const signal = callerSignal ? AbortSignal.any([callerSignal, timeoutSignal]) : timeoutSignal

  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`

  const res = await fetch(path, { headers, signal, ...rest })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // ignore — no JSON body
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) usp.set(k, String(v))
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}

type Opts = { signal?: AbortSignal; timeoutMs?: number }

export const api = {
  health: () => request<HealthInfo>('/api/health'),
  wsTicket: () => request<WsTicket>('/api/ws-ticket', { method: 'POST' }),

  // Sessions
  createSession: () => request<SessionInfo>('/api/sessions', { method: 'POST' }),
  listSessions: () => request<SessionInfo[]>('/api/sessions'),
  getSession: (id: string) => request<SessionInfo>(`/api/sessions/${id}`),
  deleteSession: (id: string) => request<{ deleted: string }>(`/api/sessions/${id}`, { method: 'DELETE' }),
  saveSession: (id: string) => request<{ saved_to: string }>(`/api/sessions/${id}/save`, { method: 'POST' }),
  loadSession: (id: string) =>
    request<{ loaded: string; n_files: number; n_files_unavailable: number; unavailable_file_ids: string[] }>(
      `/api/sessions/load/${id}`,
      { method: 'POST' },
    ),

  // Files
  openFile: (body: FileOpenRequest, opts?: Opts) =>
    request<TracePreview>('/api/files/open', { method: 'POST', body: JSON.stringify(body), ...opts }),
  fileInfo: (fileId: string, sessionId: string) =>
    request<TraceMetadata>(`/api/files/${fileId}/info${qs({ session_id: sessionId })}`),

  // Uploads
  createDataset: (name: string) =>
    request<Dataset>('/api/uploads', { method: 'POST', body: JSON.stringify({ name }) }),
  finalizeDataset: (datasetId: string) =>
    request<Dataset>(`/api/uploads/${datasetId}/finalize`, { method: 'POST' }),
  listDatasets: () => request<Dataset[]>('/api/uploads'),
  getDataset: (datasetId: string) => request<Dataset>(`/api/uploads/${datasetId}`),
  deleteDataset: (datasetId: string) =>
    request<{ deleted: string }>(`/api/uploads/${datasetId}`, { method: 'DELETE' }),
  /**
   * XHR-based, not fetch: `fetch` has no upload-progress event, and progress
   * feedback is the point when a folder drop can be hundreds of files.
   */
  uploadFile: (
    datasetId: string,
    relativePath: string,
    file: File,
    opts: { onProgress?: (loaded: number, total: number) => void; signal?: AbortSignal } = {},
  ): Promise<UploadedFileInfo> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `/api/uploads/${datasetId}/files`)
      if (auth.token) xhr.setRequestHeader('Authorization', `Bearer ${auth.token}`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) opts.onProgress?.(e.loaded, e.total)
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            reject(new ApiError(xhr.status, 'Invalid response body'))
          }
          return
        }
        let detail = xhr.statusText || `HTTP ${xhr.status}`
        try {
          const body = JSON.parse(xhr.responseText)
          detail = body.detail ?? detail
        } catch {
          // ignore — no JSON body
        }
        reject(new ApiError(xhr.status, detail))
      }
      xhr.onerror = () => reject(new ApiError(0, 'Network error'))
      xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'))
      if (opts.signal) {
        if (opts.signal.aborted) {
          xhr.abort()
          return
        }
        opts.signal.addEventListener('abort', () => xhr.abort())
      }
      const form = new FormData()
      form.append('relative_path', relativePath)
      form.append('file', file)
      xhr.send(form)
    }),

  // Traces
  getTrace: (
    fileId: string,
    opts: { session_id: string; channel: string; decimate?: number; t_start?: number | null; t_end?: number | null },
  ) => request<TraceSegment>(`/api/traces/${fileId}${qs(opts)}`),

  // Analysis
  stepFind: (body: StepFindRequest, opts?: Opts) =>
    request<StepFindResult>('/api/stepfind', { method: 'POST', body: JSON.stringify(body), ...opts }),
  wlcFit: (body: WLCFitRequest, opts?: Opts) =>
    request<WLCFitResult>('/api/wlc/fit', { method: 'POST', body: JSON.stringify(body), ...opts }),
  velocity: (body: VelocityRequest, opts?: Opts) =>
    request<VelocityResult>('/api/velocity', { method: 'POST', body: JSON.stringify(body), ...opts }),
  pwd: (body: PWDRequest, opts?: Opts) =>
    request<PWDResult>('/api/pwd', { method: 'POST', body: JSON.stringify(body), ...opts }),
  kineticsFit: (body: KineticsRequest, opts?: Opts) =>
    request<KineticsResult>('/api/kinetics/fit', { method: 'POST', body: JSON.stringify(body), ...opts }),
  kde: (body: KDERequest, opts?: Opts) =>
    request<KDEResult>('/api/kde', { method: 'POST', body: JSON.stringify(body), ...opts }),
  violin: (body: ViolinRequest, opts?: Opts) =>
    request<ViolinResult>('/api/violin', { method: 'POST', body: JSON.stringify(body), ...opts }),
  msd: (body: MSDRequest, opts?: Opts) =>
    request<MSDResult>('/api/msd', { method: 'POST', body: JSON.stringify(body), ...opts }),
}
