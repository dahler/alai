import { api } from './api'
import type { Message } from '../types/chat'

const API_URL = import.meta.env.VITE_API_URL || ''

export const messagesService = {
  async list(conversationId: number): Promise<Message[]> {
    const response = await api.get<Message[]>(
      `/conversations/${conversationId}/messages`
    )
    return response.data
  },

  async send(
    conversationId: number,
    content: string,
    attachmentIds: number[] = []
  ): Promise<Message> {
    const response = await api.post<Message>(
      `/conversations/${conversationId}/messages`,
      { content, attachment_ids: attachmentIds }
    )
    return response.data
  },

  async sendStream(
    conversationId: number,
    content: string,
    attachmentIds: number[],
    onChunk: (chunk: string) => void,
    onDone: () => void,
    onError: (error: string) => void
  ): Promise<void> {
    const token = localStorage.getItem('token')
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    try {
      const response = await fetch(
        `${API_URL}/api/conversations/${conversationId}/messages/stream`,
        {
          method: 'POST',
          headers,
          credentials: 'include',
          body: JSON.stringify({ content, attachment_ids: attachmentIds }),
        }
      )

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body')
      }

      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const text = decoder.decode(value)
        const lines = text.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') {
              onDone()
              return
            }
            if (data.startsWith('[ERROR]')) {
              onError(data.slice(8))
              return
            }
            onChunk(data)
          }
        }
      }

      onDone()
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Unknown error')
    }
  },
}
