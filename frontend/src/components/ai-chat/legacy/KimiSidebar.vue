<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NIcon, NAvatar, NTag } from 'naive-ui'
import {
  AddOutline,
  CloseOutline,
  ChatbubbleOutline,
  TrashOutline,
  ChevronDownOutline,
  MenuOutline,
  ExtensionPuzzleOutline,
  AnalyticsOutline,
  FolderOutline,
  SearchOutline,
  RocketOutline,
} from '@vicons/ionicons5'
import { isToday, isYesterday, parseISO } from 'date-fns'
import type { ChatSession, UserInfo } from '../types'

interface Props {
  sessions?: ChatSession[]
  currentSessionId?: string
  userInfo?: UserInfo
  collapsed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  sessions: () => [],
  currentSessionId: '',
  collapsed: false,
})

const emit = defineEmits<{
  newSession: []
  selectSession: [sessionId: string]
  deleteSession: [sessionId: string]
  toggleCollapse: []
  navigate: [path: string]
}>()

const activeMenu = ref('')

const functionMenus = [
  // 插件、深度研究、Agent 模式页面暂未实现，先隐藏
  // { key: 'plugin', label: '插件', icon: ExtensionPuzzleOutline, path: '/plugins' },
  { key: 'analysis', label: '分析流程', icon: AnalyticsOutline, path: '/flows' },
  { key: 'data', label: '项目数据', icon: FolderOutline, path: '/files' },
  // { key: 'research', label: '深度研究', icon: SearchOutline, path: '/research' },
  // { key: 'agent', label: 'Agent 模式', icon: RocketOutline, path: '/agent', badge: 'New' },
]

const groupedSessions = computed(() => {
  const filterBy = (fn: (d: Date) => boolean) =>
    props.sessions.filter((s) => {
      try {
        return fn(parseISO(s.updatedAt))
      } catch {
        return false
      }
    })
  const today = filterBy(isToday)
  const yesterday = filterBy(isYesterday)
  const older = filterBy((d) => !isToday(d) && !isYesterday(d))
  const groups: { label: string; sessions: ChatSession[] }[] = []
  if (today.length) groups.push({ label: '今天', sessions: today })
  if (yesterday.length) groups.push({ label: '昨天', sessions: yesterday })
  if (older.length) groups.push({ label: '更早', sessions: older })
  return groups
})

function handleMenuClick(item: { key: string; path: string }) {
  activeMenu.value = item.key
  emit('navigate', item.path)
}
</script>

<template>
  <aside class="kimi-sidebar" :class="{ collapsed }">
    <div class="sidebar-header">
      <div v-if="!collapsed" class="sidebar-logo">
        <span class="logo-text">AI 助手</span>
      </div>
      <n-button text class="collapse-btn" @click="$emit('toggleCollapse')">
        <template #icon>
          <n-icon size="18"><MenuOutline /></n-icon>
        </template>
      </n-button>
    </div>

    <div class="new-session-area">
      <n-button type="primary" class="new-session-btn" :class="{ collapsed }" @click="$emit('newSession')">
        <template #icon>
          <n-icon><AddOutline /></n-icon>
        </template>
        <span v-if="!collapsed" class="btn-text">新建会话</span>
        <span v-if="!collapsed" class="shortcut">⌘K</span>
      </n-button>
    </div>

    <div class="function-menu">
      <div v-if="!collapsed" class="menu-section-title">功能</div>
      <div class="menu-items">
        <div
          v-for="item in functionMenus"
          :key="item.key"
          class="menu-item"
          :class="{ active: activeMenu === item.key }"
          @click="handleMenuClick(item)"
        >
          <n-icon size="18" class="menu-icon"><component :is="item.icon" /></n-icon>
          <span v-if="!collapsed" class="menu-label">{{ item.label }}</span>
        </div>
      </div>
    </div>

    <div v-if="!collapsed" class="history-section">
      <div class="menu-section-title">
        <span>历史会话</span>
        <n-button text size="tiny" class="clear-btn">
          <template #icon><n-icon size="14"><TrashOutline /></n-icon></template>
        </n-button>
      </div>

      <div v-for="group in groupedSessions" :key="group.label" class="session-group">
        <div class="group-label">{{ group.label }}</div>
        <div
          v-for="session in group.sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: currentSessionId === session.id }"
          @click="$emit('selectSession', session.id)"
        >
          <n-icon size="14" class="session-icon"><ChatbubbleOutline /></n-icon>
          <span class="session-title">{{ session.title }}</span>
          <n-button text size="tiny" class="delete-btn" @click.stop="$emit('deleteSession', session.id)">
            <template #icon><n-icon size="12"><CloseOutline /></n-icon></template>
          </n-button>
        </div>
      </div>

      <div v-if="!sessions.length" class="history-empty">暂无历史会话</div>
    </div>

    <div class="user-info" :class="{ collapsed }">
      <n-avatar
        round
        size="small"
        :src="userInfo?.avatar"
        :fallback-src="`https://api.dicebear.com/7.x/initials/svg?seed=${userInfo?.name || 'U'}`"
      />
      <div v-if="!collapsed" class="user-meta">
        <div class="user-name">{{ userInfo?.name || '未登录' }}</div>
        <n-tag size="small" :bordered="false" type="success" class="role-tag">
          {{ userInfo?.roleTag || userInfo?.role || '用户' }}
        </n-tag>
      </div>
      <n-button v-if="!collapsed" text class="user-menu-btn">
        <template #icon><n-icon size="14"><ChevronDownOutline /></n-icon></template>
      </n-button>
    </div>
  </aside>
</template>

<style scoped lang="scss">
.kimi-sidebar {
  width: var(--chat-sidebar-width);
  min-width: var(--chat-sidebar-width);
  height: 100%;
  background: var(--chat-sidebar-bg);
  border-right: 1px solid var(--chat-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.3s ease, min-width 0.3s ease;
}
.kimi-sidebar.collapsed {
  width: 60px;
  min-width: 60px;
}

.new-session-btn {
  width: 100%;
}

.menu-item,
.session-item {
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease, color 0.2s ease;
}

.menu-item:hover,
.session-item:hover {
  background: var(--chat-surface-hover);
}

.menu-item.active,
.session-item.active {
  background: rgba(79, 142, 247, 0.1);
  color: var(--chat-accent);
}
</style>
