import { create } from 'zustand'

export type ToastType = 'success' | 'error' | 'info' | 'warning'

export interface ToastItem {
  id: number
  type: ToastType
  message: string
}

interface ToastStore {
  toasts: ToastItem[]
  _add: (type: ToastType, message: string, duration: number) => void
  remove: (id: number) => void
}

let _nextId = 1

const _store = create<ToastStore>((set) => ({
  toasts: [],
  _add: (type, message, duration) => {
    const id = _nextId++
    set((s) => ({ toasts: [...s.toasts, { id, type, message }] }))
    if (duration > 0)
      setTimeout(
        () => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
        duration,
      )
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

export const useToastStore = _store

export const toast = {
  success: (msg: string, duration = 4000) => _store.getState()._add('success', msg, duration),
  error:   (msg: string, duration = 5000) => _store.getState()._add('error',   msg, duration),
  info:    (msg: string, duration = 4000) => _store.getState()._add('info',    msg, duration),
  warning: (msg: string, duration = 4500) => _store.getState()._add('warning', msg, duration),
}
