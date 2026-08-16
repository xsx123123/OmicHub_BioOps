<script setup lang="ts">
import { reactive, watch } from 'vue'
import {
  NAlert,
  NButton,
  NDivider,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NSpace,
  NSwitch,
  useMessage,
} from 'naive-ui'
import {
  DEFAULT_AGENT_TEAMS_PREFERENCES,
  type AgentTeamsPreferences,
  useAgentTeamsPreferencesStore,
} from '@/stores/agentTeamsPreferences'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()
const message = useMessage()
const store = useAgentTeamsPreferencesStore()
const draft = reactive<AgentTeamsPreferences>({ ...DEFAULT_AGENT_TEAMS_PREFERENCES })

const styleOptions = [
  { label: '正式专业', value: 'professional' },
  { label: '亲切友好', value: 'friendly' },
  { label: '极简高效', value: 'concise' },
]
const autonomyOptions = [
  { label: '自主模式', value: 'autonomous' },
  { label: '谨慎模式', value: 'cautious' },
]
const languageOptions = [
  { label: '中文', value: 'zh-CN' },
  { label: 'English', value: 'en-US' },
]

function syncDraft() {
  Object.assign(draft, store.settings)
}

watch(() => props.show, (show) => { if (show) syncDraft() }, { immediate: true })

async function saveSettings() {
  try {
    await store.save({ ...draft, managerName: draft.managerName.trim() || 'Manager' })
    message.success('团队协作室设置已保存，将应用到所有协作房间。')
    emit('update:show', false)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || error?.message || '保存设置失败。')
  }
}

function restoreDefaults() {
  Object.assign(draft, DEFAULT_AGENT_TEAMS_PREFERENCES)
}
</script>

<template>
  <NDrawer :show="show" :width="480" placement="right" @update:show="emit('update:show', $event)">
    <NDrawerContent title="团队协作室设置" closable :native-scrollbar="false">
      <NAlert type="info" :show-icon="true" class="settings-note">
        这些偏好应用于你的所有协作房间。自主模式不会跳过真实计算、写入、费用或人工审批等安全闸门。
      </NAlert>

      <NForm label-placement="top" class="settings-form">
        <h3>Manager 回复偏好</h3>
        <NFormItem label="Manager 称呼">
          <NInput v-model:value="draft.managerName" maxlength="24" show-count placeholder="例如：Manager、小 O、管家" />
        </NFormItem>
        <NFormItem label="沟通风格">
          <NSelect v-model:value="draft.communicationStyle" :options="styleOptions" />
        </NFormItem>
        <NFormItem label="执行方式">
          <NSelect v-model:value="draft.autonomy" :options="autonomyOptions" />
        </NFormItem>
        <NFormItem label="沟通语言">
          <NSelect v-model:value="draft.language" :options="languageOptions" />
        </NFormItem>

        <NDivider />
        <h3>协作室行为</h3>
        <div class="setting-row">
          <div><strong>新房间初始化引导</strong><span>创建首个房间时询问称呼、风格和语言。</span></div>
          <NSwitch v-model:value="draft.showOnboarding" aria-label="新房间初始化引导" />
        </div>
        <div class="setting-row">
          <div><strong>自动拆分新任务</strong><span>在旧 Case 中识别到不相关的文件分析任务时，自动创建独立 Case。</span></div>
          <NSwitch v-model:value="draft.autoSplitNewTasks" aria-label="自动拆分新任务" />
        </div>
        <div class="setting-row">
          <div><strong>默认展开底层事件</strong><span>默认显示 Matrix、工具调用和任务状态等技术事件。</span></div>
          <NSwitch v-model:value="draft.expandTechnicalEvents" aria-label="默认展开底层事件" />
        </div>
      </NForm>

      <template #footer>
        <NSpace justify="space-between" class="settings-footer">
          <NButton secondary :disabled="store.saving" @click="restoreDefaults">恢复默认</NButton>
          <NSpace>
            <NButton :disabled="store.saving" @click="emit('update:show', false)">取消</NButton>
            <NButton type="primary" :loading="store.saving" @click="saveSettings">保存设置</NButton>
          </NSpace>
        </NSpace>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.settings-note { margin-bottom: var(--space-lg); }
.settings-form h3 { margin: 0 0 var(--space-md); color: var(--neutral-text-1); font-size: var(--font-card-title-size); }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-lg); padding: var(--space-md) 0; border-bottom: 1px solid var(--neutral-border); }
.setting-row > div { display: grid; gap: var(--space-xs); }
.setting-row strong { color: var(--neutral-text-1); font-size: var(--font-small-size); }
.setting-row span { color: var(--neutral-text-3); font-size: var(--font-caption-size); line-height: var(--font-caption-height); }
.settings-footer { width: 100%; }
</style>
