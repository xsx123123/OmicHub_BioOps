<script setup lang="ts">
import { h, ref, computed, onMounted } from 'vue'
import {
  NButton, NDataTable, NIcon, NTag, NSpace, NPopconfirm, NModal, NCard,
  NForm, NFormItem, NInput, NSelect, NColorPicker, NSwitch, NPopover, NSpin,
  NTooltip,
  useMessage,
} from 'naive-ui'
import {
  CreateOutline, TrashOutline, RefreshOutline, StarOutline, EyeOutline,
  EarthOutline, CloudUploadOutline, CodeSlashOutline, BulbOutline,
  CopyOutline, ExpandOutline, ExtensionPuzzleOutline,
} from '@vicons/ionicons5'
import { useAgentHubStore, CATEGORY_LABELS } from '@/stores/agentHub'
import { adminProviderApi } from '@/api/admin/ai_provider'
import type { AgentTemplate, AgentCategory, AgentFeatures } from '@/types/agent'

const message = useMessage()
const store = useAgentHubStore()

const showEdit = ref(false)
const editing = ref<Partial<AgentTemplate>>({})
const editingSnapshot = ref<string>('')
const isEdit = ref(false)
const saving = ref(false)
const previewId = ref<string | null>(null)
const discovering = ref(false)
const discoveryMap = ref<Record<string, { providerName: string; models: Array<{ id: string; name: string }> }>>({})
const showPromptModal = ref(false)

/** 可选模型配置（来自 /admin/ai-providers） */
const modelOptions = ref<{ label: string; value: string }[]>([])
const modelMap = computed(() => {
  const map: Record<string, string> = {}
  modelOptions.value.forEach((o) => { map[o.value] = o.label })
  return map
})

const EMOJI_LIST = [
  '🤖', '🧬', '🧪', '🔬', '💻', '📊', '🧠', '🌐', '📚', '🔭',
  '🚀', '⭐', '🌙', '☀️', '🔥', '💡', '🔧', '📈', '🎨', '🎓',
  '🐱', '🐶', '🦊', '🐼', '🐨', '🐯', '🦁', '🐸', '🐙', '🦉',
]

/** 主题色快捷色板（与平台品牌色一致） */
const COLOR_SWATCHES = [
  '#4C6FFF', '#7C6FD4', '#9B59B6', '#F53F3F', '#FF7D00',
  '#F7BA1E', '#00B42A', '#0FC6C2', '#333333', '#86909C',
]

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

async function loadModelOptions() {
  try {
    const providers = await adminProviderApi.list()
    modelOptions.value = providers.filter((provider) => provider.is_active).map((m) => ({
      label: `${m.name} (${m.model})`,
      value: m.id,
    }))
  } catch (e) {
    console.error('加载模型列表失败:', e)
    message.error('加载模型列表失败，请检查 AI Provider 配置接口')
  }
}

async function refreshModels() {
  discovering.value = true
  try {
    const providers = (await adminProviderApi.list()).filter((provider) => provider.is_active)
    await loadModelOptions()
    const discoveries = await Promise.all(
      providers.map((p) => adminProviderApi.discoverModels(p.id).catch(() => null)),
    )
    const map: Record<string, { providerName: string; models: Array<{ id: string; name: string }> }> = {}
    discoveries.forEach((d) => {
      if (d?.models?.length) {
        map[d.provider_id] = {
          providerName: d.provider_name,
          models: d.models.map((m) => ({ id: m.id, name: m.name || m.id })),
        }
      }
    })
    discoveryMap.value = map
  } catch (e) {
    message.error('刷新模型列表失败')
    console.error(e)
  } finally {
    discovering.value = false
  }
}

onMounted(async () => {
  await store.fetchAgents(false)
  await Promise.all([store.fetchMcps(), store.fetchSkills()])
  await loadModelOptions()
})

const categoryOptions = (Object.keys(CATEGORY_LABELS) as AgentCategory[]).map((k) => ({
  label: CATEGORY_LABELS[k], value: k,
}))

