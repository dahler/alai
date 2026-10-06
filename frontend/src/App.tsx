import { Routes, Route, useNavigate } from 'react-router-dom'
import { useEffect, lazy, Suspense } from 'react'
import MainLayout from './layouts/MainLayout'
import Home from './pages/Home'
import Login from './pages/Login'
import Chat from './pages/Chat'
import AuthCallback from './pages/AuthCallback'
import { useAuthStore } from './store/authStore'
import { registerNavigate } from './services/api'
import { Loading } from './components/common/Loading'

const Documents = lazy(() =>
  import('./pages/Documents').then(m => ({ default: m.Documents }))
)
const KnowledgeGraph = lazy(() =>
  import('./pages/KnowledgeGraph').then(m => ({ default: m.KnowledgeGraph }))
)
const DocumentGraph = lazy(() =>
  import('./pages/DocumentGraph').then(m => ({ default: m.DocumentGraph }))
)
const Templates = lazy(() =>
  import('./pages/Templates').then(m => ({ default: m.Templates }))
)

function App() {
  const { isAuthenticated, isLoading, checkAuth } = useAuthStore()
  const navigate = useNavigate()

  useEffect(() => {
    registerNavigate(navigate)
    checkAuth()
  }, [checkAuth, navigate])

  // Always allow the OAuth callback to render regardless of auth state
  if (window.location.pathname === '/auth/callback') {
    return (
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
      </Routes>
    )
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-dark-bg flex items-center justify-center">
        <Loading size="lg" text="Loading…" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Login />
  }

  const fallback = (
    <div className="min-h-screen bg-dark-bg flex items-center justify-center">
      <Loading size="lg" text="Loading…" />
    </div>
  )

  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Home />} />
        <Route path="chat/:conversationId" element={<Chat />} />
      </Route>
      <Route
        path="/documents"
        element={<Suspense fallback={fallback}><Documents /></Suspense>}
      />
      <Route
        path="/graph"
        element={<Suspense fallback={fallback}><KnowledgeGraph /></Suspense>}
      />
      <Route
        path="/doc-graph"
        element={<Suspense fallback={fallback}><DocumentGraph /></Suspense>}
      />
      <Route
        path="/templates"
        element={<Suspense fallback={fallback}><Templates /></Suspense>}
      />
      <Route path="/auth/callback" element={<AuthCallback />} />
    </Routes>
  )
}

export default App
