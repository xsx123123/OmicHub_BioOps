<script setup lang="ts">
import { computed } from 'vue'
import {
  NInput,
  NIcon,
  NButton,
  NPopover,
  NSlider,
  NSelect,
  useMessage,
} from 'naive-ui'
import {
  ChevronDownOutline,
  SettingsOutline,
  ShareOutline,
  StarOutline,
  Star,
  CreateOutline,
} from '@vicons/ionicons5'
import { useChatSessionStore } from '@/stores/chatSession'
import { useChatStore } from '@/stores/chat'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import { enhanceModels, topCapabilities, CAPABILITY_LABELS } from '../modelCapabilities'
import type { ModelOption, Capability, SystemStatus } from '../types'

const emit = defineEmits<{ share: [] }>()

const chatSessionStore = useChatSessionStore()
const chatStore = useChatStore()
const chatAssistantStore = useChatAssistantStore()
const message = useMessage()

// 增强后的模型列表（带能力标签）
const enhancedModels = computed<ModelOption[]>(() => enhanceModels(chatSessionStore.models))

const currentModel = computed<ModelOption | undefined>(() =>
  enhancedModels.value.find((m) => m.id === chatSessionStore.selectedModelId),
)

const currentCaps = computed<Capability[]>(() =>
  topCapabilities(currentModel.value?.capabilities ?? []),
)

// 会话标题双向绑定
const titleModel = computed<string>({
  get: () => chatSessionStore.currentSession?.title ?? '',
  set: (v: string) => {
    const sid = chatSessionStore.currentSessionId
    if (sid) chatSessionStore.updateSessionTitle(sid, v)
  },
})

// 助手选项
const assistantOptions = computed(() =>
  chatAssistantStore.assistants.map((a) => ({
    label: `${a.icon} ${a.name}`,
    value: a.assistant_id,
  })),
)

// 系统状态推断
const systemStatus = computed<SystemStatus>(() => {
  if (!chatSessionStore.isStreaming) return 'ready'
  const last = chatSessionStore.messages[chatSessionStore.messages.length - 1]
  if (last?.role === 'assistant' && last.status === 'streaming') {
    if (chatSessionStore.streamingReasoning) return 'thinking'
    return 'thinking'
  }
  return 'thinking'
})

const statusMeta = computed(() => {
  switch (systemStatus.value) {
    case 'ready':
      return { text: '就绪', cls: 'ready' }
    case 'thinking':
      return { text: '思考中...', cls: 'thinking' }
    case 'toolCalling':
      return { text: '工具调用中...', cls: 'toolCalling' }
    default:
      return { text: '就绪', cls: 'ready' }
  }
})

// 模型分组（收藏置顶 + 通用/生信专用）
const groupedModels = computed(() => {
  const fav = enhancedModels.value.filter((m) => chatStore.isFavorite(m.id))
  const general = enhancedModels.value.filter(
    (m) => !chatStore.isFavorite(m.id) && m.modelType !== 'bio',
  )
  const bio = enhancedModels.value.filter(
    (m) => !chatStore.isFavorite(m.id) && m.modelType === 'bio',
  )
  return { fav, general, bio }
})

function handleSwitchModel(id: string) {
  chatSessionStore.selectedModelId = id
}

function handleToggleFavorite(id: string, e: MouseEvent) {
  e.stopPropagation()
  chatStore.toggleFavorite(id)
}

// 对话设置
const settings = computed({
  get: () => chatStore.conversationSettings,
  set: (v) => chatStore.updateConversationSettings(v),
})

function handleTemperatureChange(v: number) {
  chatStore.updateConversationSettings({ temperature: v })
}
function handleMaxTokensChange(v: number) {
  chatStore.updateConversationSettings({ maxTokens: v })
}
function handleContextChange(v: number) {
  chatStore.updateConversationSettings({ contextLength: v })
}
function handleResetSettings() {
  chatStore.resetConversationSettings()
  message.success('已恢复默认设置')
}

