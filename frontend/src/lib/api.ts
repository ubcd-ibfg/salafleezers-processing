import type {
  FileOpenRequest,
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
  VelocityRequest,
  VelocityResult,
  ViolinRequest,
  ViolinResult,
  WLCFitRequest,
  WLCFitResult,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
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

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),

  // Sessions
  createSession: () => request<SessionInfo>('/api/sessions', { method: 'POST' }),
  listSessions: () => request<SessionInfo[]>('/api/sessions'),
  getSession: (id: string) => request<SessionInfo>(`/api/sessions/${id}`),
  deleteSession: (id: string) => request<{ deleted: string }>(`/api/sessions/${id}`, { method: 'DELETE' }),
  saveSession: (id: string) => request<{ saved_to: string }>(`/api/sessions/${id}/save`, { method: 'POST' }),
  loadSession: (id: string) =>
    request<{ loaded: string; n_files_reloaded: number }>(`/api/sessions/load/${id}`, { method: 'POST' }),

  // Files
  openFile: (body: FileOpenRequest) =>
    request<TracePreview>('/api/files/open', { method: 'POST', body: JSON.stringify(body) }),
  fileInfo: (fileId: string, sessionId: string) =>
    request<TraceMetadata>(`/api/files/${fileId}/info${qs({ session_id: sessionId })}`),

  // Traces
  getTrace: (
    fileId: string,
    opts: { session_id: string; channel: string; decimate?: number; t_start?: number | null; t_end?: number | null },
  ) => request<TraceSegment>(`/api/traces/${fileId}${qs(opts)}`),

  // Analysis
  stepFind: (body: StepFindRequest) =>
    request<StepFindResult>('/api/stepfind', { method: 'POST', body: JSON.stringify(body) }),
  wlcFit: (body: WLCFitRequest) =>
    request<WLCFitResult>('/api/wlc/fit', { method: 'POST', body: JSON.stringify(body) }),
  velocity: (body: VelocityRequest) =>
    request<VelocityResult>('/api/velocity', { method: 'POST', body: JSON.stringify(body) }),
  pwd: (body: PWDRequest) => request<PWDResult>('/api/pwd', { method: 'POST', body: JSON.stringify(body) }),
  kineticsFit: (body: KineticsRequest) =>
    request<KineticsResult>('/api/kinetics/fit', { method: 'POST', body: JSON.stringify(body) }),
  kde: (body: KDERequest) => request<KDEResult>('/api/kde', { method: 'POST', body: JSON.stringify(body) }),
  violin: (body: ViolinRequest) =>
    request<ViolinResult>('/api/violin', { method: 'POST', body: JSON.stringify(body) }),
  msd: (body: MSDRequest) => request<MSDResult>('/api/msd', { method: 'POST', body: JSON.stringify(body) }),
}
