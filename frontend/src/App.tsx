import { Routes, Route, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import MainLayout from './layouts/MainLayout'
import Home from './pages/Home'
import Chat from './pages/Chat'
import AuthCallback from './pages/AuthCallback'
import { Documents } from './pages/Documents'
import { KnowledgeGraph } from './pages/KnowledgeGraph'
import { DocumentGraph } from './pages/DocumentGraph'
import { Templates } from './pages/Templates'
import { useAuthStore } from './store/authStore'
import { registerNavigate } from './services/api'

function App() {
  const checkAuth = useAuthStore((state) => state.checkAuth)
  const navigate = useNavigate()

  useEffect(() => {
    registerNavigate(navigate)
    checkAuth()
  }, [checkAuth, navigate])

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
