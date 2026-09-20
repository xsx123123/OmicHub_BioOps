<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import type { DataFile, Directory, QuotaInfo } from '@/types'
import apiClient from '@/api/client'
import { useApi } from '@/composables/useApi'
import AppLoading from '@/components/AppLoading.vue'
import {
  CloudUploadOutline, SearchOutline, FolderOpenOutline, ScanOutline,
  CloudDownloadOutline, GlobeOutline, LinkOutline, GridOutline, ListOutline,
  DocumentTextOutline, RefreshOutline, EllipsisHorizontalOutline, DownloadOutline,
  CreateOutline, TrashOutline, MenuOutline, CloseOutline,
  EyeOutline,
} from '@vicons/ionicons5'
import {
  NButton, NBreadcrumb, NBreadcrumbItem, NDataTable, NDropdown, NDrawer,
  NIcon, NInput, NSelect, NSpin, NTag, NUpload, useDialog, useMessage,
} from 'naive-ui'
import type { DataTableColumns, UploadFileInfo } from 'naive-ui'
import DirectoryTree from '@/components/DirectoryTree.vue'
import OverviewStats from '@/components/data-management/OverviewStats.vue'
import StorageOverviewWidget from '@/components/data-management/StorageOverviewWidget.vue'
import RecentActivitiesWidget from '@/components/data-management/RecentActivitiesWidget.vue'
import FileDetailPanel from '@/components/data-management/FileDetailPanel.vue'
import FilePreviewModal from '@/components/data-management/FilePreviewModal.vue'
import JBrowseLinkGenerator from '@/components/data-management/JBrowseLinkGenerator.vue'
import { useUploadStore } from '@/stores/upload'
import { storeToRefs } from 'pinia'
import type { TeamInfo } from '@/types'

const message = useMessage()
const dialog = useDialog()
const treeRef = ref<InstanceType<typeof DirectoryTree>>()
const uploadStore = useUploadStore()
const { completedSeq } = storeToRefs(uploadStore)

const allFiles = ref<DataFile[]>([])
const directories = ref<Directory[]>([])
const samplesCount = ref(0)
const quota = ref<QuotaInfo>({ used: 0, total: 0, percent: 0 })
const teams = ref<TeamInfo[]>([])
const currentDirectory = ref('')
const activeSpace = ref<'personal' | 'team'>('personal')
const selectedTeamId = ref<string | null>(null)
const siderWidth = ref(280)

// 移动端抽屉状态
const showTreeDrawer = ref(false)
const showDetailDrawer = ref(false)
const isMobile = ref(false)
const isTablet = ref(false)

function updateViewport() {
  const w = window.innerWidth
  isMobile.value = w < 768
  isTablet.value = w >= 768 && w < 1200
  if (!isMobile.value && !isTablet.value) {
    showTreeDrawer.value = false
    showDetailDrawer.value = false
  }
}

const {
  loading,
  error,
  execute: fetchAll,
} = useApi(
  async () => {
    const [filesRes, dirsRes, samplesRes, quotaRes, teamsRes] = await Promise.all([
      apiClient.get<{ items: DataFile[]; total: number }>('/files'),
      apiClient.get<Directory[]>('/files/directories'),
      apiClient.get<{ items: unknown[]; total: number }>('/files/samples'),
      apiClient.get<QuotaInfo>('/files/quota'),
      apiClient.get<{ items: TeamInfo[]; total: number }>('/teams'),
    ])
    allFiles.value = filesRes.data.items
    directories.value = dirsRes.data
    samplesCount.value = samplesRes.data.total ?? samplesRes.data.items.length
    quota.value = quotaRes.data
    teams.value = teamsRes.data.items || []
    if (activeSpace.value === 'team' && !selectedTeamId.value && teams.value.length) {
      selectedTeamId.value = teams.value[0].id
    }
  },
  { initialData: undefined },
)

