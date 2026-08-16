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
