import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { ApiEnvelope, TokenResponse } from '../types/api'

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000'

const ACCESS_TOKEN_KEY = 'swms_access_token'
const REFRESH_TOKEN_KEY = 'swms_refresh_token'

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

export function isAuthenticated(): boolean {
  return getAccessToken() !== null
}

/** Fired when a refresh attempt fails (refresh token missing/expired) —
 * App.tsx listens for this to drop back to the login screen. */
export const AUTH_EXPIRED_EVENT = 'swms:auth-expired'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

// A single in-flight refresh shared by every 401'd request that arrives
// while it's running, so a burst of concurrent requests (e.g. the KPI
// cards + chart firing at once) triggers exactly one POST /auth/refresh,
// not one per request.
let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null
  try {
    const response = await axios.post<ApiEnvelope<TokenResponse>>(
      `${API_BASE_URL}/api/v1/auth/refresh`,
      { refresh_token: refreshToken },
      { headers: { 'Content-Type': 'application/json' } },
    )
    if (!response.data.success) return null
    setTokens(response.data.data.access_token, response.data.data.refresh_token)
    return response.data.data.access_token
  } catch {
    return null
  }
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined
    const isAuthEndpoint = original?.url?.includes('/auth/login') || original?.url?.includes('/auth/refresh')

    if (error.response?.status === 401 && original && !original._retried && !isAuthEndpoint) {
      original._retried = true
      refreshInFlight ??= refreshAccessToken().finally(() => {
        refreshInFlight = null
      })
      const newToken = await refreshInFlight
      if (newToken) {
        original.headers.set('Authorization', `Bearer ${newToken}`)
        return apiClient(original)
      }
      clearTokens()
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    }
    return Promise.reject(error)
  },
)

/** Unwraps the backend's {success, data}/{success, error} envelope into a
 * plain value or a thrown Error carrying the backend's own message/code. */
export function unwrap<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.success) return envelope.data
  const err = new Error(envelope.error.message) as Error & { code?: string }
  err.code = envelope.error.code
  throw err
}

/** login/register call the bare `axios` instance, not `apiClient` — using
 * the interceptor-wrapped client here would risk it trying to attach a
 * (nonexistent) auth token or trigger a refresh loop on the very endpoints
 * that establish auth in the first place. The cost: axios throws directly
 * on a non-2xx response before `unwrap()` ever runs, so the backend's own
 * clean error message (e.g. "Incorrect email or password", "An account
 * with this email already exists") never reached the caller — found while
 * wiring up registration, but it silently affected login too. This pulls
 * that message out of the AxiosError's own response body instead of
 * surfacing axios's generic "Request failed with status code 401" text. */
function authErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const body = err.response?.data as ApiEnvelope<unknown> | undefined
    if (body && body.success === false) return body.error.message
  }
  return err instanceof Error ? err.message : 'Request failed'
}

export async function login(email: string, password: string): Promise<void> {
  try {
    const response = await axios.post<ApiEnvelope<TokenResponse>>(
      `${API_BASE_URL}/api/v1/auth/login`,
      { email, password },
      { headers: { 'Content-Type': 'application/json' } },
    )
    const token = unwrap(response.data)
    setTokens(token.access_token, token.refresh_token)
  } catch (err) {
    throw new Error(authErrorMessage(err))
  }
}

/** Self-registration always lands as RESEARCHER — the backend forces this
 * server-side (app/auth/service.py's register_user ignores any role the
 * client sends) regardless of what this call passes, so there's nothing
 * to configure here; only an ADMIN can elevate a user afterwards. */
export async function register(email: string, password: string, fullName: string): Promise<void> {
  try {
    await axios.post<ApiEnvelope<unknown>>(
      `${API_BASE_URL}/api/v1/auth/register`,
      { email, password, full_name: fullName },
      { headers: { 'Content-Type': 'application/json' } },
    )
  } catch (err) {
    throw new Error(authErrorMessage(err))
  }
  await login(email, password)
}

export function logout(): void {
  clearTokens()
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
}
