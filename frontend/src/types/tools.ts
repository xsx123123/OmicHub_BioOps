/**
 * 工具箱注册表相关类型定义
 * 与后端 schemas/tools_registry.py 对齐
 */

/** 单个工具卡片（后端 ToolItemDTO） */
export interface ToolItem {
  /** 工具唯一标识（前端路由 token） */
  key: string
  /** 卡片标题 */
  title: string
  /** 卡片描述 */
  description: string
  /** 图标字符串 key，ToolsHubView 的 ICON_MAP 映射回 @vicons/ionicons5 组件 */
  icon: string
  /** 卡片图标背景渐变（CSS linear-gradient） */
  gradient: string
  /** 点击卡片跳转的前端路由 */
  route: string
  /** 排序权重，升序 */
  order: number
  /** 工具所属分组 key */
  group: string
  /** 是否启用；接口通常已过滤禁用工具，前端保留兼容性判断 */
  enabled?: boolean
  /** 该工具功能配置目录（相对仓库根），仅展示用 */
  config_dir: string
}
