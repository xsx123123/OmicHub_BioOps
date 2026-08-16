/**
 * 任务列表导出为 Excel（.xlsx）。
 *
 * 任务中心头部「导出 Excel」按钮的底层实现：把当前视图（已应用搜索 / 状态筛选）
 * 的任务行转成工作表并触发浏览器下载。列与表格展示对齐，并额外带上错误信息，
 * 便于线下排查失败任务。状态 / 流程标签与 TaskTable 保持一致，避免出现「表里
 * 显示已完成、导出却写成 success」的割裂。
 */
import * as XLSX from 'xlsx'
import type { Task } from '@/types'
import { displayName } from '@/utils/displayName'

/** 状态枚举 → 中文标签（与 TaskTable.statusMap 对齐）。 */
const STATUS_LABEL: Record<string, string> = {
  pending: '待审核',
  queued: '排队中',
  running: '运行中',
  success: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

/** 流程 id → 可读名称（与 TaskTable.flowLabel 对齐，未命中则原样回退）。 */
const FLOW_LABEL: Record<string, string> = {
  'rna-seq': 'RNA-seq',
  'atac-seq': 'ATAC-seq',
  rna_seq: 'RNA-seq',
  atac_seq: 'ATAC-seq',
  ebi_download: 'Data Download',
  variant_calling: 'Variant Calling',
  'spatial-transcriptomics': 'Spatial TX',
  'scrna-seq': 'scRNA-seq',
  studio_sandbox: 'AI 工作台',
  mas: 'MAS 多智能体',
}

function statusLabel(status: string): string {
  return STATUS_LABEL[status] || status
}

function flowLabel(flowId: string): string {
  return FLOW_LABEL[flowId] || flowId
}

/** 进度归一化：后端 0-100 与 0-1 混用，统一压成整数百分比（与 TaskTable.pct 同口径）。 */
function pct(progress: number): number {
  const value = Number(progress)
  if (!Number.isFinite(value)) return 0
  const percentage = value > 1 ? value : value * 100
  return Math.round(Math.min(100, Math.max(0, percentage)))
}

/** 提交时间格式化为「M月D日 HH:mm」，与表格列展示一致；缺失记为「-」。 */
function formatTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '-'
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${d.getMonth() + 1}月${d.getDate()}日 ${hh}:${mm}`
}

/** 用户展示名：优先昵称，缺失回退用户名、用户 ID，再无则「-」。 */
function ownerOf(task: Task): string {
  return displayName(task) || task.user_id || '-'
}

/** 单行任务 → 导出行（数组顺序即列顺序，需与 HEADERS 对齐）。 */
function toRow(task: Task): (string | number)[] {
  return [
    ownerOf(task),
    task.name ?? '',
    flowLabel(task.flow_id),
    statusLabel(task.status),
    pct(task.progress),
    formatTime(task.created_at),
    task.error_message ?? '',
  ]
}

const HEADERS = ['用户', '任务名称', '流程', '状态', '进度(%)', '提交时间', '错误信息']

/**
 * 把任务列表导出为 .xlsx 并触发下载。
 *
 * @param tasks   要导出的任务（通常传当前筛选后的视图）
 * @param options.fileName  不含扩展名的文件名，默认按当天日期生成
 */
export function exportTasksToExcel(
  tasks: Task[],
  options: { fileName?: string } = {},
): void {
  const rows = tasks.map(toRow)
  // 表头作为第一行，xlsx 的 aoa_to_sheet 按二维数组直接成表。
  const aoa: (string | number)[][] = [HEADERS, ...rows]
  const sheet = XLSX.utils.aoa_to_sheet(aoa)

  // 列宽：按表头 / 内容给个克制的初始宽度，避免「错误信息」把整表撑得不可读。
  sheet['!cols'] = [
    { wch: 14 }, // 用户
    { wch: 28 }, // 任务名称
    { wch: 16 }, // 流程
    { wch: 10 }, // 状态
    { wch: 9 },  // 进度
    { wch: 16 }, // 提交时间
    { wch: 40 }, // 错误信息
  ]

  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, sheet, '任务列表')

  const stamp = new Date()
  const datePart = `${stamp.getFullYear()}${String(stamp.getMonth() + 1).padStart(2, '0')}${String(stamp.getDate()).padStart(2, '0')}`
  const fileName = options.fileName || `omichub-tasks-${datePart}`

  XLSX.writeFile(workbook, `${fileName}.xlsx`)
}
