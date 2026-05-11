import { useEffect, useRef } from 'react'
import { ChatMessage } from './ChatMessage'
import { ChatInput } from './ChatInput'
import { TypingIndicator } from './TypingIndicator'
import { Loading } from '../common/Loading'
import { useChatStore } from '../../store/chatStore'

interface ChatWindowProps {
  conversationId: number
}

export function ChatWindow({ conversationId }: ChatWindowProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const {
    messages,
    isLoading,
    isStreaming,
    streamingContent,
    pendingAttachments,
    isUploading,
    fetchMessages,
    sendMessage,
    uploadFile,
    removeAttachment,
  } = useChatStore()

  useEffect(() => {
    fetchMessages(conversationId)
  }, [conversationId, fetchMessages])

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  const handleSend = (content: string) => {
    sendMessage(conversationId, content)
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loading text="Loading conversation..." />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 && pendingAttachments.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center p-8">
            <div className="w-16 h-16 rounded-full bg-dark-hover flex items-center justify-center mb-4">
              <svg
                className="w-8 h-8 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-dark-text mb-2">
              Start a Conversation
            </h2>
            <p className="text-dark-muted max-w-md">
              Ask me anything! I can help with coding, answer questions, explain
              concepts, and much more. You can also attach images and documents.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-dark-chat">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}

            {/* Streaming message */}
            {isStreaming && streamingContent && (
              <ChatMessage
                message={{
                  id: -1,
                  conversation_id: conversationId,
                  role: 'assistant',
                  content: streamingContent,
                  created_at: new Date().toISOString(),
                  attachments: [],
                }}
                isStreaming
              />
            )}

            {/* Typing indicator when streaming but no content yet */}
            {isStreaming && !streamingContent && (
              <div className="flex gap-4 p-4 bg-dark-sidebar">
                <div className="w-8 h-8 rounded-full bg-dark-hover flex items-center justify-center text-sm font-medium">
                  AI
                </div>
                <div className="flex items-center">
                  <TypingIndicator />
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <ChatInput
        onSend={handleSend}
        onFileUpload={uploadFile}
        onRemoveAttachment={removeAttachment}
        pendingAttachments={pendingAttachments}
        disabled={isStreaming}
        isUploading={isUploading}
        placeholder={isStreaming ? 'Waiting for response...' : 'Type a message...'}
      />
    </div>
  )
}
