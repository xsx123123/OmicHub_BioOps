<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NPopconfirm,
  NSelect,
  NSpin,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import {
  CheckmarkCircleOutline,
  BulbOutline,
  CloudUploadOutline,
  CodeSlashOutline,
  EarthOutline,
  RefreshOutline,
  SaveOutline,
  SearchOutline,
  SparklesOutline,
} from '@vicons/ionicons5'
import PageHeader from '@/components/PageHeader.vue'
import { agentApi } from '@/api/agent'
import { useAgentHubStore, CATEGORY_LABELS } from '@/stores/agentHub'
import type { UserAgentCapabilities, UserAgentFeatureKey } from '@/types/agent'

const store = useAgentHubStore()
const message = useMessage()

const loading = ref(true)
const loadingCapabilities = ref(false)
const saving = ref(false)
const selectedAgentId = ref('')
const agentSearch = ref('')
const capabilities = ref<UserAgentCapabilities | null>(null)
const selection = ref({
  model_id: '',
  mcp_ids: [] as string[],
  skill_ids: [] as string[],
  features: {
    enable_web_search: false,
    enable_file_upload: false,
    enable_code_execution: false,
    enable_deep_thinking: false,
  },
})
let capabilityRequestId = 0

const activeAgent = computed(() => store.agents.find((agent) => agent.id === selectedAgentId.value) ?? null)
const visibleAgents = computed(() => {
  const keyword = agentSearch.value.trim().toLocaleLowerCase()
  if (!keyword) return store.agents
  return store.agents.filter((agent) => [
    agent.name,
    agent.description,
    CATEGORY_LABELS[agent.category] || agent.category,
  ].some((value) => value.toLocaleLowerCase().includes(keyword)))
})
const modelOptions = computed(() => store.availableModels.map((model) => ({
  label: model.model && model.model !== model.name ? `${model.name} · ${model.model}` : model.name,
  value: model.id,
})))
const mcpOptions = computed(() => store.mcps
  .filter((mcp) => mcp.is_enabled)
  .map((mcp) => ({ label: `${mcp.name} · ${mcp.description || 'MCP 服务'}`, value: mcp.id })))
const skillOptions = computed(() => store.skills
  .filter((skill) => skill.is_active)
  .map((skill) => ({ label: `${skill.icon} ${skill.name} · ${skill.description || 'Skill'}`, value: skill.id })))

const selectedMcpCount = computed(() => selection.value.mcp_ids.length)
const selectedSkillCount = computed(() => selection.value.skill_ids.length)
const hasCustomSelection = computed(() => capabilities.value?.is_customized === true)
const hasUnsavedChanges = computed(() => {
  const current = capabilities.value
  if (!current) return false
  return selection.value.model_id !== (current.model_id || '')
    || selection.value.mcp_ids.join('|') !== current.mcp_ids.join('|')
    || selection.value.skill_ids.join('|') !== current.skill_ids.join('|')
    || FEATURE_SWITCHES.some((feature) => selection.value.features[feature.key] !== current.features[feature.key])
})

const FEATURE_SWITCHES: Array<{
  key: UserAgentFeatureKey
  title: string
  description: string
  icon: typeof EarthOutline
}> = [
  { key: 'enable_web_search', title: '联网搜索', description: '允许助手访问互联网获取最新信息', icon: EarthOutline },
  { key: 'enable_file_upload', title: '文件上传', description: '允许在会话中上传文件进行分析', icon: CloudUploadOutline },
  { key: 'enable_code_execution', title: '代码执行', description: '允许助手在沙盒中执行 Python 等代码', icon: CodeSlashOutline },
  { key: 'enable_deep_thinking', title: '深度思考', description: '启用推理链，适合复杂问题拆解', icon: BulbOutline },
]

function isFeatureAvailable(key: UserAgentFeatureKey): boolean {
  return Boolean(activeAgent.value?.features?.[key])
}

function applyCapabilities(current: UserAgentCapabilities) {
  capabilities.value = current
  selection.value = {
    model_id: current.model_id || '',
    mcp_ids: [...current.mcp_ids],
    skill_ids: [...current.skill_ids],
    features: { ...current.features },
  }
}

