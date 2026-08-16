<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NAlert, NButton, NCollapse, NCollapseItem, NDrawer, NDrawerContent, NEmpty,
  NForm, NFormItem, NSelect, NSpace, NTag, useMessage,
} from 'naive-ui'
import { useAgentHubStore, CATEGORY_LABELS } from '@/stores/agentHub'
import { agentApi } from '@/api/agent'
import type { AgentTemplate, UserAgentCapabilities } from '@/types/agent'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [v: boolean] }>()

const store = useAgentHubStore()
const message = useMessage()
// 统一入口会话中展示"当前实际应答"的智能体（路由徽标优先），
// 否则入口 router 会掩盖实际专家的 skill/mcp 挂载（2026-08-04 修复）
const agent = computed<AgentTemplate | null>(() => store.effectiveAgent ?? null)
const drawerShown = computed(() => props.show && agent.value !== null)

const engineLabel = computed(() => agent.value?.model_engine || '')

const editing = ref(false)
const saving = ref(false)
const capabilities = ref<UserAgentCapabilities | null>(null)
const selection = ref({ model_id: '', mcp_ids: [] as string[], skill_ids: [] as string[] })

const configuredMcps = computed(() => (
  store.mcpsByIds(
    editing.value
      ? selection.value.mcp_ids
      : (capabilities.value?.is_customized ? capabilities.value.mcp_ids : agent.value?.mcp_ids || []),
  )
))
const configuredSkills = computed(() => (
  store.skillsByIds(
    editing.value
      ? selection.value.skill_ids
      : (capabilities.value?.is_customized ? capabilities.value.skill_ids : agent.value?.skill_ids || []),
  )
))
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
const selectedModelLabel = computed(() => {
  const modelId = editing.value
    ? selection.value.model_id
    : (capabilities.value?.model_id || agent.value?.model_id || '')
  return modelOptions.value.find((item) => item.value === modelId)?.label || engineLabel.value
})

async function loadCapabilities() {
  if (!agent.value) return
  try {
    const current = await agentApi.getCapabilities(agent.value.id)
    capabilities.value = current
    selection.value = {
      model_id: current.model_id || '',
      mcp_ids: [...current.mcp_ids],
      skill_ids: [...current.skill_ids],
    }
  } catch {
    message.error('加载个人能力配置失败')
  }
}

function beginEditing() {
  if (!agent.value) return
  selection.value = {
    model_id: capabilities.value?.model_id || agent.value.model_id || '',
    mcp_ids: [...(capabilities.value?.mcp_ids || agent.value.mcp_ids)],
    skill_ids: [...(capabilities.value?.skill_ids || agent.value.skill_ids)],
  }
  editing.value = true
}

async function saveCapabilities() {
  if (!agent.value) return
  saving.value = true
  try {
    capabilities.value = await agentApi.updateCapabilities(agent.value.id, selection.value)
    editing.value = false
    message.success('个人能力配置已保存，将在下一条消息中生效')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '保存个人能力配置失败')
  } finally {
    saving.value = false
  }
}

async function resetCapabilities() {
  if (!agent.value) return
  saving.value = true
  try {
    await agentApi.resetCapabilities(agent.value.id)
    capabilities.value = null
    selection.value = {
      model_id: agent.value.model_id || '',
      mcp_ids: [...agent.value.mcp_ids],
      skill_ids: [...agent.value.skill_ids],
    }
    editing.value = false
    message.success('已恢复管理员默认能力')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '恢复默认能力失败')
  } finally {
    saving.value = false
  }
}

watch(
  () => [props.show, agent.value?.id] as const,
  ([show]) => {
    if (!show) {
      editing.value = false
      return
    }
    if (!agent.value) {
      emit('update:show', false)
      return
    }
    void loadCapabilities()
  },
)
</script>

