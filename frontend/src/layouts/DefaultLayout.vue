<script setup lang="ts">
import {
  NLayout, NLayoutSider, NLayoutContent, NIcon, NButton, NTooltip, NDropdown, NPopover,
  NDrawer, NDrawerContent, NAvatar, NBadge, NModal,
} from 'naive-ui'
import { computed, h, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  HomeOutline, GridOutline, FlaskOutline, FitnessOutline,
  DocumentTextOutline, CloudUploadOutline, DownloadOutline, BarChartOutline, SettingsOutline,
  InformationCircleOutline, PersonOutline, LogOutOutline, MoonOutline, SunnyOutline,
  MenuOutline, ChevronForwardOutline, ChevronDownOutline,
  NotificationsOutline, HelpCircleOutline, ChatbubblesOutline, Planet,
  WalletOutline, SparklesOutline, ConstructOutline, LayersOutline,
  TerminalOutline, SearchOutline, DesktopOutline, LockClosedOutline, PeopleOutline, BulbOutline,
  WarningOutline, BriefcaseOutline, ServerOutline, ArchiveOutline,
} from '@vicons/ionicons5'
import CookieBalanceBadge from '@/components/CookieBalanceBadge.vue'
import NotAuthorized from '@/components/NotAuthorized.vue'
import NotificationDrawer from '@/components/NotificationDrawer.vue'
import OnboardingPopup from '@/components/OnboardingPopup.vue'
import ChunkUploader from '@/components/ChunkUploader.vue'
import UploadFloatingBall from '@/components/UploadFloatingBall.vue'
import GlobalAiAssistantSidebar from '@/components/ai-assistant/GlobalAiAssistantSidebar.vue'
import { useAuthStore } from '@/stores/auth'
import { displayName } from '@/utils/displayName'
import { useUploadStore } from '@/stores/upload'
import { useNotificationStore } from '@/stores/notification'
import { useSiteConfigStore } from '@/stores/site-config'
import { useModulesStore } from '@/stores/modules'
import { useAdminWelcome } from '@/composables/useAdminWelcome'
import { useThemeStore } from '@/stores/theme'
import type { ModuleRegistryItem, User } from '@/types'

const authStore = useAuthStore()
const modulesStore = useModulesStore()
const notificationStore = useNotificationStore()
const siteConfig = useSiteConfigStore()
const uploadStore = useUploadStore()
const themeStore = useThemeStore()
// 管理员登录欢迎小彩蛋：setup 阶段注册 useNotification，onMounted 触发；
// 内部 watch + 会话标记确保一次会话只弹一次，刷新页面不弹。
const { triggerAdminWelcome } = useAdminWelcome()
const route = useRoute()
const router = useRouter()
const currentUser = ref<User | null>(null)
const userLoadFailed = ref(false)
const userLoadRetrying = ref(false)
let userRefreshTimer: number | null = null

const accountLabel = computed(() => {
  const name = displayName(currentUser.value)
  if (name) return name
  return userLoadFailed.value ? '用户信息加载失败' : '未登录'
})

const collapsed = ref(false)
const mobileDrawerOpen = ref(false)
const notificationDrawerOpen = ref(false)
// 首次登录迎新弹窗：由 authStore.consumeOnboarding() 触发
const onboardingVisible = ref(false)
function loadExpandedKeys(): string[] {
  const saved = localStorage.getItem('cygnusx:sidebar-expanded')
  if (!saved) return ['analysis-center']

  try {
    const parsed = JSON.parse(saved)
    return Array.isArray(parsed) && parsed.every((key) => typeof key === 'string')
      ? parsed
      : ['analysis-center']
  } catch {
    return ['analysis-center']
  }
}

const expandedKeys = ref<string[]>(loadExpandedKeys())

watch(
  () => route.path,
  (path) => {
    if (!path.startsWith('/admin/') || expandedKeys.value.includes('admin-center')) return
    expandedKeys.value.push('admin-center')
    localStorage.setItem('cygnusx:sidebar-expanded', JSON.stringify(expandedKeys.value))
  },
  { immediate: true },
)

// 记录用户最后一次手动折叠状态：进入「关于」页强制折叠前保存，离开后恢复。
const userCollapsed = ref(false)
const lastAutoCollapsed = ref(false)

// Feature 6: AI 页面（/ai, /studio）无条件默认折叠侧边栏，离开后恢复用户原状态
const autoCollapsePages = ['/studio', '/ai']

const isAdmin = computed(() => authStore.user?.role === 'admin')
const isDarkTheme = computed(() => themeStore.isDark)

// ===== 模块权限管控（UX 层；后端中间件才是硬门槛） =====
// 当前用户被禁用的模块 key 列表（/auth/me 下发）
const disabledModules = computed<string[]>(() => authStore.user?.disabled_modules ?? [])

// 当前路由命中的已锁定模块：命中时主内容区渲染 NotAuthorized 占位页。
// 管理员永不锁定（后端保证其 disabled_modules 为空，前端再短路一层）。
const lockedModule = computed<ModuleRegistryItem | null>(() => {
  if (isAdmin.value) return null
  return modulesStore.lockedModuleForPath(route.path, disabledModules.value)
})

// 菜单项是否命中锁定模块：按 item.to 的路由前缀从注册表匹配，不写死模块 key。
// lockable=false 的模块（首页、系统管理组）在匹配层就被跳过，永不显示锁。
function navItemLocked(item: NavItem): boolean {
  if (isAdmin.value) return false
  const mod = modulesStore.moduleForRoutePath(item.to)
  return mod !== null && disabledModules.value.includes(mod.key)
}

const contentStyle = computed(() => {
  if (route.meta.fullscreen) {
    return 'padding: 0; display: flex; flex-direction: column; flex: 1; min-height: 0; background: var(--neutral-bg);'
  }
  // 生信工具箱区域（列表页 + 各工具页）紧凑布局：外层 padding 0，
  // 由各工具页面根容器自行控制 16px 内边距，避免双层 padding 浪费边缘空间。
  // JBrowse 已被上方 fullscreen 分支拦截，此处再显式排除做双重保险，确保其样式完全不变。
  const isToolsArea = route.path === '/tools'
    || (route.path.startsWith('/tools/') && route.path !== '/tools/jbrowse')
  if (isToolsArea) {
    return 'padding: 0; background: var(--neutral-bg);'
  }
  return 'padding: 24px; background: var(--neutral-bg);'
})

