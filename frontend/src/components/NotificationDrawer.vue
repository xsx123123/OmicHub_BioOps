<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  NDrawer, NDrawerContent, NButton, NIcon, NSpace, NEmpty, NTag, NForm, NFormItem,
  NInput, NSelect, NSwitch, NSpin, NPopconfirm, useMessage,
} from 'naive-ui'
import {
  NotificationsOutline, CheckmarkOutline, TrashOutline, AddOutline,
  InformationCircleOutline, WarningOutline, AlertCircleOutline,
} from '@vicons/ionicons5'
import { useNotificationStore } from '@/stores/notification'
import { useAuthStore } from '@/stores/auth'
import type { Notification, NotificationLevel } from '@/types'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
}>()

const store = useNotificationStore()
const authStore = useAuthStore()
const message = useMessage()
const isAdmin = computed(() => authStore.user?.role === 'admin')
const showCreateForm = ref(false)
const submitting = ref(false)

const levelOptions = [
  { label: '普通', value: 'info' },
  { label: '警告', value: 'warning' },
  { label: '重要', value: 'error' },
]

const createForm = ref({
  title: '',
  content: '',
  level: 'info' as NotificationLevel,
  is_global: true,
  target_user_id: '',
  expires_at: null as string | null,
})

watch(
  () => props.show,
  (visible) => {
    if (visible) store.fetchNotifications()
  }
)

function levelTagType(level: NotificationLevel) {
  const map: Record<NotificationLevel, 'info' | 'warning' | 'error'> = {
    info: 'info',
    warning: 'warning',
    error: 'error',
  }
  return map[level] || 'default'
}

function levelIcon(level: NotificationLevel) {
  if (level === 'warning') return WarningOutline
  if (level === 'error') return AlertCircleOutline
  return InformationCircleOutline
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function handleMarkRead(n: Notification) {
  // 已读 / 正在标记中：直接跳过，避免重复请求
  if (store.isRead(n) || store.isMarking(n.id)) return
  try {
    await store.markRead(n.id)
  } catch (e: any) {
    message.error(e.response?.data?.detail || '标记已读失败，请稍后重试')
  }
}

async function handleCreate() {
  if (!createForm.value.title.trim() || !createForm.value.content.trim()) return
  submitting.value = true
  try {
    await store.createNotification({
      title: createForm.value.title.trim(),
      content: createForm.value.content.trim(),
      level: createForm.value.level,
      is_global: createForm.value.is_global,
      target_user_id: createForm.value.is_global ? undefined : createForm.value.target_user_id.trim() || undefined,
      expires_at: createForm.value.expires_at,
    })
    showCreateForm.value = false
    createForm.value = {
      title: '',
      content: '',
      level: 'info',
      is_global: true,
      target_user_id: '',
      expires_at: null,
    }
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: string) {
  await store.deleteNotification(id)
}
</script>

<template>
  <NDrawer
    :show="props.show"
    @update:show="(v: boolean) => emit('update:show', v)"
    :width="380"
    placement="right"
  >
    <NDrawerContent
      title="通知提醒"
      body-content-style="padding: 0; display: flex; flex-direction: column;"
    >
      <div class="notification-drawer">
        <div class="notification-header">
          <NSpace>
            <NButton
              v-if="isAdmin"
              type="primary"
              size="small"
              @click="showCreateForm = !showCreateForm"
            >
              <template #icon>
                <NIcon><AddOutline /></NIcon>
              </template>
              {{ showCreateForm ? '取消' : '发布通知' }}
            </NButton>
            <NButton size="small" @click="store.fetchNotifications">
              刷新
            </NButton>
          </NSpace>
        </div>

        <div v-if="showCreateForm" class="create-form">
          <NForm label-placement="top">
            <NFormItem label="标题">
              <NInput v-model:value="createForm.title" placeholder="通知标题" />
            </NFormItem>
            <NFormItem label="内容">
              <NInput
                v-model:value="createForm.content"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 6 }"
                placeholder="通知内容"
              />
            </NFormItem>
            <NFormItem label="级别">
              <NSelect v-model:value="createForm.level" :options="levelOptions" />
            </NFormItem>
            <NFormItem label="全员通知">
              <NSwitch v-model:value="createForm.is_global" />
            </NFormItem>
            <NFormItem v-if="!createForm.is_global" label="目标用户 ID">
              <NInput v-model:value="createForm.target_user_id" placeholder="留空则仅自己可见" />
            </NFormItem>
            <NButton type="primary" :loading="submitting" @click="handleCreate">
              发布
            </NButton>
          </NForm>
        </div>

        <div v-if="store.loading" class="notification-loading">
          <NSpin size="small" /> 加载中…
        </div>

        <div v-else-if="!store.notifications.length" class="notification-empty">
          <NEmpty description="暂无通知">
            <template #icon>
              <NIcon :size="48"><NotificationsOutline /></NIcon>
            </template>
          </NEmpty>
        </div>

        <div v-else class="notification-list">
          <div
            v-for="n in store.notifications"
            :key="n.id"
            class="notification-item"
            :class="{ 'notification-item--unread': !store.isRead(n) }"
          >
            <div class="notification-item-header">
              <NSpace align="center" size="small">
                <NIcon :size="18" :component="levelIcon(n.level)" />
                <span class="notification-title">{{ n.title }}</span>
                <NTag :type="levelTagType(n.level)" size="small" round>
                  {{ n.level === 'info' ? '普通' : n.level === 'warning' ? '警告' : '重要' }}
                </NTag>
              </NSpace>
              <span class="notification-time">{{ formatTime(n.created_at) }}</span>
            </div>
            <p class="notification-content">{{ n.content }}</p>
            <div class="notification-actions">
              <NButton
                v-if="!store.isRead(n)"
                text
                size="tiny"
                :loading="store.isMarking(n.id)"
                :disabled="store.isMarking(n.id)"
                @click="handleMarkRead(n)"
              >
                <template #icon><NIcon><CheckmarkOutline /></NIcon></template>
                标记已读
              </NButton>
              <NPopconfirm v-if="isAdmin" @positive-click="handleDelete(n.id)">
                <template #trigger>
                  <NButton text size="tiny" type="error">
                    <template #icon><NIcon><TrashOutline /></NIcon></template>
                    删除
                  </NButton>
                </template>
                确定删除这条通知吗？
              </NPopconfirm>
            </div>
          </div>
        </div>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.notification-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.notification-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--neutral-border);
}
.create-form {
  padding: 16px;
  border-bottom: 1px solid var(--neutral-border);
  background: var(--neutral-card);
}
.notification-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px;
  color: var(--neutral-text-3);
}
.notification-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.notification-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}
.notification-item {
  padding: 12px 16px;
  border-bottom: 1px solid var(--neutral-border);
  transition: background 0.2s ease;
}
.notification-item:hover {
  background: var(--neutral-hover);
}
.notification-item--unread {
  background: var(--arco-primary-light);
}
.notification-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.notification-title {
  font-weight: 500;
  font-size: 14px;
  color: var(--neutral-text-1);
}
.notification-time {
  font-size: 12px;
  color: var(--neutral-text-3);
  white-space: nowrap;
}
.notification-content {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--neutral-text-2);
  white-space: pre-wrap;
}
.notification-actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}
</style>
