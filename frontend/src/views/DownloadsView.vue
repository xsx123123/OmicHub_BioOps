<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NSelect, NTabs, NTabPane, NIcon, NButton, NPopconfirm, NSpin, useMessage,
} from 'naive-ui'
import {
  LibraryOutline, CloudDownloadOutline, ServerOutline, LinkOutline,
  InformationCircleOutline, ChevronDownOutline, DownloadOutline, RefreshOutline,
} from '@vicons/ionicons5'
import apiClient from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'

type SourceTab = 'sra' | 'cloud-drive' | 'cloud-storage' | 'direct-link'

interface DownloadTask {
  id: string
  name: string
  source: string
  accession: string
  status: 'running' | 'queued' | 'success' | 'failed' | 'pending' | 'cancelled'
  progress: number
  size: string
  speed: string
  createdAt: string
}

interface TaskResponse {
  id: string
  name: string
  flow_id: string
  status: string
  progress: number
  parameters: Record<string, unknown>
  created_at: string
}

interface TaskListResponse {
  items: TaskResponse[]
  total: number
}

const router = useRouter()
const message = useMessage()

const activeTab = ref<SourceTab>('sra')
const submitting = ref(false)
const loadingTasks = ref(false)

// ── SRA 基础表单 ──
const sraAccession = ref('')
const sraMethod = ref<'aws' | 'aspera' | 'ftp'>('aws')
const targetDirectory = ref('')

// ── 高级选项：仅 4 个正则过滤字段 ──
const advancedOpen = ref(false)
const directAdvancedOpen = ref(false)
const includeSample = ref('')
const excludeSample = ref('')
const includeRun = ref('')
const excludeRun = ref('')

// ── 云盘表单 ──
const driveProvider = ref<'baidu' | '123'>('baidu')
const driveLink = ref('')
const driveCode = ref('')

// ── 云存储表单 ──
const storageProvider = ref<'aliyun' | 'volc' | 'huawei'>('aliyun')
const storageUri = ref('')
const storageRecursive = ref(true)

// ── 直链 / FTP 表单 ──
const directLinks = ref('')
const directThreads = ref(4)
const directOverwritePolicy = ref<'auto_rename' | 'overwrite' | 'skip'>('auto_rename')
const directRecursive = ref(false)

// ── 任务列表状态筛选 ──
const statusFilter = ref<'all' | DownloadTask['status']>('all')

const tabDescriptions: Record<SourceTab, string> = {
  'sra': '输入 NCBI / EBI 登录号（如 PRJNA、SRR），支持 AWS S3 / Aspera 高并发节点拉取原始测序数据，完成后自动入库。',
  'cloud-drive': '支持解析百度网盘、123 云盘分享链接，云端内网极速提取交接数据、不消耗本地带宽，完成后自动入库。',
  'cloud-storage': '支持通过云厂商内网（阿里云 / 火山 / 华为）对象存储 CLI 拉取数据，完成后自动入库。',
  'direct-link': '支持 HTTP / HTTPS / FTP 直链批量下载，断点续传、并发加速，完成后自动入库。',
}

const statusConfig: Record<string, { label: string; badge: string; icon: string }> = {
  success: { label: '已完成', badge: 'download-status--success', icon: 'check' },
  running: { label: '下载中', badge: 'download-status--running', icon: 'loading' },
  failed:  { label: '失败', badge: 'download-status--failed', icon: 'x' },
  cancelled: { label: '已取消', badge: 'download-status--neutral', icon: 'x' },
  queued:  { label: '排队中', badge: 'download-status--neutral', icon: 'clock' },
  pending: { label: '等待中', badge: 'download-status--neutral', icon: 'clock' },
}

function scfg(status: string) {
  return statusConfig[status] || statusConfig.pending
}

function pct(task: DownloadTask) {
  return Math.round(task.progress * 100)
}

const tasks = ref<DownloadTask[]>([])