// 全屏页面（如 AI 助手）使用原生滚动容器，使 .n-layout-scroll-container 的 flex:1
// 高度规则生效，让内部 chat 布局铺满视口；非全屏页面保留 Naive 虚拟滚动条。
const useNativeScrollbar = computed(() => route.meta.fullscreen === true)

// 响应式：窗口宽度 < 1024 自动折叠，< 768 进入移动端模式
const windowWidth = ref(window.innerWidth)
const isMobile = computed(() => windowWidth.value < 768)
const isTablet = computed(() => windowWidth.value >= 768 && windowWidth.value < 1024)

function updateWindowWidth() {
  windowWidth.value = window.innerWidth
  // 「关于」页：路由驱动折叠，resize 时不覆盖其折叠态（让星空获得最大展示面积）
  if (route.meta.autoCollapseSidebar) {
    collapsed.value = true
    return
  }
  // AI 助手/工作台页：与路由 watcher 一致的自动折叠规则，避免 resize 时覆盖回展开态
  if (autoCollapsePages.some((p) => route.path.startsWith(p))) {
    collapsed.value = true
    return
  }
  if (isMobile.value) {
    collapsed.value = false
  } else if (isTablet.value) {
    collapsed.value = true
  } else {
    collapsed.value = userCollapsed.value
  }
}

// 路由 Meta 驱动：进入带 autoCollapseSidebar 的页面强制折叠，离开后恢复用户最后一次手动状态
// Feature 6: 进入 /studio 或 /ai 时也自动折叠（除非用户手动锁定了侧边栏）
watch(
  () => route.fullPath,
  () => {
    const metaCollapse = route.meta.autoCollapseSidebar === true
    // AI 助手/工作台页：无条件默认折叠（忽略手动锁定偏好），离开后恢复原状
    const aiPageCollapse = autoCollapsePages.some((p) => route.path.startsWith(p))
    const autoCollapse = metaCollapse || aiPageCollapse
    if (autoCollapse) {
      // 进入自动折叠页面：若当前未折叠则记录原状态后折叠
      if (!lastAutoCollapsed.value) {
        userCollapsed.value = collapsed.value
      }
      collapsed.value = true
    } else if (lastAutoCollapsed.value) {
      // 离开自动折叠页面：恢复用户最后一次手动状态（desktop 下生效）
      collapsed.value = isTablet.value ? true : userCollapsed.value
    }
    lastAutoCollapsed.value = autoCollapse
  },
  // immediate：直接打开/刷新 /ai、/studio 时首屏即折叠，不必等下一次路由跳转
  { immediate: true },
)

// 汉堡按钮手动切换：同时记录用户偏好，供离开自动折叠页面后恢复
function toggleCollapsed() {
  collapsed.value = !collapsed.value
  if (!route.meta.autoCollapseSidebar) {
    userCollapsed.value = collapsed.value
  }
}

async function loadCurrentUser() {
  if (!authStore.isLoggedIn || userLoadRetrying.value) return
  userLoadRetrying.value = true
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await authStore.fetchUser()
      currentUser.value = authStore.user
      userLoadFailed.value = false
      notificationStore.fetchNotifications()
      if (authStore.consumeOnboarding()) {
        siteConfig.fetchSiteConfig().catch(() => {})
        onboardingVisible.value = true
      }
      userLoadRetrying.value = false
      return
    } catch {
      if (attempt < 2) {
        await new Promise((resolve) => window.setTimeout(resolve, 300 * 2 ** attempt))
      }
    }
  }
  userLoadFailed.value = true
  userLoadRetrying.value = false
}

function retryCurrentUser() {
  void loadCurrentUser()
}

onMounted(() => {
  updateWindowWidth()
  window.addEventListener('resize', updateWindowWidth)
  window.addEventListener('storage', handleStorageChange)
  if (authStore.isLoggedIn) {
    // 模块注册表：菜单锁图标与占位页判断的数据源（并发去重，失败静默重试）
    modulesStore.ensureLoaded()
    void loadCurrentUser()
    userRefreshTimer = window.setInterval(() => {
      void loadCurrentUser()
    }, 60_000)
  }
  // 管理员欢迎彩蛋：登录后任意页面（不只是仪表板）进入即触发，
  // 内部 watch 等待 role 确定 + sessionStorage 标记保证一次会话只弹一次
  triggerAdminWelcome()
})

onBeforeUnmount(() => {
  if (userRefreshTimer !== null) window.clearInterval(userRefreshTimer)
  window.removeEventListener('resize', updateWindowWidth)
  window.removeEventListener('storage', handleStorageChange)
})

watch(windowWidth, updateWindowWidth)

interface NavItem {
  key: string
  label: string
  to: string
  icon: typeof HomeOutline
  children?: NavItem[]
}

const topNavItems = computed<NavItem[]>(() => [
  { key: 'dashboard', label: '控制台', to: '/dashboard', icon: HomeOutline },
  { key: 'flows', label: '分析中心', to: '/flows', icon: FlaskOutline },
  { key: 'knowledge', label: '实验室知识库', to: '/knowledge', icon: DocumentTextOutline },
  { key: 'about', label: '关于', to: '/about', icon: InformationCircleOutline },
])

const mainNavItems = computed<NavItem[]>(() => [
  { key: 'home', label: '首页', to: '/', icon: HomeOutline },
  { key: 'dashboard', label: '仪表板', to: '/dashboard', icon: GridOutline },
  {
    key: 'analysis-center',
    label: '分析中心',
    to: '/flows',
    icon: FlaskOutline,
    children: [
      { key: 'rna-seq', label: 'RNA-seq 分析', to: '/flows?type=rna-seq', icon: FlaskOutline },
      { key: 'atac-seq', label: 'ATAC-seq 分析', to: '/flows?type=atac-seq', icon: FitnessOutline },
    ],
  },
  { key: 'files', label: '数据管理', to: '/files', icon: CloudUploadOutline },
  { key: 'database', label: '数据库', to: '/database', icon: LayersOutline },
  { key: 'downloads', label: '数据下载', to: '/downloads', icon: DownloadOutline },
  { key: 'tasks', label: '任务中心', to: '/tasks', icon: DocumentTextOutline },
  { key: 'workflow-monitor', label: '流程监控', to: '/workflow-monitor', icon: BarChartOutline },
  { key: 'reports', label: '结果报告中心', to: '/reports', icon: DocumentTextOutline },
  { key: 'projects', label: '项目管理', to: '/projects', icon: BriefcaseOutline },
  { key: 'ai', label: 'AI 助手', to: '/ai', icon: ChatbubblesOutline },
  { key: 'studio', label: 'AI 工作台', to: '/studio', icon: DesktopOutline },
  { key: 'agent-teams-room', label: '团队协作室', to: '/agent-teams/room', icon: PeopleOutline },
  { key: 'tools', label: '生信工具箱', to: '/tools', icon: ConstructOutline },
])

