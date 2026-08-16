<script setup lang="ts">
/**
 * McpToolCallCard — 可折叠 MCP 工具调用卡片
 *
 * 从 KimiMessageItem.vue 的 .tool-card 逻辑抽离，默认折叠。
 * 折叠态：工具图标 + 工具名 + 状态标签 + 旋转箭头，单行展示。
 * 展开态：完整参数 JSON + 执行结果 + 内嵌操作区（确认/跳转/任务进度）。
 */
import { ref, computed } from 'vue'
import { NButton, NIcon, NTag } from 'naive-ui'
import { BuildOutline, ChevronForwardOutline } from '@vicons/ionicons5'
import TaskProgressCard from './TaskProgressCard.vue'
import PipelineTaskCard from './PipelineTaskCard.vue'
import type { ToolCall } from './types'
import type { PipelineType } from '@/types/pipeline'

interface Props {
  tool: ToolCall
}

const props = defineProps<Props>()

const emit = defineEmits<{
  confirmTool: [toolName: string, args: Record<string, unknown>]
  openToolPage: [route: string, args: Record<string, unknown>]
  generateVisualization: [taskId: string, type: PipelineType]
  adjustParameters: [type: PipelineType]
}>()

const collapsed = ref(true)

function toggle() {
  collapsed.value = !collapsed.value
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    toggle()
  }
}

const statusType = computed(() => {
  switch (props.tool.status) {
    case 'success': return 'success' as const
    case 'error': return 'error' as const
    case 'timed_out': return 'warning' as const
    case 'awaiting_approval': return 'warning' as const
    case 'running': return 'info' as const
    default: return 'default' as const
  }
})

const statusLabel = computed(() => {
  switch (props.tool.status) {
    case 'success': return '成功'
    case 'error': return '失败'
    case 'timed_out': return '超时·已降级'
    case 'awaiting_approval': return '等待批准'
    case 'running': return '执行中'
    case 'pending': return '等待中'
    default: return props.tool.status
  }
})

const hasArgs = computed(() =>
  props.tool.arguments && Object.keys(props.tool.arguments).length > 0,
)

const workspaceSummary = computed(() => {
  if (!['list_workspace_files', 'search_workspace_files', 'workspace_list_files'].includes(props.tool.name)) {
    return ''
  }
  if (!props.tool.result || typeof props.tool.result !== 'object') return ''

  const summary = (props.tool.result as Record<string, unknown>).summary
  return typeof summary === 'string' ? summary : ''
})

const workspaceSummaryPreview = computed(() => {
  if (!workspaceSummary.value) return ''
  // 展开态显示完整摘要；折叠态只保留首行结论（如"工作区根目录 下共 66 项"），
  // 避免文件清单类长摘要在未展开时刷屏（完整内容仍在展开后的结果区可查）。
  if (!collapsed.value) return workspaceSummary.value
  const lines = workspaceSummary.value.split('\n').filter((line) => line.trim())
  const firstLine = lines[0]?.trim() || ''
  return lines.length > 1 ? `${firstLine} …（展开查看完整结果）` : firstLine
})

function isPipelineTask(tool: ToolCall): boolean {
  return ['rna_seq', 'atac_seq'].includes(String(tool.uiPayload?.pipeline_type || ''))
}

function pipelineType(tool: ToolCall): PipelineType {
  return String(tool.uiPayload?.pipeline_type) as PipelineType
}

function handleConfirmTool() {
  emit('confirmTool', props.tool.name, { ...props.tool.arguments, _confirmed: true })
}

function handleOpenToolPage() {
  const route = String(props.tool.uiPayload?.route || '')
  emit('openToolPage', route, props.tool.arguments)
}
</script>

