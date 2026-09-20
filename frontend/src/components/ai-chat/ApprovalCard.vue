<script setup lang="ts">
/**
 * ApprovalCard — Studio HITL 审批卡片
 *
 * supervised 模式下受控工具（sandbox_execute / workspace_write / workspace_edit /
 * artifact_register）触发 approval_request 时，工具卡片进入 awaiting_approval，
 * 由本卡片接管交互：
 *  - 参数预览：CodeMirror 只读展示（sandbox_execute=code，workspace_write=content，
 *    workspace_edit=old/new，artifact_register=path+title）
 *  - 按钮组：【批准运行】【编辑后运行】（解锁编辑后以 modified_args 批准）
 *    【本会话不再询问】（always 批准，同会话同工具后续直接放行，切换权限模式失效）
 *    【让 AI 修改】（填理由退回）
 *  - 决议后展示终态徽标：已批准 / 已编辑后批准 / 已退回 / 已超时
 *
 * 仅依赖 agentHub store 的 approveToolCall / rejectToolCall，无需 Studio 上下文，
 * 无 approval 数据时不会被渲染（KimiMessageItem 按 tool.approval 门控）。
 */
import { ref, computed } from 'vue'
import { NButton, NIcon, NInput, NTag, useMessage } from 'naive-ui'
import {
  ShieldCheckmarkOutline, CheckmarkOutline, CreateOutline, ReturnUpBackOutline,
} from '@vicons/ionicons5'
import CodeEditor from '@/components/sandbox/CodeEditor.vue'
import { useAgentHubStore } from '@/stores/agentHub'
import { approvalErrorText } from './approvalErrors'
import type { ToolCall } from '@/components/ai-chat/types'

const props = defineProps<{ tool: ToolCall }>()

const store = useAgentHubStore()
const message = useMessage()

const TOOL_LABELS: Record<string, string> = {
  sandbox_execute: '沙盒执行',
  chat_sandbox_execute: '沙盒执行',
  workspace_write: '写入文件',
  workspace_edit: '修改文件',
  artifact_register: '登记产物',
  network_request: '网络访问',
}
const toolLabel = computed(() => TOOL_LABELS[props.tool.name] || props.tool.name)
/** sandbox_execute / chat_sandbox_execute 都以 code 字段预览与编辑 */
const toolUsesCodeEditor = computed(
  () => props.tool.name === 'sandbox_execute' || props.tool.name === 'chat_sandbox_execute',
)

const approval = computed(() => props.tool.approval)
const isPending = computed(() => approval.value?.status === 'pending')
const isPlanApproval = computed(
  () => approval.value?.approval_kind === 'plan' || props.tool.name === 'update_plan',
)
const planSteps = computed(() => {
  const steps = props.tool.arguments?.steps
  return Array.isArray(steps)
    ? steps.map((step) => String((step as Record<string, unknown>)?.title || step))
    : []
})

const language = computed(() => {
  const l = props.tool.arguments?.language
  if (l) return String(l).toLowerCase()
  const ext = String(props.tool.arguments?.path || '').split('.').pop()?.toLowerCase() || ''
  if (ext === 'r') return 'r'
  if (['sh', 'bash'].includes(ext)) return 'bash'
  return 'python'
})
const LANG_BADGES: Record<string, string> = { python: 'Python', r: 'R', bash: 'Bash' }

const path = computed(() => String(props.tool.arguments?.path || ''))
const title = computed(() => String(props.tool.arguments?.title || ''))
const networkUrl = computed(() => String(props.tool.arguments?.url || ''))
const networkMethod = computed(() => String(props.tool.arguments?.method || 'GET').toUpperCase())
const networkHost = computed(() => {
  try {
    return new URL(networkUrl.value).host || '未知主机'
  } catch {
    return '未知主机'
  }
})

// ---------- 编辑态 ----------
const editing = ref(false)
const submitting = ref(false)
/** 可编辑字段：sandbox_execute→code；workspace_write→content；workspace_edit→new_string */
const editCode = ref(String(props.tool.arguments?.code ?? props.tool.arguments?.content ?? ''))
const editNewString = ref(String(props.tool.arguments?.new_string ?? ''))
const oldString = computed(() => String(props.tool.arguments?.old_string ?? ''))

const canEdit = computed(() => !['artifact_register', 'network_request'].includes(props.tool.name))

// ---------- 退回理由 ----------
const rejecting = ref(false)
const rejectReason = ref('')

/** modified_args = 原 arguments 替换编辑字段 */
function buildModifiedArgs(): Record<string, unknown> {
  const args = { ...props.tool.arguments }
  if (toolUsesCodeEditor.value) args.code = editCode.value
  else if (props.tool.name === 'workspace_write') args.content = editCode.value
  else if (props.tool.name === 'workspace_edit') args.new_string = editNewString.value
  return args
}