const systemNavItems = computed<NavItem[]>(() => [
  { key: 'cookies', label: '用量统计', to: '/cookies', icon: BarChartOutline },
  { key: 'agent-capabilities', label: '我的 Agent 能力', to: '/agent-capabilities', icon: SparklesOutline },
  { key: 'settings', label: '系统设置', to: '/settings', icon: SettingsOutline },
  { key: 'about', label: '关于 CygnusX', to: '/about', icon: InformationCircleOutline },
])

const adminNavItems = computed<NavItem[]>(() => [
  {
    key: 'admin-center',
    label: '系统管理',
    to: '/admin/users',
    icon: SettingsOutline,
    children: [
      { key: 'admin-users', label: '用户管理', to: '/admin/users', icon: PersonOutline },
      { key: 'admin-memory', label: '记忆审计', to: '/admin/memory', icon: BulbOutline },
      { key: 'admin-session-logs', label: '会话日志排查', to: '/admin/session-logs', icon: DocumentTextOutline },
      { key: 'admin-database-health', label: '数据库健康', to: '/admin/database-health', icon: ServerOutline },
      { key: 'admin-ai-metrics', label: 'AI 指标仪表盘', to: '/admin/ai-metrics', icon: BarChartOutline },
      { key: 'admin-ai-config', label: 'AI 配置中心', to: '/admin/ai-config/providers', icon: SparklesOutline },
      { key: 'admin-home-quick-entries', label: '首页入口管理', to: '/admin/home-quick-entries', icon: GridOutline },
      { key: 'admin-biscuits', label: '饼干中心', to: '/admin/biscuits/accounts', icon: WalletOutline },
      { key: 'admin-announcements', label: '通知公告', to: '/admin/announcements', icon: NotificationsOutline },
      { key: 'admin-terminals', label: '沙盒终端管理', to: '/admin/terminals', icon: TerminalOutline },
      { key: 'admin-blast-databases', label: 'BLAST 数据库管理', to: '/admin/blast-databases', icon: SearchOutline },
      { key: 'admin-workspace-archive', label: '工作区归档管理', to: '/admin/workspace-archive', icon: ArchiveOutline },
    ],
  },
])

function isActive(item: NavItem): boolean {
  if (!item.children) {
    // 生信工具箱：子工具页面也保持高亮
    if (item.key === 'tools') return route.path === '/tools' || route.path.startsWith('/tools/')
    // AI 工作台：会话页面也保持高亮
    if (item.key === 'studio') return route.path === '/studio' || route.path.startsWith('/studio/')
    // 项目管理：详情页也保持高亮
    if (item.key === 'projects') return route.path === '/projects' || route.path.startsWith('/projects/')
    // 团队协作室：Case 详情页也保持高亮
    if (item.key === 'agent-teams-room') return route.path.startsWith('/agent-teams')
    // 数据库：新旧入口和详情页都保持高亮
    if (item.key === 'database') {
      return route.path === '/database'
        || route.path.startsWith('/database/')
        || route.path === '/reference-genomes'
        || route.path.startsWith('/reference-genomes/')
    }
    if (item.to.includes('?')) {
      const [path, query] = item.to.split('?')
      const type = query.split('=')[1]
      return route.path === path && route.query.type === type
    }
    if (route.path === item.to) return true
    return false
  }
  return item.children.some((child) => {
    if (child.to.includes('?type=')) {
      return route.path === '/flows' && route.query.type === child.to.split('type=')[1]
    }
    return route.name === child.key || route.path === child.to
  })
}

function isTopActive(item: NavItem): boolean {
  if (item.key === 'dashboard') return route.path === '/dashboard'
  if (item.key === 'flows') return route.path.startsWith('/flows')
  if (item.key === 'knowledge') return route.path.startsWith('/knowledge')
  if (item.key === 'about') return route.path === '/about'
  return false
}

function toggleExpanded(key: string) {
  const idx = expandedKeys.value.indexOf(key)
  if (idx >= 0) {
    expandedKeys.value.splice(idx, 1)
  } else {
    expandedKeys.value.push(key)
  }
  localStorage.setItem('cygnusx:sidebar-expanded', JSON.stringify(expandedKeys.value))
}

function isExpanded(key: string): boolean {
  return expandedKeys.value.includes(key)
}

function handleNavClick(item: NavItem) {
  if (isMobile.value) {
    mobileDrawerOpen.value = false
  }
  if (item.children && item.children.length) {
    toggleExpanded(item.key)
  }
  if (item.to) {
    router.push(item.to)
  }
}

function handleAdminGroupClick(item: NavItem) {
  if (item.children?.length) {
    toggleExpanded(item.key)
    return
  }
  handleNavClick(item)
}

async function handleLogout() {
  authStore.logout()
  await router.replace('/login')
  window.location.reload()
}

function handleStorageChange(e: StorageEvent) {
  if (e.key === 'access_token' && !e.newValue) {
    authStore.logout()
    router.replace('/login')
    window.location.reload()
  }
}

// 迎新弹窗：前往知识库 / 稍后再看
function handleOnboardingGoKnowledge() {
  onboardingVisible.value = false
  router.push('/knowledge')
}
function handleOnboardingSkip() {
  onboardingVisible.value = false
}

const userMenuOptions = computed(() => [
  { label: '个人中心', key: 'profile', icon: () => h(NIcon, null, { default: () => h(PersonOutline) }) },
  { label: '账号设置', key: 'settings', icon: () => h(NIcon, null, { default: () => h(SettingsOutline) }) },
  {
    label: isDarkTheme.value ? '浅色模式' : '深色模式',
    key: 'theme',
    icon: () => h(NIcon, null, { default: () => h(isDarkTheme.value ? SunnyOutline : MoonOutline) }),
  },
  { type: 'divider' as const, key: 'divider' },
  { label: '退出登录', key: 'logout', icon: () => h(NIcon, null, { default: () => h(LogOutOutline) }) },
])

function handleUserMenuSelect(key: string) {
  if (key === 'profile') router.push('/profile')
  else if (key === 'settings') router.push('/settings')
  else if (key === 'theme') themeStore.toggleTheme()
  else if (key === 'logout') handleLogout()
}

