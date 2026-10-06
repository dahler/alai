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

const EXAMPLE_PROMPTS: { id: string; text: string; subtitle: string }[] = [
  {
    id: 'approval',
    text: 'Siapa yang memberikan approval untuk pembelian di atas 50 juta?',
    subtitle: 'Who approves purchases over 50M IDR?',
  },
  {
    id: 'excel',
    text: 'Buatkan rekap data penjualan dalam format Excel',
    subtitle: 'Create a sales summary in Excel format',
  },
  {
    id: 'summarize',
    text: 'Rangkum dokumen yang saya upload ini',
    subtitle: 'Summarize the document I uploaded',
  },
  {
    id: 'forex',
    text: 'Berapa kurs USD/IDR hari ini?',
    subtitle: "What is today's USD/IDR exchange rate?",
  },
]

export default function Home() {
  const navigate = useNavigate()
  const createConversation = useConversationStore((state) => state.createConversation)
  const user = useAuthStore((state) => state.user)

  const handleNewChat = async (starterPrompt?: string) => {
    const conversation = await createConversation()
    if (starterPrompt) {
      sessionStorage.setItem('starter_prompt', starterPrompt)
    }
    navigate(`/chat/${conversation.id}`)
  }

  const firstName = user?.name?.split(' ')[0] || 'there'

  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-6 overflow-y-auto">
      <div className="max-w-xl w-full py-10">

        {/* Greeting */}
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-dark-hover to-amber-500 flex items-center justify-center mx-auto mb-6 shadow-glow">
          <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
            />
          </svg>
        </div>

        <h1 className="text-3xl font-bold mb-1 tracking-tight">
          Halo, <span className="text-gradient">{firstName}</span>!
        </h1>
        <p className="text-dark-muted/80 mb-10 text-sm">Apa yang bisa ALAI bantu hari ini?</p>

        {/* Example prompts */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-8 w-full">
          {EXAMPLE_PROMPTS.map((prompt) => (
            <button
              key={prompt.id}
              onClick={() => handleNewChat(prompt.text)}
              className="text-left px-4 py-3.5 bg-dark-sidebar hover:bg-dark-chat rounded-2xl transition-all group"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm text-dark-text leading-snug">{prompt.text}</p>
                  <p className="text-[11px] text-dark-muted mt-1">{prompt.subtitle}</p>
                </div>
                <svg className="w-3.5 h-3.5 text-dark-muted/50 group-hover:text-dark-hover mt-0.5 flex-shrink-0 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </button>
          ))}
        </div>

        {/* New chat button */}
        <button
          onClick={() => handleNewChat()}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-dark-hover hover:bg-amber-700 rounded-2xl font-medium transition-colors text-white text-sm mb-12 shadow-glow-sm"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Mulai Chat Baru
        </button>

        {/* Capabilities */}
        <div className="w-full">
          <p className="text-[10px] font-semibold text-dark-muted/60 uppercase tracking-widest mb-3">Kemampuan ALAI</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-left">
            {CAPABILITIES.map(({ icon, title, desc }) => (
              <div key={title} className="bg-dark-sidebar/80 rounded-2xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-6 h-6 rounded-lg bg-dark-hover/10 flex items-center justify-center flex-shrink-0">
                    <svg className="w-3.5 h-3.5 text-dark-hover" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={icon} />
                    </svg>
                  </div>
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
