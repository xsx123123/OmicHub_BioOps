/**
 * Agent Skills（SKILL.md 标准）相关类型 —— 导入预览 / 市场 / 更新检查
 */

export interface SkillFileEntry {
  path: string
  size: number
  /** skill_md | script | reference | asset | other */
  kind: string
  content?: string | null
}

/** 五入口统一解析产出：确认后才入库 */
export interface SkillImportPreview {
  skill_id: string
  name: string
  description: string
  body: string
  frontmatter: Record<string, unknown>
  icon: string
  category: string
  version: string
  author: string
  /** market | github | zip | markdown | json */
  source_type: string
  source_ref: string
  source_commit: string
  has_scripts: boolean
  warnings: string[]
  files: SkillFileEntry[]
}

export interface SkillMarketplaceItem {
  skill_id: string
  name: string
  description: string
  icon: string
  category: string
  version: string
  author: string
  has_scripts: boolean
  installed: boolean
  /** 市场分组：builtin（平台内置）/ aliyun_official（阿里云官方） */
  source?: string
  /** 官方标识（阿里云官方源为 true） */
  official?: boolean
}

/** 阿里云官方技能源同步状态（AgentExplorer OpenAPI 或 GitHub 兼容回退） */
export interface AliyunMarketStatus {
  /** 总开关（ALIYUN_SKILLS_ENABLED）；false 时市场隐藏官方源分组 */
  enabled: boolean
  available: boolean
  count: number
  repo: string
  branch: string
  commit: string
  last_synced_at: string | null
  stale: boolean
  error: string
}

/** 技能调用记录条目（资源中心"调用记录"弹窗用） */
export interface SkillInvocationRecord {
  id: string
  skill_id: string
  skill_name: string
  skill_version: string | null
  source: string
  tool_name: string
  status: string
  duration_ms: number | null
  summary: string
  error: string
  session_id: string | null
  message_id: string | null
  user_id: string | null
  created_at: string
}

/** 技能调用聚合统计（技能卡片"最近调用 · 累计 N 次"用） */
export interface SkillInvocationStat {
  skill_id: string
  total: number
  last_invoked_at: string | null
  last_status: string
}

/** 版本快照详情（含正文，diff 查看用） */
export interface SkillVersionDetail {
  revision: number
  version: string | null
  name: string
  source: string
  changelog: string
  created_by: string | null
  created_at: string
  description: string
  prompt: string
  icon: string
  category: string
  frontmatter: Record<string, unknown> | null
}

/** 引用某技能的助手（删除保护二次确认用） */
export interface SkillReference {
  agent_id: string
  name: string
}

export interface SkillUpdateCheck {
  has_update: boolean
  current_version: string
  current_commit: string
  latest_commit: string
  source_ref: string
  message: string
}
