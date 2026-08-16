/**
 * 工具箱任务的「结果页」路由解析。
 *
 * 背景：任务中心把分析中心流程（rna_seq / atac_seq …）与工具箱工具产出的任务
 * 混在一张表里。但只有分析流程会生成「报告」（/reports?taskId=），工具箱工具
 * 不产出报告——它们的结果展示在各自的工具页内（富集气泡图 / DEG 火山图等）。
 * 因此对工具箱任务，表格里「查看报告」是误导（点进去是空报告页），应改成跳到
 * 对应工具页、并按 taskId 深链直接打开该任务的结果。
 *
 * 这里集中维护「flow_id → 工具箱结果页路由」的映射，TaskTable 据此分流跳转，
 * 各工具视图据此读取 query 深链。新增会产生任务的工具箱工具时，在此登记一处，
 * 并在对应视图里接住 `TOOLBOX_RESULT_QUERY` 这个 query 参数即可。
 */
import type { RouteLocationRaw } from 'vue-router'

/** 工具箱结果页统一用这个 query 参数携带要打开的任务 id。 */
export const TOOLBOX_RESULT_QUERY = 'taskId' as const

/**
 * flow_id → 工具箱结果页路由名。
 *
 * 仅登记「会写 TaskModel、从而出现在任务中心」的工具箱工具：
 *  - kegg-enrichment：GO / KEGG 富集分析（后端 tools/enrichments）
 *  - deg-analysis：DEG 差异表达分析（后端 tools/deg）
 * BLAST 走独立的 BlastTaskModel、不进任务中心，故不在此列。
 */
const TOOLBOX_RESULT_ROUTE: Record<string, string> = {
  'kegg-enrichment': 'tools-kegg-enrichment',
  'deg-analysis': 'tools-deg-analysis',
}

/** 该 flow_id 是否属于「结果在工具箱页内展示」的工具箱任务。 */
export function isToolboxResultFlow(flowId: string | null | undefined): boolean {
  return !!flowId && Object.prototype.hasOwnProperty.call(TOOLBOX_RESULT_ROUTE, flowId)
}

/**
 * 返回打开某工具箱任务结果页的路由对象（带 taskId 深链）；
 * 非工具箱任务返回 null，调用方据此回退到报告页 / 任务详情等默认行为。
 */
export function getToolboxResultRoute(
  flowId: string | null | undefined,
  taskId: string,
): RouteLocationRaw | null {
  if (!flowId || !taskId) return null
  const name = TOOLBOX_RESULT_ROUTE[flowId]
  if (!name) return null
  return { name, query: { [TOOLBOX_RESULT_QUERY]: taskId } }
}
