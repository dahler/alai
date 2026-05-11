import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Loading } from '../components/common/Loading'
import { authService } from '../services/auth'
import { useAuthStore } from '../store/authStore'

export default function AuthCallback() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const checkAuth = useAuthStore((state) => state.checkAuth)

  useEffect(() => {
    const token = searchParams.get('token')

    if (token) {
      authService.setToken(token)
      checkAuth().then(() => {
        navigate('/')
      })
    } else {
      setError('No authentication token received')
    }
  }, [searchParams, navigate, checkAuth])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-dark-bg text-dark-text">
        <div className="text-red-500 text-lg mb-4">{error}</div>
        <button
          onClick={() => navigate('/')}
          className="px-4 py-2 bg-dark-hover rounded-lg"
        >
          Go Home
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-dark-bg">
      <Loading size="lg" text="Completing sign in..." />
    </div>
  )
}
