import { Routes, Route } from 'react-router-dom'
import { useEffect } from 'react'
import MainLayout from './layouts/MainLayout'
import Home from './pages/Home'
import Chat from './pages/Chat'
import AuthCallback from './pages/AuthCallback'
import { Files } from './pages/Files'
import { Documents } from './pages/Documents'
import { KnowledgeGraph } from './pages/KnowledgeGraph'
import { useAuthStore } from './store/authStore'

function App() {
  const checkAuth = useAuthStore((state) => state.checkAuth)

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Home />} />
        <Route path="chat/:conversationId" element={<Chat />} />
      </Route>
      <Route path="/files" element={<Files />} />
      <Route path="/documents" element={<Documents />} />
      <Route path="/graph" element={<KnowledgeGraph />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
    </Routes>
  )
}

export default App
