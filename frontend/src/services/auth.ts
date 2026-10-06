import { api } from './api'
import type { User } from '../types/auth'

export const authService = {
  async getLoginUrl(): Promise<string> {
    const response = await api.get<{ auth_url: string }>('/auth/login')
    return response.data.auth_url
  },

  async getCurrentUser(): Promise<User | null> {
    try {
      const response = await api.get<User>('/auth/me')
      return response.data
    } catch {
      return null
    }
  },

  async logout(): Promise<void> {
    await api.post('/auth/logout')
  },
}
