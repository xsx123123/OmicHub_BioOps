export type StarAgentMode = 'chat' | 'plan' | 'run' | 'research'
export type StarPermission = 'safe' | 'read' | 'analysis' | 'full'

export interface StarCommandContext {
  mode: StarAgentMode
  permission: StarPermission
  goal?: string
}

export type GoalRuntimeCommand =
  | { action: 'start'; objective: string }
  | { action: 'status' | 'pause' | 'resume' | 'cancel' }

export const STAR_MODE_COMMANDS: Record<string, StarAgentMode> = {
  '/chat': 'chat',
  '/plan': 'plan',
  '/run': 'run',
  '/research': 'research',
}

export const STAR_PERMISSION_COMMANDS: Record<string, StarPermission> = {
  '/safe': 'safe',
  '/read': 'read',
  '/analysis': 'analysis',
  '/full': 'full',
}

export const STAR_MODE_LABELS: Record<StarAgentMode, string> = {
  chat: 'Chat',
  plan: 'Plan',
  run: 'Execute',
  research: 'Research',
}

export const STAR_PERMISSION_LABELS: Record<StarPermission, string> = {
  safe: 'Safe',
  read: 'Read',
  analysis: 'Analysis',
  full: 'Full',
}

export const STAR_MODE_ICONS: Record<StarAgentMode, string> = {
  chat: '💬',
  plan: '🧭',
  run: '⚡',
  research: '🔍',
}

export const STAR_PERMISSION_ICONS: Record<StarPermission, string> = {
  safe: '🟢',
  read: '🔵',
  analysis: '🟣',
  full: '🔴',
}

function containsCommand(content: string, command: string): boolean {
  return new RegExp(`(^|\\s)${command.replace('/', '\\/')}(?=\\s|$)`, 'i').test(content)
}

export function hasStarModeCommand(content: string): boolean {
  return Object.keys(STAR_MODE_COMMANDS).some((command) => containsCommand(content, command))
}

export function hasStarPermissionCommand(content: string): boolean {
  return Object.keys(STAR_PERMISSION_COMMANDS).some((command) => containsCommand(content, command))
}

export function extractGoal(content: string): string | undefined {
  const match = content.match(/(?:^|\s)\/goal(?:\s+)([^\n]*)/i)
  const goal = match?.[1]?.trim()
  return goal || undefined
}

/**
 * Parse persistent Goal Runtime controls without changing the legacy
 * `/goal <objective>` chat hint behavior.
 */
export function parseGoalRuntimeCommand(content: string): GoalRuntimeCommand | null {
  const match = content.trim().match(/^\/goal(?:\s+([a-z]+))?(?:\s+([\s\S]*))?$/i)
  if (!match) return null

  const command = match[1]?.toLowerCase()
  const remainder = match[2]?.trim() || ''
  if (command === 'start') return { action: 'start', objective: remainder }
  if (command === 'status' || command === 'pause' || command === 'resume' || command === 'cancel') {
    return { action: command }
  }
  return null
}

export function resolveStarCommandContext(
  content: string,
  fallback: Pick<StarCommandContext, 'mode' | 'permission'>,
): StarCommandContext {
  const mode = Object.entries(STAR_MODE_COMMANDS).find(([command]) => containsCommand(content, command))?.[1] || fallback.mode
  const permission = Object.entries(STAR_PERMISSION_COMMANDS).find(([command]) => containsCommand(content, command))?.[1] || fallback.permission
  return { mode, permission, goal: extractGoal(content) }
}
