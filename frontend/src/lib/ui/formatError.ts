import { ApiError } from '../api'

/** Replaces the `e instanceof ApiError ? ... : String(e)` line duplicated across every panel. */
export function formatApiError(e: unknown): string {
  if (e instanceof ApiError) return `${e.status}: ${e.message}`
  if (e instanceof Error) return e.message
  return String(e)
}
