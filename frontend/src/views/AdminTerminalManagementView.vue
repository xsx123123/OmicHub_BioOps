<script setup lang="ts">
import apiClient from '@/api/client'
import {
  NButton,
  NCard,
  NDataTable,
  NPopconfirm,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import { h, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import { displayName } from '@/utils/displayName'

interface TerminalStats {
  cpu_percent: number
  memory_usage_mb: number
  memory_limit_mb: number
  memory_percent: number
  pids: number
}

interface AdminTerminalSession {
  id: string
  user_id: string
  username: string | null
  nickname: string | null
  session_id: string
  status: string
  container_id: string | null
  container_name: string | null
  host_port: number | null
  ws_url: string | null
  created_at: string
  last_activity: string
  expires_at: string | null
  usage_seconds: number
  image_id: string | null
  image_name: string | null
  resources: {
    memory_mb: number | null
    cpu_cores: number | null
    pid_limit: number | null
  } | null
  stats: TerminalStats | null
}

const message = useMessage()
const sessions = ref<AdminTerminalSession[]>([])
const loading = ref(false)
const includeStats = ref(false)

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN')
}

const columns = [
  {
    title: '用户',
    key: 'username',
    width: 120,
    render: (row: AdminTerminalSession) => displayName(row) || row.user_id.slice(0, 8),
  },
  { title: '会话 ID', key: 'session_id', ellipsis: { tooltip: true }, width: 160 },
  {
    title: '状态',
    key: 'status',
    width: 90,
    render: (row: AdminTerminalSession) =>
      h(
        NTag,
        { type: row.status === 'running' ? 'success' : 'default', size: 'small' },
        { default: () => row.status }
      ),
  },
  {
    title: '镜像',
    key: 'image_name',
    width: 140,
    render: (row: AdminTerminalSession) => row.image_name || row.image_id || '-',
  },
  {
    title: '容器名称',
    key: 'container_name',
    ellipsis: { tooltip: true },
    width: 220,
    render: (row: AdminTerminalSession) => row.container_name || '-',
  },
  {
    title: '已使用时长',
    key: 'usage_seconds',
    width: 120,
    render: (row: AdminTerminalSession) => formatDuration(row.usage_seconds),
  },
  {
    title: '资源配额',
    key: 'resources',
    width: 160,
    render: (row: AdminTerminalSession) => {
      const r = row.resources
      if (!r) return '-'
      return `CPU: ${r.cpu_cores ?? '-'} 核 / 内存: ${r.memory_mb ?? '-'} MB / PID: ${r.pid_limit ?? '-'}`
    },
  },
  {
    title: '实时占用',
    key: 'stats',
    width: 220,
    render: (row: AdminTerminalSession) => {
      if (!includeStats.value) return h('span', { style: 'color: #999' }, '未开启')
      const s = row.stats
      if (!s) return h('span', { style: 'color: #999' }, '无数据')
      return `CPU ${s.cpu_percent}% / 内存 ${s.memory_percent}% (${s.memory_usage_mb}/${s.memory_limit_mb} MB) / PID ${s.pids}`
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 170,
    render: (row: AdminTerminalSession) => formatDate(row.created_at),
  },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    render: (row: AdminTerminalSession) =>
      h(
        NPopconfirm,
        {
          onPositiveClick: () => destroySession(row.session_id),
        },
        {
          trigger: () =>
            h(
              NButton,
              { size: 'small', type: 'error' },
              { default: () => '销毁' }
            ),
          default: () => `确定销毁容器 ${row.container_name || row.session_id}？`,
        }
      ),
  },
]

async function fetchSessions() {
  loading.value = true
  try {
    const res = await apiClient.get<AdminTerminalSession[]>('/admin/terminals', {
      params: { include_stats: includeStats.value },
    })
    sessions.value = res.data
  } finally {
    loading.value = false
  }
}

async function destroySession(sessionId: string) {
  try {
    await apiClient.delete(`/admin/terminals/${sessionId}`)
    message.success('会话已销毁')
    await fetchSessions()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '销毁失败')
  }
}

onMounted(fetchSessions)
</script>

<template>
  <div class="page-container">
    <PageHeader title="沙盒终端管理" subtitle="查看运行中的终端会话与资源占用" />
    <NSpace vertical :size="24">
      <NCard title="活跃终端会话" :bordered="false" class="arco-card">
        <template #header-extra>
          <NSpace align="center">
            <span style="color: #666; font-size: 14px">显示实时占用</span>
            <NSwitch v-model:value="includeStats" @update:value="fetchSessions" />
            <NButton type="primary" @click="fetchSessions" :loading="loading">刷新</NButton>
          </NSpace>
        </template>
        <NDataTable
          :columns="columns"
          :data="sessions"
          :row-key="(row) => row.id"
          :loading="loading"
          :pagination="{ pageSize: 20 }"
          :bordered="false"
          size="small"
          :scroll-x="1200"
        />
      </NCard>
    </NSpace>
  </div>
</template>

<style scoped>
.page-container {
  padding: 24px;
  min-height: 100%;
  background: var(--neutral-bg);
}
.page-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0 0 24px;
}
</style>
