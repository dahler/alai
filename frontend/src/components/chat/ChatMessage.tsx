import { useMemo, useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import type { Message, Attachment, Source } from '../../types/chat'
import type { Components } from 'react-markdown'

interface ChatMessageProps {
  message: Message
  isStreaming?: boolean
  sources?: Source[]
}

// Attachment display component
function AttachmentDisplay({ attachment }: { attachment: Attachment }) {
  const [isExpanded, setIsExpanded] = useState(false)

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  if (attachment.is_image) {
    return (
      <div className="my-2">
        <img
          src={`/api/uploads/${attachment.filename}`}
          alt={attachment.original_filename}
          className={`rounded-lg cursor-pointer transition-all ${
            isExpanded ? 'max-w-full' : 'max-w-xs max-h-64 object-cover'
          }`}
          onClick={() => setIsExpanded(!isExpanded)}
        />
        <p className="text-xs text-dark-muted mt-1">
          {attachment.original_filename} ({formatFileSize(attachment.file_size)})
        </p>
      </div>
    )
  }

  // Document attachment
  return (
    <a
      href={`/api/uploads/${attachment.filename}`}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 p-3 my-2 bg-dark-chat rounded-lg hover:bg-opacity-80 transition-colors max-w-xs"
    >
      <div className="w-10 h-10 bg-dark-sidebar rounded flex items-center justify-center flex-shrink-0">
        <svg
          className="w-5 h-5 text-dark-muted"
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
      <div className="flex-1 min-w-0">
        <p className="text-sm text-dark-text truncate">
          {attachment.original_filename}
        </p>
        <p className="text-xs text-dark-muted">
          {formatFileSize(attachment.file_size)}
        </p>
      </div>
      <svg
        className="w-4 h-4 text-dark-muted flex-shrink-0"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
        />
      </svg>
    </a>
  )
}

function makeMarkdownComponents(
  sources: Source[],
  onView: (s: Source) => void
): Components {
  // Replace [N] citation markers in a text string with clickable buttons
  function processCiteStr(text: string, keyPrefix: string): ReactNode[] {
    const parts = text.split(/(\[\d+\])/g)
    if (parts.length === 1) return [text]
    return parts.map((part, i) => {
      const m = /^\[(\d+)\]$/.exec(part)
      if (m) {
        const num = parseInt(m[1])
        const src = sources.find(s => s.number === num)
        if (src) {
          return (
            <button
              key={`${keyPrefix}-${i}`}
              onClick={() => onView(src)}
              title={src.filename}
              className="inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold bg-blue-600 text-white rounded-full mx-0.5 hover:bg-blue-500 transition-colors align-middle"
            >
              {num}
            </button>
          )
        }
      }
      return part
    })
  }

  // Walk ReactNode children, replacing citation strings with buttons
  function withCites(children: ReactNode): ReactNode {
    if (typeof children === 'string') {
      const result = processCiteStr(children, 'c')
      return result.length === 1 && typeof result[0] === 'string' ? result[0] : result
    }
    if (Array.isArray(children)) {
      return (children as ReactNode[]).flatMap((child, ci) => {
        if (typeof child === 'string') return processCiteStr(child, String(ci))
        return [child]
      })
    }
    return children
  }

  return {
    h1: ({ children }) => (
      <h1 className="text-2xl font-bold mt-6 mb-4 text-dark-text">{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="text-xl font-bold mt-5 mb-3 text-dark-text">{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="text-lg font-semibold mt-4 mb-2 text-dark-text">{children}</h3>
    ),
    h4: ({ children }) => (
      <h4 className="text-base font-semibold mt-3 mb-2 text-dark-text">{children}</h4>
    ),

    p: ({ children }) => (
      <p className="mb-3 leading-7 text-dark-text last:mb-0">{withCites(children)}</p>
    ),

    ul: ({ children }) => (
      <ul className="list-disc pl-6 mb-4 space-y-2 text-dark-text">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal pl-6 mb-4 space-y-2 text-dark-text">{children}</ol>
    ),
    li: ({ children }) => (
      <li className="leading-7 pl-1">{withCites(children)}</li>
    ),

    blockquote: ({ children }) => (
      <blockquote className="border-l-4 border-dark-hover pl-4 my-4 italic text-dark-muted">
        {children}
      </blockquote>
    ),

    strong: ({ children }) => (
      <strong className="font-semibold text-dark-text">{children}</strong>
    ),
    em: ({ children }) => (
      <em className="italic">{children}</em>
    ),

    a: ({ href, children }) => {
      // Remark parses [N] as a link reference with no href — detect and render as citation button
      if (!href) {
        const text = typeof children === 'string'
          ? children
          : Array.isArray(children) && children.length === 1 && typeof children[0] === 'string'
            ? children[0]
            : null
        if (text) {
          const num = parseInt(text.trim())
          if (!isNaN(num) && String(num) === text.trim()) {
            const src = sources.find(s => s.number === num)
            if (src) {
              return (
                <button
                  onClick={() => onView(src)}
                  title={src.filename}
                  className="inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold bg-blue-600 text-white rounded-full mx-0.5 hover:bg-blue-500 transition-colors align-middle"
                >
                  {num}
                </button>
              )
            }
          }
        }
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="text-dark-hover hover:underline">
          {children}
        </a>
      )
    },

    hr: () => <hr className="my-6 border-dark-muted" />,

    table: ({ children }) => (
      <div className="overflow-x-auto my-4">
        <table className="min-w-full border border-dark-muted">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="bg-dark-sidebar">{children}</thead>
    ),
    tbody: ({ children }) => <tbody>{children}</tbody>,
    tr: ({ children }) => (
      <tr className="border-b border-dark-muted">{children}</tr>
    ),
    th: ({ children }) => (
      <th className="px-4 py-2 text-left font-semibold text-dark-text">{children}</th>
    ),
    td: ({ children }) => (
      <td className="px-4 py-2 text-dark-text">{children}</td>
    ),

    code: ({ className, children, ...props }) => {
      const match = /language-(\w+)/.exec(className || '')
      const isInline = !match && !className

      if (isInline) {
        return (
          <code
            className="bg-dark-chat px-1.5 py-0.5 rounded text-sm font-mono text-pink-400"
            {...props}
          >
            {children}
          </code>
        )
      }

      return (
        <div className="relative group my-4">
          {match && (
            <div className="absolute top-0 left-0 px-3 py-1 text-xs text-dark-muted bg-dark-chat rounded-tl rounded-br">
              {match[1]}
            </div>
          )}
          <button
            onClick={() => {
              navigator.clipboard.writeText(String(children).replace(/\n$/, ''))
            }}
            className="absolute right-2 top-2 p-1.5 rounded bg-dark-chat opacity-0 group-hover:opacity-100 transition-opacity z-10"
            title="Copy code"
          >
            <svg
              className="w-4 h-4 text-dark-text"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
              />
            </svg>
          </button>
          <SyntaxHighlighter
            style={oneDark}
            language={match?.[1] || 'text'}
            PreTag="div"
            customStyle={{
              margin: 0,
              borderRadius: '0.5rem',
              padding: '1rem',
              paddingTop: match ? '2rem' : '1rem',
            }}
          >
            {String(children).replace(/\n$/, '')}
          </SyntaxHighlighter>
        </div>
      )
    },

    pre: ({ children }) => <>{children}</>,
  }
}

// Simple streaming text component - renders text without full markdown parsing
function StreamingText({ content }: { content: string }) {
  // During streaming, render with basic formatting only
  // This avoids ReactMarkdown re-parsing incomplete markdown
  return (
    <div className="whitespace-pre-wrap leading-7 text-dark-text">
      {content}
    </div>
  )
}

function getFileType(filename: string): 'pdf' | 'image' | 'other' {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  if (ext === 'pdf') return 'pdf'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) return 'image'
  return 'other'
}

function DocumentViewerModal({ source, onClose }: { source: Source; onClose: () => void }) {
  const fileUrl = source.stored_filename ? `/api/uploads/${source.stored_filename}` : null
  const fileType = getFileType(source.filename)

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-70"
      onClick={onClose}
    >
      <div
        className="bg-dark-sidebar rounded-xl shadow-2xl flex flex-col w-full max-w-4xl"
        style={{ height: '85vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-dark-chat flex-shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-bold">
              {source.number}
            </span>
            <span className="text-sm text-dark-text font-medium truncate">{source.filename}</span>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0 ml-3">
            {fileUrl && (
              <a
                href={fileUrl}
                target="_blank"
                rel="noopener noreferrer"
                title="Open in new tab"
                className="p-1.5 rounded hover:bg-dark-chat text-dark-muted hover:text-dark-text transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            )}
            <button
              onClick={onClose}
              title="Close"
              className="p-1.5 rounded hover:bg-dark-chat text-dark-muted hover:text-dark-text transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Relevant passage */}
        {source.chunk_text && (
          <div className="px-4 py-3 bg-dark-bg border-b border-dark-chat flex-shrink-0 max-h-36 overflow-y-auto">
            <p className="text-[10px] text-dark-muted font-semibold uppercase tracking-wide mb-1">Cited passage</p>
            <p className="text-xs text-dark-text leading-5 italic border-l-2 border-blue-500 pl-2">
              {source.chunk_text.length > 500
                ? source.chunk_text.slice(0, 500) + '…'
                : source.chunk_text}
            </p>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-hidden rounded-b-xl">
          {!fileUrl ? (
            <div className="flex items-center justify-center h-full text-dark-muted text-sm">
              File not available
            </div>
          ) : fileType === 'image' ? (
            <div className="flex items-center justify-center h-full overflow-auto p-4 bg-dark-bg">
              <img src={fileUrl} alt={source.filename} className="max-w-full max-h-full object-contain rounded" />
            </div>
          ) : (
            <iframe
              src={fileUrl}
              className="w-full h-full rounded-b-xl"
              title={source.filename}
            />
          )}
        </div>
      </div>
    </div>
  )
}

export function ChatMessage({ message, isStreaming = false, sources = [] }: ChatMessageProps) {
  const isUser = message.role === 'user'
  const attachments = message.attachments || []
  const [viewing, setViewing] = useState<Source | null>(null)

  const contentKey = useMemo(() => {
    return `msg-${message.id}-${message.content.length}-${isStreaming ? 'stream' : 'done'}`
  }, [message.id, message.content.length, isStreaming])

  const mdComponents = useMemo(
    () => makeMarkdownComponents(sources, setViewing),
    [sources]
  )

  return (
    <>
      {viewing && <DocumentViewerModal source={viewing} onClose={() => setViewing(null)} />}
    <div
      className={`flex gap-4 p-4 ${
        isUser ? 'bg-dark-bg' : 'bg-dark-sidebar'
      }`}
    >
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-sm font-medium ${
          isUser ? 'bg-blue-600' : 'bg-dark-hover'
        }`}
      >
        {isUser ? 'U' : 'AI'}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 overflow-hidden">
        <div className="font-medium text-sm mb-2 text-dark-muted">
          {isUser ? 'You' : 'ALAI'}
        </div>

        {/* Attachments */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {attachments.map((attachment) => (
              <AttachmentDisplay key={attachment.id} attachment={attachment} />
            ))}
          </div>
        )}

        {/* Message content */}
        <div className="max-w-none">
          {message.content && (
            isStreaming ? (
              // During streaming: use simple text rendering for performance
              <StreamingText content={message.content} />
            ) : (
              // After streaming complete: render full markdown
              <ReactMarkdown
                key={contentKey}
                remarkPlugins={[remarkGfm]}
                components={mdComponents}
              >
                {message.content}
              </ReactMarkdown>
            )
          )}
          {isStreaming && (
            <span className="inline-block w-2 h-5 bg-dark-hover animate-pulse ml-1 align-middle" />
          )}
        </div>

        {/* Sources bar — fallback when sources exist */}
        {!isUser && sources.length > 0 && (
          <div className="mt-3 pt-3 border-t border-dark-chat">
            <p className="text-xs text-dark-muted mb-2 font-medium uppercase tracking-wide">Sources</p>
            <div className="flex flex-wrap gap-2">
              {sources.map((src) => (
                <button
                  key={src.document_id}
                  onClick={() => setViewing(src)}
                  title={src.filename}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-dark-chat hover:bg-dark-hover text-xs text-dark-text transition-colors max-w-[200px]"
                >
                  <span className="flex-shrink-0 w-4 h-4 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-bold">
                    {src.number}
                  </span>
                  <span className="truncate">{src.filename}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
    </>
  )
}