async function handleApprove(withEdits: boolean, always = false) {
  const id = approval.value?.approval_id
  if (!id || submitting.value) return
  submitting.value = true
  try {
    await store.approveToolCall(id, withEdits ? buildModifiedArgs() : undefined, always)
    message.success(
      always
        ? '已批准，本会话内该工具不再询问'
        : withEdits
          ? '已按修改后的参数批准，开始执行'
          : '已批准，开始执行',
    )
  } catch (error) {
    message.error(approvalErrorText(error, '批准失败，请重试'))
  } finally {
    submitting.value = false
  }
}

async function handleReject() {
  const id = approval.value?.approval_id
  if (!id || submitting.value) return
  submitting.value = true
  try {
    await store.rejectToolCall(id, rejectReason.value.trim() || undefined)
    message.success('已退回，等待 AI 修改')
  } catch (error) {
    message.error(approvalErrorText(error, '退回失败，请重试'))
  } finally {
    submitting.value = false
  }
}

const STATUS_META: Record<string, { text: string; type: 'success' | 'info' | 'warning' | 'error' }> = {
  approved: { text: '已批准', type: 'success' },
  edited: { text: '已编辑后批准', type: 'success' },
  rejected: { text: '已退回，等待 AI 修改', type: 'warning' },
  timeout: { text: '已超时', type: 'error' },
}
const statusMeta = computed(() => STATUS_META[approval.value?.status || ''] || null)
</script>