<template>
  <NDrawer :show="drawerShown" :width="440" placement="right" @update:show="(v) => emit('update:show', v)">
    <NDrawerContent v-if="agent" :title="`${agent.avatar} ${agent.name} · 智能体能力`" closable>
      <div class="cap-drawer">
        <div class="capability-actions">
          <NTag v-if="capabilities?.is_customized" size="small" round type="success">个人配置已启用</NTag>
          <span v-else class="default-note">使用管理员默认配置</span>
          <NSpace :size="8">
            <NButton v-if="!editing" size="small" type="primary" @click="beginEditing">配置我的能力</NButton>
            <NButton v-if="editing" size="small" @click="editing = false">取消</NButton>
            <NButton v-if="capabilities?.is_customized && !editing" size="small" :loading="saving" @click="resetCapabilities">恢复默认</NButton>
          </NSpace>
        </div>

        <NAlert v-if="editing" type="info" :show-icon="false" class="prompt-lock-note">
          可选择管理员已启用的模型、MCP 与 Skill。System Prompt 由管理员维护，不能修改。
        </NAlert>

        <NForm v-if="editing" label-placement="top" size="small" class="capability-form">
          <NFormItem label="模型">
            <NSelect v-model:value="selection.model_id" :options="modelOptions" filterable clearable placeholder="选择模型" />
          </NFormItem>
          <NFormItem label="MCP 服务">
            <NSelect v-model:value="selection.mcp_ids" :options="mcpOptions" multiple filterable clearable placeholder="选择可调用的 MCP" />
          </NFormItem>
          <NFormItem label="Skills">
            <NSelect v-model:value="selection.skill_ids" :options="skillOptions" multiple filterable clearable placeholder="选择可用 Skill" />
          </NFormItem>
          <div class="form-actions">
            <NButton type="primary" :loading="saving" @click="saveCapabilities">保存个人配置</NButton>
          </div>
        </NForm>

        <div class="meta-row">
          <span class="k">大模型引擎</span>
          <NSpace :size="4">
            <NTag size="small" round :bordered="false" type="info">{{ selectedModelLabel }}</NTag>
            <NTag v-if="agent.model_name && agent.model_name !== engineLabel" size="small" round :bordered="false">
              {{ agent.model_name }}
            </NTag>
          </NSpace>
        </div>
        <div class="meta-row">
          <span class="k">分类</span>
          <NTag size="small" round :bordered="false">{{ CATEGORY_LABELS[agent.category] }}</NTag>
        </div>

        <NCollapse :default-expanded-names="['mcp', 'skill', 'prompt']" arrow-placement="right">
          <NCollapseItem name="mcp" title="挂载的 MCP 服务">
            <template #header-extra>{{ configuredMcps.length }} 个</template>
            <NEmpty v-if="!configuredMcps.length" description="未挂载 MCP" size="small" />
            <div v-else class="mcp-list">
              <div v-for="m in configuredMcps" :key="m.id" class="mcp-block">
                <div class="mcp-head">
                  <NTag size="tiny" round :bordered="false" :type="m.status === 'online' ? 'success' : 'default'">
                    {{ m.status === 'online' ? '🟢' : '🔴' }}
                  </NTag>
                  <span class="mcp-name">{{ m.name }}</span>
                </div>
                <div class="mcp-desc">{{ m.description }}</div>
                <NSpace size="small" style="margin-top: 6px;">
                  <NTag v-for="t in m.tools" :key="t.name" size="tiny" :bordered="false">{{ t.name }}</NTag>
                </NSpace>
              </div>
            </div>
          </NCollapseItem>

          <NCollapseItem name="skill" title="挂载的技能">
            <template #header-extra>{{ configuredSkills.length }} 个</template>
            <NEmpty v-if="!configuredSkills.length" description="未挂载技能" size="small" />
            <NSpace v-else size="small">
              <NTag v-for="s in configuredSkills" :key="s.id" size="small" round type="success">
                {{ s.icon }} {{ s.name }}
              </NTag>
            </NSpace>
          </NCollapseItem>

          <NCollapseItem name="prompt" title="系统设定 (System Prompt)">
            <div class="prompt-box">{{ agent.system_prompt }}</div>
          </NCollapseItem>
        </NCollapse>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.cap-drawer { display: flex; flex-direction: column; gap: 12px; }
.capability-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.default-note { font-size: 12px; color: var(--neutral-text-3, #888); }
.prompt-lock-note { line-height: 1.6; }
.capability-form { padding: 12px; border: 1px solid var(--neutral-border, rgba(0, 0, 0, .08)); border-radius: 10px; background: var(--neutral-hover, rgba(0, 0, 0, .03)); }
.form-actions { display: flex; justify-content: flex-end; }
.meta-row { display: flex; align-items: center; justify-content: space-between; }
.meta-row .k { font-size: 13px; color: var(--neutral-text-3, #888); }
.mcp-list { display: flex; flex-direction: column; gap: 12px; }
.mcp-block { background: var(--neutral-hover, rgba(0,0,0,.03)); border-radius: 8px; padding: 10px 12px; }
.mcp-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.mcp-name { font-weight: 600; font-size: 13px; }
.mcp-desc { font-size: 12px; color: var(--neutral-text-3, #888); }
.prompt-box { font-size: 12px; color: var(--neutral-text-2, #555); white-space: pre-wrap; line-height: 1.6; background: var(--neutral-hover, rgba(0,0,0,.03)); padding: 10px 12px; border-radius: 8px; }
</style>
