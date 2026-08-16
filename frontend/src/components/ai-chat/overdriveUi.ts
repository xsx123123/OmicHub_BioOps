import type { ChatMessage, OverdriveProgress } from './types'

export function conversationMessagesWithoutProgress(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((item) => !item.overdriveProgress)
}

export function activeOverdriveProgress(messages: ChatMessage[]): OverdriveProgress | null {
  const progress = [...messages].reverse().find((item) => item.overdriveProgress)?.overdriveProgress
  return progress && progress.phase !== 'completed' ? progress : null
}

/** 最近一次超频进度（含已完成）：用于协作结束后保留卡片，不让控制面板凭空消失。 */
export function latestOverdriveProgress(messages: ChatMessage[]): OverdriveProgress | null {
  return [...messages].reverse().find((item) => item.overdriveProgress)?.overdriveProgress ?? null
}
