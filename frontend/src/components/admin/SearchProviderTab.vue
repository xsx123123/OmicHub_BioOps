<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { NButton, NEmpty, NIcon, NInput, NInputNumber, NSelect, NSwitch, NTag, useMessage } from 'naive-ui'
import { CheckmarkCircleOutline, CloudOutline, SearchOutline } from '@vicons/ionicons5'
import { searchProviderApi, type SearchProvider } from '@/api/admin/searchProvider'

const message = useMessage()
const providers = ref<SearchProvider[]>([])
const selectedId = ref('tavily')
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const form = reactive({ api_key: '', base_url: '', is_enabled: false, maxResults: 5, searchDepth: 'basic', timeout_seconds: 10 })

const apiProviders = computed(() => providers.value.filter((provider) => !provider.is_local))
const localProviders = computed(() => providers.value.filter((provider) => provider.is_local))
const selected = computed(() => providers.value.find((provider) => provider.id === selectedId.value) || null)
const needsKey = computed(() => selected.value?.provider_type === 'api')
const isLocalPlaceholder = computed(() => Boolean(selected.value?.is_local))

function fillForm(provider: SearchProvider | null) {
  if (!provider) return
  form.api_key = provider.api_key
  form.base_url = provider.base_url
  form.is_enabled = provider.is_enabled
  form.maxResults = provider.params?.maxResults || 5
  form.searchDepth = provider.params?.searchDepth || 'basic'
  form.timeout_seconds = provider.timeout_seconds || 10
}

async function load() {
  loading.value = true
  try {
    providers.value = await searchProviderApi.list()
    if (!providers.value.some((provider) => provider.id === selectedId.value)) selectedId.value = providers.value[0]?.id || ''
    fillForm(selected.value)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '加载联网搜索服务商失败')
  } finally {
    loading.value = false
  }
}

watch(selected, fillForm)

async function save() {
  if (!selected.value) return
  if (isLocalPlaceholder.value) return
  saving.value = true
  try {
    const updated = await searchProviderApi.update(selected.value.id, {
      api_key: form.api_key,
      base_url: form.base_url,
      is_enabled: form.is_enabled,
      params: { maxResults: form.maxResults, searchDepth: form.searchDepth },
      timeout_seconds: form.timeout_seconds,
    })
    providers.value = providers.value.map((provider) => provider.id === updated.id ? updated : provider)
    fillForm(updated)
    message.success('联网搜索配置已保存')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  if (!selected.value) return
  if (isLocalPlaceholder.value) return
  await save()
  testing.value = true
  try {
    const result = await searchProviderApi.test(selected.value.id)
    if (result.success) message.success(`检测成功，返回 ${result.result_count} 条结果`)
    else message.error(result.message || '检测失败')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '检测失败')
  } finally {
    testing.value = false
  }
}