const stats = computed(() => {
  const t = tasks.value
  return {
    total: t.length,
    running: t.filter(x => x.status === 'running').length,
    success: t.filter(x => x.status === 'success').length,
    failed: t.filter(x => x.status === 'failed').length,
  }
})

const filteredTasks = computed(() => {
  if (statusFilter.value === 'all') return tasks.value
  return tasks.value.filter(t => t.status === statusFilter.value)
})

const sraMethodOptions = [
  { label: 'AWS S3（推荐，最快）', value: 'aws' },
  { label: 'Aspera 高速', value: 'aspera' },
  { label: 'FTP 标准下载', value: 'ftp' },
]

const targetDirectoryOptions = [
  { label: '根目录（默认）', value: '' },
  { label: 'raw-data', value: 'raw-data' },
  { label: 'projects/rna-seq', value: 'projects/rna-seq' },
  { label: 'projects/variant', value: 'projects/variant' },
]

const storageProviderOptions = [
  { label: '阿里云 OSS', value: 'aliyun' },
  { label: '火山引擎 TOS', value: 'volc' },
  { label: '华为云 OBS', value: 'huawei' },
]

const threadOptions = [
  { label: '1 线程', value: 1 },
  { label: '4 线程（推荐）', value: 4 },
  { label: '8 线程', value: 8 },
  { label: '16 线程', value: 16 },
]

const overwritePolicyOptions = [
  { label: '自动重命名', value: 'auto_rename' },
  { label: '强制覆盖', value: 'overwrite' },
  { label: '跳过', value: 'skip' },
]

const statusFilterOptions = [
  { label: '全部状态', value: 'all' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'success' },
  { label: '失败', value: 'failed' },
]

