import { useMemo, useState, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import type { Message, Attachment, Source } from '../../types/chat'
import type { Components } from 'react-markdown'
import { documentsService } from '../../services/documents'
import type { DocumentChunk } from '../../services/documents'

interface ChatMessageProps {
  message: Message
  isStreaming?: boolean
  sources?: Source[]
  processLog?: string[]
}

function ProcessBox({ lines, isStreaming }: { lines: string[]; isStreaming: boolean }) {
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    if (!isStreaming) setExpanded(false)
  }, [isStreaming])

  if (!lines.length) return null

  return (
    <div className="mb-3">
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-1.5 text-xs text-dark-muted hover:text-dark-text transition-colors"
      >
        <svg
          className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span>Process</span>
        {isStreaming && (
          <span className="flex gap-0.5 ml-1">
            <span className="w-1 h-1 rounded-full bg-dark-muted animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1 h-1 rounded-full bg-dark-muted animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1 h-1 rounded-full bg-dark-muted animate-bounce" style={{ animationDelay: '300ms' }} />
          </span>
        )}
      </button>
      {expanded && (
        <div className="mt-2 ml-4 pl-3 border-l-2 border-dark-chat space-y-1">
          {lines.map((line, i) => (
            <ReactMarkdown
              key={i}
              remarkPlugins={[remarkGfm]}
              components={{ p: ({ children }) => <p className="text-xs text-dark-muted leading-relaxed">{children}</p> }}
            >
              {line}
            </ReactMarkdown>
          ))}
        </div>
      )}
    </div>
  )
}

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

  return (
    <a
      href={`/api/uploads/${attachment.filename}`}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 p-3 my-2 bg-dark-chat rounded-lg hover:bg-opacity-80 transition-colors max-w-xs"
    >
      <div className="w-10 h-10 bg-dark-sidebar rounded flex items-center justify-center flex-shrink-0">
        <svg className="w-5 h-5 text-dark-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-dark-text truncate">{attachment.original_filename}</p>
        <p className="text-xs text-dark-muted">{formatFileSize(attachment.file_size)}</p>
      </div>
      <svg className="w-4 h-4 text-dark-muted flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
    </a>
  )
}

