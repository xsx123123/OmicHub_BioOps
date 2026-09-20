export interface RoleIdentity {
  name: string
  avatar: string
  color: string
  role: 'manager' | 'worker'
}

const FALLBACK_IDENTITIES: Record<string, RoleIdentity> = {
  'agent-general': { name: '星尘 AI', avatar: '✨', color: '#4f8ef7', role: 'manager' },
  'bioops-manager': { name: 'Manager', avatar: '🧑‍🔬', color: '#4f8ef7', role: 'manager' },
  'agent-rnaseq': { name: 'RNA-seq 分析师', avatar: '🧬', color: '#7c3aed', role: 'worker' },
  'agent-scrna': { name: '单细胞分析师', avatar: '🔬', color: '#0891b2', role: 'worker' },
  'agent-atacseq': { name: 'ATAC-seq 分析师', avatar: '🧫', color: '#0f766e', role: 'worker' },
  'agent-code': { name: '代码工程师', avatar: '⌨️', color: '#475569', role: 'worker' },
  'agent-viz': { name: '可视化设计师', avatar: '📊', color: '#c026d3', role: 'worker' },
  'agent-data': { name: '数据管理员', avatar: '🗂️', color: '#2563eb', role: 'worker' },
  'agent-qc': { name: '质量审计员', avatar: '🛡️', color: '#d97706', role: 'worker' },
  'agent-delivery': { name: '交付报告员', avatar: '📦', color: '#16a34a', role: 'worker' },
}

export function resolveRoleIdentity(
  agentId: string,
  supplied: Partial<RoleIdentity> = {},
): RoleIdentity {
  const fallback = FALLBACK_IDENTITIES[agentId] || {
    name: agentId || '协作成员',
    avatar: '💬',
    color: '#64748b',
    role: 'worker' as const,
  }
  return {
    name: supplied.name || fallback.name,
    avatar: supplied.avatar || fallback.avatar,
    color: supplied.color || fallback.color,
    role: supplied.role || fallback.role,
  }
}
