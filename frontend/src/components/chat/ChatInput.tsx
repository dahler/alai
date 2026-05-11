import { useState, useRef, useEffect, KeyboardEvent, ChangeEvent } from 'react'
import type { UploadResponse } from '../../types/chat'

interface ChatInputProps {
  onSend: (message: string) => void
  onFileUpload: (file: File) => Promise<void>
  onRemoveAttachment: (attachmentId: number) => void
  pendingAttachments: UploadResponse[]
  disabled?: boolean
  isUploading?: boolean
  placeholder?: string
}

export function ChatInput({
  onSend,
  onFileUpload,
  onRemoveAttachment,
  pendingAttachments,
  disabled = false,
  isUploading = false,
  placeholder = 'Type a message...',
}: ChatInputProps) {
  const [message, setMessage] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
    }
  }, [message])

  const handleSubmit = () => {
    const trimmed = message.trim()
    if ((trimmed || pendingAttachments.length > 0) && !disabled) {
      onSend(trimmed)
      setMessage('')
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto'
      }
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleFileSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files) {
      for (const file of Array.from(files)) {
        await onFileUpload(file)
      }
    }
    // Reset input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <div className="border-t border-dark-sidebar bg-dark-bg p-4">
      <div className="max-w-3xl mx-auto">
        {/* Pending attachments preview */}
        {pendingAttachments.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {pendingAttachments.map((attachment) => (
              <div
                key={attachment.id}
                className="relative group bg-dark-sidebar rounded-lg p-2 flex items-center gap-2"
              >
                {attachment.is_image ? (
                  <img
                    src={`/api/uploads/${attachment.filename}`}
                    alt={attachment.original_filename}
                    className="w-16 h-16 object-cover rounded"
                  />
                ) : (
                  <div className="w-16 h-16 bg-dark-chat rounded flex items-center justify-center">
                    <svg
                      className="w-8 h-8 text-dark-muted"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                      />
                    </svg>
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-dark-text truncate max-w-[120px]">
                    {attachment.original_filename}
                  </p>
                  <p className="text-xs text-dark-muted">
                    {formatFileSize(attachment.file_size)}
                  </p>
                </div>
                <button
                  onClick={() => onRemoveAttachment(attachment.id)}
                  className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <svg
                    className="w-3 h-3 text-white"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Input area */}
        <div className="relative flex items-end bg-dark-sidebar rounded-xl border border-dark-chat focus-within:border-dark-hover transition-colors">
          {/* File upload button */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.json,.xml,.js,.css,.html"
            onChange={handleFileSelect}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || isUploading}
            className="p-3 text-dark-muted hover:text-dark-text disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="Attach file"
          >
            {isUploading ? (
              <svg
                className="w-5 h-5 animate-spin"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            ) : (
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                />
              </svg>
            )}
          </button>

          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="flex-1 bg-transparent text-dark-text placeholder-dark-muted py-3 px-2 resize-none focus:outline-none disabled:opacity-50 max-h-[200px]"
          />

          <button
            onClick={handleSubmit}
            disabled={disabled || (!message.trim() && pendingAttachments.length === 0)}
            className="p-3 text-dark-hover hover:text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          </button>
        </div>
        <p className="text-xs text-dark-muted text-center mt-2">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}