function formatTime(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function normalizeStatus(status: string): DownloadTask['status'] {
  if (status === 'running' || status === 'queued' || status === 'success' || status === 'failed' || status === 'cancelled') {
    return status
  }
  return 'pending'
}

function mapTask(task: TaskResponse): DownloadTask {
  const params = task.parameters || {}
  const source = params.source === 'cloud_storage' ? '云存储' : 'SRA'
  const accession = String(params.object_uri || params.accession || '-')
  return {
    id: task.id,
    name: task.name,
    source,
    accession,
    status: normalizeStatus(task.status),
    progress: Number(task.progress || 0),
    size: '-',
    speed: '-',
    createdAt: task.created_at,
  }
}

async function fetchDownloads() {
  loadingTasks.value = true
  try {
    const res = await apiClient.get<TaskListResponse>('/downloads')
    tasks.value = res.data.items.map(mapTask)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载下载任务失败')
  } finally {
    loadingTasks.value = false
  }
}

async function toggleAdvanced() {
  advancedOpen.value = !advancedOpen.value
  if (advancedOpen.value) {
    await nextTick()
    const el = document.getElementById('advanced-panel-bottom')
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
}

function dedupLinks() {
  directLinks.value = [...new Set(
    directLinks.value.split(/\r?\n|,/).map(link => link.trim()).filter(Boolean),
  )].join('\n')
}

async function handleSubmit() {
  if (activeTab.value === 'cloud-drive') {
    message.warning('云盘极速提取尚未接入后端，当前先支持公共数据库与云存储直拉')
    return
  }

  let payload: Record<string, unknown>
  if (activeTab.value === 'direct-link') {
    const links = directLinks.value.split(/\r?\n|,/).map(link => link.trim()).filter(Boolean)
    if (!links.length) { message.warning('请输入至少一个 HTTP / HTTPS / FTP 下载链接'); return }
    const invalid = links.find(link => !/^(https?|ftp):\/\/[^\s]+$/i.test(link))
    if (invalid) { message.warning(`链接格式不正确：${invalid}`); return }
    payload = {
      source: 'direct_link',
      links: [...new Set(links)],
      download_threads: directThreads.value,
      overwrite_policy: directOverwritePolicy.value,
      recursive: directRecursive.value,
      target_directory: targetDirectory.value,
    }
  } else if (activeTab.value === 'sra') {
    if (!sraAccession.value.trim()) { message.warning('请输入登录号'); return }
    payload = {
      source: 'sra',
      accession: sraAccession.value.trim(),
      download_method: sraMethod.value,
      target_directory: targetDirectory.value,
    }
  } else {
    if (!storageUri.value.trim()) { message.warning('请输入对象 URI'); return }
    payload = {
      source: 'cloud_storage',
      cloud_provider: storageProvider.value,
      object_uri: storageUri.value.trim(),
      recursive: storageRecursive.value,
      target_directory: targetDirectory.value,
    }
  }

  submitting.value = true
  try {
    const res = await apiClient.post<TaskResponse>('/downloads', payload)
    message.success('已提交下载任务')
    if (activeTab.value === 'sra') sraAccession.value = ''
    if (activeTab.value === 'cloud-storage') storageUri.value = ''
    if (activeTab.value === 'direct-link') directLinks.value = ''
    await fetchDownloads()
    router.push(`/tasks/${res.data.id}`)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '提交下载任务失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(task: DownloadTask) {
  try {
    await apiClient.delete(`/tasks/${task.id}`)
    message.success(`已删除「${task.name}」`)
    await fetchDownloads()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '删除失败，请稍后重试')
  }
}

onMounted(fetchDownloads)
</script>

<template>
  <div class="page-container downloads-page">
    <div class="downloads-content">
      <!-- ═══ 页面标题区 ═══ -->
      <PageHeader
        title="数据下载与聚合"
        subtitle="从 NCBI/EBI 公共数据库、网盘或云存储拉取测序数据，下载完成后自动入库"
      />

      <!-- ═══ 来源切换 Tabs（平台统一下划线式）═══ -->
      <NTabs v-model:value="activeTab" type="line" class="source-tabs">
        <!-- ── 公共数据库（SRA）── -->
        <NTabPane name="sra">
          <template #tab>
            <span class="source-tab"><NIcon :size="16"><LibraryOutline /></NIcon>公共数据库</span>
          </template>

          <div class="source-tip">
            <NIcon :size="16" class="source-tip__icon"><InformationCircleOutline /></NIcon>
            <span>{{ tabDescriptions['sra'] }}</span>
          </div>

          <div class="form-card">
            <div class="field">
              <label class="field-label">登录号 <span class="req">*</span></label>
              <textarea
                v-model="sraAccession"
                rows="1"
                placeholder="PRJNA1251654 或 SRRxxxxxx，多个用逗号或换行分隔"
                class="text-input text-input--textarea"
              />
              <p class="field-help">支持 Project / Sample / Run 级登录号，多个用逗号或换行分隔。</p>
            </div>

            <div class="field">
              <label class="field-label">下载方式</label>
              <NSelect v-model:value="sraMethod" :options="sraMethodOptions" class="field-select" />
            </div>

            <div class="field">
              <label class="field-label">下载到</label>
              <NSelect v-model:value="targetDirectory" :options="targetDirectoryOptions" class="field-select" />
            </div>

            <!-- 高级选项折叠条 -->
            <div class="field">
              <button
                type="button"
                class="adv-toggle"
                :class="{ 'is-open': advancedOpen }"
                :aria-expanded="advancedOpen"
                @click="toggleAdvanced"
              >
                <span class="adv-toggle__title">高级选项：样本与 Run 过滤</span>
                <span class="adv-toggle__desc">{{ advancedOpen ? '收起' : '支持正则匹配，留空不过滤' }}</span>
                <NIcon :size="16" class="adv-toggle__chevron" :class="{ 'is-open': advancedOpen }">
                  <ChevronDownOutline />
                </NIcon>
              </button>
              <div v-if="advancedOpen" id="advanced-panel-bottom" class="adv-panel">
                <div class="filter-grid">
                  <div class="filter-field">
                    <label class="field-label"><span class="filter-badge filter-badge--include">+</span>包含样本（Include）</label>
                    <input v-model="includeSample" type="text" placeholder="如：^SAMN.*" class="text-input" />
                    <span class="field-help">正则匹配样本 ID，留空不过滤</span>
                  </div>
                  <div class="filter-field">
                    <label class="field-label"><span class="filter-badge filter-badge--exclude">−</span>排除样本（Exclude）</label>
                    <input v-model="excludeSample" type="text" placeholder="如：.control." class="text-input" />
                    <span class="field-help">匹配到的样本将被跳过</span>
                  </div>
                  <div class="filter-field">
                    <label class="field-label"><span class="filter-badge filter-badge--include">+</span>包含 Run（Include）</label>
                    <input v-model="includeRun" type="text" placeholder="如：SRR123.*" class="text-input" />
                    <span class="field-help">正则匹配 Run 编号</span>
                  </div>
                  <div class="filter-field">
                    <label class="field-label"><span class="filter-badge filter-badge--exclude">−</span>排除 Run（Exclude）</label>
                    <input v-model="excludeRun" type="text" placeholder="如：.test." class="text-input" />
                    <span class="field-help">匹配到的 Run 将被跳过</span>
                  </div>
                </div>
                <p class="adv-panel__note">支持正则表达式过滤，留空表示不过滤。多个模式用逗号分隔。</p>
              </div>
            </div>

            <div class="form-actions">
              <NButton type="primary" :loading="submitting" @click="handleSubmit">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                提交拉取任务
              </NButton>
              <NButton secondary :disabled="submitting">Dry Run</NButton>
            </div>
          </div>
        </NTabPane>

        <!-- ── 云盘极速提取 ── -->
        <NTabPane name="cloud-drive">
          <template #tab>
            <span class="source-tab"><NIcon :size="16"><CloudDownloadOutline /></NIcon>云盘极速提取</span>
          </template>

          <div class="source-tip">
            <NIcon :size="16" class="source-tip__icon"><InformationCircleOutline /></NIcon>
            <span>{{ tabDescriptions['cloud-drive'] }}</span>
          </div>

          <div class="form-card">
            <div class="field">
              <label class="field-label">网盘来源</label>
              <div class="radio-row">
                <label class="radio-item"><input v-model="driveProvider" type="radio" value="baidu" />百度网盘</label>
                <label class="radio-item"><input v-model="driveProvider" type="radio" value="123" />123 云盘</label>
              </div>
            </div>
            <div class="field">
              <label class="field-label">分享链接 <span class="req">*</span></label>
              <input v-model="driveLink" type="text" placeholder="粘贴网盘分享链接" class="text-input" />
            </div>
            <div class="field">
              <label class="field-label">提取码</label>
              <input v-model="driveCode" type="text" placeholder="可选" maxlength="8" class="text-input text-input--code" />
              <p class="field-help">无提取码可留空。</p>
            </div>
            <div class="form-actions">
              <NButton type="primary" :loading="submitting" @click="handleSubmit">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                提交拉取任务
              </NButton>
            </div>
          </div>
        </NTabPane>

        <!-- ── 云存储直拉 ── -->
        <NTabPane name="cloud-storage">
          <template #tab>
            <span class="source-tab"><NIcon :size="16"><ServerOutline /></NIcon>云存储直拉</span>
          </template>

          <div class="source-tip">
            <NIcon :size="16" class="source-tip__icon"><InformationCircleOutline /></NIcon>
            <span>{{ tabDescriptions['cloud-storage'] }}</span>
          </div>

          <div class="form-card">
            <div class="field">
              <label class="field-label">云服务商</label>
              <NSelect v-model:value="storageProvider" :options="storageProviderOptions" class="field-select" />
            </div>
            <div class="field">
              <label class="field-label">对象 URI <span class="req">*</span></label>
              <input v-model="storageUri" type="text" placeholder="oss://bucket-name/path/to/data/" class="text-input text-input--mono" />
              <p class="field-help">支持 oss:// / tos:// / obs:// 等对象存储路径。</p>
            </div>
            <div class="field">
              <label class="field-label">下载到</label>
              <NSelect v-model:value="targetDirectory" :options="targetDirectoryOptions" class="field-select" />
            </div>
            <div class="field">
              <label class="checkbox-item"><input v-model="storageRecursive" type="checkbox" />递归拉取目录</label>
            </div>
            <div class="form-actions">
              <NButton type="primary" :loading="submitting" @click="handleSubmit">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                提交拉取任务
              </NButton>
            </div>
          </div>
        </NTabPane>

        <!-- ── 直链与 FTP ── -->
        <NTabPane name="direct-link">
          <template #tab>
            <span class="source-tab"><NIcon :size="16"><LinkOutline /></NIcon>直链与 FTP</span>
          </template>

          <div class="source-tip">
            <NIcon :size="16" class="source-tip__icon"><InformationCircleOutline /></NIcon>
            <span>{{ tabDescriptions['direct-link'] }}</span>
          </div>

          <div class="form-card">
            <div class="field">
              <label class="field-label">资源链接 <span class="req">*</span></label>
              <div class="links-wrap">
                <textarea
                  v-model="directLinks"
                  rows="5"
                  placeholder="支持 HTTP / HTTPS / FTP 协议的直接下载链接，每行一个，可批量粘贴…"
                  class="text-input text-input--textarea text-input--mono links-input"
                />
                <div class="links-actions">
                  <NButton size="tiny" quaternary @click="directLinks = ''">清空</NButton>
                  <NButton size="tiny" quaternary @click="dedupLinks">去重</NButton>
                </div>
              </div>
              <p class="field-help">每行一个链接；支持 Ensembl、UCSC、ENA 等公共数据源。</p>
            </div>

            <div class="field">
              <label class="field-label">下载到</label>
              <NSelect v-model:value="targetDirectory" :options="targetDirectoryOptions" class="field-select" />
            </div>

            <!-- 高级选项折叠条 -->
            <div class="field">
              <button
                type="button"
                class="adv-toggle"
                :class="{ 'is-open': directAdvancedOpen }"
                :aria-expanded="directAdvancedOpen"
                @click="directAdvancedOpen = !directAdvancedOpen"
              >
                <span class="adv-toggle__title">高级选项</span>
                <span class="adv-toggle__desc">{{ directAdvancedOpen ? '收起' : '下载并发、同名策略与目录解析' }}</span>
                <NIcon :size="16" class="adv-toggle__chevron" :class="{ 'is-open': directAdvancedOpen }">
                  <ChevronDownOutline />
                </NIcon>
              </button>
              <div v-if="directAdvancedOpen" class="adv-panel">
                <div class="adv-grid">
                  <div class="field">
                    <label class="field-label">下载并发</label>
                    <NSelect v-model:value="directThreads" :options="threadOptions" class="field-select" />
                  </div>
                  <div class="field">
                    <label class="field-label">同名文件</label>
                    <NSelect v-model:value="directOverwritePolicy" :options="overwritePolicyOptions" class="field-select" />
                  </div>
                  <div class="field">
                    <label class="field-label">目录解析</label>
                    <label class="checkbox-item"><input v-model="directRecursive" type="checkbox" />解析 FTP 目录</label>
                  </div>
                </div>
                <p class="adv-panel__note">任务在后台执行，支持断点续传和失败重试；FTP 目录会先展开为文件清单。</p>
              </div>
            </div>

            <div class="form-actions">
              <NButton type="primary" :loading="submitting" @click="handleSubmit">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                提交下载任务
              </NButton>
            </div>
          </div>
        </NTabPane>
      </NTabs>

      <!-- ═══ 下载任务卡片 ═══ -->
      <div class="tasks-card">
        <div class="tasks-card__header">
          <div class="tasks-card__heading">
            <h3 class="tasks-card__title">下载任务</h3>
            <span class="tasks-card__count">共 <em>{{ stats.total }}</em> 个</span>
            <span v-if="stats.running" class="download-metric download-metric--running">
              <span class="download-metric-dot"></span>{{ stats.running }} 下载中
            </span>
            <span v-if="stats.success" class="download-metric download-metric--success">
              <span class="download-metric-dot"></span>{{ stats.success }} 已完成
            </span>
          </div>
          <div class="tasks-card__tools">
            <NSelect
              v-model:value="statusFilter"
              :options="statusFilterOptions"
              size="small"
              class="tasks-filter"
            />
            <NButton size="small" quaternary :loading="loadingTasks" @click="fetchDownloads">
              <template #icon><NIcon><RefreshOutline /></NIcon></template>
              刷新
            </NButton>
          </div>
        </div>

        <!-- 初次加载 -->
        <div v-if="loadingTasks && !tasks.length" class="tasks-loading">
          <NSpin size="small" />
        </div>

        <!-- 表格 -->
        <div v-else-if="filteredTasks.length" class="tasks-card__body">
          <table class="tasks-table">
            <thead>
              <tr>
                <th class="col-name">任务名称</th>
                <th class="col-acc">登录号</th>
                <th class="col-status">状态</th>
                <th class="col-progress">进度</th>
                <th class="col-time">提交时间</th>
                <th class="col-actions">操作</th>
              </tr>
            </thead>
            <tbody v-animate-list>
              <tr v-for="task in filteredTasks" :key="task.id" class="task-row">
                <td class="col-name">
                  <span class="cell-name" :title="task.name">{{ task.name }}</span>
                </td>
                <td class="col-acc">
                  <span class="cell-acc" :title="task.accession">{{ task.accession }}</span>
                </td>
                <td class="col-status">
                  <span class="download-status" :class="scfg(task.status).badge">
                    <svg v-if="scfg(task.status).icon === 'check'" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
                    <svg v-else-if="scfg(task.status).icon === 'loading'" class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" /></svg>
                    <svg v-else-if="scfg(task.status).icon === 'x'" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                    <svg v-else class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                    {{ scfg(task.status).label }}
                  </span>
                </td>
                <td class="col-progress">
                  <div class="progress">
                    <div class="progress__track">
                      <div class="progress__bar" :style="{ width: pct(task) + '%' }"></div>
                    </div>
                    <span class="progress__pct">{{ pct(task) }}%</span>
                  </div>
                </td>
                <td class="col-time">
                  <span class="cell-time">{{ formatTime(task.createdAt) }}</span>
                </td>
                <td class="col-actions">
                  <div class="row-actions">
                    <NButton text size="tiny" @click="router.push(`/tasks/${task.id}`)">查看</NButton>
                    <NPopconfirm @positive-click="handleDelete(task)">
                      <template #trigger>
                        <NButton text size="tiny" type="error">删除</NButton>
                      </template>
                      确定要删除「{{ task.name }}」吗？此操作不可恢复。
                    </NPopconfirm>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 空状态（收敛至 240px）-->
        <div v-else class="tasks-empty">
          <NIcon :size="48" class="tasks-empty__icon"><CloudDownloadOutline /></NIcon>
          <p class="tasks-empty__title">暂无下载任务</p>
          <p class="tasks-empty__desc">提交任务后，下载完成的文件将自动出现在「数据管理」中</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.downloads-page {
  padding-bottom: 40px;
}

/* 内容与其他工作台页面一致：撑满 .page-container，不做窄列居中 */
.downloads-content {
  width: 100%;
}

/* ═══ 来源切换 Tabs ═══ */
.source-tabs {
  margin-bottom: 20px;
}
.source-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* ═══ 提示条 ═══ */
.source-tip {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 20px;
  border-radius: 8px;
  background: var(--arco-primary-light);
  color: var(--neutral-text-2);
  font-size: 14px;
  line-height: 1.6;
}
.source-tip__icon {
  flex-shrink: 0;
  margin-top: 3px;
  color: var(--arco-primary);
}

/* ═══ 表单卡片 ═══ */
.form-card {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 24px;
}

/* ═══ 字段（label 上置）═══ */
.field {
  display: flex;
  flex-direction: column;
  margin-bottom: 20px;
}
.field:last-child {
  margin-bottom: 0;
}
.field-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
  font-size: 14px;
  font-weight: 500;
  color: var(--neutral-text-1);
}
.req {
  color: var(--arco-danger);
}
.field-help {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--neutral-text-3);
}
.field-select {
  max-width: 320px;
}

