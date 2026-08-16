import apiClient from '@/api/client'
import type { ToolItem } from '@/types/tools'

/**
 * 获取工具箱工具列表（tools_setting.yaml 中 enabled=true 的工具，按 order 升序）
 */
export async function fetchTools(): Promise<ToolItem[]> {
  const { data } = await apiClient.get<{ data: ToolItem[] }>('/tools')
  return data.data
}