function renderMcpTag({ option, handleClose }: any) {
  const mcp = store.mcps.find((item) => item.id === option.value)
  return h(NTag, {
    size: 'small',
    bordered: false,
    closable: true,
    onClose: (event: MouseEvent) => {
      event.stopPropagation()
      handleClose()
    },
  }, { default: () => mcp?.name || '未知 MCP' })
}

function renderSkillTag({ option, handleClose }: any) {
  const skill = store.skills.find((item) => item.id === option.value)
  return h(NTag, {
    size: 'small',
    bordered: false,
    closable: true,
    onClose: (event: MouseEvent) => {
      event.stopPropagation()
      handleClose()
    },
  }, { default: () => skill ? `${skill.icon} ${skill.name}` : '未知 Skill' })
}

async function loadCapabilities() {
  const agentId = selectedAgentId.value
  if (!agentId) {
    capabilities.value = null
    return
  }

  const requestId = ++capabilityRequestId
  loadingCapabilities.value = true
  try {
    const current = await agentApi.getCapabilities(agentId)
    if (requestId === capabilityRequestId && selectedAgentId.value === agentId) {
      applyCapabilities(current)
    }
  } catch (error: any) {
    if (requestId === capabilityRequestId) {
      capabilities.value = null
      message.error(error?.response?.data?.detail || '加载个人 Agent 能力配置失败')
    }
  } finally {
    if (requestId === capabilityRequestId) loadingCapabilities.value = false
  }
}

async function saveCapabilities() {
  const agent = activeAgent.value
  if (!agent) return

  saving.value = true
  try {
    const current = await agentApi.updateCapabilities(agent.id, selection.value)
    if (selectedAgentId.value === agent.id) applyCapabilities(current)
    message.success(`「${agent.name}」的个人能力配置已保存，将在下一条消息中生效`)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '保存个人 Agent 能力配置失败')
  } finally {
    saving.value = false
  }
}

async function resetCapabilities() {
  const agent = activeAgent.value
  if (!agent) return

  saving.value = true
  try {
    await agentApi.resetCapabilities(agent.id)
    if (selectedAgentId.value === agent.id) await loadCapabilities()
    message.success(`「${agent.name}」已恢复管理员默认能力`)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '恢复管理员默认能力失败')
  } finally {
    saving.value = false
  }
}

watch(selectedAgentId, () => {
  void loadCapabilities()
})