const mcpOptions = computed(() =>
  store.mcps.map((m) => ({ label: `${m.name}`, value: m.id, disabled: !m.status || m.status === 'offline' })),
)
/** 技能选项：两行结构（名称 + 描述），含脚本标识在技能支持脚本后自动亮起 */
const skillOptions = computed(() =>
  store.skills.map((s) => ({
    label: `${s.icon ?? '🔧'} ${s.name}`,
    value: s.id,
    render: () =>
      h('div', { class: 'skill-opt' }, [
        h('div', { class: 'skill-opt-name' }, [
          `${s.icon ?? '🔧'} ${s.name}`,
          (s as unknown as { has_scripts?: boolean }).has_scripts
            ? h(NTag, { size: 'tiny', type: 'warning', round: true, bordered: false, class: 'skill-opt-badge' }, { default: () => '含脚本' })
            : null,
        ]),
        s.description
          ? h('div', { class: 'skill-opt-desc' }, s.description)
          : null,
      ]),
  })),
)

const isDirty = computed(() => {
  try {
    return JSON.stringify(editing.value) !== editingSnapshot.value
  } catch {
    return true
  }
})

const systemPromptLength = computed(() => editing.value.system_prompt?.length ?? 0)

/** MCP 标签：展示服务名，UUID 收进 tooltip；无名称时显示占位而非裸 ID */
function renderMcpTag({ option, handleClose }: { option: any; handleClose: () => void }) {
  const mcp = store.mcps.find((m) => m.id === option.value)
  const label = mcp?.name || '未知 MCP 服务'
  return h(NTooltip, { trigger: 'hover', placement: 'top' }, {
    trigger: () =>
      h(NTag, {
        size: 'small',
        bordered: false,
        closable: !option.disabled,
        onClose: (e: MouseEvent) => { e.stopPropagation(); handleClose() },
      }, { default: () => label }),
    default: () => `服务 ID：${option.value}`,
  })
}

/** 技能标签：图标 + 名称，可单独移除；未知技能显示占位 */
function renderSkillTag({ option, handleClose }: { option: any; handleClose: () => void }) {
  const skill = store.skills.find((s) => s.id === option.value)
  const label = skill
    ? `${skill.icon ?? '🔧'} ${skill.name}`
    : (typeof option.label === 'string' && !UUID_RE.test(option.label) ? option.label : '未知技能')
  return h(NTag, {
    size: 'small',
    bordered: false,
    closable: !option.disabled,
    onClose: (e: MouseEvent) => { e.stopPropagation(); handleClose() },
  }, { default: () => label })
}

const columns = [
  { title: '头像', key: 'avatar', width: 56, render: (r: AgentTemplate) => r.avatar },
  {
    title: '名称', key: 'name', width: 180,
    render: (r: AgentTemplate) =>
      h(NSpace, { size: 4, align: 'center' }, {
        default: () => [
          h('span', null, r.name),
          r.is_default && h(NTag, { size: 'tiny', type: 'warning', round: true }, { default: () => '默认' }),
        ],
      }),
  },
  { title: '分类', key: 'category', width: 90, render: (r: AgentTemplate) => CATEGORY_LABELS[r.category] },
  {
    title: '模型', key: 'model', width: 160,
    render: (r: AgentTemplate) => {
      const label = r.model_id ? modelMap.value[r.model_id] : ''
      return h(NTag, { size: 'tiny', type: label ? 'info' : 'default', bordered: false }, { default: () => label || '未绑定' })
    },
  },
  {
    title: '挂载能力', key: 'mounts', width: 200,
    render: (r: AgentTemplate) =>
      h(NSpace, { size: 4 }, {
        default: () => [
          h(NTag, { size: 'tiny', type: 'info', bordered: false }, { default: () => `MCP×${r.mcp_ids.length}` }),
          h(NTag, { size: 'tiny', type: 'success', bordered: false }, { default: () => `技能×${r.skill_ids.length}` }),
        ],
      }),
  },
  {
    title: '状态', key: 'is_active', width: 80,
    render: (r: AgentTemplate) => h(NTag, { type: r.is_active ? 'success' : 'default', size: 'small', round: true }, { default: () => r.is_active ? '启用' : '停用' }),
  },
  {
    title: '操作', key: 'actions', width: 280,
    render: (r: AgentTemplate) =>
      h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => openPreview(r.id) },
            { default: () => [h(NIcon, { component: EyeOutline }), '预览'] }),
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => handleEdit(r) },
            { default: () => [h(NIcon, { component: CreateOutline }), '编辑'] }),
          !r.is_default && h(NButton, { size: 'tiny', quaternary: true, onClick: () => handleSetDefault(r.id) },
            { default: () => [h(NIcon, { component: StarOutline }), '设为默认'] }),
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => handleToggle(r.id) },
            { default: () => r.is_active ? '停用' : '启用' }),
          !r.is_builtin && h(NPopconfirm, { onPositiveClick: () => handleDelete(r.id) }, {
            trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' },
              { default: () => [h(NIcon, { component: TrashOutline }), '删除'] }),
            default: () => '确定删除该助手模板？',
          }),
        ],
      }),
  },
]

