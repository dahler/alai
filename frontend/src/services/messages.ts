import { api } from './api'
import type { Message, Source } from '../types/chat'

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
    onError: (error: string) => void,
    onSources?: (sources: Source[]) => void
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
      // Buffer incomplete lines across read() calls so URLs are never truncated
      let lineBuffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        lineBuffer += decoder.decode(value, { stream: true })

        // Process only complete lines (keep trailing incomplete line in buffer)
        const lastNewline = lineBuffer.lastIndexOf('\n')
        if (lastNewline === -1) continue

        const complete = lineBuffer.slice(0, lastNewline + 1)
        lineBuffer = lineBuffer.slice(lastNewline + 1)

        for (const line of complete.split('\n')) {
          if (!line.startsWith('data: ')) continue

          const data = line.slice(6)
          if (data === '[DONE]') {
            onDone()
            return
          }
          if (data.startsWith('[ERROR]')) {
            onError(data.slice(8))
            return
          }
          if (data.startsWith('[SOURCES]')) {
            try {
              const sources: Source[] = JSON.parse(data.slice(9))
              onSources?.(sources)
            } catch {
              // ignore malformed sources
            }
            continue
          }
          // Agentic mode JSON-encodes chunks to preserve newlines/special chars;
          // detect by checking for a JSON-quoted string and decode it.
          let chunk = data
          if (data.startsWith('"')) {
            try { chunk = JSON.parse(data) } catch { /* use raw data */ }
          }
          onChunk(chunk)
        }
      }

      onDone()
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Unknown error')
    }
  },
}
