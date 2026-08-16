<script setup lang="ts">
/**
 * PendingApprovalBar — Studio HITL 待办浮动条
 *
 * 吸附在聊天输入框上方，集中呈现当前会话的待处理事项：
 *  - 待审批工具调用（approval_request，supervised 模式）：工具名 + 参数摘要，
 *    【批准运行】直接批准，【编辑/查看】定位到消息流中的内联 ApprovalCard 做编辑后运行，
 *    【退回】让 AI 修改（可选填理由）。
 *  - 待回答的 ask_user 澄清：问题摘要 + 选项快捷回答。
 *
 * 数据源完全复用 agentHub store 中消息的 tool.approval / askRequest（由 StudioView
 * 派生后传入），审批/回答动作直接调用 store 现有 API，不新造状态源。
 */
import { ref, computed } from 'vue'
import { NButton, NIcon, NInput, NTag, useMessage } from 'naive-ui'
import {
  ShieldCheckmarkOutline, CheckmarkOutline, ReturnUpBackOutline,
  LocateOutline, ChatboxEllipsesOutline,
} from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'
import type { ToolCall } from '@/components/ai-chat/types'

export interface PendingApprovalItem {
  approvalId: string
  messageId: string
  tool: ToolCall
}

export interface PendingAskItem {
  messageId: string
  question: string
  options?: string[]
}

const props = defineProps<{
  approvals: PendingApprovalItem[]
  ask: PendingAskItem | null
}>()

const emit = defineEmits<{
  locate: [messageId: string]
}>()

const store = useAgentHubStore()
const message = useMessage()

const TOOL_LABELS: Record<string, string> = {
  sandbox_execute: '沙盒执行',
  workspace_write: '写入文件',
  workspace_edit: '修改文件',
  artifact_register: '登记产物',
}

function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name
}

/** 参数摘要：文件类工具取路径，执行类取首行命令/代码预览 */
function summarize(tool: ToolCall): string {
  const args = tool.arguments || {}
  const path = String(args.path || '')
  if (path) return path
  const code = String(args.code ?? args.content ?? args.new_string ?? '')
  const firstLine = code.split('\n').find((l) => l.trim()) || ''
  if (firstLine) return firstLine.length > 80 ? `${firstLine.slice(0, 80)}…` : firstLine
  const title = String(args.title || '')
  return title || tool.name
}

const total = computed(() => props.approvals.length + (props.ask ? 1 : 0))

// ---------- 审批动作 ----------
const submittingId = ref('')
const rejectingId = ref('')
const rejectReason = ref('')

async function handleApprove(item: PendingApprovalItem) {
  if (submittingId.value) return
  submittingId.value = item.approvalId
  try {
    await store.approveToolCall(item.approvalId)
    message.success('已批准，开始执行')
  } catch (error) {
    message.error(
      error instanceof Error && error.message === 'APPROVAL_STREAM_INACTIVE'
        ? '该审批所属执行流已结束，请重新发送任务后再操作'
        : '批准失败，审批可能已超时，请重试',
    )
  } finally {
    submittingId.value = ''
  }
}

async function handleReject(item: PendingApprovalItem) {
  if (submittingId.value) return
  submittingId.value = item.approvalId
  try {
    await store.rejectToolCall(item.approvalId, rejectReason.value.trim() || undefined)
    message.success('已退回，等待 AI 修改')
    rejectingId.value = ''
    rejectReason.value = ''
  } catch (error) {
    message.error(
      error instanceof Error && error.message === 'APPROVAL_STREAM_INACTIVE'
        ? '该审批所属执行流已结束，请重新发送任务后再操作'
        : '退回失败，审批可能已超时，请重试',
    )
  } finally {
    submittingId.value = ''
  }
}

function toggleReject(item: PendingApprovalItem) {
  if (rejectingId.value === item.approvalId) {
    rejectingId.value = ''
  } else {
    rejectingId.value = item.approvalId
    rejectReason.value = ''
  }
}

// ---------- 澄清动作 ----------
const answering = ref(false)

async function handleAnswer(text: string) {
  if (answering.value) return
  answering.value = true
  try {
    await store.answerAskRequest([text])
  } finally {
    answering.value = false
  }
}
</script>