<template>
  <div class="mcp-tool-card" :class="{ collapsed }">
    <!-- 折叠态标题行（可点击展开/收起） -->
    <div
      class="tool-card-header"
      role="button"
      :aria-expanded="!collapsed"
      tabindex="0"
      @click="toggle"
      @keydown="handleKeydown"
    >
      <n-icon size="15" class="tool-icon"><BuildOutline /></n-icon>
      <span class="tool-name">{{ tool.name }}</span>
      <span v-if="tool.purpose" class="tool-purpose">{{ tool.purpose }}</span>
      <n-tag v-if="tool.mcpServer" size="tiny" type="info" class="server-tag">
        MCP: {{ tool.mcpServer }}
      </n-tag>
      <n-tag
        size="tiny"
        :type="statusType"
        class="status-tag"
      >
        {{ statusLabel }}
      </n-tag>
      <n-icon
        size="14"
        class="expand-arrow"
        :class="{ rotated: !collapsed }"
      >
        <ChevronForwardOutline />
      </n-icon>
    </div>

    <p v-if="workspaceSummaryPreview" class="workspace-summary" :class="{ 'is-collapsed': collapsed }">
      {{ workspaceSummaryPreview }}
    </p>

    <!-- 展开态内容 -->
    <transition name="tool-expand">
      <div v-show="!collapsed" class="tool-card-body">
        <div v-if="tool.purpose" class="tool-section">
          <div class="tool-section-title">调用理由</div>
          <p class="tool-purpose-detail">{{ tool.purpose }}</p>
        </div>
        <div v-if="hasArgs" class="tool-section">
          <div class="tool-section-title">参数</div>
          <pre class="tool-pre">{{ JSON.stringify(tool.arguments, null, 2) }}</pre>
        </div>
        <div class="tool-section">
          <div class="tool-section-title">结果</div>
          <pre class="tool-pre">{{ JSON.stringify(tool.result, null, 2) }}</pre>
        </div>

        <!-- 二次确认卡 -->
        <div v-if="tool.uiPayload?.confirm_card" class="confirm-card">
          <div class="confirm-title">⚠️ 需要确认</div>
          <div class="confirm-desc">
            该操作将执行 {{ tool.name }}，确认后继续？
          </div>
          <div v-if="tool.uiPayload?.args" class="confirm-preview">
            <pre>{{ JSON.stringify(tool.uiPayload.args, null, 2) }}</pre>
          </div>
          <div class="confirm-actions">
            <n-button size="small" type="primary" @click="handleConfirmTool">
              确认执行
            </n-button>
          </div>
        </div>

        <!-- open_page 引导卡 -->
        <div v-if="tool.uiPayload?.route" class="open-page-card">
          <div class="open-page-title">🔗 前往工具页</div>
          <div class="open-page-desc">
            {{ tool.uiPayload.message || `${tool.name} 需要在专用工具页完成` }}
          </div>
          <div class="open-page-actions">
            <n-button size="small" type="info" @click="handleOpenToolPage">
              打开 {{ tool.uiPayload.route }}
            </n-button>
          </div>
        </div>

        <!-- 异步任务进度卡 -->
        <PipelineTaskCard
          v-if="tool.uiPayload?.task_id && isPipelineTask(tool)"
          :task-id="String(tool.uiPayload.task_id)"
          :pipeline-type="pipelineType(tool)"
          :initial-status="tool.uiPayload.status ? String(tool.uiPayload.status) : undefined"
          :initial-progress="tool.uiPayload.progress ? Number(tool.uiPayload.progress) : 0"
          :prepared-params="tool.arguments?.prepared_params as Record<string, unknown> | undefined"
          @generate-visualization="(taskId, type) => emit('generateVisualization', taskId, type)"
          @adjust-parameters="(type) => emit('adjustParameters', type)"
        />
        <TaskProgressCard
          v-else-if="tool.uiPayload?.task_id"
          :task-id="String(tool.uiPayload.task_id)"
          :progress-url="tool.uiPayload.progress_url ? String(tool.uiPayload.progress_url) : undefined"
          :result-url="tool.uiPayload.result_url ? String(tool.uiPayload.result_url) : undefined"
          :task-url="tool.uiPayload.task_url ? String(tool.uiPayload.task_url) : undefined"
        />
      </div>
    </transition>
  </div>
</template>

