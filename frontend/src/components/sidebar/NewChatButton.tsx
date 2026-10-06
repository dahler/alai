interface NewChatButtonProps {
  onClick: () => void
}

export function NewChatButton({ onClick }: NewChatButtonProps) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-dark-chat/60 transition-colors"
    >
      <div className="w-6 h-6 flex items-center justify-center rounded-lg bg-dark-hover/10 text-dark-hover flex-shrink-0">
        <svg
          className="w-3.5 h-3.5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2.5}
            d="M12 4v16m8-8H4"
          />
        </svg>
      </div>
      <span className="flex-1 text-left text-sm font-medium text-dark-text">New chat</span>
      <span className="text-xs text-dark-muted">⌘N</span>
    </button>
  )
}
