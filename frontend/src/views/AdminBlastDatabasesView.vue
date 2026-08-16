<script setup lang="ts">
import { h, onMounted, onUnmounted, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NDivider, NForm, NFormItem, NInput, NModal, NPopconfirm, NProgress,
  NSelect, NSpace, NSpin, NStatistic, NSwitch, NTag, NUpload, useMessage, type UploadFileInfo,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  AddOutline, RefreshOutline, TrashOutline, SearchOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import {
  activateBlastDatabase, cleanupAllBlastTasks, cleanupOldBlastTasks, createBlastDatabase,
  deleteBlastDatabase, fetchAdminBlastDatabases, fetchBlastDatabaseBuildStatus, fetchBlastStorageStats,
  rebuildBlastDatabase, syncBlastDatabasesFromYaml,
} from '@/api/blast'
import type { BlastBuildStatusResponse, BlastDatabase } from '@/types/blast'
import PageHeader from '@/components/PageHeader.vue'

const message = useMessage()

const POLLING_INTERVAL = 3000

const databases = ref<BlastDatabase[]>([])
const loading = ref(false)
const showModal = ref(false)
const submitting = ref(false)
const uploadProgress = ref(0)
const pollingMap = ref<Record<string, ReturnType<typeof setInterval>>>({})
const stats = ref<{
  total_tasks: number
  completed_tasks: number
  cleaned_tasks: number
  storage_mb: number
  result_dir: string
} | null>(null)
const cleanupLoading = ref(false)

const form = ref({
  name: '',
  db_key: '',
  db_type: 'nucl' as 'nucl' | 'prot',
  source_species: '',
  source_version: '',
  version_group: '',
  is_public: true,
})
const fileList = ref<UploadFileInfo[]>([])

const statusMap: Record<string, { text: string; type: 'default' | 'success' | 'warning' | 'error' | 'info' }> = {
  pending: { text: '等待构建', type: 'default' },
  building: { text: '构建中', type: 'warning' },
  ready: { text: '就绪', type: 'success' },
  failed: { text: '失败', type: 'error' },
  deprecated: { text: '已弃用', type: 'info' },
}

const columns: DataTableColumns<BlastDatabase> = [
  { title: 'ID', key: 'id', width: 80, ellipsis: { tooltip: true }, render: (row) => row.id.slice(0, 8) },
  { title: '名称', key: 'name', ellipsis: { tooltip: true }, minWidth: 160 },
  { title: '标识', key: 'db_key', width: 150 },
  { title: '版本族', key: 'version_group', width: 130 },
  { title: '版本', key: 'source_version', width: 90, render: (row) => row.source_version || '-' },
  {
    title: '当前版本',
    key: 'is_active',
    width: 90,
    render: (row) => h(NTag, { size: 'small', type: row.is_active ? 'success' : 'default' }, { default: () => (row.is_active ? '当前' : '历史') }),
  },
  {
    title: '类型',
    key: 'db_type',
    width: 80,
    render: (row) => (row.db_type === 'nucl' ? '核酸' : '蛋白'),
  },
  {
    title: '状态',
    key: 'build_status',
    width: 100,
    render: (row) => {
      const status = statusMap[row.build_status] || { text: row.build_status, type: 'default' }
      return h(NTag, { type: status.type, size: 'small' }, { default: () => status.text })
    },
  },
  { title: '序列数', key: 'sequence_count', width: 90 },
  {
    title: '大小 (MB)',
    key: 'file_size_mb',
    width: 100,
    render: (row) => row.file_size_mb.toFixed(2),
  },
  {
    title: '公开',
    key: 'is_public',
    width: 70,
    render: (row) => (row.is_public ? '是' : '否'),
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 160,
    render: (row) => formatDate(row.created_at),
  },
  {
    title: '操作',
    key: 'actions',
    width: 225,
    fixed: 'right',
    render: (row) => {
      const building = row.build_status === 'building'
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(
            NButton,
            {
              size: 'tiny',
              type: row.is_active ? 'default' : 'primary',
              disabled: row.is_active || row.build_status !== 'ready',
              onClick: () => handleActivate(row.id),
            },
            { default: () => (row.is_active ? '当前' : '激活') },
          ),
          h(
            NButton,
            {
              size: 'tiny',
              loading: building,
              disabled: building,
              onClick: () => handleRebuild(row.id),
            },
            { default: () => '重建', icon: () => h(NIcon, null, { default: () => h(RefreshOutline) }) },
          ),
          h(
            NPopconfirm,
            { onPositiveClick: () => handleDelete(row.id) },
            {
              trigger: () => h(
                NButton,
                { size: 'tiny', type: 'error' },
                { default: () => '删除', icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) },
              ),
              default: () => '确认删除该数据库？',
            },
          ),
        ],
      })
    },
  },
]

