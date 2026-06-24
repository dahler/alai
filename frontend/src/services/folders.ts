import { api } from './api'

export interface Folder {
  id: number
  name: string
  is_company_folder: boolean
  document_count: number
  created_at: string
}

export const foldersService = {
  list: async (): Promise<Folder[]> => {
    const { data } = await api.get('/folders')
    return data
  },

  create: async (name: string, isCompanyFolder = false): Promise<Folder> => {
    const { data } = await api.post('/folders', { name, is_company_folder: isCompanyFolder })
    return data
  },

  rename: async (id: number, name: string): Promise<Folder> => {
    const { data } = await api.patch(`/folders/${id}`, { name })
    return data
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/folders/${id}`)
  },
}