const UserAvatar = () => {
  const name = displayName(currentUser.value) || 'U'
  return h(NAvatar, {
    round: true,
    size: 'small',
    style: {
      background: 'var(--arco-primary-light)',
      color: 'var(--arco-primary)',
      fontSize: '12px',
      fontWeight: 500,
    },
  }, { default: () => name.charAt(0).toUpperCase() })
}
</script>

<template>
  <div class="app-shell">
    <!-- 顶部导航栏 -->
    <header class="top-nav">
      <div class="top-nav-left">
        <NButton text class="hamburger-btn" @click="isMobile ? mobileDrawerOpen = true : toggleCollapsed()">
          <NIcon :size="20">
            <MenuOutline />
          </NIcon>
        </NButton>
        <div class="logo-block">
          <div class="logo-icon">
            <NIcon :size="24">
              <Planet />
            </NIcon>
          </div>
          <span class="logo-text">CygnusX</span>
        </div>
        <div class="top-nav-divider" />
        <nav class="top-nav-menu">
          <RouterLink
            v-for="item in topNavItems"
            :key="item.key"
            :to="item.to"
            class="top-nav-item"
            :class="{ 'top-nav-item--active': isTopActive(item), 'top-nav-item--locked': navItemLocked(item) }"
          >
            {{ item.label }}
            <NIcon v-if="navItemLocked(item)" :size="12" class="nav-lock-icon">
              <LockClosedOutline />
            </NIcon>
            <span v-if="isTopActive(item)" class="top-nav-indicator" />
          </RouterLink>
        </nav>
      </div>
      <div class="top-nav-right">
        <NTooltip v-if="userLoadFailed" placement="bottom-end" :delay="300">
          <template #trigger>
            <NButton
              tertiary
              type="warning"
              size="small"
              class="user-refresh-trigger focus-ring"
              :loading="userLoadRetrying"
              aria-label="账户信息同步失败，点击重试"
              @click="retryCurrentUser"
            >
              <template #icon>
                <NIcon :size="15">
                  <WarningOutline />
                </NIcon>
              </template>
              <span class="user-refresh-trigger__label">账户同步异常</span>
              <span class="user-refresh-trigger__action">重试</span>
            </NButton>
          </template>
          当前页面保留已有登录信息；服务恢复后会自动重试。
        </NTooltip>
        <CookieBalanceBadge />
        <NTooltip placement="bottom" :delay="300">
          <template #trigger>
            <NButton text class="top-icon-btn" @click="notificationDrawerOpen = true">
              <NBadge :value="notificationStore.unreadCount" :max="99" :show="notificationStore.unreadCount > 0">
                <NIcon :size="20">
                  <NotificationsOutline />
                </NIcon>
              </NBadge>
            </NButton>
          </template>
          通知
        </NTooltip>
        <NTooltip placement="bottom" :delay="300">
          <template #trigger>
            <NButton text class="top-icon-btn" @click="$router.push('/knowledge')">
              <NIcon :size="20">
                <HelpCircleOutline />
              </NIcon>
            </NButton>
          </template>
          帮助文档
        </NTooltip>
      </div>
    </header>

    <div class="app-body">
      <!-- 桌面端侧边栏 -->
      <NLayoutSider
        v-if="!isMobile"
        bordered
        :width="220"
        :collapsed-width="80"
        :collapsed="collapsed"
        collapse-mode="width"
        class="app-sider"
        :class="{ 'app-sider--collapsed': collapsed }"
      >
        <div class="sider-inner">
          <div class="sider-nav-groups">
            <!-- 核心功能 -->
            <nav class="nav-group">
              <div
                v-for="item in mainNavItems"
                :key="item.key"
                class="nav-group-item"
              >
                <div
                  class="nav-item"
                  :class="{
                    'nav-item--active': isActive(item),
                    'nav-item--collapsed': collapsed,
                    'nav-item--group': item.key === 'admin-center',
                    'nav-item--locked': navItemLocked(item),
                  }"
                  @click="handleNavClick(item)"
                >
                  <NTooltip v-if="collapsed && !item.children" placement="right" :delay="300">
                    <template #trigger>
                      <div class="nav-item-inner">
                        <NIcon :size="18" class="nav-icon">
                          <component :is="item.icon" />
                        </NIcon>
                      </div>
                    </template>
                    {{ item.label }}
                  </NTooltip>
                  <NPopover
                    v-else-if="collapsed && item.children"
                    trigger="hover"
                    placement="right-start"
                    :delay="150"
                    :show-arrow="false"
                    :z-index="1050"
                    class="collapsed-submenu-popover"
                  >
                    <template #trigger>
                      <div class="nav-item-inner">
                        <NIcon :size="19" class="nav-icon">
                          <component :is="item.icon" />
                        </NIcon>
                      </div>
                    </template>
                    <div class="collapsed-submenu-content">
                      <p class="collapsed-submenu-title">{{ item.label }}</p>
                      <RouterLink
                        v-for="child in item.children"
                        :key="child.key"
                        :to="child.to"
                        class="collapsed-submenu-item"
                        :class="{
                          'collapsed-submenu-item--active': isActive(child),
                          'collapsed-submenu-item--locked': navItemLocked(child),
                        }"
                      >
                        <NIcon :size="16">
                          <component :is="child.icon" />
                        </NIcon>
                        <span>{{ child.label }}</span>
                        <NIcon v-if="navItemLocked(child)" :size="12" class="nav-lock-icon">
                          <LockClosedOutline />
                        </NIcon>
                      </RouterLink>
                    </div>
                  </NPopover>
                  <div v-else class="nav-item-inner">
                    <NIcon :size="18" class="nav-icon">
                      <component :is="item.icon" />
                    </NIcon>
                    <span v-show="!collapsed" class="nav-label">{{ item.label }}</span>
                    <NIcon
                      v-if="!collapsed && navItemLocked(item)"
                      :size="13"
                      class="nav-lock-icon"
                    >
                      <LockClosedOutline />
                    </NIcon>
                    <NIcon
                      v-if="item.children && !collapsed"
                      :size="14"
                      class="nav-chevron"
                      :class="{ 'nav-chevron--expanded': isExpanded(item.key) }"
                    >
                      <ChevronForwardOutline />
                    </NIcon>
                  </div>
                </div>
                <!-- 子菜单 -->
                <div
                  v-if="item.children && !collapsed && isExpanded(item.key)"
                  class="sub-nav"
                >
                  <RouterLink
                    v-for="child in item.children"
                    :key="child.key"
                    :to="child.to"
                    class="sub-nav-item"
                    :class="{
                      'sub-nav-item--active': isActive(child),
                      'sub-nav-item--locked': navItemLocked(child),
                    }"
                  >
                    <NIcon :size="16" class="sub-nav-icon">
                      <component :is="child.icon" />
                    </NIcon>
                    <span>{{ child.label }}</span>
                    <NIcon v-if="navItemLocked(child)" :size="12" class="nav-lock-icon">
                      <LockClosedOutline />
                    </NIcon>
                  </RouterLink>
                </div>
              </div>
            </nav>

            <div class="nav-divider" />

            <!-- 系统与资源 -->
            <nav class="nav-group">
              <div
                v-for="item in systemNavItems"
                :key="item.key"
                class="nav-item"
                :class="{
                  'nav-item--active': isActive(item),
                  'nav-item--collapsed': collapsed,
                  'nav-item--locked': navItemLocked(item),
                }"
                @click="handleNavClick(item)"
              >
                <NTooltip v-if="collapsed" placement="right" :delay="300">
                  <template #trigger>
                    <div class="nav-item-inner">
                      <NIcon :size="18" class="nav-icon">
                        <component :is="item.icon" />
                      </NIcon>
                    </div>
                  </template>
                  {{ item.label }}
                </NTooltip>
                <div v-else class="nav-item-inner">
                  <NIcon :size="18" class="nav-icon">
                    <component :is="item.icon" />
                  </NIcon>
                  <span class="nav-label">{{ item.label }}</span>
                  <NIcon v-if="navItemLocked(item)" :size="13" class="nav-lock-icon">
                    <LockClosedOutline />
                  </NIcon>
                </div>
              </div>
            </nav>

            <!-- 管理员 -->
            <template v-if="isAdmin">
              <div class="nav-divider" />
              <nav class="nav-group admin-nav-group" aria-label="系统管理">
                <div
                  v-for="item in adminNavItems"
                  :key="item.key"
                  class="nav-group-item"
                >
                  <div
                    class="nav-item admin-nav-parent"
                    :class="{
                      'admin-nav-parent--contains-active': isActive(item),
                      'nav-item--collapsed': collapsed,
                    }"
                    role="button"
                    tabindex="0"
                    :aria-expanded="item.children ? isExpanded(item.key) : undefined"
                    @click="handleAdminGroupClick(item)"
                    @keydown.enter.prevent="handleAdminGroupClick(item)"
                    @keydown.space.prevent="handleAdminGroupClick(item)"
                  >
                    <NTooltip v-if="collapsed && !item.children" placement="right" :delay="300">
                      <template #trigger>
                        <div class="nav-item-inner">
                          <NIcon :size="18" class="nav-icon">
                            <component :is="item.icon" />
                          </NIcon>
                        </div>
                      </template>
                      {{ item.label }}
                    </NTooltip>
                    <NPopover
                      v-else-if="collapsed && item.children"
                      trigger="hover"
                      placement="right-start"
                      :delay="150"
                      :show-arrow="false"
                      :z-index="1050"
                      class="collapsed-submenu-popover"
                    >
                      <template #trigger>
                        <div class="nav-item-inner">
                          <NIcon :size="19" class="nav-icon">
                            <component :is="item.icon" />
                          </NIcon>
                        </div>
                      </template>
                      <div class="collapsed-submenu-content admin-collapsed-submenu-content">
                        <p class="collapsed-submenu-title">{{ item.label }}</p>
                        <RouterLink
                          v-for="child in item.children"
                          :key="child.key"
                          :to="child.to"
                          class="collapsed-submenu-item admin-collapsed-submenu-item"
                          :class="{ 'collapsed-submenu-item--active': isActive(child) }"
                          :aria-current="isActive(child) ? 'page' : undefined"
                        >
                          <span>{{ child.label }}</span>
                        </RouterLink>
                      </div>
                    </NPopover>
                    <div v-else class="nav-item-inner">
                      <NIcon :size="18" class="nav-icon">
                        <component :is="item.icon" />
                      </NIcon>
                      <span v-show="!collapsed" class="nav-label">{{ item.label }}</span>
                      <NIcon
                        v-if="item.children && !collapsed"
                        :size="14"
                        class="nav-chevron"
                        :class="{ 'nav-chevron--expanded': isExpanded(item.key) }"
                      >
                        <ChevronForwardOutline />
                      </NIcon>
                    </div>
                  </div>
                  <!-- 子菜单 -->
                  <Transition name="subnav-expand">
                    <div
                      v-if="item.children && !collapsed && isExpanded(item.key)"
                      class="sub-nav admin-sub-nav"
                    >
                      <RouterLink
                        v-for="child in item.children"
                        :key="child.key"
                        :to="child.to"
                        class="sub-nav-item admin-sub-nav-item"
                        :class="{ 'sub-nav-item--active': isActive(child) }"
                        :aria-current="isActive(child) ? 'page' : undefined"
                      >
                        <span>{{ child.label }}</span>
                      </RouterLink>
                    </div>
                  </Transition>
                </div>
              </nav>
            </template>
          </div>

          <!-- 底部用户区 -->
          <div class="sider-footer">
            <div v-if="collapsed" class="user-avatar-only">
              <NDropdown
                trigger="click"
                placement="right"
                :options="userMenuOptions"
                @select="handleUserMenuSelect"
              >
                <NButton text class="user-avatar-btn">
                  <UserAvatar />
                </NButton>
              </NDropdown>
            </div>
            <NDropdown
              v-else
              trigger="click"
              placement="top-start"
              :options="userMenuOptions"
              @select="handleUserMenuSelect"
            >
              <div class="user-card">
                <UserAvatar />
                <div class="user-info">
                  <p class="user-name">{{ accountLabel }}</p>
                  <p class="user-role">{{ isAdmin ? '管理员' : '普通用户' }}</p>
                  <NButton
                    v-if="userLoadFailed"
                    text
                    size="tiny"
                    class="user-retry-button"
                    :loading="userLoadRetrying"
                    @click.stop="retryCurrentUser"
                  >
                    重试
                  </NButton>
                </div>
                <NIcon :size="14" class="user-chevron">
                  <ChevronDownOutline />
                </NIcon>
              </div>
            </NDropdown>
          </div>
        </div>
      </NLayoutSider>

      <!-- 移动端抽屉 -->
      <NDrawer v-model:show="mobileDrawerOpen" :width="260" placement="left" class="mobile-drawer">
        <NDrawerContent body-content-style="padding: 0">
          <div class="mobile-sider">
            <div class="mobile-logo">
              <NIcon :size="26" class="mobile-logo-icon">
                <Planet />
              </NIcon>
              <span class="mobile-logo-text">CygnusX</span>
            </div>
            <nav class="mobile-nav-group">
              <RouterLink
                v-for="item in mainNavItems"
                :key="item.key"
                :to="item.to"
                class="mobile-nav-item"
                :class="{
                  'mobile-nav-item--active': isActive(item),
                  'mobile-nav-item--locked': navItemLocked(item),
                }"
                @click="mobileDrawerOpen = false"
              >
                <NIcon :size="18">
                  <component :is="item.icon" />
                </NIcon>
                <span>{{ item.label }}</span>
                <NIcon v-if="navItemLocked(item)" :size="13" class="nav-lock-icon">
                  <LockClosedOutline />
                </NIcon>
              </RouterLink>
            </nav>
            <div class="nav-divider" />
            <nav class="mobile-nav-group">
              <RouterLink
                v-for="item in systemNavItems"
                :key="item.key"
                :to="item.to"
                class="mobile-nav-item"
                :class="{
                  'mobile-nav-item--active': isActive(item),
                  'mobile-nav-item--locked': navItemLocked(item),
                }"
                @click="mobileDrawerOpen = false"
              >
                <NIcon :size="18">
                  <component :is="item.icon" />
                </NIcon>
                <span>{{ item.label }}</span>
                <NIcon v-if="navItemLocked(item)" :size="13" class="nav-lock-icon">
                  <LockClosedOutline />
                </NIcon>
              </RouterLink>
            </nav>
            <template v-if="isAdmin">
              <div class="nav-divider" />
              <nav class="mobile-nav-group">
                <RouterLink
                  v-for="item in adminNavItems.flatMap((i) => i.children || [i])"
                  :key="item.key"
                  :to="item.to"
                  class="mobile-nav-item"
                  :class="{ 'mobile-nav-item--active': isActive(item) }"
                  @click="mobileDrawerOpen = false"
                >
                  <NIcon :size="18">
                    <component :is="item.icon" />
                  </NIcon>
                  <span>{{ item.label }}</span>
                </RouterLink>
              </nav>
            </template>
            <div class="mobile-user-card" @click="handleLogout">
              <UserAvatar />
              <div class="user-info">
                <p class="user-name">{{ accountLabel }}</p>
                <p class="user-role">{{ isAdmin ? '管理员' : '普通用户' }}</p>
                <NButton
                  v-if="userLoadFailed"
                  text
                  size="tiny"
                  class="user-retry-button"
                  :loading="userLoadRetrying"
                  @click.stop="retryCurrentUser"
                >
                  重试
                </NButton>
              </div>
            </div>
          </div>
        </NDrawerContent>
      </NDrawer>

      <!-- 主内容区 -->
      <NLayout class="main-layout">
        <NLayoutContent
          :content-style="contentStyle"
          :native-scrollbar="useNativeScrollbar"
        >
          <!-- 模块未开通：统一占位页（覆盖 fullscreen 页面，锁定页内容不可见） -->
          <NotAuthorized
            v-if="lockedModule"
            :key="lockedModule.key"
            :module-key="lockedModule.key"
            :module-name="lockedModule.name"
          />
          <RouterView v-else v-slot="{ Component }">
            <Transition name="route" mode="out-in">
              <component :is="Component" />
            </Transition>
          </RouterView>
        </NLayoutContent>
      </NLayout>
    </div>

    <NotificationDrawer v-model:show="notificationDrawerOpen" />

    <!-- 全局上传弹窗（跨页面持久，最小化为悬浮球） -->
    <NModal
      v-model:show="uploadStore.modalOpen"
      preset="card"
      title="上传数据"
      style="width: 600px"
      :bordered="false"
      :mask-closable="false"
      @update:show="(v: boolean) => { if (!v) uploadStore.close() }"
    >
      <ChunkUploader />
    </NModal>
    <UploadFloatingBall />

    <!-- 平台全局 AI 助手侧边栏 -->
    <GlobalAiAssistantSidebar />

    <!-- 首次登录迎新弹窗 -->
    <OnboardingPopup
      v-model:visible="onboardingVisible"
      :admin-contact="siteConfig.adminContact"
      @go-knowledge="handleOnboardingGoKnowledge"
      @skip="handleOnboardingSkip"
    />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--neutral-bg);
}