onMounted(async () => {
  loading.value = true
  try {
    await Promise.all([
      store.fetchAgents(true),
      store.fetchUserSelectableMcps(),
      store.fetchSkills(false),
      store.fetchAvailableModels(),
    ])
    selectedAgentId.value = store.agents[0]?.id || ''
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main class="page-container agent-capabilities-page">
    <PageHeader
      title="我的 Agent 能力"
      subtitle="为每个 Agent 选择你个人使用的模型、MCP 与 Skill；这些选择只作用于你的会话。"
    >
      <template #actions>
        <NButton secondary :loading="loadingCapabilities" :disabled="!activeAgent" @click="loadCapabilities">
          <template #icon><NIcon :component="RefreshOutline" /></template>
          刷新配置
        </NButton>
      </template>
    </PageHeader>

    <NSpin :show="loading">
      <NEmpty v-if="!store.agents.length && !loading" description="当前没有可配置的 Agent" class="empty-state" />

      <div v-else class="capability-workspace">
        <aside class="agent-browser" aria-labelledby="agent-selector-title">
          <div class="browser-heading">
            <div>
              <span class="eyebrow">个人工作区</span>
              <h2 id="agent-selector-title">选择 Agent</h2>
              <p>配置按“用户 + Agent”独立保存。</p>
            </div>
            <NTag size="small" round>{{ store.agents.length }} 个</NTag>
          </div>

          <NInput v-model:value="agentSearch" clearable placeholder="搜索 Agent" class="agent-search">
            <template #prefix><NIcon :component="SearchOutline" /></template>
          </NInput>

          <NEmpty v-if="!visibleAgents.length" size="small" description="没有匹配的 Agent" class="agent-empty" />
          <div v-else class="agent-list" role="radiogroup" aria-label="可配置的 Agent">
            <button
              v-for="agent in visibleAgents"
              :key="agent.id"
              type="button"
              class="agent-card omichub-selectable-card"
              :class="{ 'is-selected': agent.id === selectedAgentId }"
              :aria-checked="agent.id === selectedAgentId"
              role="radio"
              @click="selectedAgentId = agent.id"
            >
              <span class="agent-avatar" :style="{ background: agent.color }">{{ agent.avatar }}</span>
              <span class="agent-copy">
                <span class="agent-title-row">
                  <strong>{{ agent.name }}</strong>
                  <NTag v-if="agent.is_default" size="tiny" type="warning" round>默认</NTag>
                </span>
                <span class="agent-category">{{ CATEGORY_LABELS[agent.category] || agent.category }}</span>
                <span class="agent-mounts">MCP {{ agent.mcp_ids.length }} · Skill {{ agent.skill_ids.length }}</span>
              </span>
              <NIcon v-if="agent.id === selectedAgentId" class="selected-icon" :component="CheckmarkCircleOutline" aria-hidden="true" />
            </button>
          </div>
        </aside>

        <section v-if="activeAgent" class="capability-editor" aria-labelledby="capability-editor-title">
          <div class="editor-identity">
            <span class="editor-avatar" :style="{ background: activeAgent.color }">{{ activeAgent.avatar }}</span>
            <div class="editor-title">
              <span class="eyebrow">当前 Agent</span>
              <h2 id="capability-editor-title">{{ activeAgent.name }} 的个人能力</h2>
              <p>{{ activeAgent.description || '为当前 Agent 定义仅在你的会话中生效的资源组合。' }}</p>
            </div>
            <div class="editor-state">
              <NTag v-if="hasCustomSelection" type="success" round>个人配置已启用</NTag>
              <NTag v-else round>使用管理员默认配置</NTag>
            </div>
          </div>

          <NAlert type="info" :show-icon="false" class="capability-guidance">
            仅可选择管理员已启用的模型、MCP 与 Skill。System Prompt 与 Agent 基础设置由管理员维护。
          </NAlert>

          <NSpin :show="loadingCapabilities">
            <NForm label-placement="top" class="capability-form">
              <div class="editor-grid">
                <NCard size="small" class="capability-card">
                  <template #header>
                    <div class="capability-card-title"><NIcon :component="SparklesOutline" aria-hidden="true" /> 模型</div>
                  </template>
                  <p>选择此 Agent 在你的会话中使用的大模型。</p>
                  <NFormItem label="使用的模型" :show-feedback="false">
                    <NSelect
                      v-model:value="selection.model_id"
                      :options="modelOptions"
                      filterable
                      clearable
                      placeholder="使用管理员默认模型"
                    />
                  </NFormItem>
                </NCard>

                <NCard size="small" class="capability-card">
                  <template #header>
                    <div class="capability-card-title">MCP 服务 <NTag size="tiny" round>{{ selectedMcpCount }} 个</NTag></div>
                  </template>
                  <p>只会向此 Agent 暴露所选 MCP 的工具。</p>
                  <NFormItem label="可调用的 MCP" :show-feedback="false">
                    <NSelect
                      v-model:value="selection.mcp_ids"
                      :options="mcpOptions"
                      :render-tag="renderMcpTag"
                      multiple
                      filterable
                      clearable
                      placeholder="选择可调用的 MCP"
                    />
                  </NFormItem>
                </NCard>

                <NCard size="small" class="capability-card">
                  <template #header>
                    <div class="capability-card-title">Skills <NTag size="tiny" round>{{ selectedSkillCount }} 个</NTag></div>
                  </template>
                  <p>只会为此 Agent 加载所选 Skill 的能力说明。</p>
                  <NFormItem label="可用的 Skills" :show-feedback="false">
                    <NSelect
                      v-model:value="selection.skill_ids"
                      :options="skillOptions"
                      :render-tag="renderSkillTag"
                      multiple
                      filterable
                      clearable
                      placeholder="选择可用 Skill"
                    />
                  </NFormItem>
                </NCard>
              </div>

              <NCard size="small" class="feature-card">
                <template #header>
                  <div>
                    <div class="capability-card-title"><span class="feature-title-marker" aria-hidden="true" /> 功能开关</div>
                    <p class="feature-card-subtitle">扩展能力的启停控制；只能调整管理员已开放的功能。</p>
                  </div>
                </template>
                <div class="feature-grid">
                  <div
                    v-for="feature in FEATURE_SWITCHES"
                    :key="feature.key"
                    class="feature-toggle"
                    :class="{
                      'is-enabled': selection.features[feature.key],
                      'is-locked': !isFeatureAvailable(feature.key),
                    }"
                  >
                    <span class="feature-icon"><NIcon :component="feature.icon" /></span>
                    <span class="feature-copy">
                      <strong>{{ feature.title }}</strong>
                      <small>{{ isFeatureAvailable(feature.key) ? feature.description : '管理员尚未开放此功能' }}</small>
                    </span>
                    <NSwitch
                      v-model:value="selection.features[feature.key]"
                      :disabled="!isFeatureAvailable(feature.key)"
                      :aria-label="`${feature.title}开关`"
                    />
                  </div>
                </div>
              </NCard>
            </NForm>

            <div class="editor-actions">
              <span v-if="hasUnsavedChanges" class="unsaved-state" aria-live="polite">有未保存的更改</span>
              <NPopconfirm v-if="hasCustomSelection" @positive-click="resetCapabilities">
                <template #trigger>
                  <NButton :loading="saving">恢复管理员默认</NButton>
                </template>
                恢复后将移除你为「{{ activeAgent.name }}」保存的个人能力选择，确定继续吗？
              </NPopconfirm>
              <NButton type="primary" :loading="saving" :disabled="!hasUnsavedChanges" @click="saveCapabilities">
                <template #icon><NIcon :component="SaveOutline" /></template>
                保存个人配置
              </NButton>
            </div>
          </NSpin>
        </section>
      </div>
    </NSpin>
  </main>
</template>

<style scoped>
.agent-capabilities-page {
  display: flex;
  min-height: 100%;
  flex-direction: column;
}

.empty-state {
  min-height: 320px;
  display: grid;
  place-items: center;
}

.capability-workspace {
  display: grid;
  grid-template-columns: minmax(264px, 312px) minmax(0, 1fr);
  align-items: start;
  gap: 20px;
}

.agent-browser,
.capability-editor {
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
}

.agent-browser {
  position: sticky;
  top: 24px;
  height: calc(100dvh - 160px);
  padding: 18px;
  display: flex;
  min-height: 360px;
  flex-direction: column;
  box-sizing: border-box;
}

.browser-heading,
.editor-identity {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.eyebrow {
  display: block;
  margin-bottom: 4px;
  color: var(--arco-primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  line-height: 1.4;
  text-transform: uppercase;
}

.browser-heading h2,
.editor-title h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 650;
  line-height: 1.5;
}

.browser-heading p,
.editor-title p,
.capability-card p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.agent-search {
  margin: 16px 0 12px;
}

.agent-list {
  display: grid;
  min-height: 0;
  flex: 1;
  gap: 8px;
  overflow-y: auto;
  padding: 2px;
  scrollbar-gutter: stable;
}

.agent-empty {
  min-height: 180px;
}

.agent-card {
  position: relative;
  width: 100%;
  min-height: 76px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--neutral-border);
  border-radius: 10px;
  background: var(--neutral-card);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.agent-card:active { transform: translateY(0); }

.agent-card:focus-visible {
  outline: 2px solid var(--border-focus, var(--arco-primary));
  outline-offset: 3px;
}

.agent-avatar {
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: var(--text-on-primary);
  font-size: 21px;
  box-shadow: 0 4px 10px color-mix(in srgb, currentColor 12%, transparent);
}

.agent-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.4;
}

.agent-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.agent-title-row strong {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-category { color: var(--text-secondary); }

.agent-mounts {
  color: var(--text-tertiary, var(--text-secondary));
}

.selected-icon {
  margin-left: auto;
  flex: 0 0 auto;
  color: var(--arco-primary);
  font-size: 18px;
}

.capability-editor {
  position: sticky;
  top: 24px;
  min-width: 0;
  max-height: calc(100dvh - 160px);
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-gutter: stable;
}

.editor-identity {
  position: sticky;
  top: 0;
  z-index: 2;
  align-items: center;
  padding: 20px 22px;
  border-bottom: 1px solid var(--neutral-border);
  background: color-mix(in srgb, var(--arco-primary) 5%, var(--neutral-card));
}

.editor-avatar {
  width: 46px;
  height: 46px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 13px;
  color: var(--text-on-primary);
  font-size: 23px;
  box-shadow: var(--shadow-card);
}

.editor-title {
  min-width: 0;
  flex: 1;
}

.editor-state {
  flex: 0 0 auto;
}

.capability-guidance {
  margin: 18px 22px 0;
  line-height: 1.65;
}

.editor-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  padding: 18px 22px 22px;
}

.capability-card {
  min-width: 0;
  box-shadow: none;
}

.capability-card :deep(.n-card__header) {
  padding-bottom: 8px;
}

.capability-card :deep(.n-card__content) {
  display: grid;
  gap: 12px;
}

.capability-card p {
  min-height: 44px;
}

.capability-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
  line-height: 24px;
}

.capability-form :deep(.n-form-item) {
  margin-bottom: 0;
}

.feature-card {
  margin: 0 22px 22px;
  box-shadow: none;
}

.feature-card :deep(.n-card__header) {
  padding-bottom: 10px;
}

.feature-card :deep(.n-card__content) {
  padding-top: 0;
}

.feature-title-marker {
  width: 4px;
  height: 22px;
  display: inline-block;
  border-radius: 999px;
  background: var(--arco-primary);
}

.feature-card-subtitle {
  margin-left: 12px !important;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.feature-toggle {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--neutral-border);
  border-radius: 10px;
  background: var(--neutral-card);
  transition: border-color var(--card-state-duration) var(--card-state-easing), background-color var(--card-state-duration) var(--card-state-easing);
}

.feature-toggle.is-enabled {
  border-color: color-mix(in srgb, var(--arco-primary) 36%, var(--neutral-border));
  background: color-mix(in srgb, var(--arco-primary) 5%, var(--neutral-card));
}

.feature-toggle.is-locked { opacity: 0.64; }

.feature-icon {
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: var(--arco-primary);
  background: color-mix(in srgb, var(--arco-primary) 10%, var(--neutral-card));
  font-size: 20px;
}

.feature-copy {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 2px;
}

.feature-copy strong { color: var(--text-primary); font-size: 14px; font-weight: 600; line-height: 20px; }
.feature-copy small { color: var(--text-secondary); font-size: 12px; line-height: 18px; }

.editor-actions {
  position: sticky;
  bottom: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 22px;
  border-top: 1px solid var(--neutral-border);
  background: var(--neutral-fill-2, var(--neutral-bg));
}

.unsaved-state {
  margin-right: auto;
  color: var(--arco-warning);
  font-size: 13px;
  line-height: 20px;
}

@media (max-width: 980px) {
  .capability-workspace { grid-template-columns: 1fr; }
  .agent-browser { position: static; height: auto; }
  .capability-editor { position: static; max-height: none; overflow: visible; }
  .agent-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: none;
  }
  .editor-grid { grid-template-columns: 1fr; }
  .capability-card p { min-height: 0; }
}

@media (max-width: 640px) {
  .agent-browser { padding: 16px; }
  .agent-list { grid-template-columns: 1fr; }
  .editor-identity { align-items: flex-start; flex-wrap: wrap; padding: 18px 16px; }
  .editor-state { width: 100%; margin-left: 58px; }
  .capability-guidance { margin: 16px 16px 0; }
  .editor-grid { padding: 16px; }
  .feature-card { margin: 0 16px 16px; }
  .feature-grid { grid-template-columns: 1fr; }
  .editor-actions { align-items: stretch; flex-direction: column-reverse; }
  .editor-actions { padding: 14px 16px; }
  .unsaved-state { margin-right: 0; text-align: center; }
  .editor-actions :deep(.n-button) { width: 100%; }
}
</style>