<style scoped lang="scss">
.mcp-tool-card {
  border: 1px solid var(--chat-border, #e8e8e8);
  border-radius: 8px;
  background: var(--chat-surface, #f8f9fa);
  overflow: hidden;
  transition: border-color var(--motion-quick, 140ms) ease-out;
}
.mcp-tool-card:hover {
  border-color: var(--chat-accent, #4f8ef7);
}

.tool-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--chat-text-primary, #1a1a1a);
  user-select: none;
  transition: background var(--motion-quick, 140ms) ease-out;
}
.tool-card-header:hover {
  background: var(--chat-surface-hover, rgba(0, 0, 0, 0.03));
}
.tool-card-header:focus-visible {
  outline: 2px solid var(--arco-primary, #4C6FFF);
  outline-offset: -2px;
  border-radius: 8px;
}

.tool-icon {
  flex-shrink: 0;
  color: var(--chat-text-secondary, #666);
}
.tool-name {
  flex-shrink: 0;
}
.tool-purpose {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--chat-text-muted, #999);
  font-size: 11px;
  font-weight: 400;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-purpose-detail {
  margin: 0;
  color: var(--chat-text-secondary, #666);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-line;
  word-break: break-word;
}
.server-tag {
  flex-shrink: 0;
}
.status-tag {
  margin-left: auto;
}
.expand-arrow {
  flex-shrink: 0;
  color: var(--chat-text-muted, #999);
  transition: transform var(--motion-quick, 140ms) ease-out;
}

.workspace-summary {
  margin: 0;
  padding: 0 12px 10px 35px;
  color: var(--chat-text-secondary, #555);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-line;
  word-break: break-word;
  /* 展开态：list_workspace_files 等工具可能返回几十上百行文件清单，
     限制高度并内部滚动，避免整条结果刷屏；折叠态由 is-collapsed 截断为单行 */
  max-height: 220px;
  overflow-y: auto;
}
.workspace-summary.is-collapsed {
  max-height: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.expand-arrow.rotated {
  transform: rotate(90deg);
}

.tool-card-body {
  padding: 0 12px 12px;
  border-top: 1px solid var(--chat-border, #e8e8e8);
}

.tool-section {
  margin-top: 10px;
}
.tool-section-title {
  font-size: 12px;
  color: var(--chat-text-muted, #999);
  margin-bottom: 6px;
}
.tool-pre {
  margin: 0;
  padding: 8px;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 4px;
  font-size: 12px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 展开/折叠过渡 */
.tool-expand-enter-active {
  transition: opacity var(--motion-standard, 220ms) var(--motion-spring, ease-out),
              max-height var(--motion-standard, 220ms) var(--motion-spring, ease-out);
}
.tool-expand-leave-active {
  transition: opacity var(--motion-quick, 140ms) ease-in,
              max-height var(--motion-quick, 140ms) ease-in;
}
.tool-expand-enter-from,
.tool-expand-leave-to {
  opacity: 0;
}

/* 二次确认卡 */
.confirm-card {
  margin-top: 12px;
  padding: 14px;
  background: var(--chat-surface, #fffbe6);
  border: 1px solid #ffe58f;
  border-radius: 8px;
}
.confirm-title {
  font-weight: 600;
  color: #d48806;
  margin-bottom: 6px;
}
.confirm-desc {
  font-size: 13px;
  color: var(--chat-text-secondary, #666);
  margin-bottom: 10px;
}
.confirm-preview {
  margin-bottom: 10px;
  max-height: 160px;
  overflow-y: auto;
}
.confirm-preview pre {
  margin: 0;
  font-size: 12px;
  background: rgba(0, 0, 0, 0.03);
  padding: 8px;
  border-radius: 4px;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
}

/* open_page 引导卡 */
.open-page-card {
  margin-top: 12px;
  padding: 14px;
  background: var(--chat-surface, #e6f7ff);
  border: 1px solid #91d5ff;
  border-radius: 8px;
}
.open-page-title {
  font-weight: 600;
  color: #096dd9;
  margin-bottom: 6px;
}
.open-page-desc {
  font-size: 13px;
  color: var(--chat-text-secondary, #666);
  margin-bottom: 10px;
}
.open-page-actions {
  display: flex;
  justify-content: flex-end;
}

@media (prefers-reduced-motion: reduce) {
  .expand-arrow,
  .tool-expand-enter-active,
  .tool-expand-leave-active {
    transition: none;
  }
}
</style>
