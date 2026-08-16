/** 知识库相关类型 */

/** 文档状态 */
export type KnowledgeDocStatus = 'published' | 'pending' | 'rejected'

/** 导航列表项（来自 /docs/knowledge） */
export interface KnowledgeItem {
  id: string
  title: string
  /** 可选分类，前端按它聚合成树 */
  category?: string | null
  /** 文档状态 */
  status?: KnowledgeDocStatus
}

/** 版本信息 */
export interface DocRevisionInfo {
  id: string
  editedBy: string
  editSummary?: string | null
  status: number
  createdAt: string
}

/** 编辑者信息 */
export interface DocEditorInfo {
  userName: string
  editCount: number
  lastEdit: string
}

/** Issue 回复 */
export interface IssueReply {
  id: string
  userName: string
  content: string
  status: number
  createdAt: string
}

/** Issue 留言 */
export interface IssueItem {
  id: string
  userName: string
  content: string
  status: number
  createdAt: string
  replies: IssueReply[]
}

/** 文档内容（来自 /docs/knowledge/:docId） */
export interface KnowledgeDoc {
  id: string
  title: string
  category: string
  status: KnowledgeDocStatus
  content: string
  currentRevision?: DocRevisionInfo | null
  pendingRevision?: DocRevisionInfo | null
  editors: DocEditorInfo[]
  issues: IssueItem[]
}

/** 树形目录节点（前端由 KnowledgeItem 按 category 聚合而成） */
export interface DocTreeNode {
  /** 叶子节点用文档 id；分类节点用 category 名 */
  key: string
  label: string
  /** 仅叶子节点有：对应文档 id */
  docId?: string
  /** 分类节点 */
  isCategory?: boolean
  /** 文档状态（仅叶子节点） */
  status?: KnowledgeDocStatus
  children?: DocTreeNode[]
}

/** 新建文档请求 */
export interface DocCreateRequest {
  docId: string
  title: string
  category: string
  content: string
  editSummary?: string
}

/** 提交编辑请求 */
export interface DocUpdateRequest {
  content: string
  editSummary?: string
}

/** 审核请求 */
export interface DocAuditRequest {
  action: 'approve' | 'reject'
  reason?: string
}

/** 待审核文档 */
export interface PendingDoc {
  id: string
  title: string
  category: string
  submitter: string | null
  editSummary: string | null
  createdAt: string | null
}

/** 创建 Issue 请求 */
export interface IssueCreateRequest {
  content: string
  replyTo?: string | null
}
