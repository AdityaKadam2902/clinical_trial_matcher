import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import type { PatientProfile, MatchResponse } from '../types'
import { tokenStore } from './token'

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  // Must stay above the backend pipeline budget (PIPELINE_BUDGET_SECONDS),
  // otherwise the UI aborts while the server is still working.
  timeout: 300000,
})

api.interceptors.request.use(config => {
  const accessToken = tokenStore.getAccess()
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

type RetryableRequest = InternalAxiosRequestConfig & { _retry?: boolean }
let refreshInFlight: Promise<string | null> | null = null

const refreshAccessToken = async (): Promise<string | null> => {
  const refreshToken = tokenStore.getRefresh()
  if (!refreshToken) return null
  const { data } = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
  tokenStore.set(data)
  return data.access_token as string
}

api.interceptors.response.use(
  response => response,
  async (error: AxiosError) => {
    const original = error.config as RetryableRequest | undefined
    const status = error.response?.status
    const isAuthRequest = original?.url?.includes('/auth/login') || original?.url?.includes('/auth/refresh')

    if (status === 401 && original && !original._retry && !isAuthRequest) {
      original._retry = true
      try {
        refreshInFlight ??= refreshAccessToken()
        const accessToken = await refreshInFlight
        if (!accessToken) throw new Error('No refresh token available')
        original.headers.Authorization = `Bearer ${accessToken}`
        return api(original)
      } catch {
        tokenStore.clear()
        window.dispatchEvent(new Event('ctm:unauthorized'))
      } finally {
        refreshInFlight = null
      }
    }

    return Promise.reject(error)
  }
)

export const getErrorMessage = (err: unknown, fallback = 'An unexpected error occurred.'): string => {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as
      | { error?: { message?: string }; detail?: string | Array<{ msg?: string }> }
      | undefined
    if (data?.error?.message) return data.error.message
    if (typeof data?.detail === 'string') return data.detail
    if (Array.isArray(data?.detail)) {
      return data.detail.map(item => item?.msg ?? String(item)).join('; ')
    }
    return err.message || fallback
  }
  return err instanceof Error ? err.message : fallback
}

export const matchTrials = async (
  patient: PatientProfile,
  page = 1,
  pageSize = 10
): Promise<MatchResponse> => {
  const { data } = await api.post<MatchResponse>(
    `/match?page=${page}&page_size=${pageSize}`,
    patient
  )
  return data
}

export const getTrial = async (nctId: string) => {
  const { data } = await api.get(`/trial/${nctId}`)
  return data
}

export const checkDrugInteraction = async (drug1: string, drug2: string) => {
  const { data } = await api.get('/drugs/check', { params: { drug1, drug2 } })
  return data
}

export const normalizeDrug = async (name: string) => {
  const { data } = await api.get('/drugs/normalize', { params: { name } })
  return data
}

export const healthCheck = async () => {
  const { data } = await api.get('/health')
  return data
}
