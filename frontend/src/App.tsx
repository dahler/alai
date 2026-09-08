import { Routes, Route, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import MainLayout from './layouts/MainLayout'
import Home from './pages/Home'
import Login from './pages/Login'
import Chat from './pages/Chat'
import AuthCallback from './pages/AuthCallback'
import { Documents } from './pages/Documents'
import { KnowledgeGraph } from './pages/KnowledgeGraph'
import { DocumentGraph } from './pages/DocumentGraph'
import { Templates } from './pages/Templates'
import { useAuthStore } from './store/authStore'
import { registerNavigate } from './services/api'
import { Loading } from './components/common/Loading'

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

  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Home />} />
        <Route path="chat/:conversationId" element={<Chat />} />
      </Route>
      <Route path="/documents" element={<Documents />} />
      <Route path="/graph" element={<KnowledgeGraph />} />
      <Route path="/doc-graph" element={<DocumentGraph />} />
      <Route path="/templates" element={<Templates />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
    </Routes>
  )
}

export default App
