import { useEffect, useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { documentsService, Document, BatchUploadResponse, GraphStats, GraphStatus } from '../services/documents'
import { useAuthStore } from '../store/authStore'

type TabType = 'personal' | 'company'

export function Documents() {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [activeTab, setActiveTab] = useState<TabType>('personal')
  const [personalDocs, setPersonalDocs] = useState<Document[]>([])
  const [companyDocs, setCompanyDocs] = useState<Document[]>([])
  const [graphStats, setGraphStats] = useState<GraphStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null)

  // Upload state
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadingFileCount, setUploadingFileCount] = useState(0)
  const [batchResults, setBatchResults] = useState<BatchUploadResponse | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  // Upload options
  const [uploadAsCompany, setUploadAsCompany] = useState(false)
  const [extractGraph, setExtractGraph] = useState(true)

  // Delete confirmation
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  // Re-extract graph state: set of doc IDs currently triggering re-extraction
  const [reExtracting, setReExtracting] = useState<Set<number>>(new Set())

  const fetchDocuments = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await documentsService.list()
      setPersonalDocs(data.personal_documents || [])
      setCompanyDocs(data.company_documents || [])
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  const fetchGraphStats = async () => {
    try {
      const stats = await documentsService.getGraphStats()
      setGraphStats(stats)
    } catch (error) {
      console.error('Failed to fetch graph stats:', error)
    }
  }

  // Poll graph status for documents that are still processing
  useEffect(() => {
    const allDocs = [...personalDocs, ...companyDocs]
    const inProgress = allDocs.filter(
      (d) => d.graph_status === 'pending' || d.graph_status === 'processing'
    )
    if (inProgress.length === 0) return

    const timer = setInterval(async () => {
      let anyChanged = false
      const updates = await Promise.all(
        inProgress.map((d) => documentsService.getGraphStatus(d.id).catch(() => null))
      )
      const updateDoc = (docs: Document[]) =>
        docs.map((d) => {
          const u = updates.find((r) => r?.id === d.id)
          if (u && u.graph_status !== d.graph_status) { anyChanged = true; return { ...d, graph_status: u.graph_status } }
          return d
        })

      setPersonalDocs((prev) => updateDoc(prev))
      setCompanyDocs((prev) => updateDoc(prev))
      if (anyChanged) fetchGraphStats()
    }, 4000)

    return () => clearInterval(timer)
  }, [personalDocs, companyDocs])

  useEffect(() => {
    fetchDocuments()
    fetchGraphStats()
  }, [])

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return

    setIsUploading(true)
    setUploadProgress(0)
    setUploadingFileCount(files.length)
    setBatchResults(null)
    setUploadError(null)

    try {
      const response = await documentsService.uploadBatch(
        files,
        uploadAsCompany,
        extractGraph,
        (progress) => setUploadProgress(progress)
      )
      setBatchResults(response)
      await fetchDocuments()
      await fetchGraphStats()
    } catch (error: any) {
      console.error('Upload failed:', error)
      setUploadError(error.response?.data?.detail || 'Upload failed')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleDelete = async (docId: number) => {
    setIsDeleting(true)
    try {
      await documentsService.delete(docId)
      await fetchDocuments()
      await fetchGraphStats()
      setDeleteConfirm(null)
      if (selectedDoc?.id === docId) {
        setSelectedDoc(null)
      }
    } catch (error: any) {
      console.error('Delete failed:', error)
      alert(error.response?.data?.detail || 'Failed to delete document')
    } finally {
      setIsDeleting(false)
    }
  }

  const handleReExtractGraph = async (docId: number) => {
    setReExtracting((prev) => new Set(prev).add(docId))
    try {
      await documentsService.reExtractGraph(docId)
      // Update the doc's graph_status to 'pending' immediately so polling kicks in
      const setPending = (docs: Document[]) =>
        docs.map((d) => (d.id === docId ? { ...d, graph_status: 'pending' as GraphStatus } : d))
      setPersonalDocs((prev) => setPending(prev))
      setCompanyDocs((prev) => setPending(prev))
    } catch (error: any) {
      alert(error.response?.data?.detail || 'Failed to start graph extraction')
    } finally {
      setReExtracting((prev) => { const s = new Set(prev); s.delete(docId); return s })
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const formatDate = (dateStr: string): string => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const getFileIcon = (contentType: string) => {
    if (contentType === 'application/pdf') {
      return (
        <svg className="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
        </svg>
      )
    }
    if (contentType.startsWith('text/')) {
      return (
        <svg className="w-6 h-6 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      )
    }
    return (
      <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    )
  }

  const GraphStatusBadge = ({ status }: { status: GraphStatus | undefined }) => {
    if (!status || status === 'skipped') return null
    if (status === 'pending' || status === 'processing') {
      return (
        <span className="flex items-center gap-1 px-2 py-1 text-xs bg-yellow-900/30 text-yellow-400 rounded">
          <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          Graph
        </span>
      )
    }
    if (status === 'done') {
      return (
        <span className="flex items-center gap-1 px-2 py-1 text-xs bg-purple-900/30 text-purple-400 rounded" title="Knowledge graph extracted">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          Graph
        </span>
      )
    }
    if (status === 'failed') {
      return (
        <span className="flex items-center gap-1 px-2 py-1 text-xs bg-red-900/30 text-red-400 rounded" title="Graph extraction failed">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M12 3a9 9 0 100 18A9 9 0 0012 3z" />
          </svg>
          Graph
        </span>
      )
    }
    return null
  }

  const currentDocs = activeTab === 'personal' ? personalDocs : companyDocs

  return (
    <div className="flex flex-col h-full bg-dark-bg">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-dark-chat">
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
            <p className="text-sm text-dark-muted">Upload documents for RAG and Knowledge Graph</p>
          </div>
        </div>

        {/* Graph Stats */}
        {graphStats && (
          <div className="flex items-center gap-4 text-sm">
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

      {/* Upload Section */}
      <div className="p-4 border-b border-dark-chat bg-dark-sidebar">
        <div className="flex items-start gap-6">
          {/* Upload Area */}
          <div className="flex-1">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.md,.json,.html,.xml"
              multiple
              onChange={handleFileSelect}
              className="hidden"
              disabled={isUploading || !user}
            />

            {!user ? (
              <div className="border-2 border-dashed border-dark-chat rounded-lg p-6 text-center">
                <svg className="w-10 h-10 text-dark-muted mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                <p className="text-dark-muted">Please login to upload documents</p>
              </div>
            ) : isUploading ? (
              <div className="border-2 border-dark-chat rounded-lg p-6">
                <div className="flex-1">
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-dark-text">
                      Uploading {uploadingFileCount} {uploadingFileCount === 1 ? 'file' : 'files'}...
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
                    <p className="text-sm text-dark-muted mt-2">
                      Indexing chunks and generating embeddings...
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full border-2 border-dashed border-dark-chat hover:border-blue-500 rounded-lg p-6 text-center transition-colors group"
              >
                <svg className="w-10 h-10 text-dark-muted group-hover:text-blue-400 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <p className="text-dark-text font-medium">Click to upload documents</p>
                <p className="text-sm text-dark-muted mt-1">PDF, TXT, MD, JSON, HTML, XML — multiple files supported</p>
              </button>
            )}

            {/* Upload Result */}
            {batchResults && (
              <div className="mt-3 space-y-2">
                <div className={`p-3 rounded-lg border ${
                  batchResults.failed === 0
                    ? 'bg-green-900/20 border-green-700'
                    : batchResults.succeeded === 0
                      ? 'bg-red-900/20 border-red-700'
                      : 'bg-yellow-900/20 border-yellow-700'
                }`}>
                  <p className={`font-medium mb-1 ${
                    batchResults.failed === 0 ? 'text-green-400' : batchResults.succeeded === 0 ? 'text-red-400' : 'text-yellow-400'
                  }`}>
                    {batchResults.succeeded} of {batchResults.total} {batchResults.total === 1 ? 'file' : 'files'} processed successfully
                    {batchResults.failed > 0 && ` (${batchResults.failed} failed)`}
                  </p>
                  {batchResults.succeeded > 0 && (() => {
                    const totalChunks = batchResults.results
                      .filter(r => r.status === 'success' && r.stats)
                      .reduce((acc, r) => acc + (r.stats?.chunks_created ?? 0), 0)
                    const graphPending = batchResults.results
                      .filter(r => r.status === 'success' && (r.graph_status === 'pending' || r.graph_status === 'processing'))
                      .length
                    return (
                      <div className="text-sm space-y-1">
                        <div><span className="text-dark-muted">Chunks indexed:</span><span className="text-dark-text ml-1">{totalChunks}</span></div>
                        {graphPending > 0 && (
                          <div className="flex items-center gap-1 text-yellow-400">
                            <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                            </svg>
                            Knowledge graph extraction running in background
                          </div>
                        )}
                      </div>
                    )
                  })()}
                </div>
                {batchResults.results.filter(r => r.status === 'error').map((r, i) => (
                  <div key={i} className="p-2 bg-red-900/20 border border-red-700 rounded-lg text-sm">
                    <span className="text-red-400 font-medium">{r.filename}</span>
                    <span className="text-dark-muted ml-2">{r.error}</span>
                  </div>
                ))}
              </div>
            )}

            {uploadError && (
              <div className="mt-3 p-3 bg-red-900/20 border border-red-700 rounded-lg">
                <p className="text-red-400">{uploadError}</p>
              </div>
            )}
          </div>

          {/* Upload Options */}
          <div className="w-64 space-y-4">
            <div>
              <label className="text-sm font-medium text-dark-text block mb-2">
                Document Visibility
              </label>
              <div className="space-y-2">
                <label className="flex items-center gap-3 p-2 rounded-lg hover:bg-dark-chat cursor-pointer">
                  <input
                    type="radio"
                    name="visibility"
                    checked={!uploadAsCompany}
                    onChange={() => setUploadAsCompany(false)}
                    className="w-4 h-4 text-blue-500"
                  />
                  <div>
                    <p className="text-dark-text text-sm">Personal</p>
                    <p className="text-dark-muted text-xs">Only you can access via RAG</p>
                  </div>
                </label>
                <label className="flex items-center gap-3 p-2 rounded-lg hover:bg-dark-chat cursor-pointer">
                  <input
                    type="radio"
                    name="visibility"
                    checked={uploadAsCompany}
                    onChange={() => setUploadAsCompany(true)}
                    className="w-4 h-4 text-blue-500"
                  />
                  <div>
                    <p className="text-dark-text text-sm">Company</p>
                    <p className="text-dark-muted text-xs">Everyone can access via RAG</p>
                  </div>
                </label>
              </div>
            </div>

            <div>
              <label className="flex items-center gap-3 p-2 rounded-lg hover:bg-dark-chat cursor-pointer">
                <input
                  type="checkbox"
                  checked={extractGraph}
                  onChange={(e) => setExtractGraph(e.target.checked)}
                  className="w-4 h-4 text-blue-500 rounded"
                />
                <div>
                  <p className="text-dark-text text-sm">Extract Knowledge Graph</p>
                  <p className="text-dark-muted text-xs">Extract entities & relationships</p>
                </div>
              </label>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-dark-chat">
        <button
          onClick={() => setActiveTab('personal')}
          className={`flex-1 py-3 text-sm font-medium transition-colors ${
            activeTab === 'personal'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-dark-muted hover:text-dark-text'
          }`}
        >
          My Documents ({personalDocs.length})
        </button>
        <button
          onClick={() => setActiveTab('company')}
          className={`flex-1 py-3 text-sm font-medium transition-colors ${
            activeTab === 'company'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-dark-muted hover:text-dark-text'
          }`}
        >
          Company Documents ({companyDocs.length})
        </button>
      </div>

      {/* Document List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-dark-muted">Loading documents...</div>
          </div>
        ) : currentDocs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center p-8">
            <svg className="w-16 h-16 text-dark-muted mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-dark-muted">
              {activeTab === 'personal'
                ? 'No personal documents yet'
                : 'No company documents yet'}
            </p>
            <p className="text-sm text-dark-muted mt-1">
              {activeTab === 'personal'
                ? 'Upload documents to use them in your RAG searches'
                : 'Company documents are accessible by all users'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-dark-chat">
            {currentDocs.map((doc) => (
              <div
                key={doc.id}
                className={`flex items-center gap-4 p-4 hover:bg-dark-sidebar transition-colors ${
                  selectedDoc?.id === doc.id ? 'bg-dark-sidebar' : ''
                }`}
              >
                <div className="flex-shrink-0 w-10 h-10 bg-dark-chat rounded-lg flex items-center justify-center">
                  {getFileIcon(doc.content_type)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-dark-text truncate">
                    {doc.filename}
                  </p>
                  <p className="text-xs text-dark-muted">
                    {formatFileSize(doc.file_size)} • {formatDate(doc.created_at)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {doc.is_company_doc && (
                    <span className="px-2 py-1 text-xs bg-purple-900/30 text-purple-400 rounded">
                      Company
                    </span>
                  )}
                  <GraphStatusBadge status={doc.graph_status} />
                  {user && (
                    <button
                      onClick={() => handleReExtractGraph(doc.id)}
                      disabled={reExtracting.has(doc.id) || doc.graph_status === 'pending' || doc.graph_status === 'processing'}
                      className="p-2 text-dark-muted hover:text-purple-400 hover:bg-dark-chat rounded disabled:opacity-40 disabled:cursor-not-allowed"
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
                  <button
                    onClick={() => setDeleteConfirm(doc.id)}
                    className="p-2 text-dark-muted hover:text-red-500 hover:bg-dark-chat rounded"
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

      {/* Delete Confirmation Modal */}
      {deleteConfirm !== null && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-dark-sidebar rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-dark-text mb-2">
              Delete Document?
            </h3>
            <p className="text-dark-muted mb-4">
              This will permanently delete the document and remove it from the knowledge graph.
              All extracted entities and relationships from this document will be removed.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                disabled={isDeleting}
                className="flex-1 px-4 py-2 bg-dark-chat text-dark-text rounded-lg hover:bg-dark-hover disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={isDeleting}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {isDeleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
