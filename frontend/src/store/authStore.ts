import { create } from 'zustand'
import type { User } from '../types/auth'
import { authService } from '../services/auth'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  checkAuth: () => Promise<void>
  login: () => Promise<void>
  logout: () => Promise<void>
  setUser: (user: User | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  checkAuth: async () => {
    set({ isLoading: true })
    try {
      if (authService.isAuthenticated()) {
        const user = await authService.getCurrentUser()
        set({ user, isAuthenticated: !!user, isLoading: false })
      } else {
        set({ user: null, isAuthenticated: false, isLoading: false })
      }
    } catch {
      set({ user: null, isAuthenticated: false, isLoading: false })
    }
  },

  login: async () => {
    try {
      const authUrl = await authService.getLoginUrl()
      window.location.href = authUrl
    } catch (error) {
      set({ error: 'Failed to initiate login' })
    }
  },

  logout: async () => {
    await authService.logout()
    set({ user: null, isAuthenticated: false })
  },

  setUser: (user) => {
    set({ user, isAuthenticated: !!user })
  },
}))