function makeDefaultAgent(): Partial<AgentTemplate> {
  return {
    avatar: '🤖',
    color: '#4f8ef7',
    category: 'general',
    model_id: undefined,
    mcp_ids: [],
    skill_ids: [],
    features: {
      enable_web_search: false,
      enable_file_upload: false,
      enable_code_execution: false,
      enable_deep_thinking: false,
    } as AgentFeatures,
    welcome_message: '你好，有什么可以帮你？',
    system_prompt: '',
    is_active: true,
  }
}

function handleCreate() {
  editing.value = makeDefaultAgent()
  editingSnapshot.value = JSON.stringify(editing.value)
  isEdit.value = false
  showPromptModal.value = false
  showEdit.value = true
}

function handleEdit(r: AgentTemplate) {
  // 若当前绑定的 model_id 已不在可选列表中（provider 被删），清空避免保存时 500
  const validModelId = r.model_id && modelOptions.value.some((o) => o.value === r.model_id)
    ? r.model_id
    : undefined

  editing.value = {
    ...r,
    model_id: validModelId,
    mcp_ids: [...r.mcp_ids],
    skill_ids: [...r.skill_ids],
    features: {
      enable_web_search: false,
      enable_file_upload: false,
      enable_code_execution: false,
      enable_deep_thinking: false,
      ...(r.features || {}),
    },
  }
  editingSnapshot.value = JSON.stringify(editing.value)
  isEdit.value = true
  showPromptModal.value = false
  showEdit.value = true
}

