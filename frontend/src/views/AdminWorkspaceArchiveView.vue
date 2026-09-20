<script setup lang="ts">
/**
 * AdminWorkspaceArchiveView — 工作区归档管理（WP1）
 *
 * 总览：平台归档总量/总包数、工作区总量、当前 retention/quota 配置；
 * 到期提醒（expiring_soon）、每用户用量排行；
 * 操作：按 session_id 强制休眠、按 package_id 删除归档包、配置编辑（PUT config）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import PageHeader from '@/components/PageHeader.vue'
import {
  adminWorkspaceArchiveApi,
  type WorkspaceArchiveOverview,
  type WorkspaceArchiveConfig,
} from '@/api/admin/workspaceArchive'

const message = useMessage()
const loading = ref(false)
const overview = ref<WorkspaceArchiveOverview | null>(null)

const expiringColumns: DataTableColumns<WorkspaceArchiveOverview['expiring_soon'][number]> = [
  { title: '用户', key: 'username' },
  { title: '会话', key: 'session_id', ellipsis: { tooltip: true } },
  { title: '归档包', key: 'package_id', ellipsis: { tooltip: true } },
  {
    title: '到期时间',
    key: 'expires_at',
    render: (row) => formatDateTime(row.expires_at),
  },
]

const userColumns: DataTableColumns<WorkspaceArchiveOverview['per_user'][number]> = [
  { title: '用户', key: 'username' },
  {
    title: '工作区占用',
    key: 'workspace_bytes',
    sorter: (a, b) => a.workspace_bytes - b.workspace_bytes,
    render: (row) => formatBytes(row.workspace_bytes),
  },
  {
    title: '归档占用',
    key: 'archive_bytes',
    sorter: (a, b) => a.archive_bytes - b.archive_bytes,
    render: (row) => formatBytes(row.archive_bytes),
  },
  { title: '归档包数', key: 'package_count', align: 'center' },
  { title: '会话数', key: 'session_count', align: 'center' },
]

/** 操作区：强制休眠 / 删除归档包（overview 不含会话清单，按 ID 输入，不扩后端契约） */
const dormantSessionId = ref('')
const dormanting = ref(false)
const deletePackageId = ref('')
const deletingPackage = ref(false)

const configForm = reactive<Required<WorkspaceArchiveConfig>>({
  workspace_gb: 0,
  archive_gb: 0,
  active_days: 0,
  dormant_days: 0,
  archive_retention_days: 0,
})
const savingConfig = ref(false)

