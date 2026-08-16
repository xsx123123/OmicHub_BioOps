<script setup lang="ts">
import { h, onMounted, ref, computed } from 'vue'
import {
  NButton, NCard, NDataTable, NDatePicker, NInput, NInputNumber, NModal,
  NSelect, NSpace, NSwitch, NTag, useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { adminAnnouncementApi } from '@/api/admin/announcements'
import {
  DEFAULT_ICON_BY_TYPE,
  type Announcement,
  type AnnouncementType,
  type DismissBehavior,
} from '@/types/announcement'

const message = useMessage()
const list = ref<Announcement[]>([])
const loading = ref(false)
const showEdit = ref(false)
const saving = ref(false)

interface EditForm {
  id?: string
  title: string
  description: string
  type: AnnouncementType
  icon: string
  link: string
  button_text: string
  start_time: number | null // NDatePicker 用 timestamp
  end_time: number | null
  dismiss_behavior: DismissBehavior
  priority: number
  is_enabled: boolean
}

function emptyForm(): EditForm {
  return {
    title: '',
    description: '',
    type: 'info',
    icon: '',
    link: '',
    button_text: '立即查看',
    start_time: Date.now(),
    end_time: null,
    dismiss_behavior: 'daily',
    priority: 0,
    is_enabled: true,
  }
}

const editForm = ref<EditForm>(emptyForm())

const typeOptions = [
  { label: '信息 (info)', value: 'info' },
  { label: '成功/上线 (success)', value: 'success' },
  { label: '维护/提醒 (warning)', value: 'warning' },
  { label: '新功能 (feature)', value: 'feature' },
]
const dismissOptions = [
  { label: '可关闭（当天不再显示）', value: 'daily' },
  { label: '可关闭（永久不再显示）', value: 'forever' },
  { label: '不可关闭', value: 'none' },
]

function statusOf(a: Announcement): {
  text: string
  type: 'success' | 'default' | 'info'
} {
  if (!a.is_enabled) return { text: '已停用', type: 'default' }
  const now = Date.now()
  const start = new Date(a.start_time).getTime()
  const end = a.end_time ? new Date(a.end_time).getTime() : null
  if (now < start) return { text: '待开始', type: 'info' }
  if (end !== null && now > end) return { text: '已结束', type: 'default' }
  return { text: '进行中', type: 'success' }
}

function fmtTime(s: string | null | undefined): string {
  if (!s) return '永久'
  const d = new Date(s)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const columns: DataTableColumns<Announcement> = [
  { title: '标题', key: 'title', width: 220, ellipsis: { tooltip: true } },
  {
    title: '类型', key: 'type', width: 100,
    render: (r) =>
      h(
        NTag,
        {
          size: 'small',
          type: r.type === 'warning' ? 'warning' : r.type === 'success' ? 'success' : r.type === 'feature' ? 'info' : 'default',
        },
        { default: () => r.type },
      ),
  },
  {
    title: '状态', key: 'status', width: 90,
    render: (r) => {
      const s = statusOf(r)
      return h(NTag, { size: 'small', type: s.type }, { default: () => s.text })
    },
  },
  { title: '优先级', key: 'priority', width: 80 },
  {
    title: '展示时间', key: 'time', width: 240,
    render: (r) => `${fmtTime(r.start_time)} ~ ${fmtTime(r.end_time)}`,
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
    list.value = await adminAnnouncementApi.list()
  } catch {
    message.error('加载通知列表失败')
  } finally {
    loading.value = false
  }
}

function openEdit(row?: Announcement) {
  if (row) {
    editForm.value = {
      id: row.id,
      title: row.title,
      description: row.description,
      type: row.type,
      icon: row.icon || '',
      link: row.link || '',
      button_text: row.button_text || '',
      start_time: new Date(row.start_time).getTime(),
      end_time: row.end_time ? new Date(row.end_time).getTime() : null,
      dismiss_behavior: row.dismiss_behavior,
      priority: row.priority,
      is_enabled: row.is_enabled,
    }
  } else {
    editForm.value = emptyForm()
  }
  showEdit.value = true
}

async function save() {
  if (!editForm.value.title.trim() || !editForm.value.description.trim()) {
    message.warning('标题和描述必填')
    return
  }
  // 取局部变量以便 TS 收窄 null（直接访问对象属性不会收窄）
  const startTs = editForm.value.start_time
  if (startTs === null) {
    message.warning('请选择开始时间')
    return
  }
  saving.value = true
  const f = editForm.value
  const payload = {
    title: f.title.trim(),
    description: f.description.trim(),
    type: f.type,
    icon: f.icon || null,
    link: f.link || null,
    button_text: f.button_text || null,
    start_time: new Date(startTs).toISOString(),
    end_time: f.end_time ? new Date(f.end_time).toISOString() : null,
    dismiss_behavior: f.dismiss_behavior,
    priority: f.priority,
    is_enabled: f.is_enabled,
  }
  try {
    if (f.id) {
      await adminAnnouncementApi.update(f.id, payload)
      message.success('更新成功')
    } else {
      await adminAnnouncementApi.create(payload)
      message.success('创建成功')
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
    await adminAnnouncementApi.remove(id)
    message.success('已删除')
    await fetchList()
  } catch {
    message.error('删除失败')
  }
}

const previewIcon = computed(
  () => editForm.value.icon || DEFAULT_ICON_BY_TYPE[editForm.value.type] || '📢',
)

onMounted(fetchList)
</script>

<template>
  <NCard title="首页条幅通知" :bordered="false" class="arco-card">
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
    :title="editForm.id ? '编辑条幅' : '发布条幅'"
    preset="dialog"
    style="width: 660px"
  >
    <NSpace vertical :size="14" style="padding: 12px 0">
      <!-- 实时预览（与首页 AnnouncementBanner 1:1） -->
      <div class="preview-label">实时预览</div>
      <div class="preview-banner" :class="`banner-${editForm.type}`">
        <div class="preview-icon">{{ previewIcon }}</div>
        <div class="preview-content">
          <div class="preview-title">{{ editForm.title || '通知标题' }}</div>
          <div class="preview-desc">{{ editForm.description || '通知描述' }}</div>
        </div>
        <div class="preview-actions">
          <span class="preview-btn">{{ editForm.button_text || '立即查看' }}</span>
          <span class="preview-close">✕</span>
        </div>
      </div>

      <div class="form-row">
        <label>标题 <span class="req">*</span></label>
        <NInput v-model:value="editForm.title" :maxlength="30" show-count placeholder="最多 30 字" />
      </div>
      <div class="form-row">
        <label>描述 <span class="req">*</span></label>
        <NInput v-model:value="editForm.description" :maxlength="60" show-count placeholder="最多 60 字" />
      </div>
      <div class="form-row-2">
        <div class="form-row">
          <label>类型</label>
          <NSelect v-model:value="editForm.type" :options="typeOptions" />
        </div>
        <div class="form-row">
          <label>图标（emoji，留空按类型）</label>
          <NInput v-model:value="editForm.icon" placeholder="🎉 / 📢 / 🚀" />
        </div>
      </div>
      <div class="form-row-2">
        <div class="form-row">
          <label>跳转链接</label>
          <NInput v-model:value="editForm.link" placeholder="/flows 或 https://..." />
        </div>
        <div class="form-row">
          <label>按钮文字</label>
          <NInput v-model:value="editForm.button_text" placeholder="立即查看" />
        </div>
      </div>
      <div class="form-row-2">
        <div class="form-row">
          <label>开始时间 <span class="req">*</span></label>
          <NDatePicker v-model:value="editForm.start_time" type="datetime" clearable style="width: 100%" />
        </div>
        <div class="form-row">
          <label>结束时间（空=永久）</label>
          <NDatePicker v-model:value="editForm.end_time" type="datetime" clearable style="width: 100%" />
        </div>
      </div>
      <div class="form-row-2">
        <div class="form-row">
          <label>关闭行为</label>
          <NSelect v-model:value="editForm.dismiss_behavior" :options="dismissOptions" />
        </div>
        <div class="form-row">
          <label>优先级（0-100）</label>
          <NInputNumber v-model:value="editForm.priority" :min="0" :max="100" style="width: 100%" />
        </div>
      </div>
      <div class="form-row">
        <label>启用状态</label>
        <NSwitch v-model:value="editForm.is_enabled" />
      </div>
      <div style="text-align: right; margin-top: 4px">
        <NButton type="primary" :loading="saving" @click="save">保存</NButton>
      </div>
    </NSpace>
  </NModal>
</template>

<style scoped>
.preview-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--neutral-text-3);
}

.preview-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 12px;
  color: #fff;
}
.banner-info { background: linear-gradient(90deg, #3b82f6, #7c3aed, #a855f7); }
.banner-success { background: linear-gradient(90deg, #34d399, #14b8a6); }
.banner-warning { background: linear-gradient(90deg, #fbbf24, #f97316); }
.banner-feature { background: linear-gradient(90deg, #e879f9, #a855f7); }

.preview-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}
.preview-content { flex: 1; min-width: 0; }
.preview-title {
  font-size: 15px;
  font-weight: 600;
  line-height: 20px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.preview-desc {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}
.preview-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.preview-btn {
  background: #fff;
  color: #7c3aed;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
}
.preview-close {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.18);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}

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
