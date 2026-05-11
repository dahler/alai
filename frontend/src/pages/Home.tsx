import { useNavigate } from 'react-router-dom'
import { useConversationStore } from '../store/conversationStore'

export default function Home() {
  const navigate = useNavigate()
  const createConversation = useConversationStore(
    (state) => state.createConversation
  )

  const handleNewChat = async () => {
    const conversation = await createConversation()
    navigate(`/chat/${conversation.id}`)
  }

  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-8">
      <div className="max-w-2xl">
        <div className="w-20 h-20 rounded-full bg-gradient-to-br from-dark-hover to-purple-600 flex items-center justify-center mx-auto mb-6">
          <svg
            className="w-10 h-10 text-white"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
            />
          </svg>
        </div>

        <h1 className="text-4xl font-bold text-dark-text mb-4">
          Welcome to <span className="text-dark-hover">ALAI</span>
        </h1>

        <p className="text-lg text-dark-muted mb-8">
          Your AI-powered assistant ready to help with coding, questions,
          explanations, and more. Start a conversation to explore what I can do!
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
          <div className="bg-dark-sidebar p-4 rounded-lg text-left">
            <div className="flex items-center gap-3 mb-2">
              <svg
                className="w-5 h-5 text-dark-hover"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"
                />
              </svg>
              <h3 className="font-semibold">Code Assistance</h3>
            </div>
            <p className="text-sm text-dark-muted">
              Get help with coding, debugging, and explaining code in any language.
            </p>
          </div>

          <div className="bg-dark-sidebar p-4 rounded-lg text-left">
            <div className="flex items-center gap-3 mb-2">
              <svg
                className="w-5 h-5 text-dark-hover"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                />
              </svg>
              <h3 className="font-semibold">Creative Ideas</h3>
            </div>
            <p className="text-sm text-dark-muted">
              Brainstorm ideas, get creative suggestions, and explore new concepts.
            </p>
          </div>

          <div className="bg-dark-sidebar p-4 rounded-lg text-left">
            <div className="flex items-center gap-3 mb-2">
              <svg
                className="w-5 h-5 text-dark-hover"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
                />
              </svg>
              <h3 className="font-semibold">Learning</h3>
            </div>
            <p className="text-sm text-dark-muted">
              Learn new topics, get explanations, and expand your knowledge.
            </p>
          </div>

          <div className="bg-dark-sidebar p-4 rounded-lg text-left">
            <div className="flex items-center gap-3 mb-2">
              <svg
                className="w-5 h-5 text-dark-hover"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                />
              </svg>
              <h3 className="font-semibold">Conversation</h3>
            </div>
            <p className="text-sm text-dark-muted">
              Have natural conversations with context-aware responses.
            </p>
          </div>
        </div>

        <button
          onClick={handleNewChat}
          className="inline-flex items-center gap-2 px-6 py-3 bg-dark-hover hover:bg-opacity-90 rounded-lg font-medium transition-colors"
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
              d="M12 4v16m8-8H4"
            />
          </svg>
          Start New Chat
        </button>
      </div>
    </div>
  )
}