const overviewStats = computed(() => [
  { label: '平台归档总量', value: formatBytes(overview.value?.archive_total_bytes ?? 0) },
  { label: '归档包总数', value: String(overview.value?.archive_total_packages ?? 0) },
  { label: '工作区总量', value: formatBytes(overview.value?.workspace_total_bytes ?? 0) },
  {
    label: '配额（工作区 / 归档）',
    value: overview.value
      ? `${overview.value.quota.workspace_gb} GB / ${overview.value.quota.archive_gb} GB`
      : '-',
  },
  {
    label: '休眠策略（活跃/休眠/保留）',
    value: overview.value
      ? `${overview.value.active_days} / ${overview.value.dormant_days} / ${overview.value.archive_retention_days} 天`
      : '-',
  },
])

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  const gb = bytes / 1024 ** 3
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  const mb = bytes / 1024 ** 2
  if (mb >= 1) return `${mb.toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function formatDateTime(value: string): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function applyOverview(data: WorkspaceArchiveOverview): void {
  overview.value = data
  configForm.workspace_gb = data.quota.workspace_gb
  configForm.archive_gb = data.quota.archive_gb
  configForm.active_days = data.active_days
  configForm.dormant_days = data.dormant_days
  configForm.archive_retention_days = data.archive_retention_days
}

async function fetchOverview(): Promise<void> {
  loading.value = true
  try {
    applyOverview(await adminWorkspaceArchiveApi.getOverview())
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '归档总览加载失败')
  } finally {
    loading.value = false
  }
}

async function forceDormant(): Promise<void> {
  const id = dormantSessionId.value.trim()
  if (!id) {
    message.warning('请输入要强制休眠的 session_id')
    return
  }
  dormanting.value = true
  try {
    await adminWorkspaceArchiveApi.dormantSession(id)
    message.success('该会话工作区已进入休眠归档')
    dormantSessionId.value = ''
    await fetchOverview()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '强制休眠失败')
  } finally {
    dormanting.value = false
  }
}

async function removePackage(): Promise<void> {
  const id = deletePackageId.value.trim()
  if (!id) {
    message.warning('请输入要删除的 package_id')
    return
  }
  deletingPackage.value = true
  try {
    await adminWorkspaceArchiveApi.deletePackage(id)
    message.success('归档包已删除')
    deletePackageId.value = ''
    await fetchOverview()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '删除归档包失败')
  } finally {
    deletingPackage.value = false
  }
}

async function saveConfig(): Promise<void> {
  savingConfig.value = true
  try {
    await adminWorkspaceArchiveApi.updateConfig({ ...configForm })
    message.success('配置已生效')
    await fetchOverview()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '配置保存失败')
  } finally {
    savingConfig.value = false
  }
}

onMounted(fetchOverview)
</script>

<template>
  <div class="page-container">
    <PageHeader title="工作区归档管理" subtitle="会话工作区休眠归档的容量、配额与到期治理" />

    <div class="stats-grid" aria-label="总览">
      <div v-for="stat in overviewStats" :key="stat.label" class="stat-card">
        <span class="stat-label">{{ stat.label }}</span>
        <span class="stat-value">{{ stat.value }}</span>
      </div>
    </div>

    <NCard title="到期提醒（7 天内）" :bordered="false" class="arco-card">
      <NDataTable
        :columns="expiringColumns"
        :data="overview?.expiring_soon || []"
        :loading="loading"
        :row-key="(row) => row.package_id"
        :bordered="false"
        size="small"
      />
      <p v-if="!loading && !(overview?.expiring_soon || []).length" class="empty-hint">
        暂无临近过期的归档包
      </p>
    </NCard>

    <NCard title="每用户用量排行" :bordered="false" class="arco-card">
      <NDataTable
        :columns="userColumns"
        :data="overview?.per_user || []"
        :loading="loading"
        :row-key="(row) => row.user_id"
        :bordered="false"
        size="small"
        :pagination="{ pageSize: 20 }"
      />
    </NCard>

    <NCard title="操作" :bordered="false" class="arco-card">
      <div class="action-row">
        <span class="action-label">强制休眠会话工作区</span>
        <NInput
          v-model:value="dormantSessionId"
          placeholder="输入 session_id"
          class="action-input"
          clearable
        />
        <NButton
          type="warning"
          ghost
          :loading="dormanting"
          :disabled="!dormantSessionId.trim()"
          @click="forceDormant"
        >强制休眠</NButton>
      </div>
      <div class="action-row">
        <span class="action-label">删除归档包</span>
        <NInput
          v-model:value="deletePackageId"
          placeholder="输入 package_id"
          class="action-input"
          clearable
        />
        <NPopconfirm @positive-click="removePackage">
          <template #trigger>
            <NButton
              type="error"
              ghost
              :loading="deletingPackage"
              :disabled="!deletePackageId.trim()"
            >删除归档包</NButton>
          </template>
          删除后该归档包不可恢复，确定继续吗？
        </NPopconfirm>
      </div>
    </NCard>

    <NCard title="配置" :bordered="false" class="arco-card">
      <NForm label-placement="left" label-width="auto" class="config-form">
        <NFormItem label="工作区配额 (GB)">
          <NInputNumber v-model:value="configForm.workspace_gb" :min="0" class="config-input" />
        </NFormItem>
        <NFormItem label="归档配额 (GB)">
          <NInputNumber v-model:value="configForm.archive_gb" :min="0" class="config-input" />
        </NFormItem>
        <NFormItem label="活跃天数">
          <NInputNumber v-model:value="configForm.active_days" :min="0" class="config-input" />
        </NFormItem>
        <NFormItem label="休眠天数">
          <NInputNumber v-model:value="configForm.dormant_days" :min="0" class="config-input" />
        </NFormItem>
        <NFormItem label="归档保留天数">
          <NInputNumber
            v-model:value="configForm.archive_retention_days"
            :min="0"
            class="config-input"
          />
        </NFormItem>
        <NFormItem>
          <NButton type="primary" :loading="savingConfig" @click="saveConfig">保存配置</NButton>
        </NFormItem>
      </NForm>
    </NCard>
  </div>
</template>

<style scoped lang="scss">
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  border: 1px solid var(--neutral-border);
  border-radius: 10px;
  background: var(--bg-card);
}

.stat-label {
  color: var(--text-tertiary);
  font-size: 12px;
}

.stat-value {
  color: var(--text-primary);
  font-size: 18px;
  font-weight: 650;
}

.empty-hint {
  margin: 8px 0 0;
  color: var(--text-tertiary);
  font-size: 12px;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;

  &:last-child {
    margin-bottom: 0;
  }
}

.action-label {
  flex: 0 0 auto;
  width: 160px;
  color: var(--text-secondary);
  font-size: 13px;
}

.action-input {
  max-width: 360px;
}

.config-form {
  max-width: 420px;
}

.config-input {
  width: 180px;
}
</style>
