import { useNavigate } from 'react-router-dom'
import { NewChatButton } from './NewChatButton'
import { ConversationItem } from './ConversationItem'
import { LoginButton } from '../auth/LoginButton'
import { useConversationStore } from '../../store/conversationStore'
import { useAuthStore } from '../../store/authStore'

interface SidebarProps {
  isOpen: boolean
  onToggle: () => void
}

export function Sidebar({ isOpen, onToggle }: SidebarProps) {
  const navigate = useNavigate()
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
          className="fixed inset-0 bg-black bg-opacity-50 z-20 lg:hidden"
          onClick={onToggle}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed lg:relative z-30 h-full bg-dark-sidebar flex flex-col transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        } w-72`}
      >
        {/* Header */}
        <div className="p-4 border-b border-dark-chat">
          <div className="flex items-center justify-between mb-4">
            <h1 className="text-xl font-bold text-dark-text tracking-wide">ALAI</h1>
            <button
              onClick={onToggle}
              className="lg:hidden p-2 hover:bg-dark-chat rounded-lg"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
          <NewChatButton onClick={handleNewChat} />
        </div>

        {/* Conversations list */}
        <div className="flex-1 overflow-y-auto p-2">
          <div className="space-y-1">
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

          {conversations.length === 0 && (
            <div className="text-center text-dark-muted py-8">
              <p>No conversations yet</p>
              <p className="text-sm mt-1">Start a new chat to begin</p>
            </div>
          )}
        </div>

        {/* Nav section */}
        <div className="px-4 py-2 border-t border-dark-chat space-y-1">
          <button
            onClick={() => navigate('/documents')}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm text-dark-muted hover:text-dark-text hover:bg-dark-chat rounded-lg transition-colors"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
              />
            </svg>
            Knowledge Base
          </button>
          <button
            onClick={() => navigate('/graph')}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm text-dark-muted hover:text-dark-text hover:bg-dark-chat rounded-lg transition-colors"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
            Knowledge Graph
          </button>
          <button
            onClick={() => navigate('/templates')}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm text-dark-muted hover:text-dark-text hover:bg-dark-chat rounded-lg transition-colors"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            Report Templates
          </button>
        </div>

        {/* User section */}
        <div className="p-4 border-t border-dark-chat">
          {user ? (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {user.avatar_url ? (
                  <img
                    src={user.avatar_url}
                    alt={user.name || 'User'}
                    className="w-8 h-8 rounded-full"
                  />
                ) : (
                  <div className="w-8 h-8 rounded-full bg-dark-hover flex items-center justify-center text-sm font-medium">
                    {user.name?.[0] || user.email[0].toUpperCase()}
                  </div>
                )}
                <div className="truncate">
                  <p className="text-sm font-medium truncate">
                    {user.name || 'User'}
                  </p>
                  <p className="text-xs text-dark-muted truncate">{user.email}</p>
                </div>
              </div>
              <button
                onClick={logout}
                className="p-2 hover:bg-dark-chat rounded-lg text-dark-muted hover:text-dark-text"
                title="Logout"
              >
                <svg
                  className="w-5 h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                  />
                </svg>
              </button>
            </div>
          ) : (
            <LoginButton />
          )}
        </div>
      </aside>
    </>
  )
}