/* ═══ 输入控件 ═══ */
.text-input {
  width: 100%;
  max-width: 520px;
  padding: 9px 12px;
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  background: var(--neutral-card);
  color: var(--neutral-text-1);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  transition:
    border-color var(--motion-quick) ease-out,
    box-shadow var(--motion-quick) ease-out;
}
.text-input::placeholder {
  color: var(--neutral-text-3);
}
.text-input:focus {
  outline: none;
  border-color: var(--arco-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--arco-primary) 15%, transparent);
}
.text-input--textarea {
  min-height: 44px;
  resize: vertical;
}
.text-input--mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}
.text-input--code {
  max-width: 160px;
  text-align: center;
}

/* 直链批量输入（整行宽度，便于批量粘贴）*/
.links-wrap {
  position: relative;
  width: 100%;
}
.links-input {
  max-width: none;
  width: 100%;
  min-height: 128px;
  padding-right: 96px;
}
.links-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 2px;
}

/* ═══ 高级选项折叠条（统一组件）═══ */
.adv-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 11px 14px;
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  background: var(--neutral-bg);
  color: var(--neutral-text-1);
  text-align: left;
  cursor: pointer;
  transition: background-color var(--motion-quick) ease-out;
}
.adv-toggle:hover {
  background: var(--neutral-hover);
}
.adv-toggle.is-open {
  border-bottom-color: transparent;
  border-radius: 8px 8px 0 0;
}
.adv-toggle__title {
  font-size: 14px;
  font-weight: 500;
  color: var(--neutral-text-1);
}
.adv-toggle__desc {
  margin-left: auto;
  font-size: 12px;
  color: var(--neutral-text-3);
}
.adv-toggle__chevron {
  flex-shrink: 0;
  color: var(--neutral-text-3);
  transition: transform 200ms ease;
}
.adv-toggle__chevron.is-open {
  transform: rotate(180deg);
}
.adv-panel {
  width: 100%;
  padding: 16px 14px;
  border: 1px solid var(--neutral-border);
  border-top: none;
  border-radius: 0 0 8px 8px;
  background: var(--neutral-card);
}
.adv-panel__note {
  margin: 14px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--neutral-text-3);
}

