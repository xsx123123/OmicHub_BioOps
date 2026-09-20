<script setup lang="ts">
/**
 * ChatCodeCard — 聊天模式轻量级代码执行卡片
 *
 * 渲染 chat_sandbox_execute 工具调用：
 *  - 头部：语言徽章 + 执行状态
 *  - 代码区：CodeMirror 只读展示
 *  - 输出区：stdout/stderr 实时累计
 *  - 支持 images / echarts 渲染（standalone sandbox 特有）
 *
 * 与 StudioCodeCard 的区别：
 *  - 无工作区耦合（无 workspace_write/edit）
 *  - 无重跑/编辑功能（聊天模式一次性执行）
 *  - 无产物下载（standalone sandbox 无持久化工作区）
 */
import { computed, ref } from 'vue'
import { NTag } from 'naive-ui'
import CodeEditor from '@/components/sandbox/CodeEditor.vue'
import type { ToolCall } from './types'

const props = defineProps<{ tool: ToolCall }>()

const language = computed(() => {
  const l = (props.tool.arguments?.language ?? props.tool.uiPayload?.language) as string | undefined
  if (l) return String(l).toLowerCase()
  return 'python'
})

const LANG_BADGES: Record<string, string> = { python: 'Python', r: 'R', bash: 'Bash' }
const languageBadge = computed(() => LANG_BADGES[language.value] || language.value)

const code = computed(() => String(props.tool.arguments?.code ?? ''))

/** ui_payload/result 被 200KB 落库护栏截断：优先读信封层级标记，兼容载荷本身即截断标记的旧数据 */
const payloadTruncated = computed(() => {
  if (props.tool.uiPayloadTruncation?.payload_truncated || props.tool.resultTruncation?.payload_truncated) {
    return true
  }
  return props.tool.uiPayload?._cygnusx_payload_truncated === true
    || (props.tool.result && typeof props.tool.result === 'object'
      && (props.tool.result as Record<string, unknown>)._cygnusx_payload_truncated === true)
})

// 代码超过折叠高度（约 5 行）时提供展开/收起，避免长代码被静默截断
const COLLAPSED_LINES = 5
const codeLineCount = computed(() => (code.value ? code.value.split('\n').length : 0))
const codeOverflows = computed(() => codeLineCount.value > COLLAPSED_LINES)
const codeExpanded = ref(false)

const stdoutText = computed(() => {
  const s = props.tool.uiPayload?.stdout
  return typeof s === 'string' ? s : ''
})

const stderrText = computed(() => {
  const s = props.tool.uiPayload?.stderr
  return typeof s === 'string' ? s : ''
})

const images = computed(() => {
  const imgs = props.tool.uiPayload?.images
  return Array.isArray(imgs) ? (imgs as string[]) : []
})

const echartsOptions = computed(() => {
  const opts = props.tool.uiPayload?.echarts
  return Array.isArray(opts) ? (opts as Record<string, unknown>[]) : []
})

const errorText = computed(() => {
  const e = props.tool.uiPayload?.error
  return typeof e === 'string' ? e : (props.tool.status === 'error' ? '执行出错' : '')
})

const statusText = computed(() => {
  if (props.tool.status === 'running') return '执行中'
  if (errorText.value) return '失败'
  if (props.tool.status === 'success') return '成功'
  return ''
})

const hasOutput = computed(() => stdoutText.value || stderrText.value || props.tool.output)
</script>

