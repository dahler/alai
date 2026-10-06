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
    streamingSources,
    streamingProcess,
    messageSources,
    messageProcessLog,
    pendingAttachments,
    isUploading,
    fetchMessages,
    sendMessage,
    stopStreaming,
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
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-dark-hover to-amber-500 flex items-center justify-center mb-4 shadow-glow-sm">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                />
              </svg>
            </div>
            <h2 className="text-base font-semibold text-dark-text mb-1 tracking-tight">
              How can I help?
            </h2>
            <p className="text-sm text-dark-muted max-w-xs">
              Ask anything, attach files, or start with an example prompt.
            </p>
          </div>
        ) : (
          <div className="py-4">
            {messages.map((message) => (
              <ChatMessage
                key={message.id}
                message={message}
                sources={messageSources[message.id]}
                processLog={messageProcessLog[message.id]}
              />
            ))}

            {/* Streaming message — show as soon as process lines or content arrive */}
            {isStreaming && (streamingContent || streamingProcess.length > 0) && (
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
                sources={streamingSources}
                processLog={streamingProcess}
              />
            )}

            {/* Typing indicator only when nothing has arrived yet */}
            {isStreaming && !streamingContent && streamingProcess.length === 0 && (
              <div className="flex gap-3 px-6 py-4 mx-4 rounded-2xl bg-dark-sidebar/60">
                <div className="w-7 h-7 rounded-full bg-dark-hover flex items-center justify-center text-xs font-semibold text-white flex-shrink-0 mt-0.5">
                  A
                </div>
                <div className="flex items-center pt-1">
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
        onStop={stopStreaming}
        onFileUpload={uploadFile}
        onRemoveAttachment={removeAttachment}
        pendingAttachments={pendingAttachments}
        disabled={isStreaming}
        isStreaming={isStreaming}
        isUploading={isUploading}
        placeholder={isStreaming ? 'Waiting for response...' : 'Type a message...'}
      />
    </div>
  )
}
