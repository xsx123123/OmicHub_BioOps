<script setup lang="ts">
/**
 * ApprovalDrawer — Studio HITL 审批底部抽屉
 *
 * 将审批操作从对话流内嵌卡片改为底部抽屉（NDrawer placement="bottom"），
 * 提供更宽敞的预览空间和更清晰的操作层级。
 *
 * 通过 v-model:show 控制可见性，遵循设计文档 §5.6 弹窗约定：
 *  - 打开时焦点落在「批准运行」按钮
 *  - 关闭后焦点返回触发消息
 *  - 异步审批期间按钮 :loading 防止重复提交
 */
import { ref, computed, watch, nextTick } from 'vue'
import { NDrawer, NDrawerContent, NButton, NIcon, NTag, useMessage } from 'naive-ui'
import { ShieldCheckmarkOutline, CheckmarkOutline, CloseOutline } from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'
import type { ToolCall } from './types'

interface Props {
  show: boolean
  tool: ToolCall | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const store = useAgentHubStore()
const message = useMessage()

const approveBtnRef = ref<HTMLElement | null>(null)
const submitting = ref(false)

const TOOL_LABELS: Record<string, string> = {
  sandbox_execute: '沙盒执行',
  workspace_write: '写入文件',
  workspace_edit: '修改文件',
  artifact_register: '登记产物',
}

const toolLabel = computed(() => {
  if (!props.tool) return ''
  return TOOL_LABELS[props.tool.name] || props.tool.name
})

const filePath = computed(() => {
  if (!props.tool) return ''
  return String(props.tool.arguments?.path || '')
})

const previewContent = computed(() => {
  if (!props.tool) return ''
  const args = props.tool.arguments
  return String(args?.code ?? args?.content ?? args?.new_string ?? '')
})

const language = computed(() => {
  if (!props.tool) return 'text'
  const l = props.tool.arguments?.language
  if (l) return String(l).toLowerCase()
  const ext = filePath.value.split('.').pop()?.toLowerCase() || ''
  if (ext === 'r') return 'r'
  if (['sh', 'bash'].includes(ext)) return 'bash'
  if (['py'].includes(ext)) return 'python'
  return 'text'
})

const approval = computed(() => props.tool?.approval)
const isPending = computed(() => approval.value?.status === 'pending')

function close() {
  emit('update:show', false)
}

async function handleApprove() {
  const id = approval.value?.approval_id
  if (!id || submitting.value) return
  submitting.value = true
  try {
    await store.approveToolCall(id)
    message.success('已批准，开始执行')
    close()
  } catch (error) {
    message.error(
      error instanceof Error && error.message === 'APPROVAL_STREAM_INACTIVE'
        ? '该审批所属执行流已结束，请重新发送任务后再操作'
        : '批准失败，审批可能已超时，请重试',
    )
  } finally {
    submitting.value = false
  }
}

async function handleReject() {
  const id = approval.value?.approval_id
  if (!id || submitting.value) return
  submitting.value = true
  try {
    await store.rejectToolCall(id)
    message.success('已拒绝')
    close()
  } catch {
    message.error('拒绝失败，审批可能已超时，请重试')
  } finally {
    submitting.value = false
  }
}

// 打开时将焦点移到批准按钮
watch(
  () => props.show,
  (visible) => {
    if (visible) {
      nextTick(() => {
        approveBtnRef.value?.focus()
      })
    }
  },
)
</script>

<template>
  <n-drawer
    :show="show"
    placement="bottom"
    :height="undefined"
    :style="{ height: '60vh' }"
    class="approval-drawer"
    :mask-closable="true"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <n-drawer-content
      :native-scrollbar="false"
      body-content-style="padding: 0; display: flex; flex-direction: column; height: 100%;"
    >
      <template #header>
        <div class="drawer-header">
          <n-icon size="18" class="shield-icon"><ShieldCheckmarkOutline /></n-icon>
          <span class="drawer-title">操作审批 · {{ toolLabel }}</span>
          <n-tag v-if="isPending" size="small" type="warning" round :bordered="false">
            等待批准
          </n-tag>
          <n-tag v-else-if="approval" size="small" :type="approval.status === 'approved' || approval.status === 'edited' ? 'success' : 'default'" round :bordered="false">
            {{ approval.status === 'approved' ? '已批准' : approval.status === 'edited' ? '已编辑后批准' : approval.status === 'rejected' ? '已退回' : approval.status === 'timeout' ? '已超时' : approval.status }}
          </n-tag>
        </div>
      </template>

      <div v-if="tool" class="drawer-body">
        <!-- 风险提示 -->
        <div v-if="approval?.risk_hint" class="risk-hint">
          ⚠️ {{ approval.risk_hint }}
        </div>

        <!-- 影响文件路径 -->
        <div v-if="filePath" class="file-path-line">
          <n-tag size="small" type="info" round :bordered="false">
            📄 {{ filePath }}
          </n-tag>
          <n-tag v-if="language !== 'text'" size="tiny" round :bordered="false">
            {{ language }}
          </n-tag>
        </div>

        <!-- 代码/内容预览 -->
        <div class="preview-section">
          <pre class="preview-code">{{ previewContent || JSON.stringify(tool.arguments, null, 2) }}</pre>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div v-if="tool && isPending" class="drawer-actions">
        <n-button
          ref="approveBtnRef"
          type="primary"
          :loading="submitting"
          @click="handleApprove"
        >
          <template #icon><n-icon><CheckmarkOutline /></n-icon></template>
          批准运行
        </n-button>
        <n-button
          secondary
          @click="close"
        >
          编辑后运行
        </n-button>
        <n-button
          quaternary
          type="error"
          :loading="submitting"
          @click="handleReject"
        >
          <template #icon><n-icon><CloseOutline /></n-icon></template>
          拒绝
        </n-button>
      </div>
      <div v-else-if="tool && !isPending" class="drawer-actions">
        <n-button @click="close">关闭</n-button>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped lang="scss">
.drawer-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.shield-icon {
  color: var(--arco-warning, #FF7D00);
  flex-shrink: 0;
}
.drawer-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--neutral-text-1, #1D2129);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.risk-hint {
  padding: 8px 12px;
  font-size: 13px;
  color: #d48806;
  background: var(--arco-warning-light, #FFF7E8);
  border-radius: 8px;
}

.file-path-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-section {
  flex: 1;
  min-height: 0;
}
.preview-code {
  margin: 0;
  padding: 12px 16px;
  max-height: 30vh;
  overflow: auto;
  background: #1e2127;
  color: #d7dae0;
  border-radius: 8px;
  font-size: 13px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.drawer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 24px;
  border-top: 1px solid var(--neutral-border, #E5E6EB);
}

/* 移动端抽屉高度 */
@media (max-width: 768px) {
  .approval-drawer {
    height: 80vh !important;
  }
}

/* 圆角顶部 */
:deep(.n-drawer) {
  border-radius: 16px 16px 0 0;
}
</style>
