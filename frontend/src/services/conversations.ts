import { api } from './api'
import type { Conversation, ConversationWithMessages } from '../types/chat'

export const conversationsService = {
  async list(): Promise<Conversation[]> {
    const response = await api.get<Conversation[]>('/conversations')
    return response.data
  },

  async create(title: string = 'New Chat'): Promise<Conversation> {
    const response = await api.post<Conversation>('/conversations', { title })
    return response.data
  },

  async get(conversationId: number): Promise<ConversationWithMessages> {
    const response = await api.get<ConversationWithMessages>(
      `/conversations/${conversationId}`
    )
    return response.data
  },

  async update(conversationId: number, title: string): Promise<Conversation> {
    const response = await api.patch<Conversation>(
      `/conversations/${conversationId}`,
      { title }
    )
    return response.data
  },

  async delete(conversationId: number): Promise<void> {
    await api.delete(`/conversations/${conversationId}`)
  },
}
