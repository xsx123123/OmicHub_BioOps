import type { AgentTeamsEvent } from '@/api/agentTeams'

/** Merge Bridge event pages without losing history or duplicating cursor replays.
 *  对 current 与 incoming 两侧均按 event_id 去重：incoming 中重复的事件保留最后一条，
 *  已存在于 current 中的事件用 incoming 版本覆盖（支持后端补发修正）。 */
export function mergeAgentTeamsEvents(
  current: AgentTeamsEvent[],
  incoming: AgentTeamsEvent[],
): AgentTeamsEvent[] {
  // 先对 incoming 自身去重，避免后端/SSE 单次推送含重复 event_id。
  const incomingById = new Map<string, AgentTeamsEvent>()
  for (const event of incoming) {
    incomingById.set(event.event_id, event)
  }
  const dedupedIncoming = Array.from(incomingById.values())
  const merged = current.map((event) => incomingById.get(event.event_id) ?? event)
  const knownIds = new Set(current.map((event) => event.event_id))
  return [...merged, ...dedupedIncoming.filter((event) => !knownIds.has(event.event_id))]
}

/** Background polling must not refresh a hidden browser tab. */
export function shouldPollAgentTeamsCase(visibilityState: DocumentVisibilityState): boolean {
  return visibilityState === 'visible'
}

/** qc 判决 → NTag 类型；未知判决（含 inconclusive 降级行）回落 default。 */
export function qcVerdictTagType(verdict: string): 'success' | 'warning' | 'error' | 'default' {
  return (
    { pass: 'success', warn: 'warning', fail: 'error' } as Record<
      string,
      'success' | 'warning' | 'error'
    >
  )[verdict] ?? 'default'
}

const QC_VERDICT_LABELS: Record<string, string> = {
  pass: '通过',
  warn: '警告',
  fail: '失败',
  inconclusive: '存疑',
}

/** qc 判决的中文短标签；未知值原样返回，不吞掉新判决类型。 */
export function qcVerdictLabel(verdict: string): string {
  return QC_VERDICT_LABELS[verdict] ?? verdict
}

/** 产物大小的人类可读格式（与 FilesView 的 formatSize 同一口径）。 */
export function formatAgentTeamsArtifactSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)} ${units[unit]}`
}
