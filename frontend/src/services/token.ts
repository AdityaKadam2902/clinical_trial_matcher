const ACCESS_TOKEN_KEY = 'ctm_access_token'
const REFRESH_TOKEN_KEY = 'ctm_refresh_token'

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type?: string
  expires_in?: number
}

export const tokenStore = {
  getAccess: (): string | null => localStorage.getItem(ACCESS_TOKEN_KEY),
  getRefresh: (): string | null => localStorage.getItem(REFRESH_TOKEN_KEY),
  set: (tokens: TokenPair): void => {
    localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token)
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
  },
  clear: (): void => {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  },
}
