// Shared run/error/elapsed state, replacing the `running`/`error` pair that
// was hand-duplicated in six analysis panels plus TraceViewer/ForceExtensionViewer.
//
// Also the client half of the honest-cancellation story (see the backend's
// per-principal analysis semaphore + input-size guard in api/analysis.py):
// `stopWaiting()` aborts the *client's* wait via AbortController, it does not
// stop server-side computation that's already running -- there is no job
// queue to cancel into. RunButton.svelte labels this "Stop waiting", not
// "Cancel", for exactly that reason.

import { formatApiError } from './formatError'

const DEFAULT_TIMEOUT_MS = 60_000

export class RunState<T> {
  running = $state(false)
  error = $state('')
  elapsedMs = $state(0)
  result = $state<T | null>(null)

  private controller: AbortController | null = null
  private timer: ReturnType<typeof setInterval> | null = null

  /** Run `fn`, threading it an AbortSignal that fires on stopWaiting() or timeout. */
  async run(fn: (signal: AbortSignal) => Promise<T>, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T | undefined> {
    this.controller?.abort()
    const controller = new AbortController()
    this.controller = controller
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

    this.running = true
    this.error = ''
    this.elapsedMs = 0
    const t0 = performance.now()
    this.timer = setInterval(() => {
      this.elapsedMs = performance.now() - t0
    }, 100)

    try {
      const result = await fn(controller.signal)
      if (controller.signal.aborted) return undefined
      this.result = result
      return result
    } catch (e) {
      if (controller.signal.aborted) {
        this.error = 'Stopped waiting'
        return undefined
      }
      this.error = formatApiError(e)
      return undefined
    } finally {
      clearTimeout(timeoutId)
      if (this.controller === controller) {
        this.running = false
        if (this.timer) clearInterval(this.timer)
        this.timer = null
        this.controller = null
      }
    }
  }

  stopWaiting() {
    this.controller?.abort()
  }
}

export function useRun<T>(): RunState<T> {
  return new RunState<T>()
}
