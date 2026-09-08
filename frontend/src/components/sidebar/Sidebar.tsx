import { useNavigate, useLocation } from 'react-router-dom'
import { NewChatButton } from './NewChatButton'
import { ConversationItem } from './ConversationItem'
import { useConversationStore } from '../../store/conversationStore'
import { useAuthStore } from '../../store/authStore'

interface SidebarProps {
  isOpen: boolean
  onToggle: () => void
}

const NAV_ITEMS = [
  {
    path: '/documents',
    label: 'Knowledge Base',
    icon: 'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10',
  },
  {
    path: '/doc-graph',
    label: 'Doc Connections',
    icon: 'M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4',
  },
  {
    path: '/templates',
    label: 'Report Templates',
    icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
  },
]

export function Sidebar({ isOpen, onToggle }: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const {
    conversations,
    currentConversationId,
    createConversation,
    deleteConversation,
    renameConversation,
    setCurrentConversation,
  } = useConversationStore()
  const { user, logout } = useAuthStore()

  const handleNewChat = async () => {
    const conversation = await createConversation()
    navigate(`/chat/${conversation.id}`)
  }

  const handleSelectConversation = (id: number) => {
    setCurrentConversation(id)
    navigate(`/chat/${id}`)
  }

  const handleRename = async (id: number, title: string) => {
    await renameConversation(id, title)
  }

  const handleDelete = async (id: number) => {
    await deleteConversation(id)
    if (currentConversationId === id) {
      navigate('/')
    }
  }

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-60 z-20 lg:hidden"
          onClick={onToggle}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed lg:relative z-30 h-full bg-dark-sidebar flex flex-col transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        } w-72 border-r border-dark-chat`}
      >
        {/* Header */}
        <div className="px-4 pt-4 pb-3 border-b border-dark-chat">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-dark-hover to-purple-600 flex items-center justify-center shrink-0">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                  />
                </svg>
              </div>
              <div>
                <h1 className="text-sm font-bold text-dark-text leading-none">ALAI</h1>
                <p className="text-[10px] text-dark-muted leading-none mt-0.5">Antara ETP</p>
              </div>
            </div>
            <button
              onClick={onToggle}
              className="lg:hidden p-1.5 hover:bg-dark-chat rounded-lg text-dark-muted hover:text-dark-text transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <NewChatButton onClick={handleNewChat} />
        </div>

        {/* Conversations list */}
        <div className="flex-1 overflow-y-auto p-2">
          {conversations.length > 0 ? (
            <div className="space-y-0.5">
              {conversations.map((conversation) => (
                <ConversationItem
                  key={conversation.id}
                  conversation={conversation}
                  isActive={conversation.id === currentConversationId}
                  onClick={() => handleSelectConversation(conversation.id)}
                  onRename={(title) => handleRename(conversation.id, title)}
                  onDelete={() => handleDelete(conversation.id)}
                />
              ))}
            </div>
          ) : (
            <div className="text-center text-dark-muted py-10">
              <svg className="w-8 h-8 mx-auto mb-2 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                />
              </svg>
              <p className="text-sm">No conversations yet</p>
              <p className="text-xs mt-0.5 opacity-70">Start a new chat to begin</p>
            </div>
          )}
        </div>

        {/* Tools nav */}
        <div className="px-3 py-2 border-t border-dark-chat">
          <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-widest px-2 mb-1.5">Tools</p>
          <div className="space-y-0.5">
            {NAV_ITEMS.map(({ path, label, icon }) => {
              const isActive = location.pathname === path
              return (
                <button
                  key={path}
                  onClick={() => navigate(path)}
                  className={`flex items-center gap-2.5 w-full px-3 py-2 text-sm rounded-lg transition-colors ${
                    isActive
                      ? 'bg-dark-chat text-dark-text'
                      : 'text-dark-muted hover:text-dark-text hover:bg-dark-chat/50'
                  }`}
                >
                  <svg
                    className={`w-4 h-4 shrink-0 ${isActive ? 'text-dark-hover' : ''}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={icon} />
                  </svg>
                  <span className={isActive ? 'font-medium' : ''}>{label}</span>
                  {isActive && (
                    <div className="ml-auto w-1.5 h-1.5 rounded-full bg-dark-hover" />
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* User section */}
        <div className="p-3 border-t border-dark-chat">
          {user && (
            <div className="flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-dark-chat/50 group">
              {user.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt={user.name || 'User'}
                  className="w-8 h-8 rounded-full shrink-0"
                />
              ) : (
                <div className="w-8 h-8 rounded-full bg-dark-hover flex items-center justify-center text-xs font-bold text-white shrink-0">
                  {(user.name?.[0] || user.email[0]).toUpperCase()}
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-dark-text truncate leading-tight">
                  {user.name || 'User'}
                </p>
                <p className="text-[11px] text-dark-muted truncate leading-tight">{user.email}</p>
              </div>
              <button
                onClick={logout}
                className="p-1.5 rounded-lg text-dark-muted hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                title="Sign out"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                  />
                </svg>
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