/* SRA 过滤网格（随宽度自适应列数，避免单元格过宽）*/
.filter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}
.filter-field {
  display: flex;
  flex-direction: column;
}
.filter-field .text-input {
  max-width: none;
}
.filter-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
}
.filter-badge--include {
  background: var(--arco-primary-light);
  color: var(--arco-primary);
}
.filter-badge--exclude {
  background: var(--arco-danger-light);
  color: var(--arco-danger);
}

/* 直链高级选项（随宽度自适应列数）*/
.adv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  align-items: start;
}
.adv-grid .field {
  margin-bottom: 0;
}
.adv-grid .field-select {
  max-width: none;
}

/* ═══ 单选 / 复选 ═══ */
.radio-row {
  display: flex;
  align-items: center;
  gap: 20px;
}
.radio-item,
.checkbox-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--neutral-text-1);
  cursor: pointer;
}
.radio-item input,
.checkbox-item input {
  width: 16px;
  height: 16px;
  accent-color: var(--arco-primary);
  cursor: pointer;
}

/* ═══ 提交区 ═══ */
.form-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}

/* ═══ 任务卡片 ═══ */
.tasks-card {
  margin-top: 24px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  overflow: hidden;
}
.tasks-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--neutral-border);
}
.tasks-card__heading {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
}
.tasks-card__title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1);
}
.tasks-card__count {
  font-size: 12px;
  color: var(--neutral-text-3);
}
.tasks-card__count em {
  font-style: normal;
  font-weight: 600;
  color: var(--arco-primary);
}
.tasks-card__tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tasks-filter {
  width: 160px;
}
.tasks-card__body {
  overflow-x: auto;
}
.tasks-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 240px;
}

