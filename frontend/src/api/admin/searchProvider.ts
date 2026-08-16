import apiClient from '../client'

export interface SearchProvider {
  id: string
  name: string
  provider_type: 'api' | 'searxng' | 'scrape'
  api_key: string
  base_url: string
  is_enabled: boolean
  is_default: boolean
  params: { maxResults?: number; searchDepth?: string }
  timeout_seconds: number
  key_url: string
  is_local: boolean
}

export const searchProviderApi = {
  async list(): Promise<SearchProvider[]> {
    const { data } = await apiClient.get('/admin/search-providers')
    return data || []
  },
  async update(id: string, payload: Partial<SearchProvider>): Promise<SearchProvider> {
    const { data } = await apiClient.put(`/admin/search-providers/${id}`, payload)
    return data
  },
  async setDefault(id: string): Promise<SearchProvider> {
    const { data } = await apiClient.put(`/admin/search-providers/${id}/default`)
    return data
  },
  async test(id: string): Promise<{ success: boolean; message: string; result_count: number }> {
    const { data } = await apiClient.post(`/admin/search-providers/${id}/test`)
    return data
  },
}
