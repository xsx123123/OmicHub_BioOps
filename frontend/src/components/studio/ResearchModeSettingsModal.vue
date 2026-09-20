<script setup lang="ts">
/**
 * ResearchModeSettingsModal — 会话设置 · 科研模式三开关（WP3 任务 3）
 *
 *  - 主开关「科研模式」（默认关；research_mode=null 的旧会话显示全关）
 *  - 开启后展开三个子开关：
 *    a) 渲染形态：消息流 / cell 时间线（与 cell 时间线投影共用同一个状态，两处联动）
 *    b) 工作区协议：普通 / 科研（科研态提示 state/ 目录约定，仅提示，不建目录）
 *    c) PTC 白名单：基础集 / 基础集 + llm_query（开启提示"编排中将允许 llm_query 子调用"）
 *  - 全部变更即时 PUT /chat/sessions/{id}/research-mode；失败回滚 UI 状态并提示。
 *  - 关闭科研模式时渲染形态回落消息流，cell 时间线入口不可用（置灰）。
 */
import { computed, ref, watch } from 'vue'
import {
  NModal, NSwitch, NRadioGroup, NRadioButton, NButton, NSpin, useMessage,
} from 'naive-ui'
import { useAgentHubStore } from '@/stores/agentHub'
import type { ResearchModeSettings } from '@/types/chat'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const store = useAgentHubStore()
// 与 ToolCallEntry 同策略：轻量测试宿主无 NMessageProvider 时兜底，不在 setup 中断
const message = (() => {
  try {
    return useMessage()
  } catch {
    return { error: () => undefined, success: () => undefined }
  }
})()

const DEFAULT_OFF: ResearchModeSettings = {
  enabled: false,
  render_mode: 'message_flow',
  workspace_protocol: 'standard',
  ptc_llm_query: false,
}

const draft = ref<ResearchModeSettings>({ ...DEFAULT_OFF })
const saving = ref(false)

const sessionId = computed(() => store.currentSessionId)
/** 未落库的临时会话（sess- 前缀）没有后端记录，禁用设置并提示 */
const persisted = computed(() => !!sessionId.value && !sessionId.value.startsWith('sess-'))

watch(
  () => props.show,
  (show) => {
    if (!show) return
    draft.value = { ...DEFAULT_OFF, ...(store.currentSession?.research_mode || {}) }
  },
  { immediate: true },
)

async function apply(next: ResearchModeSettings): Promise<void> {
  if (!persisted.value) return
  const previous = { ...draft.value }
  draft.value = { ...next }
  saving.value = true
  try {
    await store.updateResearchMode(sessionId.value, next)
  } catch {
    draft.value = previous
    message.error('科研模式设置保存失败，已恢复为之前的状态')
  } finally {
    saving.value = false
  }
}

function handleToggleEnabled(value: boolean) {
  apply({
    ...draft.value,
    enabled: value,
    // 关闭科研模式时渲染形态回落消息流
    render_mode: value ? draft.value.render_mode : 'message_flow',
  })
}

function handleRenderMode(value: string | number | boolean) {
  if (!draft.value.enabled) return
  if (value !== 'message_flow' && value !== 'cell_timeline') return
  apply({ ...draft.value, render_mode: value })
}

function handleProtocol(value: string | number | boolean) {
  if (value !== 'standard' && value !== 'research') return
  apply({ ...draft.value, workspace_protocol: value })
}

function handlePtc(value: string | number | boolean) {
  apply({ ...draft.value, ptc_llm_query: value === true || value === 'true' })
}
</script>

<template>
  <n-modal
    :show="show"
    preset="card"
    title="会话设置 · 科研模式"
    style="width: min(480px, calc(100vw - 32px))"
    :bordered="false"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <n-spin :show="saving" size="small">
      <div class="rm-section">
        <div class="rm-row">
          <div class="rm-label">
            <span class="rm-title">科研模式</span>
            <span class="rm-desc">面向科研编排的会话能力：cell 时间线渲染、科研工作区协议与 PTC 白名单</span>
          </div>
          <n-switch
            :value="draft.enabled"
            :disabled="!persisted"
            data-test="research-mode-enabled"
            @update:value="handleToggleEnabled"
          />
        </div>
        <p v-if="!persisted" class="rm-hint rm-warn">当前会话尚未保存，保存后即可设置科研模式。</p>
      </div>

      <div class="rm-section" :class="{ disabled: !draft.enabled }">
        <div class="rm-row">
          <div class="rm-label">
            <span class="rm-title">渲染形态</span>
            <span class="rm-desc">历史工具卡片的渲染方式；cell 时间线按代码 cell 分组展示</span>
          </div>
          <n-radio-group
            :value="draft.enabled ? draft.render_mode : 'message_flow'"
            :disabled="!draft.enabled || !persisted"
            size="small"
            data-test="research-mode-render"
            @update:value="handleRenderMode"
          >
            <n-radio-button value="message_flow">消息流</n-radio-button>
            <n-radio-button value="cell_timeline">cell 时间线</n-radio-button>
          </n-radio-group>
        </div>
        <p v-if="!draft.enabled" class="rm-hint">开启科研模式后可用；关闭时渲染形态回落为消息流。</p>
      </div>

      <div class="rm-section" :class="{ disabled: !draft.enabled }">
        <div class="rm-row">
          <div class="rm-label">
            <span class="rm-title">工作区协议</span>
            <span class="rm-desc">编排产物在工作区中的组织协议</span>
          </div>
          <n-radio-group
            :value="draft.workspace_protocol"
            :disabled="!draft.enabled || !persisted"
            size="small"
            data-test="research-mode-protocol"
            @update:value="handleProtocol"
          >
            <n-radio-button value="standard">普通</n-radio-button>
            <n-radio-button value="research">科研</n-radio-button>
          </n-radio-group>
        </div>
        <p v-if="draft.enabled && draft.workspace_protocol === 'research'" class="rm-hint">
          科研协议：编排产物按 state/ 目录约定组织（目录由后端协议创建，前端仅声明约定）。
        </p>
      </div>

      <div class="rm-section" :class="{ disabled: !draft.enabled }">
        <div class="rm-row">
          <div class="rm-label">
            <span class="rm-title">PTC 白名单</span>
            <span class="rm-desc">编排中允许 PTC 执行的子调用集合</span>
          </div>
          <n-radio-group
            :value="draft.ptc_llm_query"
            :disabled="!draft.enabled || !persisted"
            size="small"
            data-test="research-mode-ptc"
            @update:value="handlePtc"
          >
            <n-radio-button :value="false">基础集</n-radio-button>
            <n-radio-button :value="true">基础集 + llm_query</n-radio-button>
          </n-radio-group>
        </div>
        <p v-if="draft.enabled && draft.ptc_llm_query" class="rm-hint">
          编排中将允许 llm_query 子调用。
        </p>
      </div>
    </n-spin>

    <template #footer>
      <n-button size="small" @click="emit('update:show', false)">完成</n-button>
    </template>
  </n-modal>
</template>

<style scoped lang="scss">
.rm-section {
  padding: 10px 0;
  border-bottom: 1px solid var(--chat-border, var(--n-border-color, #e5e7eb));
}
.rm-section:last-of-type { border-bottom: none; }
.rm-section.disabled .rm-title { color: var(--chat-text-muted, #999); }
.rm-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.rm-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.rm-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--chat-text-primary, #333);
}
.rm-desc {
  font-size: 11px;
  color: var(--chat-text-muted, #999);
}
.rm-hint {
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--chat-text-secondary, #666);
}
.rm-hint.rm-warn { color: #d03050; }
</style>