/* 统计徽标 */
.download-metric {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
}
.download-metric-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.download-metric--running {
  color: var(--arco-primary);
}
.download-metric--success {
  color: var(--arco-success);
}
.download-metric--running .download-metric-dot {
  animation: metric-pulse 1.4s ease-in-out infinite;
}
@keyframes metric-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
@media (prefers-reduced-motion: reduce) {
  .download-metric--running .download-metric-dot {
    animation: none;
  }
}

/* ═══ 表格 ═══ */
.tasks-table {
  width: 100%;
  border-collapse: collapse;
}
.tasks-table thead {
  background: var(--neutral-bg);
}
.tasks-table th {
  padding: 10px 16px;
  border-bottom: 1px solid var(--neutral-border);
  font-size: 12px;
  font-weight: 500;
  color: var(--neutral-text-3);
  text-align: left;
  white-space: nowrap;
}
.tasks-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--neutral-border);
  vertical-align: middle;
}
.tasks-table tbody tr:last-child td {
  border-bottom: none;
}
.task-row {
  transition: background-color var(--motion-quick) ease-out;
}
.task-row:hover {
  background: var(--neutral-hover);
}

.col-acc { width: 130px; }
.col-status { width: 108px; }
.col-progress { width: 190px; }
.col-time { width: 132px; }
.col-actions { width: 116px; }
th.col-actions { text-align: right; }