/* ===== 顶部导航栏 ===== */
.top-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 16px;
  background: rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(28px) saturate(180%);
  -webkit-backdrop-filter: blur(28px) saturate(180%);
  border-bottom: 1px solid var(--neutral-border);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.42), 0 8px 24px rgba(29, 33, 41, 0.04);
  flex-shrink: 0;
  z-index: 100;
}

:root[data-theme="dark"] .top-nav {
  background: var(--surface-glass);
  border-bottom-color: var(--border-subtle);
  backdrop-filter: blur(16px) saturate(140%);
  -webkit-backdrop-filter: blur(16px) saturate(140%);
  box-shadow: none;
}

.top-nav-left {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 100%;
}

.hamburger-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neutral-text-2);
  border-radius: 6px;
}
.hamburger-btn:hover {
  background: var(--neutral-hover);
}
.hamburger-btn:active {
  transform: scale(0.97);
  transition: transform 100ms ease-out;
}

.logo-block {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  border-radius: 8px;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.top-nav-divider {
  width: 1px;
  height: 20px;
  background: var(--neutral-border);
  margin: 0 8px;
}

.top-nav-menu {
  display: flex;
  align-items: center;
  height: 100%;
}

.top-nav-item {
  position: relative;
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 16px;
  font-size: 14px;
  font-weight: 400;
  color: var(--neutral-text-2);
  text-decoration: none;
  transition: color 140ms ease-out;
}

.top-nav-item:hover {
  color: var(--neutral-text-1);
}

.top-nav-item--active {
  color: var(--arco-primary);
  font-weight: 500;
}

.top-nav-indicator {
  position: absolute;
  bottom: 0;
  left: 16px;
  right: 16px;
  height: 2px;
  background: var(--arco-primary);
  border-radius: 1px;
}

.top-nav-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-refresh-trigger {
  min-width: 0;
  padding: 0 10px;
  border-radius: 8px;
}

.user-refresh-trigger :deep(.n-button__content) {
  gap: 5px;
}

.user-refresh-trigger__label {
  font-size: 12px;
}

.user-refresh-trigger__action {
  padding-left: 6px;
  border-left: 1px solid currentColor;
  font-size: 12px;
  font-weight: 600;
}

.top-icon-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neutral-text-2);
  border-radius: 6px;
}
.top-icon-btn:hover {
  background: var(--neutral-hover);
}
.top-icon-btn:active {
  transform: scale(0.97);
  transition: transform 100ms ease-out;
}

