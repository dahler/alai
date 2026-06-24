import { useEffect, useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Document as PdfDocument, Page as PdfPage, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()
import {
  documentsService,
  Document,
  DocumentChunk,
  BatchUploadResponse,
  GraphStats,
  GraphStatus,
  ProcessingStatus,
} from '../services/documents'
import { foldersService, Folder } from '../services/folders'
import { useAuthStore } from '../store/authStore'

type TabType = 'personal' | 'company'
type FolderFilter = number | null | 0  // null=All, 0=Uncategorized

// ─── helpers ─────────────────────────────────────────────────────────────────

const ACCEPTED_EXTENSIONS =
  '.pdf,.docx,.pptx,.xlsx,.html,.eml,.msg,.txt,.md'

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function getFileIcon(contentType: string) {
  if (contentType === 'application/pdf')
    return <svg className="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
  if (
    contentType.includes('word') ||
    contentType.includes('presentation') ||
    contentType.includes('spreadsheet')
  )
    return <svg className="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
  if (contentType.startsWith('text/'))
    return <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
  return <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
}

const PROCESSING_LABELS: Record<string, string> = {
  uploaded: 'Queued',
  parsing: 'Parsing…',
  sectioning: 'Extracting sections…',
  summarizing: 'Summarizing…',
  embedding: 'Embedding…',
  done: 'Indexed',
  failed: 'Failed',
}

function ProcessingBadge({ status }: { status: ProcessingStatus | undefined }) {
  if (!status || status === 'done') return null
  const label = PROCESSING_LABELS[status] ?? status
  const isActive = !['done', 'failed', 'uploaded'].includes(status)
  const color =
    status === 'failed'
      ? 'bg-red-900/30 text-red-400'
      : isActive
      ? 'bg-blue-900/30 text-blue-400'
      : 'bg-dark-chat text-dark-muted'
  return (
    <span className={`flex items-center gap-1 px-2 py-0.5 text-xs rounded ${color}`}>
      {isActive && (
        <svg className="w-3 h-3 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
      )}
      {label}
    </span>
  )
}

function GraphStatusBadge({ status }: { status: GraphStatus | undefined }) {
  if (!status || status === 'skipped') return null
  if (status === 'pending' || status === 'processing')
    return (
      <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-yellow-900/30 text-yellow-400 rounded">
        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
        Graph
      </span>
    )
  if (status === 'done')
    return (
      <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-purple-900/30 text-purple-400 rounded" title="Knowledge graph extracted">
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        Graph
      </span>
    )
  if (status === 'failed')
    return (
      <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-red-900/30 text-red-400 rounded">
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M12 3a9 9 0 100 18A9 9 0 0012 3z" />
        </svg>
        Graph
      </span>
    )
  return null
}

// ─── component ───────────────────────────────────────────────────────────────

export function Documents() {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [activeTab, setActiveTab] = useState<TabType>('personal')
  const [personalDocs, setPersonalDocs] = useState<Document[]>([])
  const [companyDocs, setCompanyDocs] = useState<Document[]>([])
  const [graphStats, setGraphStats] = useState<GraphStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const [folders, setFolders] = useState<Folder[]>([])
  const [activeFolder, setActiveFolder] = useState<FolderFilter>(null)
  const [newFolderName, setNewFolderName] = useState('')
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [renamingFolder, setRenamingFolder] = useState<number | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [movingDoc, setMovingDoc] = useState<number | null>(null)

  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadingFileCount, setUploadingFileCount] = useState(0)
  const [batchResults, setBatchResults] = useState<BatchUploadResponse | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadAsCompany, setUploadAsCompany] = useState(false)
  const [extractGraph, setExtractGraph] = useState(false)
  const [uploadFolderId, setUploadFolderId] = useState<number | null>(null)

  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [reExtracting, setReExtracting] = useState<Set<number>>(new Set())

  const [viewerDoc, setViewerDoc] = useState<Document | null>(null)
  const [viewerChunks, setViewerChunks] = useState<DocumentChunk[]>([])
  const [viewerLoading, setViewerLoading] = useState(false)
  const [viewerTab, setViewerTab] = useState<'preview' | 'text'>('preview')
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null)
  const [pdfNumPages, setPdfNumPages] = useState(0)
  const pdfContainerRef = useRef<HTMLDivElement>(null)

  // ── data fetching ────────────────────────────────────────────────────────

  const handleCloseViewer = useCallback(() => {
    if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl)
    setPdfBlobUrl(null)
    setViewerDoc(null)
  }, [pdfBlobUrl])

  const handleViewDoc = async (doc: Document) => {
    if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl)
    setPdfBlobUrl(null)
    setPdfNumPages(0)
    setViewerDoc(doc)
    setViewerChunks([])
    setViewerLoading(true)
    setViewerTab(doc.content_type === 'application/pdf' ? 'preview' : 'text')
    try {
      const isPdf = doc.content_type === 'application/pdf'
      const [chunksData, blob] = await Promise.all([
        documentsService.getChunks(doc.id),
        isPdf ? documentsService.fetchBlob(doc.id) : Promise.resolve(null),
      ])
      setViewerChunks(chunksData.chunks)
      if (blob) setPdfBlobUrl(URL.createObjectURL(blob))
    } catch { /* ignore */ } finally {
      setViewerLoading(false)
    }
  }

  const fetchDocuments = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await documentsService.list()
      setPersonalDocs(data.personal_documents || [])
      setCompanyDocs(data.company_documents || [])
    } catch { /* ignore */ } finally {
      setIsLoading(false)
    }
  }, [])

  const fetchFolders = useCallback(async () => {
    try { setFolders(await foldersService.list()) } catch { /* ignore */ }
  }, [])

  const fetchGraphStats = async () => {
    try { setGraphStats(await documentsService.getGraphStats()) } catch { /* ignore */ }
  }

  // Poll docs that are still processing (either Docling pipeline or graph)
  useEffect(() => {
    const allDocs = [...personalDocs, ...companyDocs]
    const inProgress = allDocs.filter(
      (d) =>
        d.graph_status === 'pending' ||
        d.graph_status === 'processing' ||
        (d.processing_status && !['done', 'failed', null].includes(d.processing_status)),
    )
    if (inProgress.length === 0) return
    const timer = setInterval(async () => {
      let changed = false
      const updates = await Promise.all(
        inProgress.map((d) => documentsService.getGraphStatus(d.id).catch(() => null))
      )
      const updateDocs = (docs: Document[]) =>
        docs.map((d) => {
          const u = updates.find((r) => r?.id === d.id)
          if (!u) return d
          if (
            u.graph_status !== d.graph_status ||
            u.processing_status !== d.processing_status
          ) {
            changed = true
            return {
              ...d,
              graph_status: u.graph_status,
              processing_status: u.processing_status,
            }
          }
          return d
        })
      setPersonalDocs((prev) => updateDocs(prev))
      setCompanyDocs((prev) => updateDocs(prev))
      if (changed) fetchGraphStats()
    }, 4000)
    return () => clearInterval(timer)
  }, [personalDocs, companyDocs])

  useEffect(() => {
    fetchDocuments()
    fetchFolders()
    fetchGraphStats()
  }, [])

  // ── upload ───────────────────────────────────────────────────────────────

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return
    setIsUploading(true)
    setUploadProgress(0)
    setUploadingFileCount(files.length)
    setBatchResults(null)
    setUploadError(null)
    try {
      const res = await documentsService.uploadBatch(
        files, uploadAsCompany, extractGraph,
        (p) => setUploadProgress(p),
        uploadFolderId,
      )
      setBatchResults(res)
      await fetchDocuments()
      await fetchFolders()
      await fetchGraphStats()
    } catch (err: any) {
      setUploadError(err.response?.data?.detail || 'Upload failed')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  // ── delete ───────────────────────────────────────────────────────────────

  const handleDelete = async (docId: number) => {
    setIsDeleting(true)
    try {
      await documentsService.delete(docId)
      await fetchDocuments()
      await fetchFolders()
      await fetchGraphStats()
      setDeleteConfirm(null)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to delete document')
    } finally {
      setIsDeleting(false)
    }
  }

  // ── graph ────────────────────────────────────────────────────────────────

  const handleReExtractGraph = async (docId: number) => {
    setReExtracting((prev) => new Set(prev).add(docId))
    try {
      await documentsService.reExtractGraph(docId)
      const setPending = (docs: Document[]) =>
        docs.map((d) =>
          d.id === docId ? { ...d, graph_status: 'pending' as GraphStatus } : d
        )
      setPersonalDocs((prev) => setPending(prev))
      setCompanyDocs((prev) => setPending(prev))
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to start graph extraction')
    } finally {
      setReExtracting((prev) => { const s = new Set(prev); s.delete(docId); return s })
    }
  }

  // ── folders ──────────────────────────────────────────────────────────────

  const handleCreateFolder = async () => {
    const name = newFolderName.trim()
    if (!name) return
    try {
      await foldersService.create(name, activeTab === 'company')
      setNewFolderName('')
      setCreatingFolder(false)
      await fetchFolders()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to create folder')
    }
  }

  const handleRenameFolder = async (folderId: number) => {
    const name = renameValue.trim()
    if (!name) return
    try {
      await foldersService.rename(folderId, name)
      setRenamingFolder(null)
      await fetchFolders()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to rename folder')
    }
  }

  const handleDeleteFolder = async (folderId: number) => {
    if (!confirm('Delete this folder? Documents inside will be moved to "Uncategorized".')) return
    try {
      await foldersService.delete(folderId)
      if (activeFolder === folderId) setActiveFolder(null)
      await fetchFolders()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to delete folder')
    }
  }

  const handleMoveDoc = async (docId: number, folderId: number | null) => {
    try {
      await documentsService.moveToFolder(docId, folderId)
      const update = (docs: Document[]) =>
        docs.map((d) => d.id === docId ? { ...d, folder_id: folderId } : d)
      setPersonalDocs((prev) => update(prev))
      setCompanyDocs((prev) => update(prev))
      await fetchFolders()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to move document')
    } finally {
      setMovingDoc(null)
    }
  }

  // ── derived ──────────────────────────────────────────────────────────────

  const currentDocs = activeTab === 'personal' ? personalDocs : companyDocs
  const visibleFolders = folders.filter((f) =>
    activeTab === 'company' ? f.is_company_folder : !f.is_company_folder
  )
  const filteredDocs =
    activeFolder === null
      ? currentDocs
      : activeFolder === 0
      ? currentDocs.filter((d) => !d.folder_id)
      : currentDocs.filter((d) => d.folder_id === activeFolder)

  const uncategorizedCount = currentDocs.filter((d) => !d.folder_id).length

  // ── render ───────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-dark-bg">

      {/* ── Header ── */}
      <div className="flex items-center justify-between p-4 border-b border-dark-chat flex-shrink-0">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/')}
            className="p-2 hover:bg-dark-chat rounded-lg text-dark-muted hover:text-dark-text"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
          </button>
          <div>
            <h1 className="text-xl font-semibold text-dark-text">Document Management</h1>
            <p className="text-sm text-dark-muted">
              Docling · bge-m3 · Structure-aware RAG
            </p>
          </div>
        </div>

        {/* Graph stats pill */}
        {graphStats && (
          <div className="flex items-center gap-3 text-sm">
            <div className="flex items-center gap-2 px-3 py-1 bg-dark-sidebar rounded-lg">
              <svg className="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              <span className="text-dark-muted">Entities:</span>
              <span className="text-dark-text font-medium">{graphStats.total_entities}</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1 bg-dark-sidebar rounded-lg">
              <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              <span className="text-dark-muted">Relations:</span>
              <span className="text-dark-text font-medium">{graphStats.total_relationships}</span>
            </div>
          </div>
        )}
      </div>

      {/* ── Upload bar ── */}
      <div className="p-4 border-b border-dark-chat bg-dark-sidebar flex-shrink-0">
        <div className="flex items-start gap-6">
          <div className="flex-1">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_EXTENSIONS}
              multiple
              onChange={handleFileSelect}
              className="hidden"
              disabled={isUploading || !user}
            />

            {!user ? (
              <div className="border-2 border-dashed border-dark-chat rounded-lg p-4 text-center">
                <p className="text-dark-muted text-sm">Please login to upload documents</p>
              </div>
            ) : isUploading ? (
              <div className="border-2 border-dark-chat rounded-lg p-4">
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-dark-text">
                    Uploading {uploadingFileCount} {uploadingFileCount === 1 ? 'file' : 'files'}…
                  </span>
                  <span className="text-dark-muted">{uploadProgress}%</span>
                </div>
                <div className="w-full bg-dark-chat rounded-full h-2">
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
                {uploadProgress >= 95 && (
                  <p className="text-xs text-dark-muted mt-2">
                    Parsing structure · generating summaries · embedding chunks…
                  </p>
                )}
              </div>
            ) : (
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full border-2 border-dashed border-dark-chat hover:border-blue-500 rounded-lg p-5 text-center transition-colors group"
              >
                <svg className="w-8 h-8 text-dark-muted group-hover:text-blue-400 mx-auto mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <p className="text-dark-text text-sm font-medium">Click to upload documents</p>
                <p className="text-xs text-dark-muted mt-0.5">
                  PDF · DOCX · PPTX · XLSX · HTML · EML · MSG · TXT · MD
                </p>
              </button>
            )}

            {batchResults && (
              <div className={`mt-3 p-3 rounded-lg border text-sm ${
                batchResults.failed === 0
                  ? 'bg-green-900/20 border-green-700'
                  : batchResults.succeeded === 0
                  ? 'bg-red-900/20 border-red-700'
                  : 'bg-yellow-900/20 border-yellow-700'
              }`}>
                <p className={`font-medium ${
                  batchResults.failed === 0 ? 'text-green-400'
                  : batchResults.succeeded === 0 ? 'text-red-400'
                  : 'text-yellow-400'
                }`}>
                  {batchResults.succeeded} of {batchResults.total}{' '}
                  {batchResults.total === 1 ? 'file' : 'files'} indexed
                  {batchResults.failed > 0 && ` (${batchResults.failed} failed)`}
                </p>
                {/* Per-file stats */}
                {batchResults.results.filter((r) => r.status === 'success' && r.stats).map((r, i) => (
                  <p key={i} className="text-xs text-dark-muted mt-1">
                    {r.filename} — {r.stats!.sections_created} sections · {r.stats!.chunks_created} chunks · {r.stats!.processing_time}s
                  </p>
                ))}
              </div>
            )}

            {uploadError && (
              <div className="mt-3 p-3 bg-red-900/20 border border-red-700 rounded-lg">
                <p className="text-red-400 text-sm">{uploadError}</p>
              </div>
            )}
          </div>

          {/* Upload options */}
          <div className="w-56 space-y-3 text-sm">
            <div>
              <p className="text-xs font-medium text-dark-muted mb-1">Visibility</p>
              <div className="space-y-1">
                {([false, true] as const).map((isCompany) => (
                  <label key={String(isCompany)} className="flex items-center gap-2 p-1.5 rounded hover:bg-dark-chat cursor-pointer">
                    <input
                      type="radio"
                      name="visibility"
                      checked={uploadAsCompany === isCompany}
                      onChange={() => setUploadAsCompany(isCompany)}
                      className="w-3.5 h-3.5"
                    />
                    <span className="text-dark-text">{isCompany ? 'Company' : 'Personal'}</span>
                  </label>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-medium text-dark-muted mb-1">Upload to folder</p>
              <select
                className="w-full bg-dark-bg border border-dark-chat rounded px-2 py-1.5 text-sm text-dark-text focus:outline-none"
                value={uploadFolderId ?? ''}
                onChange={(e) => setUploadFolderId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">No folder</option>
                {folders
                  .filter((f) => uploadAsCompany ? f.is_company_folder : !f.is_company_folder)
                  .map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </div>

            <label className="flex items-center gap-2 p-1.5 rounded hover:bg-dark-chat cursor-pointer">
              <input
                type="checkbox"
                checked={extractGraph}
                onChange={(e) => setExtractGraph(e.target.checked)}
                className="w-3.5 h-3.5 rounded"
              />
              <span className="text-dark-text">Extract Knowledge Graph</span>
            </label>
          </div>
        </div>
      </div>

      {/* ── Tabs ── */}
      <div className="flex border-b border-dark-chat flex-shrink-0">
        {(['personal', 'company'] as TabType[]).map((tab) => (
          <button
            key={tab}
            onClick={() => { setActiveTab(tab); setActiveFolder(null) }}
            className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
              activeTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-dark-muted hover:text-dark-text'
            }`}
          >
            {tab === 'personal' ? 'My Documents' : 'Company Documents'}{' '}
            ({(tab === 'personal' ? personalDocs : companyDocs).length})
          </button>
        ))}
      </div>

      {/* ── Body: folder sidebar + list ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Folder sidebar */}
        <div className="w-52 border-r border-dark-chat bg-dark-sidebar flex-shrink-0 flex flex-col overflow-y-auto">
          <div className="p-3 space-y-0.5">
            {[
              { label: 'All', value: null as FolderFilter, count: currentDocs.length },
              { label: 'Uncategorized', value: 0 as FolderFilter, count: uncategorizedCount },
            ].map(({ label, value, count }) => (
              <button
                key={String(value)}
                onClick={() => setActiveFolder(value)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors ${
                  activeFolder === value
                    ? 'bg-dark-hover/20 text-dark-text'
                    : 'text-dark-muted hover:text-dark-text hover:bg-dark-chat'
                }`}
              >
                <span className="flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                  </svg>
                  {label}
                </span>
                <span className="text-xs text-dark-muted">{count}</span>
              </button>
            ))}

            {visibleFolders.length > 0 && <div className="my-2 border-t border-dark-chat" />}

            {visibleFolders.map((folder) => (
              <div key={folder.id} className="group relative">
                {renamingFolder === folder.id ? (
                  <div className="flex items-center gap-1 px-2 py-1">
                    <input
                      autoFocus
                      className="flex-1 bg-dark-bg border border-dark-hover rounded px-2 py-1 text-sm text-dark-text focus:outline-none"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleRenameFolder(folder.id)
                        if (e.key === 'Escape') setRenamingFolder(null)
                      }}
                    />
                    <button onClick={() => handleRenameFolder(folder.id)} className="text-dark-hover text-xs px-1">✓</button>
                  </div>
                ) : (
                  <button
                    onClick={() => setActiveFolder(folder.id)}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors ${
                      activeFolder === folder.id
                        ? 'bg-dark-hover/20 text-dark-text'
                        : 'text-dark-muted hover:text-dark-text hover:bg-dark-chat'
                    }`}
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <svg className="w-4 h-4 flex-shrink-0 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
                      </svg>
                      <span className="truncate">{folder.name}</span>
                    </span>
                    <span className="text-xs text-dark-muted flex-shrink-0">{folder.document_count}</span>
                  </button>
                )}
                {renamingFolder !== folder.id && (
                  <div className="absolute right-1 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center gap-0.5">
                    <button
                      onClick={(e) => { e.stopPropagation(); setRenamingFolder(folder.id); setRenameValue(folder.name) }}
                      className="p-1 rounded text-dark-muted hover:text-dark-text hover:bg-dark-chat"
                      title="Rename"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536M9 13l6-6 3.536 3.536L12.536 16.5 9 17l.5-3.5z" />
                      </svg>
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteFolder(folder.id) }}
                      className="p-1 rounded text-dark-muted hover:text-red-400 hover:bg-dark-chat"
                      title="Delete folder"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="px-3 pb-3 mt-auto">
            {creatingFolder ? (
              <div className="flex items-center gap-1">
                <input
                  autoFocus
                  className="flex-1 bg-dark-bg border border-dark-chat rounded px-2 py-1.5 text-sm text-dark-text focus:outline-none focus:border-dark-hover"
                  placeholder="Folder name"
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleCreateFolder()
                    if (e.key === 'Escape') { setCreatingFolder(false); setNewFolderName('') }
                  }}
                />
                <button onClick={handleCreateFolder} className="p-1.5 text-dark-hover hover:bg-dark-chat rounded">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </button>
              </div>
            ) : (
              <button
                onClick={() => setCreatingFolder(true)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-dark-muted hover:text-dark-text hover:bg-dark-chat transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                New folder
              </button>
            )}
          </div>
        </div>

        {/* Document list */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-dark-muted">Loading documents…</div>
            </div>
          ) : filteredDocs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center p-8">
              <svg className="w-14 h-14 text-dark-muted mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-dark-muted text-sm">
                {activeFolder !== null
                  ? 'No documents in this folder'
                  : activeTab === 'personal'
                  ? 'No personal documents yet'
                  : 'No company documents yet'}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-dark-chat">
              {filteredDocs.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-dark-sidebar transition-colors"
                >
                  <div className="w-9 h-9 bg-dark-chat rounded-lg flex items-center justify-center flex-shrink-0">
                    {getFileIcon(doc.content_type)}
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-dark-text truncate">{doc.filename}</p>
                    <div className="flex items-center flex-wrap gap-x-2 gap-y-0.5 mt-0.5">
                      <span className="text-xs text-dark-muted">{formatFileSize(doc.file_size)}</span>
                      <span className="text-xs text-dark-muted">·</span>
                      <span className="text-xs text-dark-muted">{formatDate(doc.created_at)}</span>
                      {doc.sections_count != null && doc.sections_count > 0 && (
                        <>
                          <span className="text-xs text-dark-muted">·</span>
                          <span className="text-xs text-dark-muted">{doc.sections_count} sections</span>
                        </>
                      )}
                      {doc.folder_id && (
                        <>
                          <span className="text-xs text-dark-muted">·</span>
                          <span className="text-xs text-yellow-500 flex items-center gap-1">
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                              <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
                            </svg>
                            {folders.find((f) => f.id === doc.folder_id)?.name ?? 'Folder'}
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {doc.is_company_doc && (
                      <span className="px-2 py-0.5 text-xs bg-purple-900/30 text-purple-400 rounded">Company</span>
                    )}
                    <ProcessingBadge status={doc.processing_status} />
                    <GraphStatusBadge status={doc.graph_status} />

                    {/* Move to folder */}
                    {user && (
                      <div className="relative">
                        <button
                          onClick={() => setMovingDoc(movingDoc === doc.id ? null : doc.id)}
                          className="p-1.5 text-dark-muted hover:text-yellow-400 hover:bg-dark-chat rounded"
                          title="Move to folder"
                        >
                          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
                          </svg>
                        </button>
                        {movingDoc === doc.id && (
                          <div className="absolute right-0 top-8 z-30 bg-dark-sidebar border border-dark-chat rounded-lg shadow-xl min-w-[160px] py-1">
                            <button
                              onClick={() => handleMoveDoc(doc.id, null)}
                              className="w-full text-left px-3 py-2 text-xs text-dark-muted hover:text-dark-text hover:bg-dark-chat"
                            >
                              Remove from folder
                            </button>
                            {visibleFolders.map((f) => (
                              <button
                                key={f.id}
                                onClick={() => handleMoveDoc(doc.id, f.id)}
                                className={`w-full text-left px-3 py-2 text-xs hover:bg-dark-chat flex items-center gap-2 ${
                                  doc.folder_id === f.id ? 'text-yellow-400' : 'text-dark-text'
                                }`}
                              >
                                <svg className="w-3.5 h-3.5 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
                                  <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
                                </svg>
                                {f.name}{doc.folder_id === f.id && ' ✓'}
                              </button>
                            ))}
                            {visibleFolders.length === 0 && (
                              <p className="px-3 py-2 text-xs text-dark-muted">No folders yet</p>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Re-extract graph */}
                    {user && (
                      <button
                        onClick={() => handleReExtractGraph(doc.id)}
                        disabled={
                          reExtracting.has(doc.id) ||
                          doc.graph_status === 'pending' ||
                          doc.graph_status === 'processing'
                        }
                        className="p-1.5 text-dark-muted hover:text-purple-400 hover:bg-dark-chat rounded disabled:opacity-40 disabled:cursor-not-allowed"
                        title="Re-extract knowledge graph"
                      >
                        {reExtracting.has(doc.id) ? (
                          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                          </svg>
                        ) : (
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                          </svg>
                        )}
                      </button>
                    )}

                    {/* Download */}
                    <button
                      onClick={() => documentsService.download(doc.id, doc.filename)}
                      className="p-1.5 text-dark-muted hover:text-green-400 hover:bg-dark-chat rounded"
                      title="Download"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                    </button>

                    {/* View chunks */}
                    {doc.processing_status === 'done' && (
                      <button
                        onClick={() => handleViewDoc(doc)}
                        className="p-1.5 text-dark-muted hover:text-blue-400 hover:bg-dark-chat rounded"
                        title="View document"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                      </button>
                    )}

                    {/* Delete */}
                    <button
                      onClick={() => setDeleteConfirm(doc.id)}
                      className="p-1.5 text-dark-muted hover:text-red-500 hover:bg-dark-chat rounded"
                      title="Delete"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Delete confirmation modal ── */}
      {deleteConfirm !== null && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-dark-sidebar rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl">
            <h3 className="text-lg font-semibold text-dark-text mb-2">Delete Document?</h3>
            <p className="text-dark-muted text-sm mb-5">
              This permanently deletes the document, all extracted sections, chunks, and
              knowledge graph data.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                disabled={isDeleting}
                className="flex-1 px-4 py-2 bg-dark-chat text-dark-text rounded-lg hover:bg-dark-hover disabled:opacity-50 text-sm"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={isDeleting}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 text-sm"
              >
                {isDeleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Click-outside for move dropdown */}
      {movingDoc !== null && (
        <div className="fixed inset-0 z-20" onClick={() => setMovingDoc(null)} />
      )}

      {/* ── Document viewer panel ── */}
      {viewerDoc && (
        <>
          <div className="fixed inset-0 bg-black/40 z-40" onClick={handleCloseViewer} />
          <div className="fixed right-0 top-0 h-full w-full max-w-6xl bg-dark-sidebar border-l border-dark-chat z-50 flex flex-col shadow-2xl">

            {/* Header */}
            <div className="flex items-center gap-3 px-5 py-4 border-b border-dark-chat flex-shrink-0">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-dark-text truncate">{viewerDoc.filename}</p>
                <p className="text-xs text-dark-muted mt-0.5">
                  {viewerLoading ? 'Loading…' : viewerTab === 'text' ? `${viewerChunks.length} chunks` : `${pdfNumPages} pages`}
                </p>
              </div>
              <button
                onClick={() => documentsService.download(viewerDoc.id, viewerDoc.filename)}
                className="p-1.5 text-dark-muted hover:text-green-400 hover:bg-dark-chat rounded"
                title="Download"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
              </button>
              <button onClick={handleCloseViewer} className="p-1.5 text-dark-muted hover:text-dark-text hover:bg-dark-chat rounded">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Tabs (PDF only) */}
            {viewerDoc.content_type === 'application/pdf' && (
              <div className="flex border-b border-dark-chat flex-shrink-0">
                {(['preview', 'text'] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setViewerTab(tab)}
                    className={`px-5 py-2.5 text-sm capitalize transition-colors ${
                      viewerTab === tab
                        ? 'text-blue-400 border-b-2 border-blue-400 -mb-px'
                        : 'text-dark-muted hover:text-dark-text'
                    }`}
                  >
                    {tab === 'preview' ? 'Preview' : 'Text'}
                  </button>
                ))}
              </div>
            )}

            {/* Body */}
            <div ref={pdfContainerRef} className="flex-1 overflow-y-auto">

              {/* PDF preview tab */}
              {viewerTab === 'preview' && viewerDoc.content_type === 'application/pdf' && (
                <div className="flex flex-col items-center py-4 px-2 gap-4">
                  {viewerLoading || !pdfBlobUrl ? (
                    <div className="flex items-center justify-center py-16">
                      <svg className="w-6 h-6 animate-spin text-dark-muted" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                    </div>
                  ) : (
                    <PdfDocument
                      file={pdfBlobUrl}
                      onLoadSuccess={({ numPages }) => setPdfNumPages(numPages)}
                      loading={
                        <div className="flex items-center justify-center py-16">
                          <svg className="w-6 h-6 animate-spin text-dark-muted" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                          </svg>
                        </div>
                      }
                    >
                      {Array.from({ length: pdfNumPages }, (_, i) => (
                        <div key={i} className="flex flex-col items-center">
                          <PdfPage
                            pageNumber={i + 1}
                            width={Math.min((pdfContainerRef.current?.clientWidth ?? 640) - 24, 640)}
                            renderTextLayer
                            renderAnnotationLayer={false}
                          />
                          <p className="text-xs text-dark-muted py-1">Page {i + 1} of {pdfNumPages}</p>
                          {i < pdfNumPages - 1 && <div className="w-full h-px bg-dark-chat my-2" />}
                        </div>
                      ))}
                    </PdfDocument>
                  )}
                </div>
              )}

              {/* Text / chunks tab */}
              {viewerTab === 'text' && (
                <div className="px-5 py-4 space-y-1">
                  {viewerLoading ? (
                    <div className="flex items-center justify-center py-16">
                      <svg className="w-6 h-6 animate-spin text-dark-muted" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                    </div>
                  ) : viewerChunks.length === 0 ? (
                    <p className="text-dark-muted text-sm text-center py-16">No chunks found.</p>
                  ) : (
                    viewerChunks.map((chunk, i) => {
                      const prevHeading = i > 0 ? viewerChunks[i - 1].heading_context : null
                      const showHeading = chunk.heading_context && chunk.heading_context !== prevHeading
                      const sectionTitle = chunk.heading_context
                        ? chunk.heading_context.split('>').pop()?.trim() ?? chunk.heading_context
                        : null
                      return (
                        <div key={chunk.id}>
                          {showHeading && sectionTitle && (
                            <h3 className="text-xs font-semibold text-blue-400 uppercase tracking-wide mt-5 mb-2 first:mt-0">
                              {sectionTitle}
                            </h3>
                          )}
                          <div className="bg-dark-chat rounded-lg px-4 py-3 mb-2">
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                h1: ({ children }) => <h1 className="text-lg font-bold mt-3 mb-2 text-dark-text">{children}</h1>,
                                h2: ({ children }) => <h2 className="text-base font-bold mt-3 mb-2 text-dark-text">{children}</h2>,
                                h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-1 text-dark-text">{children}</h3>,
                                p: ({ children }) => <p className="text-sm text-dark-text leading-relaxed mb-2 last:mb-0">{children}</p>,
                                ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-1 text-sm text-dark-text">{children}</ul>,
                                ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-1 text-sm text-dark-text">{children}</ol>,
                                li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                                strong: ({ children }) => <strong className="font-semibold text-dark-text">{children}</strong>,
                                em: ({ children }) => <em className="italic text-dark-muted">{children}</em>,
                                code: ({ children }) => <code className="bg-dark-bg px-1 py-0.5 rounded text-xs font-mono text-blue-300">{children}</code>,
                                blockquote: ({ children }) => <blockquote className="border-l-2 border-dark-hover pl-3 my-2 italic text-dark-muted text-sm">{children}</blockquote>,
                                table: ({ children }) => <div className="overflow-x-auto mb-2"><table className="text-xs text-dark-text border-collapse w-full">{children}</table></div>,
                                th: ({ children }) => <th className="border border-dark-hover px-2 py-1 bg-dark-bg font-semibold text-left">{children}</th>,
                                td: ({ children }) => <td className="border border-dark-hover px-2 py-1">{children}</td>,
                              }}
                            >
                              {chunk.chunk_text.replace(/<!--.*?-->/gs, '').trim()}
                            </ReactMarkdown>
                            <p className="text-xs text-dark-muted mt-2">
                              p. {chunk.page_start === chunk.page_end ? chunk.page_start : `${chunk.page_start}–${chunk.page_end}`}
                            </p>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              )}

            </div>
          </div>
        </>
      )}
    </div>
  )
}