async function handleSave() {
  if (!editing.value.name?.trim()) {
    message.warning('请填写助手名称')
    return
  }
  if (!editing.value.category) {
    message.warning('请选择分类')
    return
  }
  if (
    editing.value.model_id &&
    !modelOptions.value.some((o) => o.value === editing.value.model_id)
  ) {
    message.warning('所选模型已不可用，请重新选择')
    editing.value.model_id = undefined
    return
  }
  saving.value = true
  try {
    const saved = await store.upsertAgent(editing.value)
    if (saved) {
      message.success(isEdit.value ? '已更新' : '已创建')
      showEdit.value = false
    } else {
      message.error('保存失败，请检查后端接口')
    }
  } catch (e: any) {
    console.error('Agent 保存失败:', e, 'payload:', editing.value)
    message.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleToggle(id: string) {
  try {
    await store.toggleAgent(id)
    const agent = store.getAgent(id)
    message.success(agent?.is_active ? '已启用' : '已停用')
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleSetDefault(id: string) {
  try {
    await store.setDefaultAgent(id)
    message.success('已设为默认助手')
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '设置失败')
  }
}

async function handleDelete(id: string) {
  try {
    await store.deleteAgent(id)
    message.success('已删除')
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '删除失败')
  }
}

function openPreview(id: string) { previewId.value = id }
const previewAgent = computed(() => store.getAgent(previewId.value || ''))

function onSelectEmoji(emoji: string) {
  editing.value.avatar = emoji
}

function onColorChange(color: string) {
  editing.value.color = color
}

async function copyColor() {
  try {
    await navigator.clipboard.writeText(editing.value.color ?? '')
    message.success('已复制色值')
  } catch {
    message.error('复制失败，请手动选择复制')
  }
}

function restoreSystemPrompt() {
  editing.value.system_prompt = ''
}

const featureSwitches = computed(() => [
  {
    key: 'enable_web_search',
    title: '联网搜索',
    desc: '允许助手访问互联网获取最新信息',
    icon: EarthOutline,
  },
  {
    key: 'enable_file_upload',
    title: '文件上传',
    desc: '允许用户上传文件进行分析',
    icon: CloudUploadOutline,
  },
  {
    key: 'enable_code_execution',
    title: '代码执行',
    desc: '允许助手在沙盒中执行 Python 等代码',
    icon: CodeSlashOutline,
  },
  {
    key: 'enable_deep_thinking',
    title: '深度思考',
    desc: '启用推理链，适合复杂问题拆解',
    icon: BulbOutline,
  },
])

function updateFeature(key: keyof AgentFeatures, val: boolean) {
  if (!editing.value.features) editing.value.features = {}
  editing.value.features[key] = val
}
</script>

<template>
  <div class="resource-tab">
    <div class="tab-header">
      <span class="tab-hint">编排 Agent 模板：定义角色设定，并挂载 MCP 服务与技能。</span>
      <NButton type="primary" size="small" @click="handleCreate">
        <template #icon><NIcon :component="CreateOutline" /></template>
        新建助手
      </NButton>
    </div>
    <NDataTable :columns="columns" :data="store.agents" :bordered="false" size="small" :row-key="(r: AgentTemplate) => r.id" />

    <!-- 编辑/新建 -->
    <NModal
      v-model:show="showEdit"
      preset="card"
      :title="isEdit ? '编辑助手模板' : '新建助手模板'"
      style="width: min(1180px, calc(100vw - 48px))"
      class="agent-edit-modal"
      :segmented="{ content: true, footer: true }"
    >
      <div class="edit-body">
          <!-- 基本信息 -->
          <NCard
          size="small"
          class="form-card form-card--basic"
          style="border-radius: 16px"
          :header-style="{ padding: '14px 18px 0' }"
          :content-style="{ padding: '12px 18px 16px' }"
          >
          <template #header>
            <div class="basic-card-head">
              <div class="basic-card-title-row">
                <span class="basic-card-title-marker" aria-hidden="true" />
                <div class="sec-title">基本信息</div>
              </div>
              <div class="sec-sub">助手的名称、分类、头像与主题色</div>
            </div>
          </template>
          <NForm class="basic-form" label-placement="top" size="small">
            <NFormItem label="头像与主题色">
              <div class="identity-row">
                <NPopover trigger="click" placement="bottom" style="padding: 8px">
                  <template #trigger>
                    <div class="avatar-picker" :style="{ background: editing.color }">
                      {{ editing.avatar || '🤖' }}
                    </div>
                  </template>
                  <div class="emoji-grid">
                    <div
                      v-for="emoji in EMOJI_LIST"
                      :key="emoji"
                      class="emoji-cell"
                      @click="onSelectEmoji(emoji)"
                    >
                      {{ emoji }}
                    </div>
                  </div>
                </NPopover>
                <div class="color-block">
                  <NPopover trigger="click" placement="bottom-start" style="padding: 12px">
                    <template #trigger>
                      <button type="button" class="color-trigger" :aria-label="`选择主题色，当前为 ${editing.color}`">
                        <span class="color-value">{{ editing.color }}</span>
                      </button>
                    </template>
                    <NColorPicker
                      :value="editing.color"
                      size="small"
                      :show-alpha="false"
                      :modes="['hex']"
                      :swatches="COLOR_SWATCHES"
                      style="width: 184px"
                      @update:value="onColorChange"
                    />
                  </NPopover>
                  <span class="color-divider" aria-hidden="true" />
                  <NTooltip trigger="hover">
                    <template #trigger>
                      <NButton size="tiny" quaternary circle class="copy-color-btn" aria-label="复制主题色值" @click="copyColor">
                        <template #icon><NIcon :component="CopyOutline" /></template>
                      </NButton>
                    </template>
                    复制色值 {{ editing.color }}
                  </NTooltip>
                </div>
              </div>
            </NFormItem>
            <div class="form-grid">
              <NFormItem class="basic-field" label="名称" required>
                <NInput v-model:value="editing.name" placeholder="如：单细胞分析师" />
              </NFormItem>
              <NFormItem class="basic-field" label="分类" required>
                <NSelect v-model:value="editing.category" :options="categoryOptions" />
              </NFormItem>
            </div>
            <NFormItem label="描述">
              <NInput
                v-model:value="editing.description"
                class="basic-description"
                type="textarea"
                :autosize="{ minRows: 4, maxRows: 6 }"
                placeholder="一句话描述该助手的定位"
              />
            </NFormItem>
          </NForm>
          </NCard>

          <!-- 模型与交互 -->
          <NCard
          size="small"
          class="form-card form-card--model"
          style="border-radius: 16px"
          :header-style="{ padding: '14px 18px 0' }"
          :content-style="{ padding: '12px 18px 16px' }"
          >
          <template #header>
            <div class="sec-head">
              <span class="sec-bar" />
              <div class="sec-head-text">
                <div class="sec-title">模型与交互</div>
                <div class="sec-sub">绑定底层模型并设置开场欢迎语</div>
              </div>
            </div>
          </template>
          <NForm label-placement="top" size="small">
            <NFormItem label="绑定模型配置">
              <div class="model-select-group">
                <NSelect
                  v-model:value="editing.model_id"
                  :options="modelOptions"
                  placeholder="选择后端已配置的模型（决定 Base URL / API Key）"
                  clearable
                  filterable
                  :consistent-menu-width="false"
                  class="model-select"
                />
                <NPopover trigger="click" placement="bottom" style="max-width: 360px" @update:show="refreshModels">
                  <template #trigger>
                    <NTooltip trigger="hover" :delay="300">
                      <template #trigger>
                        <NButton
                          size="small"
                          secondary
                          circle
                          class="model-refresh-btn"
                          :loading="discovering"
                          aria-label="刷新模型列表"
                        >
                          <template #icon><NIcon :component="RefreshOutline" /></template>
                        </NButton>
                      </template>
                      刷新模型列表
                    </NTooltip>
                  </template>
                  <div style="max-height: 260px; overflow-y: auto">
                    <div v-if="discovering" style="padding: 12px; text-align: center">
                      <NSpin size="small" />
                    </div>
                    <template v-else>
                      <div v-if="!Object.keys(discoveryMap).length" style="padding: 8px; color: var(--neutral-text-3, #999); font-size: 12px">
                        未从任何 Provider 发现可用模型，请检查 API Key / Base URL。
                      </div>
                      <div v-for="item in Object.values(discoveryMap)" :key="item.providerName" style="margin-bottom: 10px">
                        <div style="font-size: 12px; font-weight: 500; margin-bottom: 4px">{{ item.providerName }}</div>
                        <NSpace size="small" wrap>
                          <NTag v-for="m in item.models" :key="m.id" size="tiny" round>{{ m.name || m.id }}</NTag>
                        </NSpace>
                      </div>
                    </template>
                  </div>
                </NPopover>
              </div>
            </NFormItem>
            <NFormItem label="欢迎语">
              <NInput v-model:value="editing.welcome_message" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" />
            </NFormItem>
          </NForm>
          </NCard>
          <!-- 系统设定 -->
          <NCard
          size="small"
          class="form-card form-card--system"
          style="border-radius: 16px"
          :header-style="{ padding: '14px 18px 0' }"
          :content-style="{ padding: '12px 18px 16px' }"
          >
          <template #header>
            <div class="sec-head">
              <span class="sec-bar" />
              <div class="sec-head-text">
                <div class="sec-title">系统设定</div>
                <div class="sec-sub">定义角色、能力边界与输出风格</div>
              </div>
            </div>
          </template>
          <NForm label-placement="top" size="small">
            <NFormItem>
              <template #label>
                <div class="prompt-label-row">
                  <span>系统提示词</span>
                  <NSpace :size="6" align="center">
                    <NButton size="tiny" secondary @click="showPromptModal = true">
                      <template #icon><NIcon :component="ExpandOutline" /></template>
                      展开
                    </NButton>
                    <NPopconfirm @positive-click="restoreSystemPrompt">
                      <template #trigger>
                        <NButton size="tiny" quaternary>恢复默认</NButton>
                      </template>
                      确定恢复默认？将清空当前系统提示词。
                    </NPopconfirm>
                  </NSpace>
                </div>
              </template>
              <div class="prompt-wrap">
                <NInput
                  v-model:value="editing.system_prompt"
                  type="textarea"
                  :rows="3"
                  placeholder="System Prompt：角色、能力边界、输出风格…"
                />
                <div class="char-count">{{ systemPromptLength }} / 2000</div>
              </div>
            </NFormItem>
          </NForm>
          </NCard>

          <!-- 能力挂载 -->
          <NCard
          size="small"
          class="form-card form-card--capabilities"
          style="border-radius: 16px"
          :header-style="{ padding: '14px 18px 0' }"
          :content-style="{ padding: '12px 18px 16px' }"
          >
          <template #header>
            <div class="sec-head">
              <span class="sec-bar" />
              <div class="sec-head-text">
                <div class="sec-title">能力挂载</div>
                <div class="sec-sub">按需挂载 MCP 服务与技能，运行时按索引加载</div>
              </div>
            </div>
          </template>
          <NForm label-placement="top" size="small">
            <NFormItem label="挂载 MCP">
              <NSelect
                v-model:value="editing.mcp_ids"
                :options="mcpOptions"
                multiple
                filterable
                placeholder="选择要挂载的 MCP 服务"
                :max-tag-count="3"
                :render-tag="renderMcpTag"
              />
            </NFormItem>
            <NFormItem label="挂载技能">
              <NSelect
                v-model:value="editing.skill_ids"
                :options="skillOptions"
                multiple
                filterable
                placeholder="搜索并选择要挂载的技能"
                :max-tag-count="3"
                :render-tag="renderSkillTag"
              >
                <template #empty>
                  <div class="skill-empty">
                    <NIcon :component="ExtensionPuzzleOutline" :size="26" />
                    <div class="skill-empty-title">暂无可用技能</div>
                    <div class="skill-empty-desc">请先在「技能」页导入技能</div>
                  </div>
                </template>
              </NSelect>
            </NFormItem>
          </NForm>
          </NCard>
        <!-- 功能开关 -->
        <NCard
          size="small"
          class="form-card form-card--features"
          style="border-radius: 16px"
          :header-style="{ padding: '14px 18px 0' }"
          :content-style="{ padding: '10px 18px 14px' }"
        >
          <template #header>
            <div class="sec-head">
              <span class="sec-bar" />
              <div class="sec-head-text">
                <div class="sec-title">功能开关</div>
                <div class="sec-sub">扩展能力的启停控制</div>
              </div>
            </div>
          </template>
          <div class="switch-list">
            <div
              v-for="f in featureSwitches"
              :key="f.key"
              class="switch-row"
              :class="{ 'is-on': !!editing.features?.[f.key as keyof AgentFeatures] }"
            >
              <span class="switch-icon"><NIcon :component="f.icon" /></span>
              <div class="switch-info">
                <div class="switch-title">{{ f.title }}</div>
                <div class="switch-desc">{{ f.desc }}</div>
              </div>
              <NSwitch
                :value="!!editing.features?.[f.key as keyof AgentFeatures]"
                @update:value="(v) => updateFeature(f.key as keyof AgentFeatures, v)"
              />
            </div>
          </div>
        </NCard>
      </div>

      <template #footer>
        <div class="edit-footer">
          <NSpace justify="end" align="center">
            <NButton size="small" @click="showEdit = false">取消</NButton>
            <NButton
              size="small"
              type="primary"
              :disabled="!isDirty"
              :loading="saving"
              @click="handleSave"
            >
              保存
            </NButton>
          </NSpace>
        </div>
      </template>
    </NModal>

    <!-- 系统提示词大编辑模态 -->
    <NModal
      v-model:show="showPromptModal"
      preset="card"
      title="编辑系统提示词"
      style="width: 720px"
      :segmented="{ content: true, footer: true }"
    >
      <div class="prompt-wrap prompt-wrap--modal">
        <NInput
          v-model:value="editing.system_prompt"
          type="textarea"
          :autosize="{ minRows: 16, maxRows: 24 }"
          placeholder="System Prompt：角色、能力边界、输出风格…"
        />
        <div class="char-count">{{ systemPromptLength }} / 2000</div>
      </div>
      <template #footer>
        <NSpace justify="end">
          <NButton size="small" type="primary" @click="showPromptModal = false">完成</NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- 预览能力 -->
    <NModal :show="!!previewAgent" preset="card" :title="previewAgent ? `${previewAgent.avatar} ${previewAgent.name} · 能力预览` : ''" style="width: 520px" @update:show="previewId = null">
      <template v-if="previewAgent">
        <div class="preview-section">
          <div class="preview-label">挂载 MCP（{{ previewAgent.mcp_ids.length }}）</div>
          <NSpace size="small">
            <NTag v-for="m in store.mcpsByIds(previewAgent.mcp_ids)" :key="m.id" type="info" round>{{ m.name }}</NTag>
            <span v-if="!previewAgent.mcp_ids.length" class="empty">未挂载</span>
          </NSpace>
        </div>
        <div class="preview-section">
          <div class="preview-label">挂载技能（{{ previewAgent.skill_ids.length }}）</div>
          <NSpace size="small">
            <NTag v-for="s in store.skillsByIds(previewAgent.skill_ids)" :key="s.id" type="success" round>{{ s.icon }} {{ s.name }}</NTag>
            <span v-if="!previewAgent.skill_ids.length" class="empty">未挂载</span>
          </NSpace>
        </div>
        <div class="preview-section">
          <div class="preview-label">系统设定</div>
          <div class="preview-prompt">{{ previewAgent.system_prompt }}</div>
        </div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.tab-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
.tab-hint { font-size: 12px; color: var(--n-text-color-3, #999); }
.form-card {
  margin: 0;
  animation: section-in 0.24s ease both;
  background: var(--n-color, var(--neutral-card, #fff));
}
.edit-body {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  grid-template-areas:
    "basic basic model model system system"
    "capabilities capabilities capabilities features features features";
  align-items: start;
  gap: 14px 16px;
}
.form-card--basic { grid-area: basic; }
.form-card--model { grid-area: model; animation-delay: 0.03s; }
.form-card--system { grid-area: system; animation-delay: 0.06s; }
.form-card--capabilities,
.form-card--features {
  align-self: stretch;
  height: 100%;
  animation-delay: 0.12s;
}
.form-card--capabilities { grid-area: capabilities; }
.form-card--features { grid-area: features; }
@keyframes section-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 分区标题：短色标代替贯穿式竖线，保证标题基线与卡片边缘统一。 */
.sec-head { display: flex; align-items: center; gap: 9px; }
.sec-bar {
  width: 3px;
  height: 30px;
  border-radius: 2px;
  background: var(--brand-primary, #4C6FFF);
  flex-shrink: 0;
}
.sec-head-text { display: flex; flex-direction: column; justify-content: center; gap: 2px; }
.sec-title { font-size: 16px; font-weight: 600; line-height: 1.3; color: var(--n-text-color-1, #1D2129); }
.sec-sub { font-size: 12px; color: var(--n-text-color-3, #86909C); line-height: 1.4; }

/* 修复编辑弹窗内容过长时底部按钮被挤出可视区域的问题 */
.agent-edit-modal :deep(.n-card) {
  max-height: calc(100vh - 36px);
  display: flex;
  flex-direction: column;
}
.agent-edit-modal :deep(.n-card__content) {
  flex: 1 1 auto;
  overflow-y: auto;
  min-height: 0;
}
/* 吸底操作条：毛玻璃 + 上边框分割线 */
.agent-edit-modal :deep(.n-card__footer) {
  flex-shrink: 0;
  position: sticky;
  bottom: 0;
  background: var(--n-card-color, var(--neutral-card, #fff));
  border-top: 1px solid var(--n-border-color, var(--neutral-border));
}
.edit-footer { padding: 4px 0; }

@media (max-width: 1080px) {
  .edit-body {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    grid-template-areas:
      "basic basic model model"
      "system system system system"
      "capabilities capabilities features features";
  }
}

@media (max-width: 640px) {
  .edit-body {
    grid-template-columns: 1fr;
    grid-template-areas:
      "basic"
      "model"
      "system"
      "capabilities"
      "features";
  }
}

/* 基本信息 */
.basic-card-head {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.basic-card-title-row { display: flex; align-items: center; gap: 9px; }
.basic-card-title-marker {
  width: 4px;
  height: 18px;
  border-radius: 2px;
  flex-shrink: 0;
  background: var(--brand-primary, #4C6FFF);
}
.basic-form {
  --basic-control-height: 38px;
  --basic-control-border: var(--n-border-color, var(--neutral-border, #d9d9d9));
  --basic-focus-color: var(--brand-primary, #4C6FFF);
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.form-grid { display: flex; gap: 20px; }
.form-grid > * { flex: 1 1 0; min-width: 0; }
.form-card :deep(.n-form-item) { margin-bottom: 12px; }
.form-card :deep(.n-form-item:last-child) { margin-bottom: 0; }
.form-card :deep(.n-form-item-label) { padding-bottom: 5px; }
.basic-form :deep(.n-form-item) { margin-bottom: 0; }
.basic-form :deep(.n-form-item-label__asterisk) { color: var(--n-error-color, #ff4d4f); }
.basic-field :deep(.n-input),
.basic-field :deep(.n-base-selection) {
  height: var(--basic-control-height) !important;
  border-radius: 8px;
}
.basic-field :deep(.n-input__border),
.basic-field :deep(.n-base-selection__border) { border-color: var(--basic-control-border); }
.basic-field:focus-within :deep(.n-input__state-border),
.basic-field:focus-within :deep(.n-base-selection__state-border) {
  border-color: var(--basic-focus-color) !important;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--basic-focus-color) 20%, transparent);
}
.basic-description :deep(.n-input__textarea-el) { min-height: 80px; }

/* 头像 + 取色器 */
.identity-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.avatar-picker {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  border: 2px solid var(--n-border-color, #e0e0e6);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  cursor: pointer;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.avatar-picker:hover { border-color: var(--brand-primary, #4C6FFF); transform: scale(1.04); }

.emoji-grid { display: grid; grid-template-columns: repeat(10, 28px); gap: 4px; }
.emoji-cell {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s;
}
.emoji-cell:hover { background: var(--n-border-color, #e0e0e6); }

.color-block { display: flex; align-items: center; gap: 12px; min-width: 0; }
.color-trigger {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  border: 0;
  padding: 0;
  color: var(--n-text-color-2, #4E5969);
  background: transparent;
  cursor: pointer;
  font: inherit;
}
.color-trigger:hover .color-value,
.color-trigger:focus-visible .color-value { color: var(--brand-primary, #4C6FFF); }
.color-value { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 13px; }
.color-divider { width: 1px; height: 16px; background: var(--n-border-color, var(--neutral-border, #e5e7eb)); }
.copy-color-btn { color: var(--n-text-color-3, #86909C); }
.copy-color-btn:hover { color: var(--brand-primary, #4C6FFF); }

.model-select-group {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: stretch;
  gap: 8px;
  width: 100%;
}
.model-select { min-width: 0; }
.model-refresh-btn { flex-shrink: 0; }

/* 系统提示词：4 行 + 右下角字数统计 + 大编辑模态 */
.prompt-label-row { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.prompt-wrap { position: relative; width: 100%; }
.char-count {
  position: absolute;
  right: 10px;
  bottom: 8px;
  pointer-events: none;
  font-size: 11px;
  line-height: 1;
  color: var(--n-text-color-3, #86909C);
  background: color-mix(in srgb, var(--n-color, #fff) 88%, transparent);
  padding: 2px 5px;
  border-radius: 4px;
  white-space: nowrap;
}
.prompt-wrap--modal .char-count { bottom: 12px; }

/* 技能下拉选项：两行结构（名称 + 描述） */
.skill-opt { padding: 2px 0; }
.skill-opt-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 500;
  color: var(--n-text-color-1, #1D2129);
}
.skill-opt-badge { margin-left: 2px; }
.skill-opt-desc {
  font-size: 12px;
  color: var(--n-text-color-3, #86909C);
  margin-top: 2px;
  line-height: 1.45;
  white-space: normal;
}
.skill-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 20px 12px;
  color: var(--n-text-color-3, #86909C);
}
.skill-empty-title { font-size: 13px; font-weight: 500; color: var(--n-text-color-2, #4E5969); }
.skill-empty-desc { font-size: 12px; }

/* 功能开关：图标 + 名称 + 说明，开启态名称加深 */
.switch-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 12px;
}
.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 64px;
  padding: 10px 12px;
  border: 1px solid var(--n-border-color, var(--neutral-border, #e5e7eb));
  border-radius: 12px;
  background: var(--n-color-embedded, var(--neutral-hover, #f7f8fa));
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease;
}
.switch-row:hover { border-color: color-mix(in srgb, var(--brand-primary, #4C6FFF) 30%, var(--n-border-color, #e5e7eb)); }
.switch-row.is-on {
  border-color: color-mix(in srgb, var(--brand-primary, #4C6FFF) 34%, var(--n-border-color, #e5e7eb));
  background: color-mix(in srgb, var(--brand-primary, #4C6FFF) 5%, var(--n-color, #fff));
}
.switch-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 17px;
  flex-shrink: 0;
  color: var(--brand-primary, #4C6FFF);
  background: var(--brand-primary-light, color-mix(in srgb, var(--brand-primary, #4C6FFF) 12%, transparent));
  transition: transform 0.2s ease;
}
.switch-row.is-on .switch-icon { transform: scale(1.06); }
.switch-info { flex: 1; min-width: 0; }
.switch-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--n-text-color-2, #4E5969);
  transition: color 0.2s ease;
}
.switch-row.is-on .switch-title { color: var(--n-text-color-1, #1D2129); font-weight: 600; }
.switch-desc { font-size: 12px; color: var(--n-text-color-3, #86909C); margin-top: 2px; line-height: 1.35; }

@media (max-width: 640px) {
  .form-grid { flex-direction: column; gap: 24px; }
  .switch-list { grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  .form-card,
  .switch-row,
  .avatar-picker,
  .switch-icon { animation: none; transition: none; }
}

.preview-section { margin-bottom: 16px; }
.preview-label { font-size: 12px; color: var(--neutral-text-3); margin-bottom: 6px; }
.preview-prompt { font-size: 12px; color: var(--neutral-text-2); background: var(--neutral-hover); padding: 10px; border-radius: 6px; white-space: pre-wrap; line-height: 1.6; }
.empty { font-size: 12px; color: var(--neutral-text-4); }
</style>
