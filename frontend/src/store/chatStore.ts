import { create } from 'zustand'
import type { Message, Attachment, UploadResponse } from '../types/chat'
import { messagesService } from '../services/messages'
import { conversationsService } from '../services/conversations'
import { uploadsService } from '../services/uploads'

interface ChatState {
  messages: Message[]
  isLoading: boolean
  isStreaming: boolean
  streamingContent: string
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
  error: null,
  pendingAttachments: [],
  isUploading: false,

  fetchMessages: async (conversationId: number) => {
    set({ isLoading: true, error: null })
    try {
      const conversation = await conversationsService.get(conversationId)
      set({ messages: conversation.messages, isLoading: false })
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
      error: null,
      pendingAttachments: [],
    }))

    let fullContent = ''

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
        // Stop streaming
        set({ isStreaming: false, streamingContent: '' })

        // Re-fetch messages from server to ensure proper rendering
        // This mimics what happens on page refresh and guarantees correct formatting
        try {
          const conversation = await conversationsService.get(conversationId)
          set({ messages: conversation.messages })
        } catch {
          // Fallback: add message locally if fetch fails
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
          error: error,
        })
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