// Finder 状态
const viewMode = ref<'list' | 'grid'>('list')
const searchQuery = ref('')
const sortBy = ref<'name' | 'size' | 'time'>('time')
const selectedFile = ref<DataFile | null>(null)
const showJbrowseLinkGen = ref(false)
const showPreview = ref(false)

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / k ** i).toFixed(2)} ${sizes[i]}`
}

const projectsCount = computed(
  () => directories.value.filter((d) => !d.parent_path && !d.is_system).length,
)

/** 当前团队角色 */
const currentTeamRole = computed(() => {
  if (activeSpace.value !== 'team' || !selectedTeamId.value) return null
  return teams.value.find((t) => t.id === selectedTeamId.value)?.role || null
})

/** 当前空间下的文件（个人按目录过滤，团队按 team_id 过滤） */
const spaceFiles = computed(() => {
  if (activeSpace.value === 'team') {
    if (!selectedTeamId.value) return []
    return allFiles.value.filter(
      (f) => f.owner_scope === 'team' && f.team_id === selectedTeamId.value,
    )
  }
  return allFiles.value.filter(
    (f) => (f.owner_scope || 'personal') === 'personal' && (f.directory || '') === currentDirectory.value,
  )
})

/** 面包屑：根目录 > seg1 > seg2 ...，可点击跳转（仅个人空间） */
const breadcrumbItems = computed(() => {
  if (activeSpace.value === 'team') {
    const team = teams.value.find((t) => t.id === selectedTeamId.value)
    return [{ label: team?.name || '团队空间', path: '' }]
  }
  const segs = currentDirectory.value.split('/').filter(Boolean)
  const items: { label: string; path: string }[] = [{ label: '根目录', path: '' }]
  let acc = ''
  for (const s of segs) {
    acc = acc ? `${acc}/${s}` : s
    items.push({ label: s, path: acc })
  }
  return items
})
function navigateTo(path: string) {
  currentDirectory.value = path
}

function switchSpace(space: 'personal' | 'team') {
  activeSpace.value = space
  currentDirectory.value = ''
  if (space === 'team' && !selectedTeamId.value && teams.value.length) {
    selectedTeamId.value = teams.value[0].id
  }
}

/** 搜索 + 排序后的展示列表 */
const displayFiles = computed(() => {
  let list = spaceFiles.value
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter((f) => f.original_name.toLowerCase().includes(q))
  }
  const sorted = [...list]
  sorted.sort((a, b) => {
    if (sortBy.value === 'name') return a.original_name.localeCompare(b.original_name)
    if (sortBy.value === 'size') return b.size - a.size
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  })
  return sorted
})

/** 文件格式 Tag 元信息 */
const fileTypeTagMeta: Record<
  string,
  { label: string; type?: 'info' | 'success' | 'warning' | 'default'; color?: string }
> = {
  fastq: { label: 'FASTQ', type: 'info' },
  bam: { label: 'BAM', type: 'success' },
  vcf: { label: 'VCF', type: 'warning' },
  count_matrix: { label: '矩阵', color: '#0FC6C2' },
  h5ad: { label: 'H5AD', color: '#8E54E9' },
  rds: { label: 'RDS', color: '#8E54E9' },
  meta: { label: '元数据', type: 'default' },
  report: { label: '报告', type: 'default' },
  image: { label: '图片', type: 'default' },
  other: { label: '其他', type: 'default' },
}

function renderFileTypeTag(fileType: string) {
  const meta = fileTypeTagMeta[fileType] || fileTypeTagMeta.other
  return h(
    NTag,
    {
      size: 'small',
      round: true,
      type: meta.type,
      color: meta.color
        ? { color: meta.color, textColor: '#fff', borderColor: meta.color }
        : undefined,
    },
    { default: () => meta.label },
  )
}

function fileIcon() {
  return ScanOutline
}

/** 文件名后缀 → emoji 图标 */
function fileEmoji(name: string): string {
  const n = name.toLowerCase()
  if (n.endsWith('.zip')) return '📦'
  if (n.endsWith('.tsv') || n.endsWith('.csv')) return '📊'
  if (n.endsWith('.fastq.gz') || n.endsWith('.fq.gz') || n.endsWith('.fastq') || n.endsWith('.fq')) return '🧬'
  if (n.endsWith('.log')) return '📜'
  return '📄'
}

function rowActionOptions(row: DataFile) {
  const isReader = activeSpace.value === 'team' && currentTeamRole.value === 'reader'
  const canWrite = activeSpace.value !== 'team' || ['owner', 'writer'].includes(currentTeamRole.value || '')
  const canDelete = activeSpace.value !== 'team' || currentTeamRole.value === 'owner'
  const options = [
    { label: '预览', key: 'preview', icon: () => h(NIcon, null, { default: () => h(EyeOutline) }) },
    { label: '下载', key: 'download', icon: () => h(NIcon, null, { default: () => h(DownloadOutline) }) },
  ]
  if (!isReader && canWrite) {
    options.push({ label: '重命名', key: 'rename', icon: () => h(NIcon, null, { default: () => h(CreateOutline) }) })
  }
  if (canDelete) {
    options.push({ label: '删除', key: 'delete', icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) })
  }
  return options
}

function onRowAction(key: string, row: DataFile) {
  if (key === 'preview') openPreview(row)
  else if (key === 'download') downloadFile(row)
  else if (key === 'rename') message.info('重命名功能即将上线')
  else if (key === 'delete') confirmDelete(row)
}

const columns = computed<DataTableColumns<DataFile>>(() => [
  {
    title: '文件名',
    key: 'original_name',
    render: (row) =>
      h('div', { class: 'file-name-cell' }, [
        h('span', { class: 'file-emoji' }, fileEmoji(row.original_name)),
        h('span', null, row.original_name),
      ]),
  },
  { title: '格式', key: 'file_type', width: 100, render: (row) => renderFileTypeTag(row.file_type) },
  { title: '大小', key: 'size', width: 110, render: (row) => formatSize(row.size) },
  {
    title: '创建时间',
    key: 'created_at',
    width: 170,
    render: (row) => (row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-'),
  },
  {
    title: '操作',
    key: 'actions',
    width: 70,
    render: (row) =>
      h(
        NDropdown,
        {
          trigger: 'click',
          placement: 'bottom-end',
          options: rowActionOptions(row),
          onSelect: (k: string) => onRowAction(k, row),
        },
        {
          default: () =>
            h(
              NButton,
              { size: 'tiny', quaternary: true, onClick: (e: Event) => e.stopPropagation() },
              { icon: () => h(NIcon, null, { default: () => h(EllipsisHorizontalOutline) }) },
            ),
        },
      ),
  },
])

const sortOptions = [
  { label: '按时间排序', value: 'time' },
  { label: '按名称排序', value: 'name' },
  { label: '按大小排序', value: 'size' },
]

const syncing = ref(false)

type SyncFilesResponse = {
  added: number
  added_size: number
  removed?: number
  removed_size?: number
  renamed?: number
}

/** 对账磁盘文件与 file_records，silent=true 用于进页面自动同步（不弹提示） */
async function syncFiles(silent = false) {
  syncing.value = true
  try {
    const res = await apiClient.post<SyncFilesResponse>('/files/sync')
    if (!silent) {
      const changes: string[] = []
      if (res.data.added > 0) changes.push(`新增 ${res.data.added} 个文件`)
      if ((res.data.removed ?? 0) > 0) changes.push(`清理 ${res.data.removed} 条已删除记录`)
      if ((res.data.renamed ?? 0) > 0) changes.push(`修正 ${res.data.renamed} 个显示名`)
      message.success(changes.length ? `同步完成，${changes.join('，')}` : '同步完成，无变化')
    }
  } catch {
    if (!silent) message.error('同步失败，请稍后重试')
  } finally {
    syncing.value = false
    await fetchAll()
  }
}

/** 拖拽调整左侧目录树宽度（200~480px） */
function startResize(e: MouseEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startW = siderWidth.value
  const onMove = (ev: MouseEvent) => {
    siderWidth.value = Math.min(480, Math.max(200, startW + ev.clientX - startX))
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

function selectFile(row: DataFile) {
  selectedFile.value = selectedFile.value?.id === row.id ? null : row
  if (selectedFile.value && isMobile.value) {
    showDetailDrawer.value = true
  }
}

function openPreview(row: DataFile) {
  selectedFile.value = row
  showPreview.value = true
}

function rowProps(row: DataFile) {
  return {
    style: selectedFile.value?.id === row.id ? 'background: var(--arco-primary-light)' : '',
    onClick: () => selectFile(row),
  }
}

async function downloadFile(row: DataFile) {
  try {
    const res = await apiClient.get(`/files/${row.id}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = row.original_name
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    message.error('下载失败，请稍后重试')
  }
}

