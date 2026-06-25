import { create } from 'zustand'
import type { Conversation } from '../types/chat'
import { conversationsService } from '../services/conversations'

interface ConversationState {
  conversations: Conversation[]
  currentConversationId: number | null
  isLoading: boolean
  error: string | null
  fetchConversations: () => Promise<void>
  createConversation: () => Promise<Conversation>
  deleteConversation: (id: number) => Promise<void>
  renameConversation: (id: number, title: string) => Promise<void>
  setCurrentConversation: (id: number | null) => void
  updateConversationInList: (conversation: Conversation) => void
}

export const useConversationStore = create<ConversationState>((set) => ({
  conversations: [],
  currentConversationId: null,
  isLoading: false,
  error: null,

  fetchConversations: async () => {
    set({ isLoading: true, error: null })
    try {
      const conversations = await conversationsService.list()
      set({ conversations, isLoading: false })
    } catch (error) {
      set({ error: 'Failed to fetch conversations', isLoading: false })
    }
  },

  createConversation: async () => {
    const conversation = await conversationsService.create()
    set((state) => ({
      conversations: [conversation, ...state.conversations],
      currentConversationId: conversation.id,
    }))
    return conversation
  },

  deleteConversation: async (id: number) => {
    await conversationsService.delete(id)
    set((state) => ({
      conversations: state.conversations.filter((c) => c.id !== id),
      currentConversationId:
        state.currentConversationId === id ? null : state.currentConversationId,
    }))
  },

  renameConversation: async (id: number, title: string) => {
    const updated = await conversationsService.update(id, title)
    set((state) => ({
      conversations: state.conversations.map((c) =>
        c.id === id ? updated : c
      ),
    }))
  },

  setCurrentConversation: (id) => {
    set({ currentConversationId: id })
  },

  updateConversationInList: (conversation) => {
    set((state) => ({
      conversations: state.conversations.map((c) =>
        c.id === conversation.id ? conversation : c
      ),
    }))
  },
}))
