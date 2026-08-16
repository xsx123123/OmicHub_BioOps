import apiClient from '../client'

export interface KnowledgeBase {
  id: string
  name: string
  description: string
  show_in_lab: boolean
  ai_searchable: boolean
  is_enabled: boolean
  doc_count: number
  updated_at: string | null
}

export interface KnowledgeBaseDoc {
  doc_id: string
  title: string
  category: string
  status: number
  updated_at: string | null
}

export const knowledgeBaseApi = {
  async list(): Promise<KnowledgeBase[]> {
    const { data } = await apiClient.get('/admin/knowledge-bases')
    return data || []
  },
  async create(payload: Partial<KnowledgeBase>): Promise<KnowledgeBase> {
    const { data } = await apiClient.post('/admin/knowledge-bases', payload)
    return data
  },
  async update(id: string, payload: Partial<KnowledgeBase>): Promise<KnowledgeBase> {
    const { data } = await apiClient.put(`/admin/knowledge-bases/${id}`, payload)
    return data
  },
  async remove(id: string): Promise<void> {
    await apiClient.delete(`/admin/knowledge-bases/${id}`)
  },
  async docs(id: string): Promise<KnowledgeBaseDoc[]> {
    const { data } = await apiClient.get(`/admin/knowledge-bases/${id}/docs`)
    return data || []
  },
}
