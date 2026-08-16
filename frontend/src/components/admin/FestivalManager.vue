<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NInput,
  NInputNumber,
  NModal,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { adminFestivalApi } from '@/api/admin/festival'
import FestivalPopup from '@/components/FestivalPopup.vue'
import type { FestivalConfig, FestivalAdminUpdateRequest } from '@/types/festival'

const message = useMessage()
const list = ref<FestivalConfig[]>([])
const globalEnabled = ref(true)
const loading = ref(false)
const showEdit = ref(false)
const saving = ref(false)

const editForm = ref<FestivalAdminUpdateRequest & { id?: string }>({})
const showPreview = ref(false)
const previewFestival = ref<FestivalConfig | null>(null)

const calendarTypeLabels: Record<string, string> = {
  lunar: '农历',
  solar: '公历',
  solar_term: '节气',
}

const columns: DataTableColumns<FestivalConfig> = [
  {
    title: '名称',
    key: 'name',
    width: 180,
    render: (r) => `${r.name}`,
  },
  {
    title: '类型',
    key: 'calendarType',
    width: 80,
    render: (r) => calendarTypeLabels[r.calendarType] || r.calendarType,
  },
  {
    title: '弹窗',
    key: 'popup',
    width: 80,
    render: (r) => (r.popup.enabled ? '✅' : '—'),
  },
  {
    title: '额度',
    key: 'quota',
    width: 80,
    render: (r) => (r.quotaBonus.enabled ? `+${Math.floor(r.quotaBonus.amount)}` : '—'),
  },
  {
    title: '优先级',
    key: 'priority',
    width: 80,
  },
  {
    title: '状态',
    key: 'status',
    width: 90,
    render: (r) =>
      h(
        NTag,
        { size: 'small', type: r.enabled ? 'success' : 'default' },
        { default: () => (r.enabled ? '已启用' : '已停用') },
      ),
  },
  {
    title: '操作',
    key: 'actions',
    width: 180,
    render: (row) =>
      h(NSpace, {}, {
        default: () => [
          h(NButton, { size: 'small', onClick: () => openPreview(row) }, { default: () => '预览' }),
          h(NButton, { size: 'small', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        ],
      }),
  },
]

async function fetchList() {
  loading.value = true
  try {
    const res = await adminFestivalApi.list()
    globalEnabled.value = res.globalEnabled
    list.value = res.festivals
  } catch {
    message.error('加载节日列表失败')
  } finally {
    loading.value = false
  }
}

function openPreview(row: FestivalConfig) {
  previewFestival.value = row
  showPreview.value = true
}

function openEdit(row: FestivalConfig) {
  editForm.value = {
    id: row.id,
    enabled: row.enabled,
    priority: row.priority,
    popup: {
      enabled: row.popup.enabled,
      title: row.popup.title,
      content: row.popup.content,
      animation: row.popup.animation
        ? {
            enabled: row.popup.animation.enabled,
            type: row.popup.animation.type,
            duration: row.popup.animation.duration,
          }
        : undefined,
    },
    quotaBonus: {
      enabled: row.quotaBonus.enabled,
      amount: row.quotaBonus.amount,
    },
  }
  showEdit.value = true
}

async function save() {
  if (!editForm.value.id) return
  saving.value = true
  try {
    await adminFestivalApi.update(editForm.value.id, editForm.value)
    message.success('保存成功')
    showEdit.value = false
    await fetchList()
  } catch {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function reloadConfig() {
  try {
    await adminFestivalApi.reload()
    message.success('配置已重载')
    await fetchList()
  } catch {
    message.error('重载失败')
  }
}

onMounted(fetchList)
</script>

<template>
  <NCard title="节日彩蛋" :bordered="false" class="arco-card">
    <template #header-extra>
      <NSpace>
        <NButton @click="reloadConfig">刷新配置</NButton>
        <NTag :type="globalEnabled ? 'success' : 'default'">
          {{ globalEnabled ? '系统总开关：开启' : '系统总开关：关闭' }}
        </NTag>
      </NSpace>
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
    title="编辑节日"
    preset="dialog"
    style="width: 600px"
  >
    <NSpace vertical :size="14" style="padding: 12px 0">
      <div class="form-row">
        <label>启用状态</label>
        <NSwitch v-model:value="editForm.enabled" />
      </div>
      <div class="form-row">
        <label>优先级</label>
        <NInputNumber v-model:value="editForm.priority" :min="0" :max="1000" style="width: 100%" />
      </div>

      <div class="form-row">
        <label>弹窗标题</label>
        <NInput v-model:value="editForm.popup!.title" />
      </div>
      <div class="form-row">
        <label>弹窗内容（支持 <span v-pre>{{bonusAmount}}</span>）</label>
        <NInput
          v-model:value="editForm.popup!.content"
          type="textarea"
          :rows="3"
        />
      </div>
      <div class="form-row-2">
        <div class="form-row">
          <label>启用动画</label>
          <NSwitch v-model:value="editForm.popup!.animation!.enabled" />
        </div>
        <div class="form-row">
          <label>动画持续（秒）</label>
          <NInputNumber v-model:value="editForm.popup!.animation!.duration" :min="1" :max="120" style="width: 100%" />
        </div>
      </div>

      <div class="form-row-2">
        <div class="form-row">
          <label>赠送额度</label>
          <NSwitch v-model:value="editForm.quotaBonus!.enabled" />
        </div>
        <div class="form-row">
          <label>赠送数量</label>
          <NInputNumber v-model:value="editForm.quotaBonus!.amount" :min="0" style="width: 100%" />
        </div>
      </div>

      <div style="text-align: right; margin-top: 4px">
        <NButton type="primary" :loading="saving" @click="save">保存</NButton>
      </div>
    </NSpace>
  </NModal>

  <FestivalPopup
    v-if="previewFestival"
    :festival="previewFestival"
    :preview="true"
    @close="showPreview = false; previewFestival = null"
  />
</template>

<style scoped>
.form-row { width: 100%; }
.form-row label {
  display: block;
  font-size: 12px;
  color: var(--neutral-text-2);
  margin-bottom: 4px;
}
.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
}
</style>