.cell-name {
  display: block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-text-1);
}
.cell-acc {
  display: block;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--neutral-text-2);
}
.cell-time {
  font-size: 12px;
  color: var(--neutral-text-3);
  white-space: nowrap;
}

/* 状态徽标（平台语义色）*/
.download-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}
.download-status--success { background: color-mix(in srgb, var(--arco-success) 12%, transparent); color: var(--arco-success); }
.download-status--running { background: color-mix(in srgb, var(--arco-primary) 12%, transparent); color: var(--arco-primary); }
.download-status--failed { background: color-mix(in srgb, var(--arco-danger) 12%, transparent); color: var(--arco-danger); }
.download-status--neutral { background: var(--neutral-hover); color: var(--neutral-text-2); }

/* 进度条（细条 + 百分比）*/
.progress {
  display: flex;
  align-items: center;
  gap: 8px;
}
.progress__track {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--neutral-hover);
  overflow: hidden;
}
.progress__bar {
  height: 100%;
  border-radius: 3px;
  background: var(--arco-primary);
  transition: width 400ms ease;
}
.progress__pct {
  width: 36px;
  text-align: right;
  font-size: 12px;
  font-weight: 500;
  color: var(--neutral-text-2);
  font-variant-numeric: tabular-nums;
}

/* 操作列（文字按钮）*/
.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

/* ═══ 空状态 ═══ */
.tasks-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 240px;
  padding: 0 16px;
  text-align: center;
}
.tasks-empty__icon {
  margin-bottom: 4px;
  color: var(--neutral-text-3);
  opacity: 0.6;
}
.tasks-empty__title {
  margin: 0;
  font-size: 14px;
  font-weight: 500;
  color: var(--neutral-text-2);
}
.tasks-empty__desc {
  margin: 0;
  font-size: 12px;
  color: var(--neutral-text-3);
}

/* ═══ 响应式 ═══ */
@media (max-width: 768px) {
  .adv-grid {
    grid-template-columns: 1fr;
  }
  .tasks-card__header {
    flex-direction: column;
    align-items: stretch;
  }
  .tasks-card__tools {
    justify-content: space-between;
  }
}
@media (max-width: 640px) {
  .filter-grid {
    grid-template-columns: 1fr;
  }
  .field-select {
    max-width: none;
  }
}
</style>
