import { useState } from 'react'
import { useAuthStore } from '../store/authStore'

export default function Login() {
  const login = useAuthStore((state) => state.login)
  const [loading, setLoading] = useState(false)

  const handleLogin = async () => {
    setLoading(true)
    await login()
  }

  return (
    <div className="min-h-screen bg-dark-bg flex items-center justify-center p-4">
      <div className="w-full max-w-md">

        {/* Branding */}
        <div className="text-center mb-8">
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-dark-hover to-amber-600 flex items-center justify-center mx-auto mb-5 shadow-xl shadow-dark-hover/20">
            <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
              />
            </svg>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-gradient">
            ALAI
          </h1>
          <p className="text-dark-muted mt-1 text-sm">Enterprise AI Assistant · Antara ETP</p>
        </div>

        {/* Feature pills */}
        <div className="grid grid-cols-2 gap-2.5 mb-8">
          {[
            { label: 'Company Knowledge', icon: 'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10' },
            { label: 'Document Analysis', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
            { label: 'Report Generation', icon: 'M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
            { label: 'Email & Tools', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
          ].map(({ label, icon }) => (
            <div key={label} className="bg-dark-sidebar border border-dark-chat rounded-lg px-3 py-2.5 flex items-center gap-2.5">
              <svg className="w-4 h-4 text-dark-hover shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={icon} />
              </svg>
              <span className="text-xs text-dark-muted">{label}</span>
            </div>
          ))}
        </div>

        {/* Login card */}
        <div className="bg-dark-sidebar border border-dark-chat rounded-xl p-6 shadow-xl">
          <h2 className="text-base font-semibold text-dark-text mb-0.5">Sign in to continue</h2>
          <p className="text-xs text-dark-muted mb-5">Use your Antara ETP Microsoft account</p>

          <button
            onClick={handleLogin}
            disabled={loading}
            className="w-full flex items-center justify-center gap-3 px-4 py-3 bg-dark-chat hover:bg-dark-hover disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors text-dark-text font-medium"
          >
            {loading ? (
              <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-5 h-5" viewBox="0 0 21 21" fill="none">
                <rect x="1" y="1" width="9" height="9" fill="#F25022" />
                <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
                <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
                <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
              </svg>
            )}
            {loading ? 'Redirecting…' : 'Sign in with Microsoft'}
          </button>

          <div className="flex items-center gap-2 mt-4">
            <div className="flex-1 h-px bg-dark-chat" />
            <p className="text-xs text-dark-muted px-2">@antaraetp.com accounts only</p>
            <div className="flex-1 h-px bg-dark-chat" />
          </div>
        </div>

        <p className="text-center text-xs text-dark-muted mt-6 opacity-50">
          © {new Date().getFullYear()} Antara ETP · ALAI
        </p>
      </div>
    </div>
  )
}
