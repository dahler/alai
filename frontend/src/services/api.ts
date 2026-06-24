import axios, { AxiosError } from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

export const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
})

// Request interceptor to add auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Registered by the router once it mounts — lets the axios interceptor
// do a client-side redirect instead of a hard page reload.
let _navigate: ((path: string) => void) | null = null
export function registerNavigate(fn: (path: string) => void) {
  _navigate = fn
}

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      if (_navigate) {
        _navigate('/')
      } else {
        window.location.href = '/'
      }
    }
    return Promise.reject(error)
  }
)

export const setAuthToken = (token: string | null) => {
  if (token) {
    localStorage.setItem('token', token)
  } else {
    localStorage.removeItem('token')
  }
}