function FileDownloadButton({ href, label }: { href: string; label: string }) {
  const [downloading, setDownloading] = useState(false)
  const ext = label.split('.').pop()?.toLowerCase() ?? ''
  const iconColor: Record<string, string> = {
    xlsx: 'text-green-600', csv: 'text-green-600',
    docx: 'text-blue-600', pdf: 'text-red-500',
    pptx: 'text-orange-500',
  }

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault()
    setDownloading(true)
    try {
      const token = localStorage.getItem('token')
      const headers: HeadersInit = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(href, { credentials: 'include', headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = label
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch {
      window.open(href, '_blank', 'noreferrer')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <span className="inline-flex flex-col gap-1 my-1">
      <button
        onClick={handleClick}
        disabled={downloading}
        className="inline-flex items-center gap-2 px-3 py-2 bg-dark-sidebar border border-dark-chat rounded-lg hover:border-dark-hover transition-colors group disabled:opacity-60"
      >
        <svg className={`w-5 h-5 flex-shrink-0 ${iconColor[ext] ?? 'text-dark-muted'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
        </svg>
        <span className="text-sm text-dark-text group-hover:text-dark-hover transition-colors">
          {downloading ? 'Downloading…' : label}
        </span>
        <svg className="w-4 h-4 text-dark-muted group-hover:text-dark-hover transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
      </button>
    </span>
  )
}

// Inline citation badge — superscript style
function CiteBadge({ num, onClick, filename }: { num: number; onClick: () => void; filename: string }) {
  return (
    <button
      onClick={onClick}
      title={filename}
      className="inline-flex items-center justify-center min-w-[1.15rem] h-[1.15rem] px-0.5 text-[9px] font-bold bg-amber-100 text-amber-700 border border-amber-300 rounded-full mx-0.5 hover:bg-amber-200 hover:border-amber-500 transition-colors align-middle relative -top-px"
    >
      {num}
    </button>
  )
}

function makeMarkdownComponents(
  sources: Source[],
  onView: (s: Source) => void
): Components {
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
            <CiteBadge
              key={`${keyPrefix}-${i}`}
              num={num}
              onClick={() => onView(src)}
              filename={src.filename}
            />
          )
        }
      }
      return part
    })
  }

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
                <CiteBadge num={num} onClick={() => onView(src)} filename={src.filename} />
              )
            }
          }
        }
      }
      if (href && href.startsWith('/api/files/download/')) {
        return <FileDownloadButton href={href} label={
          typeof children === 'string' ? children
          : Array.isArray(children) && typeof children[0] === 'string' ? children[0]
          : 'Download file'
        } />
      }

      return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="text-dark-hover hover:underline">
          {children}
        </a>
      )
    },

    hr: () => <hr className="my-6 border-dark-chat" />,

    table: ({ children }) => (
      <div className="overflow-x-auto my-4 rounded-lg border border-dark-chat">
        <table className="min-w-full">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="bg-dark-sidebar border-b border-dark-chat">{children}</thead>
    ),
    tbody: ({ children }) => <tbody className="divide-y divide-dark-chat">{children}</tbody>,
    tr: ({ children }) => <tr className="hover:bg-dark-sidebar transition-colors">{children}</tr>,
    th: ({ children }) => (
      <th className="px-4 py-2.5 text-left text-xs font-semibold text-dark-muted uppercase tracking-wide">{children}</th>
    ),
    td: ({ children }) => (
      <td className="px-4 py-2.5 text-sm text-dark-text">{children}</td>
    ),

    code: ({ className, children, ...props }) => {
      const match = /language-(\w+)/.exec(className || '')
      const isInline = !match && !className

      if (isInline) {
        return (
          <code
            className="bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded text-sm font-mono text-amber-800"
            {...props}
          >
            {children}
          </code>
        )
      }

      return (
        <div className="relative group my-4 rounded-xl overflow-hidden border border-dark-chat">
          <div className="flex items-center justify-between px-4 py-2 bg-dark-sidebar border-b border-dark-chat">
            <span className="text-xs text-dark-muted font-mono">{match?.[1] || 'code'}</span>
            <button
              onClick={() => navigator.clipboard.writeText(String(children).replace(/\n$/, ''))}
              className="flex items-center gap-1.5 text-xs text-dark-muted hover:text-dark-text transition-colors"
              title="Copy code"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              Copy
            </button>
          </div>
          <SyntaxHighlighter
            style={oneLight}
            language={match?.[1] || 'text'}
            PreTag="div"
            customStyle={{ margin: 0, borderRadius: 0, padding: '1rem', background: '#faf8f5' }}
          >
            {String(children).replace(/\n$/, '')}
          </SyntaxHighlighter>
        </div>
      )
    },

    pre: ({ children }) => <>{children}</>,
  }
}

function StreamingText({ content }: { content: string }) {
  return (
    <div className="whitespace-pre-wrap leading-7 text-dark-text">
      {content}
    </div>
  )
}

// ── Document viewer modal ──────────────────────────────────────────────────────

function DocumentViewerModal({ source, onClose }: { source: Source; onClose: () => void }) {
  const [chunks, setChunks] = useState<DocumentChunk[]>([])
  const [loading, setLoading] = useState(true)
  const highlightRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  useEffect(() => {
    if (!source.document_id) { setLoading(false); return }
    setLoading(true)
    documentsService.getChunks(source.document_id)
      .then(data => setChunks(data.chunks || []))
      .catch(() => setChunks([]))
      .finally(() => setLoading(false))
  }, [source.document_id])

  useEffect(() => {
    if (!loading && highlightRef.current) {
      setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }, 150)
    }
  }, [loading])

  const isMatch = (chunk: DocumentChunk): boolean => {
    if (source.chunk_index !== undefined) return chunk.chunk_index === source.chunk_index
    if (source.chunk_text) return chunk.chunk_text.includes(source.chunk_text.slice(0, 80))
    return false
  }

  const citedChunk = chunks.find(isMatch)

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center sm:p-4 bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-dark-bg rounded-t-2xl sm:rounded-2xl shadow-2xl flex flex-col w-full sm:max-w-2xl border border-dark-chat"
        style={{ maxHeight: '90vh' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-dark-chat flex-shrink-0">
          <div className="w-9 h-9 rounded-lg bg-amber-100 flex items-center justify-center flex-shrink-0">
            <svg className="w-5 h-5 text-amber-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-dark-text truncate">{source.filename}</p>
            <p className="text-xs text-dark-muted">
              {citedChunk?.page_start
                ? `Page ${citedChunk.page_start}${citedChunk.page_end !== citedChunk.page_start ? `–${citedChunk.page_end}` : ''}`
                : `Source ${source.number}`}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-dark-chat text-dark-muted hover:text-dark-text transition-colors flex-shrink-0"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Cited passage — shown prominently when found */}
        {!loading && citedChunk && (
          <div className="px-5 py-4 bg-amber-50 border-b border-amber-200/80 flex-shrink-0">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-4 h-4 rounded-full bg-amber-600 text-white text-[10px] font-bold flex items-center justify-center flex-shrink-0">
                {source.number}
              </span>
              <span className="text-xs font-semibold text-amber-700 uppercase tracking-wider">Cited passage</span>
              {citedChunk.heading_context && (
                <span className="text-xs text-amber-600 truncate">· {citedChunk.heading_context}</span>
              )}
            </div>
            <p className="text-sm text-dark-text leading-relaxed line-clamp-5 whitespace-pre-wrap">
              {citedChunk.chunk_text}
            </p>
          </div>
        )}

        {/* Full document chunks */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <svg className="w-5 h-5 animate-spin text-dark-muted" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
          ) : chunks.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 gap-2 text-dark-muted">
              <svg className="w-8 h-8 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-sm">Content not available</p>
            </div>
          ) : (
            <div className="py-3">
              <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-wider px-5 pb-2">
                Full document · {chunks.length} sections
              </p>
              <div className="space-y-px">
                {chunks.map((chunk) => {
                  const highlighted = isMatch(chunk)
                  return (
                    <div
                      key={chunk.id}
                      ref={highlighted ? highlightRef : undefined}
                      className={`mx-3 px-3 py-3 rounded-lg border-l-2 transition-colors ${
                        highlighted
                          ? 'border-amber-500 bg-amber-50'
                          : 'border-transparent hover:bg-dark-chat/40'
                      }`}
                    >
                      {chunk.heading_context && (
                        <p className="text-[10px] text-dark-muted font-semibold uppercase tracking-wider mb-1 truncate">
                          {chunk.heading_context}
                        </p>
                      )}
                      {highlighted && (
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0" />
                          <span className="text-[10px] text-amber-600 font-semibold uppercase tracking-wider">Cited here</span>
                        </div>
                      )}
                      <p className={`text-xs leading-relaxed whitespace-pre-wrap ${
                        highlighted ? 'text-dark-text' : 'line-clamp-3 text-dark-muted'
                      }`}>
                        {chunk.chunk_text}
                      </p>
                      {chunk.page_start > 0 && (
                        <p className="text-[10px] text-dark-muted mt-1.5 opacity-60">
                          p.{chunk.page_start}{chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ''}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main message component ─────────────────────────────────────────────────────

export function ChatMessage({ message, isStreaming = false, sources = [], processLog }: ChatMessageProps) {
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
      <div className={`flex gap-4 px-6 py-5 ${isUser ? 'bg-dark-bg' : 'bg-dark-sidebar'}`}>
        {/* Avatar */}
        <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-semibold text-white ${
          isUser ? 'bg-stone-400' : 'bg-dark-hover'
        }`}>
          {isUser ? 'U' : 'AI'}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 overflow-hidden">
          <div className="font-medium text-sm mb-2 text-dark-muted">
            {isUser ? 'You' : 'ALAI'}
          </div>

          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {attachments.map((attachment) => (
                <AttachmentDisplay key={attachment.id} attachment={attachment} />
              ))}
            </div>
          )}

          {!isUser && processLog && processLog.length > 0 && (
            <ProcessBox lines={processLog} isStreaming={isStreaming} />
          )}

          <div className="max-w-none">
            {message.content && (
              isStreaming ? (
                <StreamingText content={message.content} />
              ) : (
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

          {/* Sources list */}
          {!isUser && sources.length > 0 && (
            <div className="mt-4 pt-3 border-t border-dark-chat">
              <p className="text-[11px] font-semibold text-dark-muted uppercase tracking-wider mb-2">
                Sources
              </p>
              <div className="space-y-0.5">
                {sources.map((src) => (
                  <button
                    key={src.document_id ?? src.number}
                    onClick={() => setViewing(src)}
                    className="flex items-center gap-2.5 w-full text-left px-2.5 py-2 rounded-lg hover:bg-dark-chat transition-colors group"
                  >
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-amber-600 text-white flex items-center justify-center text-[10px] font-bold">
                      {src.number}
                    </span>
                    <svg className="w-3.5 h-3.5 text-dark-muted flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <span className="text-xs text-dark-text truncate flex-1 group-hover:text-dark-hover transition-colors">
                      {src.filename}
                    </span>
                    <svg className="w-3 h-3 text-dark-muted opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
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
