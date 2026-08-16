import { defineStore } from 'pinia'
import { ref } from 'vue'
import apiClient from '@/api/client'
import type { MCPServer, MCPTool } from '@/types'

export const useMCPStore = defineStore('mcp', () => {
  const servers = ref<MCPServer[]>([])
  const toolsCache = ref<Record<string, MCPTool[]>>({})
  const loading = ref(false)

  async function fetchServers() {
    loading.value = true
    try {
      const res = await apiClient.get<MCPServer[]>('/mcp/servers')
      servers.value = res.data
    } finally {
      loading.value = false
    }
  }

  async function fetchTools(serverId: string): Promise<MCPTool[]> {
    const res = await apiClient.get<MCPTool[]>(`/mcp/servers/${serverId}/tools`)
    toolsCache.value[serverId] = res.data
    return res.data
  }

  async function invokeTool(
    serverId: string,
    toolName: string,
    args: Record<string, unknown>
  ): Promise<Record<string, unknown>> {
    const res = await apiClient.post(`/mcp/servers/${serverId}/tools/${toolName}/invoke`, {
      tool_name: toolName,
      arguments: args,
    })
    return res.data
  }

  async function createServer(data: {
    name: string
    description?: string
    transport: string
    command?: string
    url?: string
    env?: Record<string, string>
    timeout?: number
    auto_restart?: boolean
  }): Promise<MCPServer> {
    const res = await apiClient.post<MCPServer>('/mcp/servers', data)
    servers.value.push(res.data)
    return res.data
  }

  async function updateServer(
    serverId: string,
    data: Partial<{
      name: string
      description: string
      command: string
      url: string
      env: Record<string, string>
      timeout: number
      auto_restart: boolean
    }>
  ): Promise<MCPServer> {
    const res = await apiClient.put<MCPServer>(`/mcp/servers/${serverId}`, data)
    const idx = servers.value.findIndex((s) => s.id === serverId)
    if (idx >= 0) servers.value[idx] = res.data
    return res.data
  }

  async function deleteServer(serverId: string): Promise<void> {
    await apiClient.delete(`/mcp/servers/${serverId}`)
    servers.value = servers.value.filter((s) => s.id !== serverId)
  }

  async function testServer(serverId: string): Promise<{
    success: boolean
    tool_count: number
    status: string
    error?: string
  }> {
    const res = await apiClient.post(`/mcp/servers/${serverId}/test`)
    return res.data
  }

  return {
    servers,
    toolsCache,
    loading,
    fetchServers,
    fetchTools,
    invokeTool,
    createServer,
    updateServer,
    deleteServer,
    testServer,
  }
})
