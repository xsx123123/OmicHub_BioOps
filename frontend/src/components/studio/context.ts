/**
 * Studio 工作台上下文（provide/inject）
 *
 * StudioView 提供；KimiMessageItem 注入以识别 Studio 代码卡片渲染分支，
 * StudioCodeCard 注入以获取会话 ID（重跑/下载）与刷新工作区回调。
 */
import type { InjectionKey, Ref } from 'vue'

export interface StudioContext {
  /** 当前 Studio 会话 ID */
  sessionId: Readonly<Ref<string>>
  /** 工具结果/重跑完成后刷新文件树、产物列表与沙盒状态 */
  refreshWorkspace: () => void
  /** 将工作区文件带入代码工作室；AI 写入时可标记外部变更。 */
  openFileInEditor?: (path: string, options?: { pin?: boolean; externallyChanged?: boolean }) => void
}

export const StudioContextKey: InjectionKey<StudioContext> = Symbol('studio-context')

/** Studio 内置工具名（与后端 STUDIO_TOOL_NAMES 对齐） */
export const STUDIO_CODE_TOOLS = new Set(['sandbox_execute', 'workspace_write', 'workspace_edit', 'tool_orchestrate'])

export function isStudioCodeTool(toolName: string): boolean {
  return STUDIO_CODE_TOOLS.has(toolName)
}
