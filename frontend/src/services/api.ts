import axios, { AxiosError } from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

export const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // sends the auth_token httponly cookie automatically
})

// Registered by the router once it mounts — lets the axios interceptor
// do a client-side redirect instead of a hard page reload.
let _navigate: ((path: string) => void) | null = null
export function registerNavigate(fn: (path: string) => void) {
  _navigate = fn
}

/** Navigate programmatically; falls back to hard reload if router not ready. */
export function navigateTo(path: string): void {
  if (_navigate) {
    _navigate(path)
  } else {
    window.location.href = path
  }
}

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      if (_navigate) {
        _navigate('/')
      } else {
        window.location.href = '/'
      }
    }
    return Promise.reject(error)
  }
)
