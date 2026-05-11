import { api } from './api'
import type { UploadResponse } from '../types/chat'

export interface FileInfo {
  id: number
  filename: string
  original_filename: string
  content_type: string
  file_size: number
  url: string
  is_image: boolean
  created_at: string | null
}

export const uploadsService = {
  async upload(file: File): Promise<UploadResponse> {
    const formData = new FormData()
    formData.append('file', file)

    const response = await api.post<UploadResponse>('/uploads', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  async list(): Promise<FileInfo[]> {
    const response = await api.get<FileInfo[]>('/uploads')
    return response.data
  },

  async delete(attachmentId: number): Promise<void> {
    await api.delete(`/uploads/${attachmentId}`)
  },

  async deleteAll(): Promise<void> {
    const files = await this.list()
    await Promise.all(files.map(f => this.delete(f.id)))
  },

  getFileUrl(filename: string): string {
    const baseUrl = import.meta.env.VITE_API_URL || ''
    return `${baseUrl}/api/uploads/${filename}`
  },

  getDownloadAllUrl(): string {
    const baseUrl = import.meta.env.VITE_API_URL || ''
    return `${baseUrl}/api/uploads/download/all`
  },
}
