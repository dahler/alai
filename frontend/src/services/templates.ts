import { api } from './api'

export interface TemplateSection {
  heading: string
  level: number
  placeholder: string
  has_table: boolean
  table_headers: string[]
}

export interface ReportTemplate {
  id: number
  name: string
  description: string | null
  format: 'pdf' | 'docx' | 'xlsx' | 'pptx'
  sections: TemplateSection[]
  keywords: string | null
  owner_id: number | null
  is_company_wide: boolean
  is_mine: boolean
  has_template_file: boolean
}

export interface TemplateCreate {
  name: string
  description?: string
  format: string
  sections: TemplateSection[]
  keywords?: string
  temp_file_id?: string
}

export interface ExtractedHeading {
  heading: string
  level: number
}

export interface ExtractHeadingsResponse {
  headings: ExtractedHeading[]
  temp_file_id: string | null
}

export const templatesService = {
  list: async (): Promise<ReportTemplate[]> => {
    const { data } = await api.get('/templates')
    return data
  },

  get: async (id: number): Promise<ReportTemplate> => {
    const { data } = await api.get(`/templates/${id}`)
    return data
  },

  create: async (payload: TemplateCreate): Promise<ReportTemplate> => {
    const { data } = await api.post('/templates', payload)
    return data
  },

  update: async (id: number, payload: Partial<TemplateCreate>): Promise<ReportTemplate> => {
    const { data } = await api.put(`/templates/${id}`, payload)
    return data
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/templates/${id}`)
  },

  toggleCompanyWide: async (id: number): Promise<ReportTemplate> => {
    const { data } = await api.patch(`/templates/${id}/company-wide`)
    return data
  },

  extractHeadings: async (file: File): Promise<ExtractHeadingsResponse> => {
    const form = new FormData()
    form.append('file', file)
    const { data } = await api.post('/templates/extract-headings', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },
}

export const defaultSection = (): TemplateSection => ({
  heading: '',
  level: 1,
  placeholder: '',
  has_table: false,
  table_headers: [],
})
