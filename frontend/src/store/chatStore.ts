import { create } from 'zustand'
import type { Message, Attachment, UploadResponse, Source } from '../types/chat'
import { messagesService } from '../services/messages'
import { conversationsService } from '../services/conversations'
import { uploadsService } from '../services/uploads'

interface ChatState {
  messages: Message[]
  isLoading: boolean
  isStreaming: boolean
  streamingContent: string
  streamingSources: Source[]
  messageSources: Record<number, Source[]>  // message id → sources
  error: string | null
  pendingAttachments: UploadResponse[]
  isUploading: boolean
  fetchMessages: (conversationId: number) => Promise<void>
  sendMessage: (conversationId: number, content: string) => Promise<void>
  clearMessages: () => void
  addMessage: (message: Message) => void
  uploadFile: (file: File) => Promise<void>
  removeAttachment: (attachmentId: number) => void
  clearAttachments: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isLoading: false,
  isStreaming: false,
  streamingContent: '',
  streamingSources: [],
  messageSources: {},
  error: null,
  pendingAttachments: [],
  isUploading: false,

  fetchMessages: async (conversationId: number) => {
    set({ isLoading: true, error: null })
    try {
      const conversation = await conversationsService.get(conversationId)
      const messages = conversation.messages
      const messageSources: Record<number, Source[]> = {}
      for (const msg of messages) {
        // Primary: DB-persisted sources
        if (msg.sources && msg.sources.length > 0) {
          messageSources[msg.id] = msg.sources as Source[]
        } else {
          // Fallback: localStorage cache written at session time
          const cached = localStorage.getItem(`citation_${msg.id}`)
          if (cached) {
            try { messageSources[msg.id] = JSON.parse(cached) } catch { /* ignore */ }
          }
        }
      }
      set({ messages, messageSources, isLoading: false })
    } catch (error) {
      set({ error: 'Failed to fetch messages', isLoading: false })
    }
  },

  sendMessage: async (conversationId: number, content: string) => {
    const { pendingAttachments } = get()
    const attachmentIds = pendingAttachments.map((a) => a.id)

    // Create attachments array for the message
    const attachments: Attachment[] = pendingAttachments.map((a) => ({
      id: a.id,
      filename: a.filename,
      original_filename: a.original_filename,
      content_type: a.content_type,
      file_size: a.file_size,
      url: a.url,
      is_image: a.is_image,
    }))

    // Add user message immediately
    const tempUserMessage: Message = {
      id: Date.now(),
      conversation_id: conversationId,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
      attachments,
    }

    set((state) => ({
      messages: [...state.messages, tempUserMessage],
      isStreaming: true,
      streamingContent: '',
      streamingSources: [],
      error: null,
      pendingAttachments: [],
    }))

    let fullContent = ''
    let latestSources: Source[] = []

    await messagesService.sendStream(
      conversationId,
      content,
      attachmentIds,
      // On chunk
      (chunk: string) => {
        fullContent += chunk
        set({ streamingContent: fullContent })
      },
      // On done
      async () => {
        const sseSources = latestSources
        set({ isStreaming: false, streamingContent: '', streamingSources: [] })

        try {
          const conversation = await conversationsService.get(conversationId)
          const messages = conversation.messages
          const messageSources: Record<number, Source[]> = {}

          // Primary: DB-persisted sources; fallback: localStorage cache
          for (const msg of messages) {
            if (msg.sources && msg.sources.length > 0) {
              messageSources[msg.id] = msg.sources as Source[]
            } else {
              const cached = localStorage.getItem(`citation_${msg.id}`)
              if (cached) {
                try { messageSources[msg.id] = JSON.parse(cached) } catch { /* ignore */ }
              }
            }
          }

          // Fallback: use in-memory SSE sources for the last assistant message
          if (sseSources.length > 0) {
            const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
            if (lastAssistant && !messageSources[lastAssistant.id]) {
              messageSources[lastAssistant.id] = sseSources
            }
            // Persist to localStorage so it survives refresh
            if (lastAssistant) {
              localStorage.setItem(`citation_${lastAssistant.id}`, JSON.stringify(sseSources))
            }
          }

          set({ messages, messageSources })
        } catch {
          const assistantMessage: Message = {
            id: Date.now(),
            conversation_id: conversationId,
            role: 'assistant',
            content: fullContent,
            created_at: new Date().toISOString(),
            attachments: [],
          }
          set((state) => ({
            messages: [...state.messages, assistantMessage],
          }))
        }
      },
      // On error
      (error: string) => {
        set({
          isStreaming: false,
          streamingContent: '',
          streamingSources: [],
          error: error,
        })
      },
      // On sources
      (sources: Source[]) => {
        latestSources = sources
        set({ streamingSources: sources })
      }
    )
  },

  clearMessages: () => {
    set({ messages: [], error: null, pendingAttachments: [] })
  },

  addMessage: (message: Message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }))
  },

  uploadFile: async (file: File) => {
    set({ isUploading: true, error: null })
    try {
      const response = await uploadsService.upload(file)
      set((state) => ({
        pendingAttachments: [...state.pendingAttachments, response],
        isUploading: false,
      }))
    } catch (error) {
      set({
        isUploading: false,
        error: 'Failed to upload file',
      })
    }
  },

  removeAttachment: (attachmentId: number) => {
    set((state) => ({
      pendingAttachments: state.pendingAttachments.filter(
        (a) => a.id !== attachmentId
      ),
    }))
    // Also delete from server
    uploadsService.delete(attachmentId).catch(console.error)
  },

  clearAttachments: () => {
    const { pendingAttachments } = get()
    // Delete all pending attachments from server
    pendingAttachments.forEach((a) => {
      uploadsService.delete(a.id).catch(console.error)
    })
    set({ pendingAttachments: [] })
  },
}))