/* ===== 主体 ===== */
.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.app-sider {
  background: rgba(255, 255, 255, 0.56);
  backdrop-filter: blur(24px) saturate(165%);
  -webkit-backdrop-filter: blur(24px) saturate(165%);
  border-right: none;
  overflow: visible;
  transition: width 300ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

:root[data-theme="dark"] .app-sider {
  background: var(--surface-card);
  border-right: 1px solid var(--border-subtle);
}

.sider-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px 12px 12px;
  transition: opacity 180ms ease-out;
}

.app-sider--collapsed .sider-inner {
  padding-right: 8px;
  padding-left: 8px;
}

.sider-nav-groups {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
  scrollbar-color: transparent transparent;
  transition: scrollbar-color 180ms ease-out;
}

.sider-nav-groups::-webkit-scrollbar {
  width: 6px;
}

.sider-nav-groups::-webkit-scrollbar-track {
  background: transparent;
  border: 0;
}

.sider-nav-groups::-webkit-scrollbar-thumb {
  background-color: transparent;
  border: 1px solid transparent;
  border-radius: 999px;
  background-clip: padding-box;
  transition: background-color 180ms ease-out;
}

.app-sider:hover .sider-nav-groups {
  scrollbar-color: var(--scrollbar-thumb-hover) transparent;
}