<template>
  <div class="chat-code-card">
    <div class="card-header">
      <span class="card-title">代码执行</span>
      <NTag size="tiny" round :bordered="false" type="info">{{ languageBadge }}</NTag>
      <NTag
        v-if="statusText"
        size="tiny"
        round
        :bordered="false"
        :type="errorText ? 'error' : 'success'"
      >
        {{ statusText }}
      </NTag>
      <button
        v-if="codeOverflows"
        type="button"
        class="code-expand-toggle"
        @click="codeExpanded = !codeExpanded"
      >
        {{ codeExpanded ? '收起' : `展开全部 ${codeLineCount} 行` }}
      </button>
    </div>

    <div class="editor-wrap" :class="{ expanded: codeExpanded }">
      <CodeEditor :model-value="code" readonly />
    </div>

    <div v-if="payloadTruncated" class="truncation-notice">
      内容已截断，完整结果见产物/归档
    </div>

    <div v-if="hasOutput || tool.status === 'running'" class="output-block">
      <div v-if="stdoutText || tool.output" class="output-section">
        <div class="output-label">stdout</div>
        <pre class="output-view">{{ tool.output || stdoutText }}</pre>
      </div>
      <div v-if="stderrText" class="output-section stderr">
        <div class="output-label">stderr</div>
        <pre class="output-view">{{ stderrText }}</pre>
      </div>
    </div>

    <div v-if="images.length" class="image-previews">
      <img
        v-for="(img, idx) in images"
        :key="idx"
        :src="img.startsWith('data:') ? img : `data:image/png;base64,${img}`"
        class="preview-image"
      />
    </div>

    <div v-if="echartsOptions.length" class="echarts-previews">
      <div v-for="(opt, idx) in echartsOptions" :key="idx" class="echarts-placeholder">
        图表 {{ idx + 1 }}（ECharts 渲染待接入）
      </div>
    </div>

    <div v-if="errorText && !hasOutput" class="error-block">
      {{ errorText }}
    </div>
  </div>
</template>

<style scoped>
.chat-code-card {
  border: 1px solid var(--chat-border, #e8ecf1);
  border-radius: 10px;
  background: var(--chat-surface, #fff);
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--chat-border, #e8ecf1);
  background: var(--chat-bg-subtle, #f8f9fb);
}

.card-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--chat-text-secondary, #666);
}

.editor-wrap {
  /* 与 AI 工作台代码卡片统一：默认折叠为约 5 行高，超出时可通过头部按钮展开 */
  min-height: 22px;
  max-height: 110px;
  overflow: hidden;
  border-bottom: 1px solid var(--chat-border, #e8ecf1);
}

.editor-wrap.expanded {
  max-height: none;
}

.code-expand-toggle {
  margin-left: auto;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--brand-primary, #6366f1);
  background: transparent;
  border: 1px solid var(--chat-border, #e8ecf1);
  border-radius: 6px;
  cursor: pointer;
}

.code-expand-toggle:hover {
  background: var(--brand-primary-light, rgba(99, 102, 241, 0.08));
}

.output-block {
  padding: 8px 12px;
}

.truncation-notice {
  padding: 6px 12px;
  border-top: 1px solid var(--chat-border, #e8ecf1);
  background: rgba(240, 156, 60, 0.08);
  color: var(--chat-text-secondary, #8a6d3b);
  font-size: 11px;
}

.output-section {
  margin-bottom: 6px;
}

.output-section.stderr {
  border-top: 1px dashed var(--chat-border, #e8ecf1);
  padding-top: 6px;
}

.output-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--chat-text-muted, #999);
  margin-bottom: 2px;
}

.output-view {
  margin: 0;
  padding: 6px 8px;
  font-size: 12px;
  line-height: 1.5;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  color: var(--chat-text-primary, #1a1a1a);
  background: var(--chat-bg-code, #f5f6f8);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
}

.image-previews {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
}

.preview-image {
  max-width: 100%;
  max-height: 360px;
  border-radius: 8px;
  border: 1px solid var(--chat-border, #e8ecf1);
}

.echarts-previews {
  padding: 8px 12px;
}

.echarts-placeholder {
  font-size: 12px;
  color: var(--chat-text-muted, #999);
  padding: 8px;
  border: 1px dashed var(--chat-border, #e8ecf1);
  border-radius: 6px;
  text-align: center;
}

.error-block {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--error-color, #d03050);
  background: rgba(208, 48, 80, 0.06);
}
</style>
