<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NDatePicker, NInput, NModal, NSelect, NSpace,
  NSwitch, NTag, useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { adminNotificationApi, type NotificationPayload } from '@/api/admin/notifications'
import type { Notification, NotificationLevel } from '@/types'

const message = useMessage()
const list = ref<Notification[]>([])
const loading = ref(false)
const showEdit = ref(false)
const saving = ref(false)

interface EditForm {
  id?: string
  title: string
  content: string
  level: NotificationLevel
  is_global: boolean
  target_user_id: string
  expires_at: number | null // NDatePicker 用 timestamp
}

function emptyForm(): EditForm {
  return {
    title: '',
    content: '',
    level: 'info',
    is_global: true,
    target_user_id: '',
    expires_at: null,
  }
}

const editForm = ref<EditForm>(emptyForm())

const levelOptions = [
  { label: '信息 (info)', value: 'info' },
  { label: '警告 (warning)', value: 'warning' },
  { label: '错误 (error)', value: 'error' },
]

function fmtTime(s: string | null): string {
  if (!s) return '永久'
  const d = new Date(s)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function statusOf(n: Notification): { text: string; type: 'success' | 'default' } {
  if (n.expires_at && new Date(n.expires_at).getTime() < Date.now()) {
    return { text: '已过期', type: 'default' }
  }
  return { text: '进行中', type: 'success' }
}

const columns: DataTableColumns<Notification> = [
  { title: '标题', key: 'title', width: 200, ellipsis: { tooltip: true } },
  {
    title: '级别', key: 'level', width: 90,
    render: (r) =>
      h(
        NTag,
        {
          size: 'small',
          type: r.level === 'error' ? 'error' : r.level === 'warning' ? 'warning' : 'info',
        },
        { default: () => r.level },
      ),
  },
  {
    title: '受众', key: 'audience', width: 110,
    render: (r) => (r.is_global ? '全员' : r.target_user_id ? '定向用户' : '-'),
  },
  {
    title: '已读', key: 'read_count', width: 70,
    render: (r) => `${r.read_by.length}`,
  },
  {
    title: '过期时间', key: 'expires_at', width: 160,
    render: (r) => fmtTime(r.expires_at),
  },
  {
    title: '状态', key: 'status', width: 90,
    render: (r) => {
      const s = statusOf(r)
      return h(NTag, { size: 'small', type: s.type }, { default: () => s.text })
    },
  },
  {
    title: '操作', key: 'actions', width: 140,
    render: (row) =>
      h(NSpace, {}, {
        default: () => [
          h(NButton, { size: 'small', onClick: () => openEdit(row) }, { default: () => '编辑' }),
          h(NButton, { size: 'small', type: 'error', onClick: () => del(row.id) }, { default: () => '删除' }),
        ],
      }),
  },
]

async function fetchList() {
  loading.value = true
  try {
    list.value = await adminNotificationApi.listAll()
  } catch {
    message.error('加载通知列表失败')
  } finally {
    loading.value = false
  }
}

function openEdit(row?: Notification) {
  if (row) {
    editForm.value = {
      id: row.id,
      title: row.title,
      content: row.content,
      level: row.level,
      is_global: row.is_global,
      target_user_id: row.target_user_id || '',
      expires_at: row.expires_at ? new Date(row.expires_at).getTime() : null,
    }
  } else {
    editForm.value = emptyForm()
  }
  showEdit.value = true
}

async function save() {
  if (!editForm.value.title.trim() || !editForm.value.content.trim()) {
    message.warning('标题和内容必填')
    return
  }
  saving.value = true
  const f = editForm.value
  const payload: NotificationPayload = {
    title: f.title.trim(),
    content: f.content.trim(),
    level: f.level,
    is_global: f.is_global,
    // 全员通知时清空定向用户；定向时取输入的 UUID
    target_user_id: f.is_global ? null : f.target_user_id.trim() || null,
    expires_at: f.expires_at ? new Date(f.expires_at).toISOString() : null,
  }
  try {
    if (f.id) {
      await adminNotificationApi.update(f.id, payload)
      message.success('更新成功')
    } else {
      await adminNotificationApi.create(payload)
      message.success('发布成功')
    }
    showEdit.value = false
    await fetchList()
  } catch {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function del(id: string) {
  try {
    await adminNotificationApi.remove(id)
    message.success('已删除')
    await fetchList()
  } catch {
    message.error('删除失败')
  }
}

onMounted(fetchList)
</script>

<template>
  <NCard title="通知提醒" :bordered="false" class="arco-card">
    <template #header-extra>
      <NButton type="primary" @click="openEdit()">发布通知</NButton>
    </template>
    <NDataTable
      :columns="columns"
      :data="list"
      :row-key="(row) => row.id"
      :loading="loading"
      :pagination="{ pageSize: 20 }"
      :bordered="false"
      size="small"
    />
  </NCard>

  <NModal
    v-model:show="showEdit"
    :title="editForm.id ? '编辑通知' : '发布通知'"
    preset="dialog"
    style="width: 560px"
  >
    <NSpace vertical :size="14" style="padding: 12px 0">
      <div class="form-row">
        <label>标题 <span class="req">*</span></label>
        <NInput v-model:value="editForm.title" placeholder="通知标题" />
      </div>
      <div class="form-row">
        <label>内容 <span class="req">*</span></label>
        <NInput v-model:value="editForm.content" type="textarea" :rows="4" placeholder="通知正文" />
      </div>
      <div class="form-row-2">
        <div class="form-row">
          <label>级别</label>
          <NSelect v-model:value="editForm.level" :options="levelOptions" />
        </div>
        <div class="form-row">
          <label>过期时间（空=永久）</label>
          <NDatePicker v-model:value="editForm.expires_at" type="datetime" clearable style="width: 100%" />
        </div>
      </div>
      <div class="form-row">
        <label>全员可见</label>
        <NSwitch v-model:value="editForm.is_global" />
      </div>
      <div class="form-row" v-if="!editForm.is_global">
        <label>目标用户 ID（定向通知）</label>
        <NInput v-model:value="editForm.target_user_id" placeholder="用户 UUID" />
      </div>
      <div style="text-align: right; margin-top: 4px">
        <NButton type="primary" :loading="saving" @click="save">保存</NButton>
      </div>
    </NSpace>
  </NModal>
</template>

<style scoped>
.form-row { width: 100%; }
.form-row label {
  display: block;
  font-size: 12px;
  color: var(--neutral-text-2);
  margin-bottom: 4px;
}
.form-row .req { color: #f53f3f; }
.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
}
</style>
