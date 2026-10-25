import type { FetchBaseQueryError } from '@reduxjs/toolkit/query'

type ApiError = { error?: { code?: string; message?: string; details?: { field: string; message: string }[] } }

export function getHttpStatus(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null || !('status' in error)) return undefined
  const status = (error as FetchBaseQueryError).status
  return typeof status === 'number' ? status : undefined
}

export function getApiErrorCode(error: unknown): string | undefined {
  if (typeof error !== 'object' || error === null || !('data' in error)) return undefined
  const data = (error as { data?: ApiError }).data
  return typeof data?.error?.code === 'string' ? data.error.code : undefined
}

export function getSafeErrorMessage(error: unknown, fallback: string): string {
  if (typeof error !== 'object' || error === null || !('data' in error)) return fallback
  const data = (error as { data?: ApiError }).data
  const message = data?.error?.message
  return typeof message === 'string' && message.length > 0 && message.length <= 240 ? message : fallback
}