<template>
  <div v-if="total" class="pending-bar" role="alert">
    <div class="pending-bar-header">
      <n-icon size="14" class="pending-icon"><ShieldCheckmarkOutline /></n-icon>
      <span class="pending-title">待你处理</span>
      <n-tag size="tiny" round :bordered="false" type="warning">{{ total }}</n-tag>
    </div>

    <div class="pending-list">
      <!-- 待审批工具调用（排队展示） -->
      <div v-for="item in approvals" :key="item.approvalId" class="pending-item">
        <div class="pending-row">
          <span class="item-label">{{ toolLabel(item.tool.name) }}</span>
          <span class="item-summary" :title="summarize(item.tool)" @click="emit('locate', item.messageId)">
            {{ summarize(item.tool) }}
          </span>
          <div class="item-actions">
            <n-button
              size="tiny"
              type="success"
              :loading="submittingId === item.approvalId"
              @click="handleApprove(item)"
            >
              <template #icon><n-icon><CheckmarkOutline /></n-icon></template>
              批准运行
            </n-button>
            <n-button size="tiny" quaternary @click="emit('locate', item.messageId)">
              <template #icon><n-icon><LocateOutline /></n-icon></template>
              编辑/查看
            </n-button>
            <n-button size="tiny" type="warning" secondary @click="toggleReject(item)">
              <template #icon><n-icon><ReturnUpBackOutline /></n-icon></template>
              让 AI 修改
            </n-button>
          </div>
        </div>
        <div v-if="rejectingId === item.approvalId" class="reject-row">
          <n-input
            v-model:value="rejectReason"
            size="small"
            placeholder="告诉 AI 需要怎么改（可选，留空则仅退回）"
            @keyup.enter="handleReject(item)"
          />
          <n-button size="tiny" type="warning" :loading="submittingId === item.approvalId" @click="handleReject(item)">
            确认退回
          </n-button>
        </div>
      </div>

      <!-- 待回答 ask_user 澄清 -->
      <div v-if="ask" class="pending-item ask-item">
        <div class="pending-row">
          <n-icon size="14" class="ask-icon"><ChatboxEllipsesOutline /></n-icon>
          <span class="item-summary ask-question" :title="ask.question" @click="emit('locate', ask.messageId)">
            {{ ask.question }}
          </span>
          <div class="item-actions">
            <n-button size="tiny" quaternary @click="emit('locate', ask.messageId)">
              <template #icon><n-icon><LocateOutline /></n-icon></template>
              查看
            </n-button>
          </div>
        </div>
        <div v-if="ask.options?.length" class="ask-options">
          <n-button
            v-for="opt in ask.options"
            :key="opt"
            size="tiny"
            secondary
            type="primary"
            :loading="answering"
            @click="handleAnswer(opt)"
          >
            {{ opt }}
          </n-button>
        </div>
        <div v-else class="ask-hint">请在下方输入框回答</div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.pending-bar {
  flex-shrink: 0;
  margin: 0 16px;
  border: 1px solid rgba(240, 160, 32, 0.55);
  border-radius: 12px;
  background: var(--chat-surface, var(--bg-card, #fff));
  box-shadow: 0 6px 24px rgba(240, 160, 32, 0.14), 0 2px 8px rgba(30, 50, 100, 0.10);
  overflow: hidden;
}

.pending-bar-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(240, 160, 32, 0.08);
  border-bottom: 1px solid var(--chat-border, #e5e7eb);
}
.pending-icon { color: #f0a020; flex-shrink: 0; }
.pending-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--chat-text-primary, #333);
}

.pending-list {
  max-height: 220px;
  overflow-y: auto;
}

.pending-item {
  padding: 8px 12px;
}
.pending-item + .pending-item {
  border-top: 1px dashed var(--chat-border, #e5e7eb);
}

.pending-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.item-label {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--chat-text-primary, #333);
}
.item-summary {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: var(--chat-text-muted, #888);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.item-summary:hover {
  color: var(--chat-accent, #4f8ef7);
}
.item-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.reject-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.ask-icon { color: var(--chat-accent, #4f8ef7); flex-shrink: 0; }
.ask-question {
  font-family: inherit;
  color: var(--chat-text-primary, #333);
}
.ask-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.ask-hint {
  margin-top: 4px;
  font-size: 11px;
  color: var(--chat-text-muted, #999);
}
</style>
