import apiClient from '@/api/client'
import type { Report, ReportFilter, ReportListResponse, ReportStats } from '@/types/report'

export const reportApi = {
  getReports: (params: ReportFilter) =>
    apiClient.get<ReportListResponse>('/reports', { params }),

  getReportStats: () =>
    apiClient.get<ReportStats>('/reports/stats'),

  getReportDetail: (id: string) =>
    apiClient.get<Report>(`/reports/${id}`),

  previewReport: (id: string) =>
    apiClient.get<string>(`/reports/${id}/preview`),

  downloadReport: (reportId: string, fileId: string) =>
    apiClient.get<Blob>(`/reports/${reportId}/files/${fileId}/download`, {
      responseType: 'blob',
    }),

  deleteReport: (id: string) =>
    apiClient.delete(`/reports/${id}`),

  toggleStar: (id: string, isStarred: boolean) =>
    apiClient.patch<Report>(`/reports/${id}/star`, { is_starred: isStarred }),

  markAsRead: (id: string) =>
    apiClient.patch<Report>(`/reports/${id}/read`, {}),
}
