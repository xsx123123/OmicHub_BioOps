/**
 * 多智能体协作平台 — 资产类型定义
 *
 * 后台「AI 资源中心」与前台「AI 助手」共享的资产模型。
 * 当前由 Mock store（agentHub）承载，后续可平滑切换到真实后端 DTO。
 */

export type AgentCategory = 'general' | 'analysis' | 'code' | 'visualization'

/** MCP 服务内置工具 */
export interface McpTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

/** MCP 服务（后台可展开表格的单元） */
export interface McpService {
  id: string
  name: string
  description: string
  /** 在线状态：🟢 online / 🔴 offline */
  status: 'online' | 'offline'
  transport: 'stdio' | 'sse' | 'builtin'
  command: string
  args: string[]
  url: string
  env: Record<string, string>
  registry: string
  working_dir: string
  version: string
  /** 当前生效版本号（版本管理真实指针，展示优先于遗留 version 字段） */
  current_version?: string
  /** 所属池：production 正式 / experimental 实验（AI 生成，带 TTL）/ deprecated 废弃 */
  pool?: 'production' | 'experimental' | 'deprecated'
  review_status?: string
  expires_at?: string | null
  is_enabled: boolean
  tools: McpTool[]
  timeout: number
  auto_restart: boolean
  tool_count: number
  is_preset: boolean
}

/** MCP 服务版本历史条目（GET /mcp/servers/{id}/versions） */
export interface McpVersion {
  id: string | number
  version: string
  /** 是否主版本（列表用主色 tag 突出） */
  is_major: boolean
  /** 变更来源：register 初始注册 / preset 内置预设升级 / builder 构建发布 / admin 手工更新 / rollback 回滚 / publish 转正发布 */
  source: 'register' | 'preset' | 'builder' | 'admin' | 'rollback' | 'publish'
  changelog?: string
  created_by?: string
  created_at?: string
  /** 该版本是否有配置快照，无快照则不可回滚 */
  has_config_snapshot: boolean
}

/** MCP 日志条目 */
export interface McpLogEntry {
  timestamp: string
  level: 'info' | 'stderr' | 'error' | 'warn'
  message: string
  source: string
}

/** 技能版本历史条目（GET /admin/skills/{id}/versions，revision 倒序） */
export interface SkillVersion {
  /** 修订号（回滚 body 使用该字段） */
  revision: number
  version?: string
  name?: string
  /** 变更来源：admin 手工更新 / import 导入升级 / rollback 回滚 */
  source: 'admin' | 'import' | 'rollback'
  changelog?: string
  created_by?: string
  created_at?: string
}

/** 技能（SKILL.md 标准；支持市场 / GitHub / zip / JSON 四入口导入 + 阿里云官方源） */
export interface SkillItem {
  id: string
  name: string
  description: string
  icon: string
  category: string
  source: 'market' | 'github' | 'zip' | 'json' | 'builtin' | 'url' | 'aliyun_official'
  source_url?: string
  version?: string
  author?: string
  /** 是否包含可执行脚本（挂载选择器需带标识） */
  has_scripts?: boolean
  /** JSON 模式下原始配置文本 */
  config?: string
  is_active: boolean
}

export interface AgentFeatures {
  enable_web_search?: boolean
  enable_code_execution?: boolean
  enable_file_upload?: boolean
  enable_deep_thinking?: boolean
  studio?: {
    default_mode?: 'chat' | 'studio'
  }
  /** 智能路由：统一入口，自动识别需求并转接对应专家 */
  router?: boolean
}

/** Agent 模板 —— 后台编排、前台按需唤醒的「专家角色」 */
export interface AgentTemplate {
  id: string
  name: string
  description: string
  /** emoji 头像 */
  avatar: string
  /** 主题色（头像背景 / 卡片高亮） */
  color: string
  category: AgentCategory
  /** 大模型引擎，如 claude-3-5-sonnet / gpt-4o（展示用 label） */
  model_engine: string
  /** YAML 中写的模型名称（按 name 匹配 ai_provider_configs） */
  model_name?: string
  /** 绑定的真实模型配置 ID（ai_provider_configs.id，UUID） */
  model_id?: string
  /** 系统设定 */
  system_prompt: string
  /** 进入沙盒时自动发送的欢迎语 */
  welcome_message: string
  /** 挂载的 MCP 服务 id 列表 */
  mcp_ids: string[]
  /** 挂载的技能 id 列表 */
  skill_ids: string[]
  /** 功能开关 */
  features: AgentFeatures
  is_active: boolean
  is_builtin: boolean
  is_default: boolean
}

/** 当前用户为某个 Agent 保存的个人能力选择；不包含系统提示词。 */
export interface UserAgentCapabilities {
  agent_id: string
  model_id?: string
  mcp_ids: string[]
  skill_ids: string[]
  features: UserAgentFeatureSelection
  is_customized: boolean
}

export type UserAgentFeatureKey =
  | 'enable_web_search'
  | 'enable_file_upload'
  | 'enable_code_execution'
  | 'enable_deep_thinking'

export type UserAgentFeatureSelection = Record<UserAgentFeatureKey, boolean>

/** 普通用户能力配置页可选择的 MCP 摘要，不包含管理员连接配置。 */
export interface UserSelectableMcp {
  id: string
  name: string
  description: string
  status: 'online' | 'offline'
  tool_count: number
}

/** 大模型引擎选项（Agent 编排表单下拉用） */
export interface ModelEngineOption {
  label: string
  value: string
}
