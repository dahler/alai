import { useState, useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from '../components/sidebar/Sidebar'
import { useConversations } from '../hooks/useConversations'

export default function MainLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { fetchConversations } = useConversations()

  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])

  return (
    <div className="flex h-screen bg-dark-bg">
      {/* Sidebar */}
      <Sidebar isOpen={sidebarOpen} onToggle={() => setSidebarOpen(!sidebarOpen)} />

      {/* Main content */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Mobile header */}
        <header className="lg:hidden flex items-center justify-between p-4 border-b border-dark-sidebar">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 hover:bg-dark-sidebar rounded-lg"
          >
            <svg
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
          <h1 className="text-lg font-bold text-dark-hover">ALAI</h1>
          <div className="w-10" /> {/* Spacer for centering */}
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-hidden">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
