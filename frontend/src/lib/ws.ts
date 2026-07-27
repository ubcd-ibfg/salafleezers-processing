// Thin wrapper around the /ws/session/{id} protocol documented in
// src/salafleezers/web/ws/session.py.

import { api } from './api'

export interface WsTraceMsg {
  type: 'trace'
  file_id: string
  channel: string
  time: number[]
  data: number[]
}

export interface WsCropAckMsg {
  type: 'crop_ack'
  file_id: string
  t_start: number
  t_end: number
  channels: Record<string, { time: number[]; data: number[] }>
}

export interface WsMeasurementMsg {
  type: 'measurement'
  file_id: string
  mean: number
  std: number
  median: number
  min: number
  max: number
  n_pts: number
  t_start: number
  t_end: number
  duration: number
}

export interface WsErrorMsg {
  type: 'error'
  detail: string
}

export interface WsPongMsg {
  type: 'pong'
}

export type WsMessage = WsTraceMsg | WsCropAckMsg | WsMeasurementMsg | WsErrorMsg | WsPongMsg

type Listener = (msg: WsMessage) => void

export class SessionSocket {
  private ws: WebSocket | null = null
  private listeners = new Set<Listener>()
  private queue: string[] = []
  private sessionId: string

  constructor(sessionId: string) {
    this.sessionId = sessionId
    this.connect()
  }

  private async connect() {
    // Browsers can't attach an Authorization header to a WS handshake, so a
    // short-lived single-use ticket (see web/auth.py) stands in for one.
    // Fetching it always -- even with auth disabled, where the server just
    // returns a ticket for the anonymous principal -- keeps this path
    // uniform instead of duplicating the server's auth_required() branch here.
    let ticketQs = ''
    try {
      const { ticket } = await api.wsTicket()
      ticketQs = `?ticket=${encodeURIComponent(ticket)}`
    } catch {
      // Ticket endpoint unreachable -- fall back to a bare connect; the
      // server rejects it with a clear close code if auth is required.
    }

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws/session/${this.sessionId}${ticketQs}`
    this.ws = new WebSocket(url)
    this.ws.onopen = () => {
      for (const msg of this.queue.splice(0)) this.ws!.send(msg)
    }
    this.ws.onmessage = (ev) => {
      let parsed: WsMessage
      try {
        parsed = JSON.parse(ev.data)
      } catch {
        return
      }
      for (const l of this.listeners) l(parsed)
    }
    this.ws.onclose = () => {
      this.ws = null
    }
  }

  onMessage(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private send(payload: Record<string, unknown>) {
    const text = JSON.stringify(payload)
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(text)
    } else {
      this.queue.push(text)
    }
  }

  ping() {
    this.send({ type: 'ping' })
  }

  filter(fileId: string, channel: string, halfWidth: number, decimate: number) {
    this.send({ type: 'filter', file_id: fileId, channel, half_width: halfWidth, decimate })
  }

  crop(fileId: string, tStart: number, tEnd: number, channels: string[], decimate: number) {
    this.send({ type: 'crop', file_id: fileId, t_start: tStart, t_end: tEnd, channels, decimate })
  }

  measure(fileId: string, channel: string, tStart: number, tEnd: number) {
    this.send({ type: 'measure', file_id: fileId, channel, t_start: tStart, t_end: tEnd })
  }

  decimate(fileId: string, channel: string, factor: number, tStart?: number, tEnd?: number) {
    this.send({ type: 'decimate', file_id: fileId, channel, factor, t_start: tStart, t_end: tEnd })
  }

  close() {
    this.ws?.close()
    this.listeners.clear()
  }
}
