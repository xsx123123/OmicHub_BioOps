import apiClient from '../client'

export interface DiscoveredModel {
  id: string
  name: string
  owned_by: string
}

export interface DiscoverModelsResponse {
  provider_id: string
  provider_name: string
  models: DiscoveredModel[]
}

export interface ProviderTemplate {
  name: string
  provider_type: string
  base_url: string
  default_models: string[]
  env_key: string
  exists: boolean
}

export const adminProviderApi = {
  /** 列出所有 AI Provider 配置（/admin/ai-providers） */
  async list(): Promise<Array<{
    id: string
    name: string
    model: string
    provider_type: string
    is_active: boolean
    is_default: boolean
  }>> {
    const res = await apiClient.get('/admin/ai-providers')
    return res.data || []
  },

  /** 自动发现某个 Provider 下的可用模型 */
  async discoverModels(providerId: string): Promise<DiscoverModelsResponse> {
    const res = await apiClient.post(`/admin/ai-providers/${providerId}/discover-models`)
    return res.data
  },

  /** 内置 Provider 模板列表 */
  async listTemplates(): Promise<ProviderTemplate[]> {
    const res = await apiClient.get('/admin/ai-providers/templates')
    return res.data || []
  },
}