function confirmDelete(row: DataFile) {
  dialog.error({
    title: '删除文件',
    content: `确认删除「${row.original_name}」？将释放 ${formatSize(row.size)} 空间。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await apiClient.delete(`/files/${row.id}`)
        message.success('已删除')
        if (selectedFile.value?.id === row.id) selectedFile.value = null
        await fetchAll()
      } catch (e: any) {
        message.error(e.response?.data?.detail || '删除失败')
      }
    },
  })
}

async function openMoveModal(row: DataFile) {
  let dirs: Directory[] = []
  try {
    const res = await apiClient.get<Directory[]>('/files/directories')
    dirs = res.data
  } catch {
    message.error('获取目录失败')
    return
  }
  const options = [{ label: '根目录', value: '' }, ...dirs.map((d) => ({ label: d.path, value: d.path }))]
  let target = row.directory || ''
  dialog.create({
    title: `移动「${row.original_name}」`,
    content: () =>
      h(NSelect, {
        value: target,
        'onUpdate:value': (v: string) => (target = v),
        options,
        placeholder: '选择目标目录',
        filterable: true,
      }),
    positiveText: '移动',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await apiClient.put(`/files/${row.id}/move`, { directory: target })
        message.success('已移动')
        await fetchAll()
      } catch (e: any) {
        message.error(e.response?.data?.detail || '移动失败')
      }
    },
  })
}

function handleDropUpload({ file }: { file: UploadFileInfo }): boolean {
  if (file.file) {
    uploadStore.open(currentDirectory.value)
    uploadStore.addFile(file.file)
  }
  return false
}

function importFromSRA() {
  message.info('SRA 公共数据库导入即将上线')
}
function importFromGEO() {
  message.info('GEO 公共数据库导入即将上线')
}
function importFromURL() {
  message.info('URL 导入即将上线')
}

const supportedFormats = ['FASTQ', 'BAM', 'VCF', 'CRAM', 'ZIP']

watch(completedSeq, () => {
  fetchAll()
})
watch(currentDirectory, () => {
  selectedFile.value = null
})

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
  syncFiles(true)
})
onUnmounted(() => {
  window.removeEventListener('resize', updateViewport)
})
</script>

<template>
  <main class="finder-page" aria-label="数据管理">
    <!-- 顶部统计大盘 -->
    <OverviewStats
      :samples="samplesCount"
      :files="allFiles.length"
      :projects="projectsCount"
      :quota="quota"
    />

    <!-- Finder 三栏 -->
    <div class="finder-grid" :class="{ 'finder-grid--mobile': isMobile || isTablet }">
      <!-- 左：目录树 / 团队空间选择器（桌面端可拖拽调宽） -->
      <aside v-if="!isMobile && !isTablet" class="col-tree" :style="{ width: siderWidth + 'px' }">
        <div class="space-tabs">
          <NButton
            size="small"
            :type="activeSpace === 'personal' ? 'primary' : 'default'"
            quaternary
            @click="switchSpace('personal')"
          >
            个人空间
          </NButton>
          <NButton
            size="small"
            :type="activeSpace === 'team' ? 'primary' : 'default'"
            quaternary
            @click="switchSpace('team')"
          >
            团队空间
          </NButton>
        </div>
        <DirectoryTree
          v-if="activeSpace === 'personal'"
          v-model="currentDirectory"
          ref="treeRef"
          @refresh-files="fetchAll"
        />
        <div v-else class="team-selector">
          <NSelect
            v-model:value="selectedTeamId"
            :options="teams.map((t) => ({ label: t.name + ' (' + t.role + ')', value: t.id }))"
            placeholder="选择团队"
            size="small"
            clearable
          />
          <p v-if="!teams.length" class="team-empty">暂无团队空间</p>
        </div>
        <div class="resize-handle" title="拖拽调整宽度" @mousedown="startResize"></div>
      </aside>

      <!-- 中：Data Workspace -->
      <section class="col-workspace">
        <!-- 面包屑导航 -->
        <div class="breadcrumb-bar">
          <div class="breadcrumb-left">
            <NButton v-if="isMobile || isTablet" size="small" quaternary @click="showTreeDrawer = true">
              <template #icon>
                <NIcon><MenuOutline /></NIcon>
              </template>
              目录
            </NButton>
            <NBreadcrumb>
              <NBreadcrumbItem
                v-for="item in breadcrumbItems"
                :key="item.path"
                @click="navigateTo(item.path)"
              >
                {{ item.label }}
              </NBreadcrumbItem>
            </NBreadcrumb>
          </div>
        </div>

        <!-- 工具栏 -->
        <div class="toolbar">
          <div class="toolbar-left">
            <NButton
              type="primary"
              size="small"
              :disabled="activeSpace === 'team'"
              @click="uploadStore.open(currentDirectory)"
            >
              <template #icon>
                <NIcon><CloudUploadOutline /></NIcon>
              </template>
              上传
            </NButton>
            <NButton
              size="small"
              :disabled="activeSpace === 'team'"
              @click="treeRef?.openCreateModal?.(currentDirectory)"
            >
              <template #icon>
                <NIcon><FolderOpenOutline /></NIcon>
              </template>
              新建文件夹
            </NButton>
            <NButton
              size="small"
              :loading="syncing"
              :disabled="activeSpace === 'team'"
              @click="syncFiles(false)"
            >
              <template #icon>
                <NIcon><RefreshOutline /></NIcon>
              </template>
              同步
            </NButton>
            <NButton size="small" @click="showJbrowseLinkGen = true">
              <template #icon>
                <NIcon><LinkOutline /></NIcon>
              </template>
              JBrowse 直链
            </NButton>
            <NSelect v-model:value="sortBy" :options="sortOptions" size="small" style="width: 130px" />
          </div>
          <div class="toolbar-right">
            <NInput
              v-model:value="searchQuery"
              size="small"
              placeholder="搜索文件..."
              clearable
              style="width: 180px"
            >
              <template #prefix>
                <NIcon :size="14"><SearchOutline /></NIcon>
              </template>
            </NInput>
            <div class="view-toggle">
              <NButton
                size="small"
                :type="viewMode === 'list' ? 'primary' : 'default'"
                quaternary
                @click="viewMode = 'list'"
              >
                <template #icon>
                  <NIcon><ListOutline /></NIcon>
                </template>
              </NButton>
              <NButton
                size="small"
                :type="viewMode === 'grid' ? 'primary' : 'default'"
                quaternary
                @click="viewMode = 'grid'"
              >
                <template #icon>
                  <NIcon><GridOutline /></NIcon>
                </template>
              </NButton>
            </div>
            <NButton
              v-if="isMobile || isTablet"
              size="small"
              quaternary
              @click="showDetailDrawer = true"
            >
              <template #icon>
                <NIcon><MenuOutline /></NIcon>
              </template>
              详情
            </NButton>
          </div>
        </div>

        <!-- 工作台主体 -->
        <NSpin :show="loading" class="workspace-body" :aria-busy="loading">
          <!-- 错误状态 -->
          <div v-if="error && !displayFiles.length" class="workspace-error" role="alert">
            <AppLoading text="加载失败，请重试" size="small" />
            <NButton size="small" @click="fetchAll">重试</NButton>
          </div>

          <!-- 有文件 -->
          <template v-else-if="displayFiles.length">
            <!-- 列表视图 -->
            <NDataTable
              v-if="viewMode === 'list'"
              :columns="columns"
              :data="displayFiles"
              :row-key="(row: DataFile) => row.id"
              :bordered="false"
              size="small"
              :row-props="rowProps"
              class="file-table"
            />
            <!-- 网格视图 -->
            <div v-else class="file-grid">
              <div
                v-for="f in displayFiles"
                :key="f.id"
                class="grid-card cygnusx-card"
                :class="{ active: selectedFile?.id === f.id, 'is-selected': selectedFile?.id === f.id }"
                role="button"
                tabindex="0"
                :aria-selected="selectedFile?.id === f.id"
                @click="selectFile(f)"
                @keydown.enter.prevent="selectFile(f)"
                @keydown.space.prevent="selectFile(f)"
              >
                <div class="grid-icon">
                  <NIcon :size="28" color="var(--arco-primary)"
                    ><component :is="fileIcon()" /></NIcon
                  >
                </div>
                <span class="grid-name" :title="f.original_name">{{ f.original_name }}</span>
                <span class="grid-size">{{ formatSize(f.size) }}</span>
                <div class="grid-tag">
                  <component :is="renderFileTypeTag(f.file_type)" />
                </div>
              </div>
            </div>
          </template>

          <!-- 空状态 -->
          <div v-else class="empty-state">
            <svg
              class="dna-illustration"
              width="96"
              height="96"
              viewBox="0 0 120 120"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M30 15 C 90 15, 90 105, 30 105"
                stroke="var(--arco-primary)"
                stroke-width="2.5"
                stroke-linecap="round"
                fill="none"
                opacity="0.4"
              />
              <path
                d="M90 15 C 30 15, 30 105, 90 105"
                stroke="var(--arco-primary)"
                stroke-width="2.5"
                stroke-linecap="round"
                fill="none"
                opacity="0.4"
              />
              <line
                x1="38" y1="28" x2="82" y2="28"
                stroke="var(--arco-primary)"
                stroke-width="2"
                opacity="0.3"
                stroke-linecap="round"
              />
              <line
                x1="44" y1="44" x2="76" y2="44"
                stroke="var(--arco-primary)"
                stroke-width="2"
                opacity="0.3"
                stroke-linecap="round"
              />
              <line
                x1="46" y1="60" x2="74" y2="60"
                stroke="var(--arco-primary)"
                stroke-width="2"
                opacity="0.3"
                stroke-linecap="round"
              />
              <line
                x1="44" y1="76" x2="76" y2="76"
                stroke="var(--arco-primary)"
                stroke-width="2"
                opacity="0.3"
                stroke-linecap="round"
              />
              <line
                x1="38" y1="92" x2="82" y2="92"
                stroke="var(--arco-primary)"
                stroke-width="2"
                opacity="0.3"
                stroke-linecap="round"
              />
            </svg>
            <h3 class="empty-title">当前文件夹暂无数据</h3>
            <p class="empty-subtitle">
              拖拽测序数据到下方，或点击选择文件上传到「{{ currentDirectory || '根目录' }}」
            </p>

            <NUpload
              class="empty-dropzone"
              :show-file-list="false"
              :default-upload="false"
              multiple
              directory-dnd
              @before-upload="handleDropUpload"
            >
              <div class="dropzone-inner"
              >
                <NIcon :size="28" class="dropzone-icon"
                  ><CloudDownloadOutline /></NIcon
                >
                <p class="dropzone-title">拖拽文件到此处，或点击选择</p>
                <div class="format-chips">
                  <span v-for="fmt in supportedFormats" :key="fmt" class="format-chip">{{ fmt }}</span>
                </div>
              </div>
            </NUpload>

            <div class="import-row">
              <NButton size="small" quaternary @click="importFromSRA"
              >
                <template #icon>
                  <NIcon><GlobeOutline /></NIcon>
                </template>
                从 SRA 导入
              </NButton>
              <NButton size="small" quaternary @click="importFromGEO"
              >
                <template #icon>
                  <NIcon><GlobeOutline /></NIcon>
                </template>
                从 GEO 导入
              </NButton>
              <NButton size="small" quaternary @click="importFromURL"
              >
                <template #icon>
                  <NIcon><LinkOutline /></NIcon>
                </template>
                从链接导入
              </NButton>
            </div>
            <a class="help-link" @click="message.info('帮助文档即将上线')"
            >
              <NIcon :size="13"><DocumentTextOutline /></NIcon> 查看支持的数据格式与上传帮助
            </a>
          </div>
        </NSpin>
      </section>

      <!-- 右：详情面板（桌面端常驻） -->
      <aside v-if="!isMobile && !isTablet" class="col-detail">
        <JBrowseLinkGenerator v-model:show="showJbrowseLinkGen" :files="displayFiles" />
        <FileDetailPanel
          v-if="selectedFile"
          :file="selectedFile"
          @close="selectedFile = null"
          @preview="openPreview"
          @download="downloadFile"
          @move="openMoveModal"
          @delete="confirmDelete"
        />
        <template v-else>
          <StorageOverviewWidget
            :quota="quota"
            :directory-count="directories.length"
            @clean-cache="fetchAll"
            @manage-storage="message.info('存储管理面板即将上线')"
          />
          <RecentActivitiesWidget :files="allFiles" :directories="directories" />
        </template>
      </aside>
    </div>

    <!-- 移动端目录树抽屉 -->
    <NDrawer
      v-model:show="showTreeDrawer"
      :width="260"
      placement="left"
      :auto-focus="false"
    >
      <div class="mobile-drawer-header"
      >
        <span class="font-medium">目录</span>
        <NButton text circle size="small" @click="showTreeDrawer = false"
        >
          <template #icon>
            <NIcon><CloseOutline /></NIcon>
          </template>
        </NButton>
      </div>
      <div class="space-tabs">
        <NButton
          size="small"
          :type="activeSpace === 'personal' ? 'primary' : 'default'"
          quaternary
          @click="switchSpace('personal')"
        >
          个人空间
        </NButton>
        <NButton
          size="small"
          :type="activeSpace === 'team' ? 'primary' : 'default'"
          quaternary
          @click="switchSpace('team')"
        >
          团队空间
        </NButton>
      </div>
      <DirectoryTree
        v-if="activeSpace === 'personal'"
        v-model="currentDirectory"
        @refresh-files="fetchAll"
      />
      <div v-else class="team-selector">
        <NSelect
          v-model:value="selectedTeamId"
          :options="teams.map((t) => ({ label: t.name + ' (' + t.role + ')', value: t.id }))"
          placeholder="选择团队"
          size="small"
          clearable
        />
        <p v-if="!teams.length" class="team-empty">暂无团队空间</p>
      </div>
    </NDrawer>

    <!-- 移动端详情抽屉 -->
    <NDrawer
      v-model:show="showDetailDrawer"
      :width="320"
      placement="right"
      :auto-focus="false"
    >
      <div class="mobile-drawer-header"
      >
        <span class="font-medium">详情</span>
        <NButton text circle size="small" @click="showDetailDrawer = false"
        >
          <template #icon>
            <NIcon><CloseOutline /></NIcon>
          </template>
        </NButton>
      </div>
      <div class="mobile-detail-body"
      >
        <JBrowseLinkGenerator v-model:show="showJbrowseLinkGen" :files="displayFiles" />
        <FileDetailPanel
          v-if="selectedFile"
          :file="selectedFile"
          @close="selectedFile = null; showDetailDrawer = false"
          @preview="openPreview"
          @download="downloadFile"
          @move="openMoveModal"
          @delete="confirmDelete"
        />
        <template v-else>
          <StorageOverviewWidget
            :quota="quota"
            :directory-count="directories.length"
            @clean-cache="fetchAll"
            @manage-storage="message.info('存储管理面板即将上线')"
          />
          <RecentActivitiesWidget :files="allFiles" :directories="directories" />
        </template>
      </div>
    </NDrawer>

    <FilePreviewModal
      v-model:show="showPreview"
      :file="selectedFile"
      @download="downloadFile"
    />
  </main>
</template>

<style scoped>
.finder-page {
  background: var(--page-bg, var(--neutral-bg));
  flex: 1;
  min-height: 0;
  padding: 16px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: hidden;
}

.finder-grid {
  flex: 1;
  display: flex;
  gap: 16px;
  min-height: 0;
}

.finder-grid--mobile {
  flex-direction: column;
  gap: 12px;
}

.col-tree,
.col-workspace,
.col-detail {
  background: var(--neutral-card, #fff);
  border-radius: var(--radius-lg, 16px);
  box-shadow: var(--shadow-soft, 0 4px 12px rgba(0, 0, 0, 0.05));
  border: 1px solid var(--neutral-border);
  min-height: 0;
}

.col-tree {
  position: relative;
  flex-shrink: 0;
  overflow: visible;
}

.space-tabs {
  display: flex;
  gap: 8px;
  padding: 12px 12px 8px;
  border-bottom: 1px solid var(--neutral-border);
}

.team-selector {
  padding: 12px;
}

.team-empty {
  padding: 16px 12px;
  color: var(--neutral-text-tertiary, #86909c);
  font-size: 13px;
  text-align: center;
}

.resize-handle {
  position: absolute;
  top: 0;
  right: -6px;
  width: 12px;
  height: 100%;
  cursor: col-resize;
  z-index: 5;
}

.resize-handle:hover,
.resize-handle:active {
  background: var(--arco-primary-light);
  border-radius: 4px;
}

.col-workspace {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.breadcrumb-bar {
  padding: 10px 16px;
  border-bottom: 1px solid var(--neutral-border);
  flex-shrink: 0;
}

.breadcrumb-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.col-detail {
  width: 300px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  padding: 16px;
}

.file-emoji {
  font-size: 16px;
  line-height: 1;
  margin-right: 6px;
}

/* 工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--neutral-border);
  flex-wrap: wrap;
  flex-shrink: 0;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.view-toggle {
  display: flex;
  gap: 2px;
  background: var(--neutral-bg);
  border-radius: 8px;
  padding: 2px;
}

.workspace-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 12px 16px;
}

.workspace-body :deep(.n-spin-content) {
  height: 100%;
}

.workspace-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px 24px;
}

/* 文件表格 */
.file-table {
  cursor: default;
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 网格视图 */
.file-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  padding: 8px 4px;
}

.grid-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 16px 10px;
  cursor: pointer;
  text-align: center;
}

.grid-icon {
  width: 52px;
  height: 52px;
  border-radius: var(--radius-md, 12px);
  background: var(--neutral-hover);
  display: flex;
  align-items: center;
  justify-content: center;
}

.grid-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--neutral-text-1);
  word-break: break-all;
  line-height: 1.3;
  max-width: 100%;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.grid-size {
  font-size: 11px;
  color: var(--neutral-text-3);
  font-variant-numeric: tabular-nums;
}

.grid-tag {
  margin-top: 2px;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 24px 40px;
}

.dna-illustration {
  margin-bottom: 16px;
}

.empty-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0 0 6px;
}

.empty-subtitle {
  font-size: 13px;
  color: var(--neutral-text-3);
  margin: 0 0 22px;
  text-align: center;
}

.empty-dropzone {
  width: 100%;
  max-width: 480px;
}

.empty-dropzone :deep(.n-upload-trigger) {
  width: 100%;
}

.dropzone-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px;
  border: 2px dashed var(--neutral-border);
  border-radius: var(--radius-lg, 16px);
  background: var(--neutral-card);
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  width: 100%;
  box-sizing: border-box;
}

.dropzone-inner:hover {
  border-color: var(--arco-primary);
  background: var(--arco-primary-light);
}

.dropzone-icon {
  color: var(--arco-primary);
  margin-bottom: 8px;
}

.dropzone-title {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--neutral-text-1);
}

.format-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
}

.format-chip {
  font-size: 11px;
  font-weight: 600;
  color: var(--arco-primary);
  background: var(--arco-primary-light);
  padding: 3px 10px;
  border-radius: 8px;
}

.import-row {
  display: flex;
  gap: 10px;
  margin-top: 18px;
  flex-wrap: wrap;
  justify-content: center;
}

.help-link {
  margin-top: 16px;
  font-size: 12px;
  color: var(--neutral-text-3);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.help-link:hover {
  color: var(--arco-primary);
}

/* 移动端抽屉 */
.mobile-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--neutral-border);
}

.mobile-detail-body {
  padding: 16px;
}

/* 响应式 */
@media (max-width: 1200px) {
  .finder-grid {
    flex-direction: column;
  }

  .col-tree,
  .col-detail {
    display: none;
  }

  .col-workspace {
    min-height: 0;
  }
}

@media (max-width: 768px) {
  .finder-page {
    padding: 12px;
    gap: 12px;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .toolbar-left,
  .toolbar-right {
    justify-content: flex-start;
  }

  .toolbar-left :deep(.n-select),
  .toolbar-right :deep(.n-input) {
    flex: 1;
    min-width: 120px;
  }
}
</style>