function formatDate(iso: string | undefined) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}

async function loadDatabases() {
  loading.value = true
  try {
    databases.value = await fetchAdminBlastDatabases()
    // 对 building/pending 状态启动轮询
    databases.value.forEach((db) => {
      if (db.build_status === 'building' || db.build_status === 'pending') {
        startPolling(db.id)
      }
    })
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '加载数据库列表失败')
  } finally {
    loading.value = false
  }
}

function startPolling(dbId: string) {
  if (pollingMap.value[dbId]) return
  pollingMap.value[dbId] = setInterval(async () => {
    try {
      const status = await fetchBlastDatabaseBuildStatus(dbId)
      const idx = databases.value.findIndex((d) => d.id === dbId)
      if (idx >= 0) {
        databases.value[idx] = { ...databases.value[idx], ...status }
      }
      if (status.build_status === 'ready' || status.build_status === 'failed') {
        stopPolling(dbId)
        if (status.build_status === 'ready') message.success(`数据库 ${dbId.slice(0, 8)} 构建完成`)
        if (status.build_status === 'failed') message.error(`数据库 ${dbId.slice(0, 8)} 构建失败`)
      }
    } catch {
      stopPolling(dbId)
    }
  }, POLLING_INTERVAL)
}

function stopPolling(dbId: string) {
  const timer = pollingMap.value[dbId]
  if (timer) {
    clearInterval(timer)
    delete pollingMap.value[dbId]
  }
}

function handleFileChange(data: { fileList: UploadFileInfo[] }) {
  fileList.value = data.fileList
}

function resetForm() {
  form.value = {
    name: '',
    db_key: '',
    db_type: 'nucl',
    source_species: '',
    source_version: '',
    version_group: '',
    is_public: true,
  }
  fileList.value = []
}

async function handleSubmit() {
  if (!form.value.name || !form.value.db_key) {
    message.error('请填写数据库名称和标识')
    return
  }
  if (!/^[a-z0-9_]+$/.test(form.value.db_key)) {
    message.error('数据库标识只能包含小写字母、数字和下划线')
    return
  }
  const file = fileList.value[0]?.file
  if (!file) {
    message.error('请上传 FASTA 文件')
    return
  }

  submitting.value = true
  uploadProgress.value = 0
  try {
    const db = await createBlastDatabase(form.value, file, (progress) => {
      uploadProgress.value = progress
    })
    message.success(`数据库创建任务已提交：${db.name}`)
    showModal.value = false
    resetForm()
    await loadDatabases()
    startPolling(db.id)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '创建数据库失败')
  } finally {
    submitting.value = false
    uploadProgress.value = 0
  }
}

async function handleActivate(dbId: string) {
  try {
    await activateBlastDatabase(dbId)
    message.success('数据库版本已激活')
    await loadDatabases()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '激活版本失败')
  }
}

async function handleRebuild(dbId: string) {
  try {
    await rebuildBlastDatabase(dbId)
    message.info('重建任务已投递')
    await loadDatabases()
    startPolling(dbId)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '重建失败')
  }
}

async function handleDelete(dbId: string) {
  try {
    await deleteBlastDatabase(dbId)
    message.success('已删除')
    stopPolling(dbId)
    await loadDatabases()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '删除失败')
  }
}

async function handleSyncFromYaml() {
  try {
    const created = await syncBlastDatabasesFromYaml()
    message.success(`从 YAML 同步完成，新增 ${created.length} 个数据库`)
    await loadDatabases()
    created.forEach((db) => {
      if (db.build_status === 'building' || db.build_status === 'pending') {
        startPolling(db.id)
      }
    })
  } catch (err: any) {
    message.error(err?.response?.data?.detail || 'YAML 同步失败')
  }
}

async function loadStorageStats() {
  try {
    stats.value = await fetchBlastStorageStats()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '加载存储统计失败')
  }
}

async function handleCleanupOld() {
  cleanupLoading.value = true
  try {
    const result = await cleanupOldBlastTasks(7)
    message.success(result.message)
    await loadStorageStats()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '清理旧数据失败')
  } finally {
    cleanupLoading.value = false
  }
}

