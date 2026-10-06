import { useToastStore } from '../../store/toastStore'
import type { ToastItem } from '../../store/toastStore'

const STYLES: Record<string, string> = {
  success: 'bg-green-700 border-green-600',
  error:   'bg-red-700   border-red-600',
  info:    'bg-blue-700  border-blue-600',
  warning: 'bg-amber-600 border-amber-500',
}

const ICONS: Record<string, string> = {
  success: '✓',
  error:   '✕',
  info:    'ℹ',
  warning: '⚠',
}

function Toast({ item }: { item: ToastItem }) {
  const remove = useToastStore((s) => s.remove)
  return (
    <div
      role="alert"
      className={`flex items-start gap-3 px-4 py-3 rounded-lg shadow-xl border text-white text-sm min-w-[260px] max-w-sm ${STYLES[item.type]}`}
    >
      <span className="font-bold shrink-0 mt-0.5">{ICONS[item.type]}</span>
      <p className="flex-1 leading-snug">{item.message}</p>
      <button
        onClick={() => remove(item.id)}
        aria-label="Dismiss"
        className="shrink-0 opacity-60 hover:opacity-100 transition-opacity ml-1"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts)
  if (!toasts.length) return null
  return (
    <div className="fixed bottom-5 right-5 z-[200] flex flex-col gap-2 items-end pointer-events-none">
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto">
          <Toast item={t} />
        </div>
      ))}
    </div>
  )
}
