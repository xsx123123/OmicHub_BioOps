import apiClient from '@/api/client'
import type {
  MonitorTemplate,
  MonitorTemplateListItem,
  WorkflowEvent,
  WorkflowOverviewResponse,
  WorkflowTaskSnapshot,
} from '@/types/workflowMonitor'

export const workflowMonitorApi = {
  listTemplates: () =>
    apiClient
      .get<{ items: MonitorTemplateListItem[]; total: number }>('/workflow-monitor/templates')
      .then((res) => res.data),

  getTemplate: (templateId = 'default') =>
    apiClient.get<MonitorTemplate>(`/workflow-monitor/templates/${templateId}`).then((res) => res.data),

  getOverview: (params: Record<string, unknown>) =>
    apiClient.get<WorkflowOverviewResponse>('/workflow-monitor/overview', { params }).then((res) => res.data),

  getTaskSummary: (taskId: string) =>
    apiClient
      .get<WorkflowTaskSnapshot>(`/workflow-monitor/tasks/${taskId}/summary`)
      .then((res) => res.data),

  getTaskEvents: (taskId: string, params: Record<string, unknown> = {}) =>
    apiClient
      .get<{ items: WorkflowEvent[]; total: number }>(`/workflow-monitor/tasks/${taskId}/events`, { params })
      .then((res) => res.data),
}