async function handleCleanupAll() {
  cleanupLoading.value = true
  try {
    const result = await cleanupAllBlastTasks()
    message.success(result.message)
    await loadStorageStats()
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '清理所有数据失败')
  } finally {
    cleanupLoading.value = false
  }
}

onMounted(() => {
  loadDatabases()
  loadStorageStats()
})

onUnmounted(() => {
  Object.keys(pollingMap.value).forEach(stopPolling)
})
</script>

<template>
  <div class="admin-blast-page">
    <PageHeader title="BLAST 数据库管理" subtitle="维护检索数据库、构建状态和历史任务存储" />
    <NCard title="BLAST 存储管理" class="storage-card">
      <div v-if="stats" class="stats-row">
        <NStatistic title="总任务数" :value="stats.total_tasks" />
        <NStatistic title="已完成" :value="stats.completed_tasks" />
        <NStatistic title="已清理" :value="stats.cleaned_tasks" />
        <NStatistic title="存储占用" :value="`${stats.storage_mb} MB`" />
      </div>
      <NSpin v-else size="small" />

      <NDivider />

      <NSpace>
        <NPopconfirm @positive-click="handleCleanupOld">
          <template #trigger>
            <NButton type="warning" :loading="cleanupLoading">
              清理 7 天前数据
            </NButton>
          </template>
          确认清理 7 天前完成的 BLAST 任务结果文件？保留数据库记录。
        </NPopconfirm>

        <NPopconfirm @positive-click="handleCleanupAll">
          <template #trigger>
            <NButton type="error" :loading="cleanupLoading">
              清理所有数据
            </NButton>
          </template>
          确认清理所有 BLAST 任务结果文件？此操作不可恢复！
        </NPopconfirm>
      </NSpace>
    </NCard>

    <NCard title="BLAST 数据库管理">
      <template #header-extra>
        <NSpace>
          <NButton @click="handleSyncFromYaml">
            同步 YAML
          </NButton>
          <NButton type="primary" @click="showModal = true">
            <template #icon><NIcon><AddOutline /></NIcon></template>
            新建数据库
          </NButton>
        </NSpace>
      </template>

      <NDataTable
        :columns="columns"
        :data="databases"
        :loading="loading"
        :single-line="false"
        :scroll-x="1350"
        size="small"
        :row-key="(row: BlastDatabase) => row.id"
      />
    </NCard>

    <NModal v-model:show="showModal" title="新建 BLAST 数据库" style="width: 520px;" preset="card">
      <NForm label-placement="left" label-width="100">
        <NFormItem label="数据库名称" required>
          <NInput v-model:value="form.name" placeholder="例如：水稻泛基因组 v2" />
        </NFormItem>
        <NFormItem label="数据库标识" required>
          <NInput v-model:value="form.db_key" placeholder="小写字母+下划线，例如：rice_pan_genome_v2" />
        </NFormItem>
        <NFormItem label="序列类型" required>
          <NSelect v-model:value="form.db_type" :options="[
            { label: '核酸 (nucl)', value: 'nucl' },
            { label: '蛋白 (prot)', value: 'prot' },
          ]" />
        </NFormItem>
        <NFormItem label="物种">
          <NInput v-model:value="form.source_species" placeholder="例如：Oryza sativa" />
        </NFormItem>
        <NFormItem label="版本">
          <NInput v-model:value="form.source_version" placeholder="例如：v2.1" />
        </NFormItem>
        <NFormItem label="版本族">
          <NInput v-model:value="form.version_group" placeholder="同一数据库多版本使用相同标识；默认使用数据库标识" />
        </NFormItem>
        <NFormItem label="公开可见">
          <NSwitch v-model:checked="form.is_public" />
        </NFormItem>
        <NFormItem label="FASTA 文件" required>
          <NUpload
            :default-upload="false"
            :max="1"
            accept=".fasta,.fa,.fna,.faa"
            @change="handleFileChange"
          >
            <NButton>选择文件</NButton>
          </NUpload>
        </NFormItem>
      </NForm>

      <template #footer>
        <NSpace justify="end" align="center">
          <NProgress
            v-if="submitting"
            type="line"
            :percentage="uploadProgress"
            :show-indicator="true"
            style="width: 160px;"
          />
          <NButton @click="showModal = false">取消</NButton>
          <NButton type="primary" :loading="submitting" @click="handleSubmit">提交</NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.admin-blast-page {
  padding: 16px;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.storage-card .stats-row {
  display: flex;
  flex-wrap: wrap;
  gap: 32px;
}
</style>