<template>
  <div class="approval-card" :class="{ pending: isPending }">
    <div class="approval-header">
      <n-icon size="15" class="shield-icon"><ShieldCheckmarkOutline /></n-icon>
      <span class="approval-title">{{ isPlanApproval ? '计划审批' : '操作审批' }} · {{ toolLabel }}</span>
      <n-tag v-if="toolUsesCodeEditor" size="tiny" round :bordered="false" type="info">
        {{ LANG_BADGES[language] || language }}
      </n-tag>
      <n-tag v-if="isPending" size="tiny" round :bordered="false" type="warning">等待批准</n-tag>
      <n-tag v-else-if="statusMeta" size="tiny" round :bordered="false" :type="statusMeta.type">
        {{ statusMeta.text }}
      </n-tag>
      <span v-if="isPending && approval?.timeout_seconds" class="timeout-hint">
        {{ Math.max(1, Math.round(approval.timeout_seconds / 60)) }} 分钟内未响应将自动退回
      </span>
    </div>

    <div v-if="approval?.risk_hint" class="risk-hint">⚠️ {{ approval.risk_hint }}</div>

    <div v-if="isPlanApproval && planSteps.length" class="plan-approval-steps">
      <div class="plan-approval-caption">批准后将按以下步骤自动执行：</div>
      <ol>
        <li v-for="(step, index) in planSteps" :key="`${index}-${step}`">{{ step }}</li>
      </ol>
    </div>

    <!-- 参数预览 -->
    <div class="approval-body">
      <template v-if="tool.name === 'sandbox_execute' || tool.name === 'chat_sandbox_execute'">
        <div class="editor-wrap" :class="{ editing }">
          <CodeEditor v-model="editCode" :readonly="!editing" />
        </div>
      </template>
      <template v-else-if="tool.name === 'workspace_write'">
        <div class="path-line" :title="path">📄 {{ path }}</div>
        <div class="editor-wrap" :class="{ editing }">
          <CodeEditor v-model="editCode" :readonly="!editing" />
        </div>
      </template>
      <template v-else-if="tool.name === 'workspace_edit'">
        <div class="path-line" :title="path">📄 {{ path }}</div>
        <div class="edit-section-title">原内容（只读）</div>
        <pre class="code-view">{{ oldString || '（空）' }}</pre>
        <div class="edit-section-title">新内容{{ editing ? '（可编辑）' : '' }}</div>
        <div class="editor-wrap" :class="{ editing }">
          <CodeEditor v-model="editNewString" :readonly="!editing" />
        </div>
      </template>
      <template v-else-if="tool.name === 'artifact_register'">
        <div class="artifact-info">
          <div class="path-line" :title="path">📦 {{ path }}</div>
          <div v-if="title" class="artifact-title">标题：{{ title }}</div>
        </div>
      </template>
      <template v-else-if="tool.name === 'network_request'">
        <div class="network-request-preview">
          <div class="path-line">🌐 {{ networkMethod }} · {{ networkHost }}</div>
          <a :href="networkUrl" target="_blank" rel="noreferrer noopener">{{ networkUrl }}</a>
          <div class="network-request-note">仅访问公开 HTTP(S)，不携带 Cookie 或 Authorization；响应大小受限。</div>
        </div>
      </template>
      <pre v-else class="code-view">{{ JSON.stringify(tool.arguments, null, 2) }}</pre>
    </div>

    <!-- 按钮组（等待批准时） -->
    <div v-if="isPending" class="approval-actions">
      <n-button
        size="small"
        type="success"
        :loading="submitting"
        @click="handleApprove(editing)"
      >
        <template #icon><n-icon><CheckmarkOutline /></n-icon></template>
        {{ editing ? '以修改后参数运行' : '批准运行' }}
      </n-button>
      <n-button
        v-if="!isPlanApproval && !editing"
        size="small"
        type="success"
        secondary
        :loading="submitting"
        title="批准后本会话内该工具的后续调用不再逐次询问（切换权限模式后失效）"
        @click="handleApprove(false, true)"
      >
        <template #icon><n-icon><CheckmarkOutline /></n-icon></template>
        本会话不再询问
      </n-button>
      <n-button
        v-if="canEdit && !editing"
        size="small"
        @click="editing = true"
      >
        <template #icon><n-icon><CreateOutline /></n-icon></template>
        编辑后运行
      </n-button>
      <n-button
        v-if="editing"
        size="small"
        @click="editing = false"
      >
        取消编辑
      </n-button>
      <n-button size="small" type="warning" secondary @click="rejecting = !rejecting">
        <template #icon><n-icon><ReturnUpBackOutline /></n-icon></template>
        让 AI 修改
      </n-button>
    </div>

    <!-- 退回理由输入 -->
    <div v-if="isPending && rejecting" class="reject-block">
      <n-input
        v-model:value="rejectReason"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 5 }"
        placeholder="告诉 AI 需要怎么改（可选，留空则仅退回）"
      />
      <div class="reject-actions">
        <n-button size="small" type="warning" :loading="submitting" @click="handleReject">
          确认退回
        </n-button>
        <n-button size="small" quaternary @click="rejecting = false">取消</n-button>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.approval-card {
  margin-top: 10px;
  border: 1px solid var(--chat-border, #e5e7eb);
  border-radius: 10px;
  overflow: hidden;
  background: var(--chat-surface, #fff);
}
.approval-card.pending {
  border-color: rgba(240, 160, 32, 0.55);
  box-shadow: 0 0 0 1px rgba(240, 160, 32, 0.12);
}

.approval-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  background: var(--chat-surface-hover, #f7f8fa);
  border-bottom: 1px solid var(--chat-border, #e5e7eb);
}
.shield-icon { color: #f0a020; flex-shrink: 0; }
.approval-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--chat-text-primary, #333);
}
.timeout-hint {
  margin-left: auto;
  font-size: 11px;
  color: var(--chat-text-muted, #999);
}

.risk-hint {
  padding: 6px 12px;
  font-size: 12px;
  color: #d48806;
  background: rgba(240, 160, 32, 0.08);
  border-bottom: 1px solid var(--chat-border, #e5e7eb);
}

.approval-body {
  padding: 8px 12px;
}
.path-line {
  font-size: 12px;
  font-weight: 600;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: var(--chat-text-primary, #333);
  margin-bottom: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.artifact-title {
  font-size: 12px;
  color: var(--chat-text-muted, #888);
}
.network-request-preview a {
  display: block;
  color: var(--chat-accent, #4f8ef7);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.network-request-note {
  margin-top: 6px;
  color: var(--chat-text-muted, #888);
  font-size: 11px;
  line-height: 1.5;
}
.edit-section-title {
  font-size: 11px;
  color: var(--chat-text-muted, #999);
  margin: 6px 0 4px;
}
.editor-wrap {
  border: 1px solid var(--chat-border, #e5e7eb);
  border-radius: 6px;
  overflow: hidden;
}
/* 只读预览：高度随内容自适应，最多约 5 行，超出在编辑器内部滚动 */
.editor-wrap:not(.editing) :deep(.cm-editor) {
  max-height: 120px;
}
.editor-wrap.editing {
  height: 200px;
  outline: 2px solid var(--chat-accent, #4f8ef7);
  outline-offset: -2px;
}
.code-view {
  margin: 0;
  padding: 8px 10px;
  max-height: 200px;
  overflow: auto;
  background: #1e2127;
  color: #d7dae0;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.approval-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--chat-border, #e5e7eb);
}

.reject-block {
  padding: 8px 12px;
  border-top: 1px solid var(--chat-border, #e5e7eb);
}
.reject-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
</style>
