<script setup lang="ts">
import apiClient from '@/api/client'
import type { AIProviderConfig } from '@/types'
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSpace,
  NSwitch,
  NSelect,
  useMessage,
  NTag,
} from 'naive-ui'
import { h, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'

withDefaults(defineProps<{ embedded?: boolean }>(), {
  embedded: false,
})

const message = useMessage()

const configs = ref<AIProviderConfig[]>([])
const loading = ref(false)
const showEdit = ref(false)
const testing = ref(false)

const providerOptions = [
  { label: 'OpenAI 兼容', value: 'openai_compatible' },
  { label: 'Kimi (Moonshot)', value: 'kimi' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
  { label: 'Azure OpenAI', value: 'azure' },
  { label: 'Ollama', value: 'ollama' },
  { label: 'vLLM', value: 'vllm' },
]

const editForm = ref<Partial<AIProviderConfig> & { api_key?: string }>({
  name: '',
  provider_type: 'openai_compatible',
  model: '',
  base_url: '',
  api_key: '',
  temperature: 0.7,
  max_tokens: 2048,
  top_p: 1.0,
  timeout: 120,
  is_active: true,
  extra_params: {},
})

const columns = [
  {
    title: '默认',
    key: 'is_default',
    width: 80,
    render: (row: AIProviderConfig) =>
      row.is_default ? h(NTag, { type: 'success', size: 'small' }, { default: () => '默认' }) : null,
  },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  { title: 'Provider', key: 'provider_type', width: 140 },
  { title: '模型', key: 'model', ellipsis: { tooltip: true } },
  { title: 'Base URL', key: 'base_url', ellipsis: { tooltip: true } },
  { title: '温度', key: 'temperature', width: 80 },
  { title: 'Max Tokens', key: 'max_tokens', width: 110 },
  {
    title: '状态',
    key: 'is_active',
    width: 80,
    render: (row: AIProviderConfig) => (row.is_active ? '启用' : '停用'),
  },
  {
    title: '操作',
    key: 'actions',
    width: 280,
    render: (row: AIProviderConfig) =>
      h(NSpace, {}, {
        default: () => [
          h(NButton, { size: 'small', onClick: () => openEdit(row) }, { default: () => '编辑' }),
          h(
            NButton,
            { size: 'small', type: 'primary', onClick: () => setDefault(row.id) },
            { default: () => '设为默认' }
          ),
          h(NButton, { size: 'small', onClick: () => testConfig(row.id) }, { default: () => '测试' }),
          h(NButton, { size: 'small', type: 'error', onClick: () => delConfig(row.id) }, { default: () => '删除' }),
        ],
      }),
  },
]

async function fetchConfigs() {
  loading.value = true
  try {
    const res = await apiClient.get<AIProviderConfig[]>('/admin/ai-providers')
    configs.value = res.data
  } finally {
    loading.value = false
  }
}

function openEdit(row?: AIProviderConfig) {
  if (row) {
    // 回显后端脱敏值（已配置为 "********"，未配置为空）；
    // 用户不改则原样回传，由后端判定保留原值；改了则回传新 Key。
    editForm.value = { ...row, api_key: row.api_key ?? '' }
  } else {
    editForm.value = {
      name: '',
      provider_type: 'openai_compatible',
      model: '',
      base_url: '',
      api_key: '',
      temperature: 0.7,
      max_tokens: 2048,
      top_p: 1.0,
      timeout: 120,
      is_active: true,
      extra_params: {},
    }
  }
  showEdit.value = true
}

async function saveConfig() {
  const data = { ...editForm.value }
  try {
    if (data.id) {
      await apiClient.put(`/admin/ai-providers/${data.id}`, data)
      message.success('更新成功')
    } else {
      await apiClient.post('/admin/ai-providers', data)
      message.success('创建成功')
    }
    showEdit.value = false
    await fetchConfigs()
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    const status = error?.response?.status
    if (error?.response?.status === 401) {
      message.error(detail || '当前登录态已失效，请重新登录后再保存')
    } else if (status === 403) {
      message.error(detail || '当前账号没有保存该配置的权限')
    } else {
      message.error(detail || '保存失败')
    }
  }
}

async function delConfig(id: string) {
  // 被会话/Agent 引用时后端会降级为停用（软删除），按返回的 message 提示
  const res = await apiClient.delete(`/admin/ai-providers/${id}`)
  const msg = (res.data as { message?: string; soft_deleted?: boolean })?.message || '已删除'
  message.success(msg)
  await fetchConfigs()
}

async function setDefault(id: string) {
  await apiClient.post(`/admin/ai-providers/${id}/set-default`)
  message.success('已设为默认')
  await fetchConfigs()
}

async function testConfig(id: string) {
  testing.value = true
  try {
    const res = await apiClient.post(`/admin/ai-providers/${id}/test`, { message: '你好' })
    if (res.data.success) {
      message.success(`连接成功：${res.data.response.slice(0, 60)}...`)
    } else {
      message.error(`连接失败：${res.data.error}`)
    }
  } finally {
    testing.value = false
  }
}

onMounted(fetchConfigs)
</script>

<template>
  <div class="page-container" :class="{ 'page-container--embedded': embedded }">
    <PageHeader v-if="!embedded" title="AI 模型配置" subtitle="管理应用可用的模型 Provider 与调用参数" />
    <NSpace vertical :size="24">
      <NCard title="Provider 配置" :bordered="false" class="arco-card">
        <template #header-extra>
          <NButton type="primary" @click="openEdit()">新建配置</NButton>
        </template>
        <NDataTable
          :columns="columns"
          :data="configs"
          :row-key="(row) => row.id"
          :loading="loading"
          :pagination="{ pageSize: 20 }"
          :bordered="false"
          size="small"
        />
      </NCard>
    </NSpace>

    <NModal v-model:show="showEdit" :title="editForm.id ? '编辑配置' : '新建配置'" preset="card" style="width: 600px">
      <NForm label-placement="left" label-width="120">
        <NFormItem label="名称">
          <NInput v-model:value="editForm.name" placeholder="如：生产 Kimi" />
        </NFormItem>
        <NFormItem label="Provider">
          <NSelect v-model:value="editForm.provider_type" :options="providerOptions" />
        </NFormItem>
        <NFormItem label="模型">
          <NInput v-model:value="editForm.model" placeholder="如：moonshot-v1-8k" />
        </NFormItem>
        <NFormItem label="Base URL">
          <NInput v-model:value="editForm.base_url" placeholder="如：https://api.moonshot.cn/v1" />
        </NFormItem>
        <NFormItem label="API Key">
          <NInput
            v-model:value="editForm.api_key"
            type="password"
            placeholder="留空则保留原密钥"
            show-password-on="mousedown"
          />
        </NFormItem>
        <NFormItem label="Temperature">
          <NInputNumber v-model:value="editForm.temperature" :min="0" :max="2" :step="0.1" />
        </NFormItem>
        <NFormItem label="Max Tokens">
          <NInputNumber v-model:value="editForm.max_tokens" :min="1" :step="1" />
        </NFormItem>
        <NFormItem label="Top P">
          <NInputNumber v-model:value="editForm.top_p" :min="0" :max="1" :step="0.1" />
        </NFormItem>
        <NFormItem label="Timeout">
          <NInputNumber v-model:value="editForm.timeout" :min="1" :step="1" />
        </NFormItem>
        <NFormItem label="启用">
          <NSwitch v-model:value="editForm.is_active" />
        </NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="showEdit = false">取消</NButton>
          <NButton type="primary" @click="saveConfig">保存</NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.page-container {
  padding: 24px;
  min-height: 100%;
  background: var(--neutral-bg);
}
.page-container--embedded {
  padding: 0;
  background: transparent;
}
.page-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0 0 24px;
}
</style>
