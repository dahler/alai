import { api } from './api'

export interface Document {
  id: number
  filename: string
  content_type: string
  file_size: number
  is_company_doc: boolean
  created_at: string
}

export interface DocumentListResponse {
  personal_documents: Document[]
  company_documents: Document[]
}

export interface UploadStats {
  chunks_created: number
  entities_extracted: number
  entities_new: number
  entities_linked: number
  relationships_created: number
  processing_time: number
}

export interface UploadResponse {
  id: number
  filename: string
  content_type: string
  file_size: number
  is_company_doc: boolean
  message: string
  stats: UploadStats
}

export interface DeleteResponse {
  message: string
  chunks_deleted: number
  graph_links_deleted: number
  graph_relationships_deleted: number
}

export interface GraphStats {
  total_entities: number
  total_relationships: number
  documents_with_graph: number
  entities_by_type: Record<string, number>
  relationships_by_type: Record<string, number>
}

export const documentsService = {
  // List all documents (personal + company)
  async list(): Promise<DocumentListResponse> {
    const response = await api.get('/documents')
    return response.data
  },

  // Upload a document for RAG
  async upload(
    file: File,
    isCompanyDoc: boolean = false,
    extractGraph: boolean = true,
    onProgress?: (progress: number) => void
  ): Promise<UploadResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('is_company_doc', String(isCompanyDoc))
    formData.append('extract_graph', String(extractGraph))

    const response = await api.post('/documents/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          onProgress(progress)
        }
      },
    })
    return response.data
  },

  // Delete a document
  async delete(documentId: number): Promise<DeleteResponse> {
    const response = await api.delete(`/documents/${documentId}`)
    return response.data
  },

  // Search documents
  async search(query: string, topK: number = 5): Promise<any> {
    const response = await api.get('/documents/search', {
      params: { query, top_k: topK },
    })
    return response.data
  },

  // Get graph statistics
  async getGraphStats(): Promise<GraphStats> {
    const response = await api.get('/graph/stats')
    return response.data
  },

  // Get document graph data
  async getDocumentGraph(documentId: number): Promise<any> {
    const response = await api.get(`/graph/documents/${documentId}`)
    return response.data
  },

  // Get related documents
  async getRelatedDocuments(documentId: number): Promise<any> {
    const response = await api.get(`/graph/documents/${documentId}/related`)
    return response.data
  },
}
