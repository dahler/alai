import { useAuthStore } from '../../store/authStore'

export function LoginButton() {
  const login = useAuthStore((state) => state.login)

  return (
    <button
      onClick={login}
      className="w-full flex items-center justify-center gap-3 px-4 py-3 bg-dark-chat hover:bg-dark-hover rounded-lg transition-colors text-dark-text"
    >
      <svg className="w-5 h-5" viewBox="0 0 21 21" fill="none">
        <rect x="1" y="1" width="9" height="9" fill="#F25022" />
        <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
        <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
        <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
      </svg>
      <span>Sign in with Microsoft</span>
    </button>
  )
}