function handleShare() {
  emit('share')
  message.info('分享功能开发中')
}
</script>

<template>
  <div class="model-nav-bar">
    <div class="nav-left">
      <n-input v-model:value="titleModel" class="session-title-input" placeholder="会话标题" size="small">
        <template #prefix>
          <n-icon><CreateOutline /></n-icon>
        </template>
      </n-input>

      <n-popover trigger="click" placement="bottom-start" :width="380" style="padding: 0">
        <template #trigger>
          <div class="model-chip">
            <span class="model-name">{{ currentModel?.name || '选择模型' }}</span>
            <span
              class="model-type-tag"
              :class="currentModel?.modelType === 'bio' ? 'bio' : 'general'"
            >
              {{ currentModel?.modelType === 'bio' ? '生信专用' : '通用' }}
            </span>
            <span v-for="cap in currentCaps" :key="cap" class="cap-tag" :class="cap">
              {{ CAPABILITY_LABELS[cap] }}
            </span>
            <n-icon size="14" class="model-chevron"><ChevronDownOutline /></n-icon>
          </div>
        </template>
        <div class="model-switcher-panel" role="listbox" aria-label="选择模型">
          <template v-if="groupedModels.fav.length">
            <div class="group-title">收藏</div>
            <div
              v-for="m in groupedModels.fav"
              :key="m.id"
              class="model-item omichub-selectable-card"
              :class="{ selected: m.id === chatSessionStore.selectedModelId, 'is-selected': m.id === chatSessionStore.selectedModelId }"
              role="option"
              tabindex="0"
              :aria-selected="m.id === chatSessionStore.selectedModelId"
              @click="handleSwitchModel(m.id)"
              @keydown.enter.prevent="handleSwitchModel(m.id)"
              @keydown.space.prevent="handleSwitchModel(m.id)"
            >
              <div class="model-meta">
                <div class="name">{{ m.name }}</div>
                <div class="desc">{{ m.description }}</div>
                <div v-if="m.capabilities?.length" class="caps">
                  <span
                    v-for="cap in topCapabilities(m.capabilities)"
                    :key="cap"
                    class="cap-tag"
                    :class="cap"
                  >{{ CAPABILITY_LABELS[cap] }}</span>
                </div>
              </div>
              <n-button text class="fav-btn active" @click="(e) => handleToggleFavorite(m.id, e)">
                <n-icon size="16"><Star /></n-icon>
              </n-button>
            </div>
          </template>

          <div class="group-title">通用模型</div>
          <div
            v-for="m in groupedModels.general"
            :key="m.id"
            class="model-item omichub-selectable-card"
            :class="{ selected: m.id === chatSessionStore.selectedModelId, 'is-selected': m.id === chatSessionStore.selectedModelId }"
            role="option"
            tabindex="0"
            :aria-selected="m.id === chatSessionStore.selectedModelId"
            @click="handleSwitchModel(m.id)"
            @keydown.enter.prevent="handleSwitchModel(m.id)"
            @keydown.space.prevent="handleSwitchModel(m.id)"
          >
            <div class="model-meta">
              <div class="name">{{ m.name }}</div>
              <div class="desc">{{ m.description }}</div>
              <div v-if="m.capabilities?.length" class="caps">
                <span
                  v-for="cap in topCapabilities(m.capabilities)"
                  :key="cap"
                  class="cap-tag"
                  :class="cap"
                >{{ CAPABILITY_LABELS[cap] }}</span>
              </div>
            </div>
            <n-button
              text
              class="fav-btn"
              :class="{ active: chatStore.isFavorite(m.id) }"
              @click="(e) => handleToggleFavorite(m.id, e)"
            >
              <n-icon size="16">
                <Star v-if="chatStore.isFavorite(m.id)" />
                <StarOutline v-else />
              </n-icon>
            </n-button>
          </div>

          <template v-if="groupedModels.bio.length">
            <div class="group-title">生信专用模型</div>
            <div
              v-for="m in groupedModels.bio"
              :key="m.id"
              class="model-item omichub-selectable-card"
              :class="{ selected: m.id === chatSessionStore.selectedModelId, 'is-selected': m.id === chatSessionStore.selectedModelId }"
              role="option"
              tabindex="0"
              :aria-selected="m.id === chatSessionStore.selectedModelId"
              @click="handleSwitchModel(m.id)"
              @keydown.enter.prevent="handleSwitchModel(m.id)"
              @keydown.space.prevent="handleSwitchModel(m.id)"
            >
              <div class="model-meta">
                <div class="name">{{ m.name }}</div>
                <div class="desc">{{ m.description }}</div>
              </div>
              <n-button text class="fav-btn active" @click="(e) => handleToggleFavorite(m.id, e)">
                <n-icon size="16"><Star /></n-icon>
              </n-button>
            </div>
          </template>
          <div v-if="!enhancedModels.length" class="group-title" style="padding: 16px; text-align: center">
            暂无可用模型，请先在系统设置中配置
          </div>
        </div>
      </n-popover>
    </div>

    <div class="nav-center">
      <div class="status-badge" :class="statusMeta.cls">
        <span class="status-dot" />
        <span>{{ statusMeta.text }}</span>
      </div>
    </div>

    <div class="nav-right">
      <n-select
        v-if="assistantOptions.length > 0"
        v-model:value="chatAssistantStore.currentAssistantId"
        :options="assistantOptions"
        size="small"
        style="width: 150px"
        placeholder="选择助手"
      />

      <n-popover trigger="click" placement="bottom-end" :width="320" style="padding: 0">
        <template #trigger>
          <n-button text class="action-btn" title="对话设置">
            <n-icon size="18"><SettingsOutline /></n-icon>
          </n-button>
        </template>
        <div class="conversation-settings-panel">
          <div class="panel-title">对话设置</div>
          <div class="setting-item">
            <div class="setting-label">温度 (Temperature)</div>
            <div class="setting-desc">越低越严谨，越高越具创造性</div>
            <div style="display: flex; align-items: center; gap: 8px">
              <n-slider
                :value="settings.temperature"
                :min="0"
                :max="1"
                :step="0.1"
                @update:value="handleTemperatureChange"
              />
              <span style="font-size: 13px; width: 32px; text-align: right">{{ settings.temperature.toFixed(1) }}</span>
            </div>
          </div>
          <div class="setting-item">
            <div class="setting-label">最大输出长度 (Tokens)</div>
            <div class="setting-desc">单次回复的最大 token 数</div>
            <div style="display: flex; align-items: center; gap: 8px">
              <n-slider
                :value="settings.maxTokens"
                :min="256"
                :max="8192"
                :step="256"
                @update:value="handleMaxTokensChange"
              />
              <span style="font-size: 13px; width: 48px; text-align: right">{{ settings.maxTokens }}</span>
            </div>
          </div>
          <div class="setting-item">
            <div class="setting-label">上下文窗口 (消息数)</div>
            <div class="setting-desc">携带的历史消息轮次</div>
            <div style="display: flex; align-items: center; gap: 8px">
              <n-slider
                :value="settings.contextLength"
                :min="2"
                :max="50"
                :step="2"
                @update:value="handleContextChange"
              />
              <span style="font-size: 13px; width: 32px; text-align: right">{{ settings.contextLength }}</span>
            </div>
          </div>
          <n-button block secondary size="small" @click="handleResetSettings">恢复默认</n-button>
        </div>
      </n-popover>

      <n-button text class="action-btn" title="分享" @click="handleShare">
        <n-icon size="18"><ShareOutline /></n-icon>
      </n-button>
    </div>
  </div>
</template>
