import { useNavigate } from 'react-router-dom'
import { useConversationStore } from '../store/conversationStore'
import { useAuthStore } from '../store/authStore'

const CAPABILITIES = [
  {
    icon: 'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10',
    title: 'Search Company Knowledge',
    desc: 'Find answers from SOPs, policies, procedures, and internal documents instantly.',
  },
  {
    icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
    title: 'Analyze Documents',
    desc: 'Upload files and ask questions — ALAI reads and summarizes them for you.',
  },
  {
    icon: 'M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
    title: 'Generate Reports',
    desc: 'Create Excel, Word, PDF, or PowerPoint reports from your data and templates.',
  },
  {
    icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
    title: 'Email & Live Data',
    desc: 'Read and send emails, get live exchange rates, stock prices, and news.',
  },
]

const EXAMPLE_PROMPTS = [
  'Siapa yang memberikan approval untuk pembelian di atas 50 juta?',
  'Buatkan rekap data penjualan dalam format Excel',
  'Rangkum dokumen yang saya upload ini',
  'Berapa kurs USD/IDR hari ini?',
]

export default function Home() {
  const navigate = useNavigate()
  const createConversation = useConversationStore((state) => state.createConversation)
  const user = useAuthStore((state) => state.user)

  const handleNewChat = async () => {
    const conversation = await createConversation()
    navigate(`/chat/${conversation.id}`)
  }

  const firstName = user?.name?.split(' ')[0] || 'there'

  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-6 overflow-y-auto">
      <div className="max-w-2xl w-full py-8">

        {/* Greeting */}
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-dark-hover to-purple-600 flex items-center justify-center mx-auto mb-5 shadow-lg shadow-dark-hover/20">
          <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
            />
          </svg>
        </div>

        <h1 className="text-3xl font-bold mb-1">
          Halo, <span className="text-gradient">{firstName}</span>!
        </h1>
        <p className="text-dark-muted mb-8">Apa yang bisa ALAI bantu hari ini?</p>

        {/* Example prompts */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mb-8">
          {EXAMPLE_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              onClick={handleNewChat}
              className="text-left px-4 py-3 bg-dark-sidebar hover:bg-dark-chat border border-dark-chat hover:border-dark-hover rounded-lg text-sm text-dark-muted hover:text-dark-text transition-all"
            >
              {prompt}
            </button>
          ))}
        </div>

        {/* New chat button */}
        <button
          onClick={handleNewChat}
          className="inline-flex items-center gap-2 px-6 py-3 bg-dark-hover hover:bg-opacity-90 rounded-lg font-medium transition-colors text-white mb-10"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Mulai Chat Baru
        </button>

        {/* Capabilities */}
        <div className="border-t border-dark-chat pt-8">
          <p className="text-xs text-dark-muted uppercase tracking-widest mb-4">Yang bisa ALAI lakukan</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
            {CAPABILITIES.map(({ icon, title, desc }) => (
              <div key={title} className="bg-dark-sidebar border border-dark-chat rounded-lg p-4">
                <div className="flex items-center gap-2.5 mb-1.5">
                  <svg className="w-4 h-4 text-dark-hover shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={icon} />
                  </svg>
                  <h3 className="text-sm font-semibold text-dark-text">{title}</h3>
                </div>
                <p className="text-xs text-dark-muted leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
