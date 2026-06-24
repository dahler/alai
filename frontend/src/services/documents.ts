import { api } from './api'

export type GraphStatus =
  | 'pending' | 'processing' | 'done' | 'failed' | 'skipped' | null

export type ProcessingStatus =
  | 'uploaded' | 'parsing' | 'sectioning' | 'summarizing'
  | 'embedding' | 'done' | 'failed' | null

export interface Document {
  id: number
  filename: string
  content_type: string
  file_size: number
  is_company_doc: boolean
  created_at: string
  graph_status?: GraphStatus
  processing_status?: ProcessingStatus
  sections_count?: number
  version?: number
  folder_id?: number | null
}

export interface DocumentListResponse {
  personal_documents: Document[]
  company_documents: Document[]
}

export interface UploadStats {
  sections_created: number
  chunks_created: number
  processing_time: number
}

export interface UploadResponse {
  id: number
  filename: string
  content_type: string
  file_size: number
  is_company_doc: boolean
  graph_status: GraphStatus
  processing_status: ProcessingStatus
  message: string
  stats: UploadStats
}

export interface BatchUploadResult {
  filename: string
  status: 'success' | 'error'
  id?: number
  file_size?: number
  graph_status?: GraphStatus
  processing_status?: ProcessingStatus
  stats?: UploadStats
  error?: string
}

export interface BatchUploadResponse {
  results: BatchUploadResult[]
  total: number
  succeeded: number
  failed: number
}

export interface DeleteResponse {
  message: string
  chunks_deleted: number
  graph_links_deleted: number
  graph_relationships_deleted: number
}

export interface DocumentChunk {
  id: number
  chunk_index: number
  chunk_text: string
  heading_context: string | null
  page_start: number
  page_end: number
}

export interface DocumentChunksResponse {
  document: { id: number; filename: string; sections_count: number }
  chunks: DocumentChunk[]
}

export interface GraphStats {
  total_entities: number
  total_relationships: number
  documents_with_graph: number
  entities_by_type: Record<string, number>
  relationships_by_type: Record<string, number>
}

export const documentsService = {
  async list(): Promise<DocumentListResponse> {
    const response = await api.get('/documents')
    return response.data
  },

  async upload(
    file: File,
    isCompanyDoc = false,
    extractGraph = true,
    onProgress?: (progress: number) => void,
    folderId?: number | null,
  ): Promise<UploadResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('is_company_doc', String(isCompanyDoc))
    formData.append('extract_graph', String(extractGraph))
    if (folderId != null) formData.append('folder_id', String(folderId))
    const response = await api.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total)
          onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
    return response.data
  },

  async uploadBatch(
    files: File[],
    isCompanyDoc = false,
    extractGraph = true,
    onProgress?: (progress: number) => void,
    folderId?: number | null,
  ): Promise<BatchUploadResponse> {
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    formData.append('is_company_doc', String(isCompanyDoc))
    formData.append('extract_graph', String(extractGraph))
    if (folderId != null) formData.append('folder_id', String(folderId))
    const response = await api.post('/documents/upload-batch', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total)
          onProgress(Math.min(Math.round((e.loaded * 100) / e.total), 95))
      },
    })
    return response.data
  },

  async delete(documentId: number): Promise<DeleteResponse> {
    const response = await api.delete(`/documents/${documentId}`)
    return response.data
  },

  async search(query: string, topK = 5): Promise<any> {
    const response = await api.get('/documents/search', {
      params: { query, top_k: topK },
    })
    return response.data
  },

  async getGraphStatus(
    documentId: number,
  ): Promise<{ id: number; graph_status: GraphStatus; processing_status: ProcessingStatus }> {
    const response = await api.get(`/documents/${documentId}/graph-status`)
    return response.data
  },

  async reExtractGraph(
    documentId: number,
  ): Promise<{ id: number; graph_status: GraphStatus }> {
    const response = await api.post(`/documents/${documentId}/extract-graph`)
    return response.data
  },

  async moveToFolder(
    documentId: number,
    folderId: number | null,
  ): Promise<{ id: number; folder_id: number | null }> {
    const response = await api.patch(`/documents/${documentId}/folder`, {
      folder_id: folderId,
    })
    return response.data
  },

  async getChunks(documentId: number): Promise<DocumentChunksResponse> {
    const response = await api.get(`/documents/${documentId}/chunks`)
    return response.data
  },

  async fetchBlob(documentId: number): Promise<Blob> {
    const response = await api.get(`/documents/${documentId}/download`, {
      responseType: 'blob',
    })
    return response.data
  },

  async download(documentId: number, filename: string): Promise<void> {
    const response = await api.get(`/documents/${documentId}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(response.data)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  },

  async getGraphStats(): Promise<GraphStats> {
    const response = await api.get('/graph/stats')
    return response.data
  },

  async getDocumentGraph(documentId: number): Promise<any> {
    const response = await api.get(`/graph/documents/${documentId}`)
    return response.data
  },

  async getRelatedDocuments(documentId: number): Promise<any> {
    const response = await api.get(`/graph/documents/${documentId}/related`)
    return response.data
  },
}
