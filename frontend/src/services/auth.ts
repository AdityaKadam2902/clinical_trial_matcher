import { api } from './api'
import { tokenStore, type TokenPair } from './token'

export interface CurrentUser {
  id: string | null
  email: string
  full_name?: string | null
  role: string
  is_active: boolean
  is_verified: boolean
}

export const login = async (email: string, password: string): Promise<TokenPair> => {
  const body = new URLSearchParams({ username: email, password })
  const { data } = await api.post<TokenPair>('/auth/login', body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  tokenStore.set(data)
  return data
}

export const getMe = async (): Promise<CurrentUser> => {
  const { data } = await api.get<CurrentUser>('/auth/me')
  return data
}

export const logout = async (): Promise<void> => {
  const refreshToken = tokenStore.getRefresh()
  try {
    if (refreshToken) {
      await api.post('/auth/logout', { refresh_token: refreshToken })
    }
  } finally {
    tokenStore.clear()
  }
}
