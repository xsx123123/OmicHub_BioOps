import type { AgentCategory } from '@/types/agent'

/** 展示层领域映射；后端枚举保持不变。 */
export const AGENT_DOMAIN_LABELS: Record<string, string> = {
  general: '通用',
  analysis: '分析',
  code: '编程',
  visualization: '可视化',
  development: '工程',
  operations: '工程',
  exploration: '工程',
}

export function agentDomainLabel(category: AgentCategory | string): string {
  return AGENT_DOMAIN_LABELS[category] || category
}