async function setDefault() {
  if (!selected.value) return
  if (isLocalPlaceholder.value) return
  try {
    const updated = await searchProviderApi.setDefault(selected.value.id)
    providers.value = providers.value.map((provider) => ({ ...provider, is_default: provider.id === updated.id }))
    message.success(`已设「${updated.name}」为默认搜索源`)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '设置默认搜索源失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="search-provider-tab-page" :aria-busy="loading">
    <div class="tab-header">
      <span class="tab-hint">选择搜索服务商并配置密钥与参数，设为默认后 AI 助手将优先使用该来源。</span>
    </div>
    <div class="search-provider-tab">
    <aside class="provider-list" aria-label="联网搜索服务商">
      <div class="provider-group-title">API 服务商</div>
      <button v-for="provider in apiProviders" :key="provider.id" class="provider-item" :class="{ active: provider.id === selectedId }" @click="selectedId = provider.id">
        <NIcon :component="CloudOutline" /><span>{{ provider.name }}</span>
        <NTag v-if="provider.is_default" size="tiny" type="success" :bordered="false">默认</NTag>
      </button>
      <div class="provider-group-title">本地搜索</div>
      <button v-for="provider in localProviders" :key="provider.id" class="provider-item" :class="{ active: provider.id === selectedId }" @click="selectedId = provider.id">
        <NIcon :component="SearchOutline" /><span>{{ provider.name }}</span><span class="unstable">免费 · 不稳定</span>
      </button>
    </aside>

    <section v-if="selected" class="provider-panel">
      <div class="panel-heading">
        <div><h3>{{ selected.name }}</h3><p>{{ isLocalPlaceholder ? '本地 HTML 抓取将于后续阶段开放，目前仅展示路线图占位。' : '配置服务端密钥与搜索参数；密钥仅以掩码回显。' }}</p></div>
        <NButton secondary type="primary" :disabled="!form.is_enabled || isLocalPlaceholder" @click="setDefault"><template #icon><NIcon :component="CheckmarkCircleOutline" /></template>设为默认</NButton>
      </div>
      <template v-if="!isLocalPlaceholder">
        <div class="field-row"><label>启用服务</label><NSwitch v-model:value="form.is_enabled" /></div>
        <div v-if="needsKey" class="field"><label>API 密钥</label><div class="field-control"><NInput v-model:value="form.api_key" type="password" show-password-on="click" placeholder="保存后仅显示掩码" /><NButton :loading="testing" @click="testConnection">检测</NButton></div><a v-if="selected.key_url" :href="selected.key_url" target="_blank" rel="noopener noreferrer">点击这里获取密钥</a></div>
        <div class="field"><label>API 地址</label><NInput v-model:value="form.base_url" :placeholder="needsKey ? '请输入 API 地址' : '请输入 SearXNG 实例地址'" /></div>
        <div class="form-grid"><div class="field"><label>结果条数</label><NInputNumber v-model:value="form.maxResults" :min="1" :max="20" /></div><div class="field"><label>搜索深度</label><NSelect v-model:value="form.searchDepth" :options="[{ label: '基础', value: 'basic' }, { label: '深入', value: 'advanced' }]" /></div></div>
        <div class="panel-actions"><NButton type="primary" :loading="saving" @click="save">保存配置</NButton></div>
      </template>
    </section>
    <NEmpty v-else description="选择左侧服务商并填入 API 密钥" />
    </div>
  </div>
</template>

<style scoped>
.tab-header { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:14px; }
.tab-hint { font-size:12px; color:var(--neutral-text-3); }
.search-provider-tab { display:grid; grid-template-columns:minmax(190px, .32fr) minmax(0, 1fr); min-height:440px; border:1px solid var(--neutral-border); border-radius:12px; overflow:hidden; background:var(--neutral-card); }
.provider-list { padding:12px; border-right:1px solid var(--neutral-border); background:var(--neutral-bg); }
.provider-group-title { margin:10px 8px 6px; font-size:12px; color:var(--neutral-text-3); font-weight:600; }
.provider-item { width:100%; min-height:36px; display:flex; align-items:center; gap:8px; padding:0 8px; border:0; border-radius:7px; background:transparent; color:var(--neutral-text-2); text-align:left; cursor:pointer; }
.provider-item:hover,.provider-item.active { background:var(--arco-primary-light); color:var(--arco-primary); }.provider-item span:nth-child(2){flex:1}.unstable{font-size:11px;color:var(--neutral-text-3)}
.provider-panel { padding:24px; max-width:760px; }.panel-heading{display:flex;justify-content:space-between;gap:16px;margin-bottom:20px}.panel-heading h3{margin:0;color:var(--neutral-text-1)}.panel-heading p{margin:6px 0 0;font-size:13px;color:var(--neutral-text-2)}
.field,.field-row{margin:16px 0}.field label,.field-row label{display:block;margin-bottom:7px;font-size:13px;font-weight:500;color:var(--neutral-text-1)}.field-row{display:flex;align-items:center;justify-content:space-between}.field-row label{margin:0}.field-control{display:flex;gap:8px}.field-control :deep(.n-input){flex:1}.field a{display:inline-block;margin-top:6px;font-size:12px;color:var(--arco-primary)}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.panel-actions{display:flex;justify-content:flex-end;margin-top:24px}
@media (max-width: 760px){.search-provider-tab{grid-template-columns:1fr}.provider-list{border-right:0;border-bottom:1px solid var(--neutral-border)}.provider-item{display:inline-flex;width:auto;margin-right:4px}.provider-group-title{margin-left:0}.provider-panel{padding:18px}.form-grid{grid-template-columns:1fr}.panel-heading{align-items:flex-start;flex-direction:column}}
</style>