.app-sider:hover .sider-nav-groups::-webkit-scrollbar-thumb {
  background-color: var(--scrollbar-thumb-hover);
}

.app-sider:hover .sider-nav-groups::-webkit-scrollbar-thumb:hover {
  background-color: var(--scrollbar-thumb-active);
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-group-item {
  display: flex;
  flex-direction: column;
}

.nav-item {
  display: flex;
  flex-direction: column;
  margin: 0 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 180ms ease-out, color 180ms ease-out, box-shadow 220ms cubic-bezier(0.2, 0.8, 0.2, 1), transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
  color: var(--neutral-text-2);
}

.nav-item:hover {
  background: linear-gradient(90deg, rgba(22, 93, 255, 0.12), rgba(22, 93, 255, 0.04));
  color: var(--neutral-text-1);
  box-shadow: inset 0 0 0 1px rgba(22, 93, 255, 0.1), 0 4px 12px rgba(22, 93, 255, 0.08);
  transform: translateX(2px);
}

.nav-item--active {
  background: var(--sidebar-active);
  color: var(--sidebar-active-text);
  font-weight: 500;
  position: relative;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--arco-primary) 16%, transparent);
}

:root[data-theme="dark"] .nav-item--active {
  box-shadow: inset 0 0 0 1px var(--border-focus), var(--brand-glow);
}

.nav-item--active:hover {
  transform: none;
}

.nav-item--active::before {
  content: '';
  position: absolute;
  top: 50%;
  height: 26px;
  transform: translateY(-50%);
  left: 4px;
  width: 3px;
  background: var(--arco-primary);
  border-radius: 999px;
}

.nav-item--collapsed.nav-item--active::before {
  height: 30px;
}

.nav-item--group.nav-item--active {
  background: transparent;
  color: var(--neutral-text-1);
  font-weight: 500;
}

.nav-item--group.nav-item--active::before {
  display: none;
}

.nav-item--group:hover {
  background: var(--neutral-hover);
  box-shadow: none;
  transform: none;
}

.nav-item-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 40px;
  padding: 0 12px;
}

.nav-item--collapsed .nav-item-inner {
  width: 100%;
  height: 44px;
  justify-content: center;
  padding: 0;
  border-radius: 12px;
}

.nav-item--collapsed {
  margin: 0;
  width: 100%;
}

.nav-icon {
  flex-shrink: 0;
}

.nav-item--collapsed:hover .nav-icon {
  filter: drop-shadow(0 0 6px rgba(22, 93, 255, 0.5));
}

.nav-label {
  flex: 1;
  font-size: 14px;
  line-height: 22px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-chevron {
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

/* ===== 模块未开通：菜单项锁图标 + 降透明度（保持可点击） ===== */
.nav-item--locked,
.sub-nav-item--locked,
.collapsed-submenu-item--locked,
.top-nav-item--locked,
.mobile-nav-item--locked {
  opacity: 0.6;
}

.nav-lock-icon {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--neutral-text-3);
}

.nav-chevron--expanded {
  transform: rotate(90deg);
}

.subnav-expand-enter-active,
.subnav-expand-leave-active {
  overflow: hidden;
  transition: max-height 220ms ease-in-out, opacity 180ms ease-in-out;
}

.subnav-expand-enter-from,
.subnav-expand-leave-to {
  max-height: 0;
  opacity: 0;
}

.subnav-expand-enter-to,
.subnav-expand-leave-from {
  max-height: 520px;
  opacity: 1;
}

/* 子菜单 */
.sub-nav {
  margin-left: 22px;
  padding-left: 12px;
  border-left: 1px solid var(--neutral-border);
  display: flex;
  flex-direction: column;
}

.sub-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 12px;
  font-size: 13px;
  color: var(--neutral-text-2);
  text-decoration: none;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.sub-nav-item:hover {
  color: var(--neutral-text-1);
  background: var(--neutral-hover);
}

.sub-nav-item--active {
  color: var(--arco-primary);
  background: var(--arco-primary-light);
  font-weight: 500;
}

.sub-nav-icon {
  flex-shrink: 0;
}

/* ===== 系统管理：轻量 Tree Navigation ===== */
.admin-nav-group {
  gap: 2px;
  padding: 4px 0;
}

.admin-nav-parent {
  margin: 0 12px;
  color: var(--neutral-text-2);
  background: transparent;
  box-shadow: none;
  transform: none;
  transition: color 180ms ease-out, background-color 180ms ease-out;
}

.admin-nav-parent.nav-item--collapsed {
  margin: 0;
}

.admin-nav-parent:hover {
  color: var(--neutral-text-1);
  background: var(--neutral-hover);
  box-shadow: none;
  transform: none;
}

.admin-nav-parent:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
}

.admin-nav-parent--contains-active {
  color: var(--neutral-text-1);
  background: transparent;
  box-shadow: none;
}

