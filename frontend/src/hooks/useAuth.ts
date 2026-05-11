import { useAuthStore } from '../store/authStore'

export function useAuth() {
  const { user, isAuthenticated, isLoading, error, login, logout, checkAuth } =
    useAuthStore()

  return {
    user,
    isAuthenticated,
    isLoading,
    error,
    login,
    logout,
    checkAuth,
  }
}
