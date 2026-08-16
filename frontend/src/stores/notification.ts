import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { Notification } from '@/types'

export const useNotificationStore = defineStore('notification', () => {
  const notifications = ref<Notification[]>([])
  const loading = ref(false)
  // 正在标记已读的通知 id 集合：用于防连点 + 按钮 loading 态。
  // 用“整体替换 Set”保证 .has() 的响应式追踪。
  const markingIds = ref<Set<string>>(new Set())

  const authStore = useAuthStore()
  const currentUserId = computed(() => authStore.user?.id || '')

  const unreadCount = computed(() => {
    const uid = currentUserId.value
    return notifications.value.filter((n) => !n.read_by.includes(uid)).length
  })

  /** 某条通知是否正在标记已读（供按钮 loading / 禁用） */
  function isMarking(id: string): boolean {
    return markingIds.value.has(id)
  }

  async function fetchNotifications() {
    loading.value = true
    try {
      const res = await apiClient.get<Notification[]>('/notifications')
      notifications.value = res.data
    } finally {
      loading.value = false
    }
  }

  /**
   * 标记单条通知已读。
   * - 防连点：同一条通知在途时直接返回，不重复发请求。
   * - 错误向上抛出：由调用方（组件）决定如何提示用户。
   * - 局部更新：用接口返回的最新通知替换列表对应项，避免整表重拉。
   */
  async function markRead(id: string) {
    if (markingIds.value.has(id)) return
    const next = new Set(markingIds.value)
    next.add(id)
    markingIds.value = next
    try {
      const res = await apiClient.patch<Notification>(`/notifications/${id}/read`)
      const idx = notifications.value.findIndex((n) => n.id === id)
      if (idx >= 0) {
        notifications.value[idx] = res.data
      }
    } finally {
      const after = new Set(markingIds.value)
      after.delete(id)
      markingIds.value = after
    }
  }

  async function createNotification(payload: {
    title: string
    content: string
    level: string
    is_global: boolean
    target_user_id?: string
    expires_at?: string | null
  }) {
    const res = await apiClient.post<Notification>('/notifications', payload)
    notifications.value.unshift(res.data)
    return res.data
  }

  async function deleteNotification(id: string) {
    await apiClient.delete(`/notifications/${id}`)
    notifications.value = notifications.value.filter((n) => n.id !== id)
  }

  function isRead(notification: Notification): boolean {
    return notification.read_by.includes(currentUserId.value)
  }

  return {
    notifications,
    loading,
    markingIds,
    unreadCount,
    fetchNotifications,
    markRead,
    createNotification,
    deleteNotification,
    isRead,
    isMarking,
  }
})