.admin-nav-parent--contains-active .nav-icon,
.admin-nav-parent--contains-active .nav-chevron {
  color: var(--arco-primary);
}

.admin-nav-parent .nav-item-inner {
  height: 40px;
  gap: 12px;
  padding: 0 12px;
}

.admin-nav-parent .nav-label {
  font-size: 14px;
  font-weight: 500;
}

.admin-nav-parent .nav-chevron {
  transition: transform 180ms ease-out, color 180ms ease-out;
}

.admin-sub-nav {
  gap: 2px;
  margin: 2px 4px 6px 32px;
  padding: 2px 0 2px 12px;
  border-left: 1px solid var(--neutral-border);
}

.admin-sub-nav.subnav-expand-enter-active,
.admin-sub-nav.subnav-expand-leave-active {
  transition: max-height 180ms ease-out, opacity 150ms ease-out;
}

.admin-sub-nav-item {
  position: relative;
  height: 36px;
  padding: 0 10px;
  color: var(--neutral-text-3);
  border-radius: 7px;
  font-size: 13px;
  font-weight: 400;
  transition: color 150ms ease-out, background-color 150ms ease-out;
}

.admin-sub-nav-item:hover {
  color: var(--neutral-text-1);
  background: var(--neutral-hover);
}

.admin-sub-nav-item.sub-nav-item--active {
  color: var(--arco-primary);
  background: transparent;
  font-weight: 500;
}

.admin-sub-nav-item.sub-nav-item--active::before {
  content: '';
  position: absolute;
  top: 7px;
  bottom: 7px;
  left: -14px;
  width: 3px;
  border-radius: 999px;
  background: var(--arco-primary);
}

.admin-sub-nav-item:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 1px;
}

.admin-collapsed-submenu-content {
  min-width: 196px;
  padding: 6px;
}

.admin-collapsed-submenu-item {
  position: relative;
  padding-left: 14px;
  color: var(--neutral-text-2);
}

.collapsed-submenu-item.admin-collapsed-submenu-item:hover {
  color: var(--neutral-text-1);
  background: var(--neutral-hover);
}

.admin-collapsed-submenu-item.collapsed-submenu-item--active {
  color: var(--arco-primary);
  background: transparent;
}

.admin-collapsed-submenu-item.collapsed-submenu-item--active::before {
  content: '';
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 4px;
  width: 3px;
  border-radius: 999px;
  background: var(--arco-primary);
}

.collapsed-submenu-content {
  min-width: 184px;
  padding: 6px;
}

.collapsed-submenu-title {
  margin: 0;
  padding: 7px 8px 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--neutral-text-3);
}

.collapsed-submenu-item {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 36px;
  padding: 0 9px;
  border-radius: 7px;
  color: var(--neutral-text-2);
  font-size: 13px;
  line-height: 20px;
  text-decoration: none;
  transition: background 0.2s ease, color 0.2s ease;
}

.collapsed-submenu-item:hover {
  color: var(--neutral-text-1);
  background: rgba(22, 93, 255, 0.1);
}

.collapsed-submenu-item--active {
  color: var(--arco-primary);
  background: var(--arco-primary-light);
  font-weight: 500;
}

.nav-divider {
  height: 1px;
  background: var(--neutral-border);
  margin: 12px 12px;
}

@media (prefers-reduced-motion: reduce) {
  .admin-nav-parent,
  .admin-nav-parent .nav-chevron,
  .admin-sub-nav-item,
  .admin-collapsed-submenu-item {
    transition: none;
  }
}

/* ===== 底部用户区 ===== */
.sider-footer {
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid var(--neutral-border);
}

.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.user-card:hover {
  background: var(--neutral-hover);
}

.user-info {
  flex: 1;
  min-width: 0;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--neutral-text-1);
  line-height: 20px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 12px;
  color: var(--neutral-text-3);
  line-height: 18px;
}

.user-retry-button {
  display: block;
  min-height: 18px;
  margin-top: 2px;
  color: var(--arco-primary);
}

@media (max-width: 640px) {
  .user-refresh-trigger {
    width: 32px;
    padding: 0;
  }

  .user-refresh-trigger__label,
  .user-refresh-trigger__action {
    display: none;
  }
}

.user-chevron {
  color: var(--neutral-text-3);
  flex-shrink: 0;
}

.user-avatar-only {
  display: flex;
  justify-content: center;
  padding: 6px 0 2px;
}

.user-avatar-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: 1px solid transparent;
  transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.user-avatar-btn:hover {
  background: rgba(22, 93, 255, 0.1);
  border-color: rgba(22, 93, 255, 0.24);
  box-shadow: 0 0 12px rgba(22, 93, 255, 0.16);
}

/* ===== 移动端抽屉 ===== */
.mobile-sider {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px;
}

.mobile-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}

.mobile-logo-icon {
  color: var(--arco-primary);
}

.mobile-logo-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.mobile-nav-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mobile-nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 40px;
  padding: 0 12px;
  font-size: 14px;
  color: var(--neutral-text-2);
  text-decoration: none;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.mobile-nav-item:hover {
  background: var(--neutral-hover);
  color: var(--neutral-text-1);
}

.mobile-nav-item--active {
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  font-weight: 500;
}

.mobile-user-card {
  margin-top: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s ease;
  border-top: 1px solid var(--neutral-border);
}

.mobile-user-card:hover {
  background: var(--neutral-hover);
}

/* ===== 主内容区 ===== */
.main-layout {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--neutral-bg);
}

.main-layout :deep(.n-layout) {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.main-layout :deep(.n-layout-scroll-container) {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

.main-layout :deep(.n-layout-content) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  position: relative;
  overflow: hidden;
}

/* 隐藏 Naive UI LayoutSider 默认 border 以使用自定义边框 */
:deep(.n-layout-sider) {
  background: var(--sidebar-bg);
  border-right: none;
}

:deep(.n-layout-sider .n-layout-sider-scroll-container) {
  border-right: none;
  overflow: visible;
}

/* z-index !important 保留：teleported popover 脱离组件树，scoped 特异性无法覆盖 Naive UI 内联 z-index */
:global(.collapsed-submenu-popover.n-popover) {
  z-index: 1050 !important;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--sidebar-border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(24px) saturate(170%);
  -webkit-backdrop-filter: blur(24px) saturate(170%);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.18), 0 0 0 1px rgba(22, 93, 255, 0.08);
}

:global(:root[data-theme="dark"] .collapsed-submenu-popover.n-popover) {
  background: rgba(24, 30, 44, 0.76);
}
</style>
