# 6.5 OmicsHub 前端路由、页面结构与 AI 对话面板架构

> **文档版本**: v1.0  
> **技术栈**: Vue 3.4+ / TypeScript 5.0+ / Vite 5+ / Naive UI 2.38+ / Element Plus 2.5+ / Pinia 2.1+ / Vue Router 4+ / Axios 1.6+  
> **作者**: 前端架构组  
> **日期**: 2025-06-09

---

## 目录

1. [完整路由表设计](#1-完整路由表设计)
2. [页面布局架构](#2-页面布局架构)
3. [核心页面组件设计](#3-核心页面组件设计)
4. [Pinia Store 设计](#4-pinia-store-设计)
5. [AI 对话面板架构](#5-ai-对话面板架构)
6. [暗黑模式实现](#6-暗黑模式实现)
7. [文件目录结构总览](#7-文件目录结构总览)

---

## 1. 完整路由表设计

### 1.1 路由类型定义

```typescript
// src/router/types.ts
import type { RouteRecordRaw } from 'vue-router'

/** 布局类型 */
export type LayoutType = 'blank' | 'main' | 'admin'

/** 路由元信息 */
export interface RouteMeta {
  /** 页面标题 */
  title: string
  /** 是否需要认证 */
  requiresAuth: boolean
  /** 是否需要管理员权限 */
  requiresAdmin?: boolean
  /** 布局类型 */
  layout: LayoutType
  /** 左侧菜单图标 */
  icon?: string
  /** 是否在侧边栏菜单中隐藏 */
  hideInMenu?: boolean
  /** 面包屑父级路由名 */
  breadcrumbParent?: string
  /** 页面缓存名称（keep-alive） */
  keepAlive?: string
  /** 当前激活的菜单项（用于子路由高亮父菜单） */
  activeMenu?: string
}

// 扩展 Vue Router 的 RouteRecordRaw 类型声明
declare module 'vue-router' {
  interface RouteMeta {
    title: string
    requiresAuth: boolean
    requiresAdmin?: boolean
    layout: LayoutType
    icon?: string
    hideInMenu?: boolean
    breadcrumbParent?: string
    keepAlive?: string
    activeMenu?: string
  }
}
```

### 1.2 完整路由表

```typescript
// src/router/routes.ts
import type { RouteRecordRaw } from 'vue-router'

// ─────────────────────────────────────────
// 布局组件（懒加载）
// ─────────────────────────────────────────
const BlankLayout = () => import('@/layouts/BlankLayout.vue')
const MainLayout = () => import('@/layouts/MainLayout.vue')
const AdminLayout = () => import('@/layouts/AdminLayout.vue')

// ─────────────────────────────────────────
// 页面组件（懒加载）
// ─────────────────────────────────────────
// 认证
const LoginView = () => import('@/views/auth/LoginView.vue')
const RegisterView = () => import('@/views/auth/RegisterView.vue')

// 仪表盘
const DashboardView = () => import('@/views/dashboard/DashboardView.vue')

// 项目
const ProjectsView = () => import('@/views/project/ProjectsView.vue')
const ProjectDetailView = () => import('@/views/project/ProjectDetailView.vue')
const ProjectSamplesView = () => import('@/views/project/ProjectSamplesView.vue')
const ProjectFilesView = () => import('@/views/project/ProjectFilesView.vue')

// 流程市场
const FlowMarketView = () => import('@/views/flow/FlowMarketView.vue')
const FlowDetailView = () => import('@/views/flow/FlowDetailView.vue')

// 任务（核心）
const TaskListView = () => import('@/views/task/TaskListView.vue')
const TaskSubmitView = () => import('@/views/task/TaskSubmitView.vue')
const TaskDetailView = () => import('@/views/task/TaskDetailView.vue')

// 管理后台
const AdminFlowManager = () => import('@/views/admin/AdminFlowManager.vue')
const AdminUserManager = () => import('@/views/admin/AdminUserManager.vue')
const AdminMCPManager = () => import('@/views/admin/AdminMCPManager.vue')
const AdminSystemSettings = () => import('@/views/admin/AdminSystemSettings.vue')

// 个人设置
const ProfileView = () => import('@/views/profile/ProfileView.vue')

// 404
const NotFoundView = () => import('@/views/error/NotFoundView.vue')

// ═════════════════════════════════════════
// 路由表定义
// ═════════════════════════════════════════
export const routes: RouteRecordRaw[] = [
  // ─────────────────────────────────────
  // 1. 认证路由（Blank 布局）
  // ─────────────────────────────────────
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: {
      title: '登录',
      requiresAuth: false,
      layout: 'blank',
    },
  },
  {
    path: '/register',
    name: 'Register',
    component: RegisterView,
    meta: {
      title: '注册',
      requiresAuth: false,
      layout: 'blank',
    },
  },

  // ─────────────────────────────────────
  // 2. 主工作区路由（Main 布局）
  // ─────────────────────────────────────
  {
    path: '/',
    component: MainLayout,
    meta: {
      title: 'OmicsHub',
      requiresAuth: true,
      layout: 'main',
    },
    children: [
      // 仪表盘
      {
        path: '',
        name: 'Dashboard',
        component: DashboardView,
        meta: {
          title: '仪表盘',
          requiresAuth: true,
          layout: 'main',
          icon: 'DashboardOutlined',
          keepAlive: 'DashboardView',
        },
      },

      // ── 项目管理 ──
      {
        path: 'projects',
        name: 'Projects',
        component: ProjectsView,
        meta: {
          title: '项目管理',
          requiresAuth: true,
          layout: 'main',
          icon: 'FolderOutlined',
          keepAlive: 'ProjectsView',
        },
      },
      {
        path: 'projects/:id',
        name: 'ProjectDetail',
        component: ProjectDetailView,
        meta: {
          title: '项目详情',
          requiresAuth: true,
          layout: 'main',
          icon: 'FolderOpenOutlined',
          activeMenu: 'Projects',
          hideInMenu: true,
        },
        redirect: (to) => `/projects/${to.params.id}/samples`,
        children: [
          {
            path: 'samples',
            name: 'ProjectSamples',
            component: ProjectSamplesView,
            meta: {
              title: '样本管理',
              requiresAuth: true,
              layout: 'main',
              hideInMenu: true,
            },
          },
          {
            path: 'files',
            name: 'ProjectFiles',
            component: ProjectFilesView,
            meta: {
              title: '文件列表',
              requiresAuth: true,
              layout: 'main',
              hideInMenu: true,
            },
          },
        ],
      },

      // ── 流程市场 ──
      {
        path: 'flows',
        name: 'FlowMarket',
        component: FlowMarketView,
        meta: {
          title: '流程市场',
          requiresAuth: true,
          layout: 'main',
          icon: 'ApartmentOutlined',
          keepAlive: 'FlowMarketView',
        },
      },
      {
        path: 'flows/:id',
        name: 'FlowDetail',
        component: FlowDetailView,
        meta: {
          title: '流程详情',
          requiresAuth: true,
          layout: 'main',
          hideInMenu: true,
          activeMenu: 'FlowMarket',
        },
      },

      // ── 任务管理（核心） ──
      {
        path: 'tasks',
        name: 'TaskList',
        component: TaskListView,
        meta: {
          title: '任务列表',
          requiresAuth: true,
          layout: 'main',
          icon: 'ExperimentOutlined',
          keepAlive: 'TaskListView',
        },
      },
      {
        path: 'tasks/new',
        name: 'TaskSubmit',
        component: TaskSubmitView,
        meta: {
          title: '新建任务',
          requiresAuth: true,
          layout: 'main',
          hideInMenu: true,
          icon: 'PlusOutlined',
        },
      },
      {
        path: 'tasks/:id',
        name: 'TaskDetail',
        component: TaskDetailView,
        meta: {
          title: '任务详情',
          requiresAuth: true,
          layout: 'main',
          hideInMenu: true,
          activeMenu: 'TaskList',
        },
      },

      // ── 个人设置 ──
      {
        path: 'profile',
        name: 'Profile',
        component: ProfileView,
        meta: {
          title: '个人设置',
          requiresAuth: true,
          layout: 'main',
          icon: 'UserOutlined',
          hideInMenu: true,
        },
      },
    ],
  },

  // ─────────────────────────────────────
  // 3. 管理后台路由（Admin 布局）
  // ─────────────────────────────────────
  {
    path: '/admin',
    component: AdminLayout,
    meta: {
      title: '管理后台',
      requiresAuth: true,
      requiresAdmin: true,
      layout: 'admin',
    },
    redirect: '/admin/flows',
    children: [
      {
        path: 'flows',
        name: 'AdminFlowManager',
        component: AdminFlowManager,
        meta: {
          title: '流程管理',
          requiresAuth: true,
          requiresAdmin: true,
          layout: 'admin',
          icon: 'CodeOutlined',
        },
      },
      {
        path: 'users',
        name: 'AdminUserManager',
        component: AdminUserManager,
        meta: {
          title: '用户管理',
          requiresAuth: true,
          requiresAdmin: true,
          layout: 'admin',
          icon: 'TeamOutlined',
        },
      },
      {
        path: 'mcp',
        name: 'AdminMCPManager',
        component: AdminMCPManager,
        meta: {
          title: 'MCP Server 管理',
          requiresAuth: true,
          requiresAdmin: true,
          layout: 'admin',
          icon: 'CloudServerOutlined',
        },
      },
      {
        path: 'system',
        name: 'AdminSystemSettings',
        component: AdminSystemSettings,
        meta: {
          title: '系统设置',
          requiresAuth: true,
          requiresAdmin: true,
          layout: 'admin',
          icon: 'SettingOutlined',
        },
      },
    ],
  },

  // ─────────────────────────────────────
  // 4. 404 与重定向
  // ─────────────────────────────────────
  {
    path: '/404',
    name: 'NotFound',
    component: NotFoundView,
    meta: {
      title: '页面不存在',
      requiresAuth: false,
      layout: 'blank',
    },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/404',
    meta: {
      title: '重定向',
      requiresAuth: false,
      layout: 'blank',
    },
  },
]
```

### 1.3 路由守卫与导航逻辑

```typescript
// src/router/guard.ts
import type { Router, NavigationGuardNext } from 'vue-router'
import { useAuthStore } from '@/stores/modules/auth'
import { useThemeStore } from '@/stores/modules/theme'
import { message } from '@/utils/naiveMessage'

export function setupRouterGuard(router: Router) {
  // ── 全局前置守卫 ──
  router.beforeEach(
    async (to, _from, next: NavigationGuardNext) => {
      const authStore = useAuthStore()
      const themeStore = useThemeStore()

      // 1. 动态设置页面标题
      const baseTitle = 'OmicsHub'
      document.title = to.meta.title
        ? `${to.meta.title} | ${baseTitle}`
        : baseTitle

      // 2. 同步主题（避免闪烁）
      themeStore.applyThemeImmediately()

      // 3. 无需认证的路由直接放行
      if (!to.meta.requiresAuth) {
        return next()
      }

      // 4. 未登录 → 跳转登录页
      if (!authStore.isLoggedIn) {
        // 尝试静默刷新 token
        const refreshed = await authStore.tryRefreshToken()
        if (!refreshed) {
          message.warning('请先登录')
          return next({
            name: 'Login',
            query: { redirect: to.fullPath },
          })
        }
      }

      // 5. 需要管理员权限但未满足
      if (to.meta.requiresAdmin && !authStore.isAdmin) {
        message.error('无权访问该页面')
        return next({ name: 'Dashboard' })
      }

      // 6. 放行
      next()
    }
  )

  // ── 全局后置钩子 ──
  router.afterEach((to) => {
    // 滚动到顶部
    window.scrollTo({ top: 0, behavior: 'smooth' })

    // 记录最近访问路由（用于返回功能）
    const authStore = useAuthStore()
    if (to.meta.requiresAuth) {
      authStore.setLastVisitedRoute(to.path)
    }
  })

  // ── 全局错误处理 ──
  router.onError((error) => {
    console.error('[Router Error]', error)
    message.error('页面加载失败，请刷新重试')
  })
}
```

### 1.4 路由入口

```typescript
// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from './routes'
import { setupRouterGuard } from './guard'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

setupRouterGuard(router)

export default router
```

---

## 2. 页面布局架构

### 2.1 三种布局类型概览

| 布局 | 路径 | 用途 | 特征 |
|------|------|------|------|
| `BlankLayout` | `/login`, `/register`, `/404` | 认证 & 错误页 | 无导航，纯白/暗色背景 |
| `MainLayout` | `/`, `/projects`, `/flows`, `/tasks/*` | 主工作区 | 左侧导航 + 顶部 Header + 内容区 + **右侧 AI 面板** |
| `AdminLayout` | `/admin/*` | 管理后台 | 独立侧边栏 + 内容区（无 AI 面板） |

### 2.2 BlankLayout.vue — 空布局（登录/注册）

```vue
<!-- src/layouts/BlankLayout.vue -->
<template>
  <n-config-provider :theme="themeStore.naiveTheme" :locale="zhCN">
    <n-loading-bar-provider>
      <n-dialog-provider>
        <n-notification-provider>
          <n-message-provider>
            <div class="blank-layout" :class="{ dark: themeStore.isDark }">
              <!-- 装饰性背景 -->
              <div class="blank-layout__bg">
                <div class="blob blob-1"></div>
                <div class="blob blob-2"></div>
                <div class="blob blob-3"></div>
              </div>

              <!-- 左侧品牌展示区（仅宽屏） -->
              <div class="blank-layout__brand" v-if="!isMobile">
                <div class="brand-content">
                  <img src="/logo.svg" alt="OmicsHub" class="brand-logo" />
                  <h1 class="brand-title">OmicsHub</h1>
                  <p class="brand-subtitle">多组学智能分析平台</p>
                  <div class="brand-features">
                    <div class="feature-item">
                      <n-icon size="20"><DnaOutlined /></n-icon>
                      <span>基因组 / 转录组 / 蛋白质组</span>
                    </div>
                    <div class="feature-item">
                      <n-icon size="20"><RobotOutlined /></n-icon>
                      <span>AI 助手全流程辅助</span>
                    </div>
                    <div class="feature-item">
                      <n-icon size="20"><ThunderboltOutlined /></n-icon>
                      <span>可视化流程编排</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 右侧表单区 -->
              <div class="blank-layout__form">
                <div class="form-card">
                  <router-view v-slot="{ Component }">
                    <transition name="fade-slide" mode="out-in">
                      <component :is="Component" />
                    </transition>
                  </router-view>
                </div>
              </div>
            </div>
          </n-message-provider>
        </n-notification-provider>
      </n-dialog-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useWindowSize } from '@vueuse/core'
import { NConfigProvider, NLoadingBarProvider, NDialogProvider, NNotificationProvider, NMessageProvider, NIcon } from 'naive-ui'
import { zhCN } from 'naive-ui'
import { DnaOutlined, RobotOutlined, ThunderboltOutlined } from '@vicons/antd'
import { useThemeStore } from '@/stores/modules/theme'

const themeStore = useThemeStore()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)
</script>

<style scoped lang="scss">
.blank-layout {
  min-height: 100vh;
  display: flex;
  position: relative;
  overflow: hidden;

  &__bg {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;

    .blob {
      position: absolute;
      border-radius: 50%;
      filter: blur(80px);
      opacity: 0.35;
      animation: float 20s ease-in-out infinite;

      &-1 {
        width: 400px; height: 400px;
        background: #6366f1;
        top: -100px; left: -100px;
        animation-delay: 0s;
      }
      &-2 {
        width: 300px; height: 300px;
        background: #8b5cf6;
        bottom: -50px; right: 10%;
        animation-delay: -7s;
      }
      &-3 {
        width: 250px; height: 250px;
        background: #ec4899;
        top: 40%; left: 30%;
        animation-delay: -14s;
      }
    }
  }

  &__brand {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    z-index: 1;
    background: linear-gradient(135deg, rgba(99,102,241,0.08) 0%, rgba(139,92,246,0.05) 100%);

    .brand-content {
      text-align: center;
      padding: 48px;

      .brand-logo { width: 72px; height: 72px; margin-bottom: 16px; }
      .brand-title { font-size: 32px; font-weight: 700; margin-bottom: 8px; color: var(--text-primary); }
      .brand-subtitle { font-size: 16px; color: var(--text-secondary); margin-bottom: 40px; }

      .brand-features {
        display: flex;
        flex-direction: column;
        gap: 16px;

        .feature-item {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          font-size: 14px;
          color: var(--text-secondary);
        }
      }
    }
  }

  &__form {
    width: 480px;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    z-index: 1;
    padding: 32px;

    .form-card {
      width: 100%;
      max-width: 400px;
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 16px;
      padding: 40px 32px;
      backdrop-filter: blur(12px);
      box-shadow: 0 8px 32px rgba(0,0,0,0.08);
    }
  }

  // 移动端适配
  @media (max-width: 768px) {
    .blank-layout__form {
      width: 100%;
      padding: 16px;

      .form-card {
        border-radius: 12px;
        padding: 32px 24px;
      }
    }
  }
}

@keyframes float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -30px) scale(1.05); }
  66% { transform: translate(-20px, 20px) scale(0.95); }
}

.fade-slide-enter-active, .fade-slide-leave-active {
  transition: all 0.3s ease;
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateX(20px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}
</style>
```

### 2.3 MainLayout.vue — 主布局（核心）

```vue
<!-- src/layouts/MainLayout.vue -->
<template>
  <n-config-provider
    :theme="themeStore.naiveTheme"
    :theme-overrides="themeStore.naiveThemeOverrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <n-loading-bar-provider>
      <n-dialog-provider>
        <n-notification-provider>
          <n-message-provider>
            <n-layout class="main-layout" has-sider>
              <!-- 左侧导航栏 -->
              <n-layout-sider
                class="main-layout__sider"
                :collapsed="siderCollapsed"
                :collapsed-width="64"
                :width="220"
                :native-scrollbar="false"
                bordered
                collapse-mode="width"
                show-trigger
                @update:collapsed="siderCollapsed = $event"
              >
                <AppSidebar :collapsed="siderCollapsed" />
              </n-layout-sider>

              <!-- 右侧主区域 -->
              <n-layout class="main-layout__right">
                <!-- 顶部 Header -->
                <n-layout-header class="main-layout__header" bordered>
                  <AppHeader
                    :sider-collapsed="siderCollapsed"
                    @toggle-sider="siderCollapsed = !siderCollapsed"
                  />
                </n-layout-header>

                <!-- 内容区 + AI 面板 -->
                <n-layout class="main-layout__body" has-sider sider-placement="right">
                  <!-- 主内容区 -->
                  <n-layout-content
                    class="main-layout__content"
                    :style="contentStyle"
                    :native-scrollbar="false"
                  >
                    <AppBreadcrumb />
                    <div class="main-layout__content-inner">
                      <router-view v-slot="{ Component, route }">
                        <transition name="fade" mode="out-in">
                          <keep-alive :include="cachedViews">
                            <component :is="Component" :key="route.path" />
                          </keep-alive>
                        </transition>
                      </router-view>
                    </div>
                  </n-layout-content>

                  <!-- AI 对话面板 -->
                  <n-layout-sider
                    class="main-layout__ai-sider"
                    :width="380"
                    :collapsed-width="0"
                    :collapsed="!chatStore.panelVisible"
                    collapse-mode="transform"
                    show-trigger="bar"
                    trigger-style=""
                    @update:collapsed="chatStore.togglePanel"
                  >
                    <AIChatPanel />
                  </n-layout-sider>
                </n-layout>
              </n-layout>
            </n-layout>

            <!-- AI 面板折叠时的浮动按钮 -->
            <AIChatFab v-if="!chatStore.panelVisible" />
          </n-message-provider>
        </n-notification-provider>
      </n-dialog-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NConfigProvider, NLoadingBarProvider, NDialogProvider,
  NNotificationProvider, NMessageProvider,
  NLayout, NLayoutSider, NLayoutHeader, NLayoutContent,
} from 'naive-ui'
import { zhCN, dateZhCN } from 'naive-ui'

import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppBreadcrumb from '@/components/layout/AppBreadcrumb.vue'
import AIChatPanel from '@/components/ai-chat/AIChatPanel.vue'
import AIChatFab from '@/components/ai-chat/AIChatFab.vue'

import { useThemeStore } from '@/stores/modules/theme'
import { useChatStore } from '@/stores/modules/chat'
import { useTabStore } from '@/stores/modules/tab'

// ── stores ──
const themeStore = useThemeStore()
const chatStore = useChatStore()
const tabStore = useTabStore()
const route = useRoute()

// ── 侧边栏折叠 ──
const siderCollapsed = ref(false)

// ── 缓存视图列表（keep-alive） ──
const cachedViews = computed(() => tabStore.cachedViews)

// ── 内容区样式（根据 AI 面板状态自适应宽度） ──
const contentStyle = computed(() => {
  return {
    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
  }
})

// ── 路由变化时自动收集 AI 上下文 ──
watch(
  () => route.path,
  (newPath) => {
    chatStore.collectRouteContext(newPath, route.params, route.query)
  },
  { immediate: true }
)
</script>

<style scoped lang="scss">
.main-layout {
  height: 100vh;

  &__sider {
    z-index: 100;
    :deep(.n-layout-sider-scroll-container) {
      display: flex;
      flex-direction: column;
    }
  }

  &__right {
    display: flex;
    flex-direction: column;
  }

  &__header {
    height: 56px;
    padding: 0 16px;
    display: flex;
    align-items: center;
    z-index: 99;
  }

  &__body {
    flex: 1;
    overflow: hidden;
  }

  &__content {
    flex: 1;
    overflow: auto;
    background: var(--content-bg);

    &-inner {
      padding: 20px;
      min-height: calc(100% - 40px);
    }
  }

  &__ai-sider {
    z-index: 98;
    :deep(.n-layout-sider-scroll-container) {
      border-left: 1px solid var(--border-color);
    }
  }
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
```

### 2.4 AdminLayout.vue — 管理后台布局

```vue
<!-- src/layouts/AdminLayout.vue -->
<template>
  <n-config-provider
    :theme="themeStore.naiveTheme"
    :theme-overrides="themeStore.naiveThemeOverrides"
    :locale="zhCN"
  >
    <n-loading-bar-provider>
      <n-dialog-provider>
        <n-notification-provider>
          <n-message-provider>
            <n-layout class="admin-layout" has-sider>
              <!-- 管理后台侧边栏 -->
              <n-layout-sider
                class="admin-layout__sider"
                :collapsed="collapsed"
                :collapsed-width="64"
                :width="240"
                bordered
                collapse-mode="width"
                show-trigger
                @update:collapsed="collapsed = $event"
              >
                <!-- Logo -->
                <div class="admin-logo">
                  <img src="/logo.svg" alt="" class="admin-logo__icon" />
                  <span v-if="!collapsed" class="admin-logo__text">OmicsHub Admin</span>
                </div>

                <!-- 管理菜单 -->
                <n-menu
                  :value="activeMenuKey"
                  :collapsed="collapsed"
                  :collapsed-width="64"
                  :options="adminMenuOptions"
                  @update:value="handleMenuSelect"
                />
              </n-layout-sider>

              <!-- 内容区 -->
              <n-layout class="admin-layout__main">
                <n-layout-header class="admin-layout__header" bordered>
                  <div class="header-left">
                    <n-button text @click="$router.push({ name: 'Dashboard' })">
                      <template #icon><n-icon><ArrowLeftOutlined /></n-icon></template>
                      返回工作台
                    </n-button>
                  </div>
                  <div class="header-right">
                    <ThemeToggle />
                    <UserDropdown />
                  </div>
                </n-layout-header>

                <n-layout-content class="admin-layout__content" :native-scrollbar="false">
                  <div class="admin-layout__content-inner">
                    <router-view />
                  </div>
                </n-layout-content>
              </n-layout>
            </n-layout>
          </n-message-provider>
        </n-notification-provider>
      </n-dialog-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, ref, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NConfigProvider, NLoadingBarProvider, NDialogProvider,
  NNotificationProvider, NMessageProvider,
  NLayout, NLayoutSider, NLayoutHeader, NLayoutContent,
  NMenu, NButton, NIcon,
} from 'naive-ui'
import { zhCN } from 'naive-ui'
import {
  CodeOutlined, TeamOutlined, CloudServerOutlined, SettingOutlined, ArrowLeftOutlined,
} from '@vicons/antd'
import { useThemeStore } from '@/stores/modules/theme'
import ThemeToggle from '@/components/common/ThemeToggle.vue'
import UserDropdown from '@/components/layout/UserDropdown.vue'

const themeStore = useThemeStore()
const route = useRoute()
const router = useRouter()

const collapsed = ref(false)
const activeMenuKey = computed(() => route.name as string)

const adminMenuOptions = [
  {
    label: '流程管理',
    key: 'AdminFlowManager',
    icon: renderIcon(CodeOutlined),
    path: '/admin/flows',
  },
  {
    label: '用户管理',
    key: 'AdminUserManager',
    icon: renderIcon(TeamOutlined),
    path: '/admin/users',
  },
  {
    label: 'MCP Server',
    key: 'AdminMCPManager',
    icon: renderIcon(CloudServerOutlined),
    path: '/admin/mcp',
  },
  {
    label: '系统设置',
    key: 'AdminSystemSettings',
    icon: renderIcon(SettingOutlined),
    path: '/admin/system',
  },
]

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function handleMenuSelect(key: string) {
  const item = adminMenuOptions.find(o => o.key === key)
  if (item) router.push(item.path)
}
</script>

<style scoped lang="scss">
.admin-layout {
  height: 100vh;

  &__sider {
    .admin-logo {
      height: 56px;
      display: flex;
      align-items: center;
      padding: 0 20px;
      gap: 12px;
      border-bottom: 1px solid var(--border-color);

      &__icon { width: 28px; height: 28px; }
      &__text {
        font-size: 16px;
        font-weight: 600;
        white-space: nowrap;
        color: var(--text-primary);
      }
    }
  }

  &__main {
    display: flex;
    flex-direction: column;
  }

  &__header {
    height: 56px;
    padding: 0 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__content {
    flex: 1;
    overflow: auto;
    background: var(--content-bg);

    &-inner {
      padding: 24px;
      max-width: 1200px;
      margin: 0 auto;
    }
  }
}
</style>
```

### 2.5 AppSidebar.vue — 左侧导航组件

```vue
<!-- src/components/layout/AppSidebar.vue -->
<template>
  <div class="app-sidebar">
    <!-- Logo 区 -->
    <div class="app-sidebar__logo" @click="$router.push('/')">
      <img src="/logo.svg" alt="OmicsHub" class="logo-img" />
      <span v-if="!collapsed" class="logo-text">OmicsHub</span>
    </div>

    <!-- 主导航菜单 -->
    <n-menu
      class="app-sidebar__menu"
      :value="activeKey"
      :collapsed="collapsed"
      :collapsed-width="64"
      :options="mainMenuOptions"
      :render-label="renderMenuLabel"
      @update:value="handleMenuSelect"
    />

    <!-- 底部操作区 -->
    <div class="app-sidebar__footer" v-if="!collapsed">
      <n-divider style="margin: 8px 0" />
      <n-button text block @click="$router.push('/profile')">
        <template #icon><n-icon><SettingOutlined /></n-icon></template>
        设置
      </n-button>
    </div>

    <!-- 折叠时的底部图标 -->
    <div class="app-sidebar__footer-collapsed" v-else>
      <n-button text circle @click="$router.push('/profile')">
        <template #icon><n-icon><SettingOutlined /></n-icon></template>
      </n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NMenu, NButton, NIcon, NDivider } from 'naive-ui'
import {
  DashboardOutlined,
  FolderOutlined,
  ApartmentOutlined,
  ExperimentOutlined,
  SettingOutlined,
  SafetyCertificateOutlined,
} from '@vicons/antd'
import type { MenuOption } from 'naive-ui'
import { useAuthStore } from '@/stores/modules/auth'

const props = defineProps<{ collapsed: boolean }>()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const activeKey = computed(() => {
  // 如果当前路由有 activeMenu 元信息，使用它高亮父菜单
  const activeMenu = route.meta?.activeMenu
  return (activeMenu as string) || (route.name as string)
})

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function renderMenuLabel(option: MenuOption) {
  return h('span', {}, option.label as string)
}

const mainMenuOptions = computed<MenuOption[]>(() => {
  const items: MenuOption[] = [
    {
      label: '仪表盘',
      key: 'Dashboard',
      icon: renderIcon(DashboardOutlined),
      path: '/',
    },
    {
      label: '项目管理',
      key: 'Projects',
      icon: renderIcon(FolderOutlined),
      path: '/projects',
    },
    {
      label: '流程市场',
      key: 'FlowMarket',
      icon: renderIcon(ApartmentOutlined),
      path: '/flows',
    },
    {
      label: '任务中心',
      key: 'TaskList',
      icon: renderIcon(ExperimentOutlined),
      path: '/tasks',
    },
  ]

  // 管理员额外显示管理后台入口
  if (authStore.isAdmin) {
    items.push({
      label: '管理后台',
      key: 'AdminFlowManager',
      icon: renderIcon(SafetyCertificateOutlined),
      path: '/admin',
    })
  }

  return items
})

function handleMenuSelect(key: string) {
  const item = mainMenuOptions.value.find(o => o.key === key)
  if (item && item.path) {
    router.push(item.path)
  }
}
</script>

<style scoped lang="scss">
.app-sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;

  &__logo {
    height: 56px;
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 10px;
    cursor: pointer;
    border-bottom: 1px solid var(--border-color);
    transition: background 0.2s;

    &:hover { background: var(--hover-bg); }

    .logo-img { width: 28px; height: 28px; flex-shrink: 0; }
    .logo-text {
      font-size: 16px;
      font-weight: 600;
      white-space: nowrap;
      color: var(--text-primary);
    }
  }

  &__menu {
    flex: 1;
    padding: 8px 0;
  }

  &__footer {
    padding: 0 12px 12px;
  }

  &__footer-collapsed {
    padding: 12px 0;
    display: flex;
    justify-content: center;
  }
}
</style>
```

### 2.6 AppHeader.vue — 顶部 Header 组件

```vue
<!-- src/components/layout/AppHeader.vue -->
<template>
  <div class="app-header">
    <!-- 左侧：面包屑 + 页面标题 -->
    <div class="app-header__left">
      <n-breadcrumb separator="/">
        <n-breadcrumb-item v-for="item in breadcrumbs" :key="item.path">
          <router-link v-if="item.to" :to="item.to">{{ item.title }}</router-link>
          <span v-else>{{ item.title }}</span>
        </n-breadcrumb-item>
      </n-breadcrumb>
    </div>

    <!-- 右侧：操作区 -->
    <div class="app-header__right">
      <!-- AI 面板开关 -->
      <n-tooltip placement="bottom">
        <template #trigger>
          <n-badge :value="chatStore.unreadCount" :max="99" processing>
            <n-button
              text
              circle
              :type="chatStore.panelVisible ? 'primary' : 'default'"
              @click="chatStore.togglePanel()"
            >
              <template #icon>
                <n-icon size="20"><RobotOutlined /></n-icon>
              </template>
            </n-button>
          </n-badge>
        </template>
        {{ chatStore.panelVisible ? '收起 AI 助手' : '展开 AI 助手' }}
      </n-tooltip>

      <!-- 通知中心 -->
      <NotificationBell />

      <!-- 主题切换 -->
      <ThemeToggle />

      <!-- 用户下拉 -->
      <UserDropdown />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NBreadcrumb, NBreadcrumbItem, NButton, NIcon, NTooltip, NBadge } from 'naive-ui'
import { RobotOutlined } from '@vicons/antd'

import ThemeToggle from '@/components/common/ThemeToggle.vue'
import UserDropdown from '@/components/layout/UserDropdown.vue'
import NotificationBell from '@/components/layout/NotificationBell.vue'

import { useChatStore } from '@/stores/modules/chat'

const route = useRoute()
const chatStore = useChatStore()

// ── 面包屑计算 ──
interface BreadcrumbItem {
  title: string
  path: string
  to?: string
}

const breadcrumbs = computed<BreadcrumbItem[]>(() => {
  const items: BreadcrumbItem[] = []
  const matched = route.matched

  for (let i = 0; i < matched.length; i++) {
    const m = matched[i]
    if (m.meta?.title) {
      items.push({
        title: m.meta.title as string,
        path: m.path,
        to: i < matched.length - 1 ? m.path : undefined,
      })
    }
  }

  return items
})
</script>

<style scoped lang="scss">
.app-header {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;

  &__left {
    flex: 1;
    min-width: 0;
  }

  &__right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
}
</style>
```

### 2.7 AIChatFab.vue — AI 面板折叠时的浮动按钮

```vue
<!-- src/components/ai-chat/AIChatFab.vue -->
<template>
  <div
    class="ai-chat-fab"
    :class="{ pulsing: chatStore.unreadCount > 0 }"
    @click="chatStore.togglePanel(true)"
  >
    <n-badge :value="chatStore.unreadCount" :max="99" :show="chatStore.unreadCount > 0">
      <div class="ai-chat-fab__btn">
        <n-icon size="24"><RobotOutlined /></n-icon>
        <span class="fab-label">AI 助手</span>
      </div>
    </n-badge>
  </div>
</template>

<script setup lang="ts">
import { NIcon, NBadge } from 'naive-ui'
import { RobotOutlined } from '@vicons/antd'
import { useChatStore } from '@/stores/modules/chat'

const chatStore = useChatStore()
</script>

<style scoped lang="scss">
.ai-chat-fab {
  position: fixed;
  right: 24px;
  bottom: 32px;
  z-index: 999;
  cursor: pointer;
  transition: transform 0.3s ease;

  &:hover {
    transform: scale(1.05);
  }

  &__btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 12px 20px;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: #fff;
    border-radius: 28px;
    box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4);
    font-weight: 500;
    font-size: 14px;

    .fab-label {
      white-space: nowrap;
    }
  }

  &.pulsing {
    animation: pulse-ring 2s ease-in-out infinite;
  }
}

@keyframes pulse-ring {
  0%, 100% { box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.4); }
  50% { box-shadow: 0 0 0 12px rgba(99, 102, 241, 0); }
}
</style>
```

---

## 3. 核心页面组件设计

### 3.1 仪表盘页（DashboardView.vue）

```vue
<!-- src/views/dashboard/DashboardView.vue -->
<template>
  <div class="dashboard-view">
    <!-- 欢迎语 -->
    <div class="dashboard-welcome">
      <h2>{{ welcomeText }}，{{ authStore.user?.display_name || '研究员' }}</h2>
      <p class="text-secondary">这是您今天的工作概览</p>
    </div>

    <!-- 统计卡片 -->
    <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
      <n-grid-item span="4 s:2 l:1">
        <StatCard
          title="进行中任务"
          :value="stats.runningTasks"
          icon="LoadingOutlined"
          color="#6366f1"
          :to="{ name: 'TaskList', query: { status: 'running' } }"
        />
      </n-grid-item>
      <n-grid-item span="4 s:2 l:1">
        <StatCard
          title="已完成任务"
          :value="stats.completedTasks"
          icon="CheckCircleOutlined"
          color="#10b981"
          :to="{ name: 'TaskList', query: { status: 'completed' } }"
        />
      </n-grid-item>
      <n-grid-item span="4 s:2 l:1">
        <StatCard
          title="项目总数"
          :value="stats.projectCount"
          icon="FolderOutlined"
          color="#f59e0b"
          :to="{ name: 'Projects' }"
        />
      </n-grid-item>
      <n-grid-item span="4 s:2 l:1">
        <StatCard
          title="待处理通知"
          :value="stats.notifications"
          icon="BellOutlined"
          color="#ef4444"
        />
      </n-grid-item>
    </n-grid>

    <!-- 快速开始 + 最近任务 -->
    <n-grid :cols="3" :x-gap="16" :y-gap="16" style="margin-top: 20px" responsive="screen">
      <!-- 快速开始 -->
      <n-grid-item span="3 m:1">
        <n-card title="快速开始" class="dashboard-card">
          <n-space vertical>
            <QuickStartItem
              v-for="flow in popularFlows"
              :key="flow.id"
              :flow="flow"
              @click="handleQuickStart(flow)"
            />
          </n-space>
        </n-card>
      </n-grid-item>

      <!-- 最近任务 -->
      <n-grid-item span="3 m:2">
        <n-card title="最近任务" class="dashboard-card">
          <TaskTableLite
            :tasks="recentTasks"
            :loading="loading"
            @row-click="handleTaskClick"
          />
          <template #header-extra>
            <n-button text type="primary" @click="$router.push({ name: 'TaskList' })">
              查看全部
              <template #icon><n-icon><ArrowRightOutlined /></n-icon></template>
            </n-button>
          </template>
        </n-card>
      </n-grid-item>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NGrid, NGridItem, NCard, NSpace, NButton, NIcon } from 'naive-ui'
import {
  LoadingOutlined, CheckCircleOutlined, FolderOutlined, BellOutlined, ArrowRightOutlined,
} from '@vicons/antd'

import StatCard from '@/components/dashboard/StatCard.vue'
import QuickStartItem from '@/components/dashboard/QuickStartItem.vue'
import TaskTableLite from '@/components/task/TaskTableLite.vue'

import { useAuthStore } from '@/stores/modules/auth'
import { useTaskStore } from '@/stores/modules/task'
import { useFlowStore } from '@/stores/modules/flow'
import type { FlowSummary } from '@/types/flow'

const router = useRouter()
const authStore = useAuthStore()
const taskStore = useTaskStore()
const flowStore = useFlowStore()

const loading = ref(false)
const stats = ref({
  runningTasks: 0,
  completedTasks: 0,
  projectCount: 0,
  notifications: 0,
})

const recentTasks = computed(() => taskStore.recentTasks)
const popularFlows = computed<FlowSummary[]>(() => flowStore.popularFlows)

const welcomeText = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 9) return '早上好'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

async function loadDashboardData() {
  loading.value = true
  try {
    await Promise.all([
      taskStore.fetchStats().then(s => { stats.value = s }),
      taskStore.fetchRecentTasks(5),
      flowStore.fetchPopularFlows(),
    ])
  } finally {
    loading.value = false
  }
}

function handleQuickStart(flow: FlowSummary) {
  router.push({
    name: 'TaskSubmit',
    query: { flow: flow.id },
  })
}

function handleTaskClick(taskId: string) {
  router.push({ name: 'TaskDetail', params: { id: taskId } })
}

onMounted(loadDashboardData)
</script>

<style scoped lang="scss">
.dashboard-view {
  .dashboard-welcome {
    margin-bottom: 20px;

    h2 { font-size: 22px; font-weight: 600; margin-bottom: 4px; }
    .text-secondary { color: var(--text-secondary); font-size: 14px; }
  }

  .dashboard-card {
    height: 100%;
  }
}
</style>
```

### 3.2 任务提交页（TaskSubmitView.vue）— 核心页面

```vue
<!-- src/views/task/TaskSubmitView.vue -->
<template>
  <div class="task-submit-view">
    <!-- 步骤条 -->
    <n-steps :current="currentStep" size="small" style="margin-bottom: 24px">
      <n-step title="选择流程" description="选择分析流程" />
      <n-step title="配置参数" description="填写分析参数" />
      <n-step title="确认提交" description="检查并提交" />
    </n-steps>

    <!-- Step 1: 选择流程 & 项目 -->
    <div v-if="currentStep === 1" class="step-panel">
      <n-grid :cols="2" :x-gap="16">
        <n-grid-item>
          <FlowSelector
            v-model="selectedFlowId"
            :flows="flowStore.flowList"
            @select="onFlowSelect"
          />
        </n-grid-item>
        <n-grid-item>
          <ProjectSelector
            v-model="selectedProjectId"
            :projects="projectStore.projectList"
            @select="onProjectSelect"
            @create="showCreateProject = true"
          />
        </n-grid-item>
      </n-grid>

      <div class="step-actions">
        <n-button type="primary" size="large" :disabled="!canNextStep1" @click="currentStep = 2">
          下一步 <template #icon><n-icon><ArrowRightOutlined /></n-icon></template>
        </n-button>
      </div>
    </div>

    <!-- Step 2: 动态表单 -->
    <div v-if="currentStep === 2" class="step-panel">
      <n-spin :show="parsingYaml">
        <template #description>正在解析流程参数...</template>

        <DynamicForm
          v-if="flowSchema"
          ref="dynamicFormRef"
          :schema="flowSchema"
          :project-id="selectedProjectId!"
          :flow-id="selectedFlowId!"
          v-model="formValues"
        />

        <n-empty v-else description="请先选择流程" />
      </n-spin>

      <div class="step-actions">
        <n-button size="large" @click="currentStep = 1">上一步</n-button>
        <n-button type="primary" size="large" :disabled="!flowSchema" @click="handlePreview">
          下一步 <template #icon><n-icon><ArrowRightOutlined /></n-icon></template>
        </n-button>
      </div>
    </div>

    <!-- Step 3: 确认提交 -->
    <div v-if="currentStep === 3" class="step-panel">
      <TaskSubmitPreview
        :flow="selectedFlow"
        :project="selectedProject"
        :params="formValues"
        @edit="currentStep = 2"
      />

      <div class="step-actions">
        <n-button size="large" @click="currentStep = 2">上一步</n-button>
        <n-button
          type="primary"
          size="large"
          :loading="submitting"
          @click="handleSubmit"
        >
          确认提交 <template #icon><n-icon><SendOutlined /></n-icon></template>
        </n-button>
      </div>
    </div>

    <!-- 创建项目弹窗 -->
    <CreateProjectModal v-model:show="showCreateProject" @created="onProjectCreated" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NSteps, NStep, NGrid, NGridItem, NButton, NIcon, NSpin, NEmpty } from 'naive-ui'
import { ArrowRightOutlined, SendOutlined } from '@vicons/antd'

import FlowSelector from '@/components/task/submit/FlowSelector.vue'
import ProjectSelector from '@/components/task/submit/ProjectSelector.vue'
import DynamicForm from '@/components/dynamic-form/DynamicForm.vue'
import TaskSubmitPreview from '@/components/task/submit/TaskSubmitPreview.vue'
import CreateProjectModal from '@/components/project/CreateProjectModal.vue'

import { useFlowStore } from '@/stores/modules/flow'
import { useProjectStore } from '@/stores/modules/project'
import { useTaskStore } from '@/stores/modules/task'
import type { FlowSchema } from '@/types/flow'
import { message } from '@/utils/naiveMessage'

const route = useRoute()
const router = useRouter()
const flowStore = useFlowStore()
const projectStore = useProjectStore()
const taskStore = useTaskStore()

// ── 步骤控制 ──
const currentStep = ref(1)
const submitting = ref(false)
const parsingYaml = ref(false)
const showCreateProject = ref(false)
const dynamicFormRef = ref<InstanceType<typeof DynamicForm>>()

// ── 选择状态 ──
const selectedFlowId = ref<string | null>(
  (route.query.flow as string) || null
)
const selectedProjectId = ref<string | null>(
  (route.query.project as string) || null
)
const flowSchema = ref<FlowSchema | null>(null)
const formValues = ref<Record<string, any>>({})

// ── 计算属性 ──
const selectedFlow = computed(() =>
  flowStore.flowList.find(f => f.id === selectedFlowId.value)
)
const selectedProject = computed(() =>
  projectStore.projectList.find(p => p.id === selectedProjectId.value)
)
const canNextStep1 = computed(() =>
  Boolean(selectedFlowId.value && selectedProjectId.value)
)

// ── 方法 ──
async function onFlowSelect(flowId: string) {
  selectedFlowId.value = flowId
  parsingYaml.value = true
  try {
    flowSchema.value = await flowStore.fetchFlowSchema(flowId)
    // 初始化表单默认值
    formValues.value = flowStore.getDefaultValues(flowSchema.value)
  } catch (err: any) {
    message.error('流程参数解析失败: ' + err.message)
  } finally {
    parsingYaml.value = false
  }
}

function onProjectSelect(projectId: string) {
  selectedProjectId.value = projectId
}

function onProjectCreated(projectId: string) {
  selectedProjectId.value = projectId
  projectStore.fetchProjectList()
}

function handlePreview() {
  const valid = dynamicFormRef.value?.validate()
  if (!valid) {
    message.warning('请检查表单填写是否正确')
    return
  }
  currentStep.value = 3
}

async function handleSubmit() {
  if (!selectedFlowId.value || !selectedProjectId.value) return

  submitting.value = true
  try {
    const taskId = await taskStore.submitTask({
      flow_id: selectedFlowId.value,
      project_id: selectedProjectId.value,
      params: formValues.value,
    })
    message.success('任务提交成功！')
    router.push({ name: 'TaskDetail', params: { id: taskId } })
  } catch (err: any) {
    message.error('提交失败: ' + err.message)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  flowStore.fetchFlowList()
  projectStore.fetchProjectList()
  // URL 中已指定流程时自动加载
  if (selectedFlowId.value) {
    onFlowSelect(selectedFlowId.value)
  }
})
</script>

<style scoped lang="scss">
.task-submit-view {
  max-width: 1200px;
  margin: 0 auto;

  .step-panel {
    animation: slideIn 0.3s ease;
  }

  .step-actions {
    display: flex;
    justify-content: center;
    gap: 12px;
    margin-top: 32px;
    padding-top: 20px;
    border-top: 1px solid var(--border-color);
  }
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
```

### 3.3 DynamicForm.vue — 动态表单渲染器（核心组件）

```vue
<!-- src/components/dynamic-form/DynamicForm.vue -->
<template>
  <div class="dynamic-form">
    <!-- 表单头部：流程信息 -->
    <div class="dynamic-form__header" v-if="schema">
      <h3>{{ schema.title || '参数配置' }}</h3>
      <p class="text-secondary">{{ schema.description }}</p>
    </div>

    <!-- 按 Section 渲染 -->
    <n-form
      v-if="schema"
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-placement="top"
      size="medium"
    >
      <template v-for="section in schema.sections" :key="section.key">
        <SectionCollapsible
          :title="section.title"
          :description="section.description"
          :default-collapsed="section.collapsed"
        >
          <!-- Section 内的字段 -->
          <template v-for="field in section.fields" :key="field.key">
            <ConditionRenderer
              :field="field"
              :form-data="formData"
              :context="{ projectId, flowId }"
            >
              <FormFieldRenderer
                v-model="formData[field.key]"
                :field="field"
                :form-data="formData"
                @update:model-value="onFieldChange(field.key, $event)"
              />
            </ConditionRenderer>
          </template>

          <!-- 可重复的 Group -->
          <template v-if="section.repeatable">
            <GroupRepeater
              v-model="formData[section.key]"
              :section="section"
              :context="{ projectId, flowId }"
            />
          </template>
        </SectionCollapsible>

        <n-divider style="margin: 8px 0" />
      </template>
    </n-form>

    <!-- 空状态 -->
    <n-empty v-else description="暂无可配置参数" />
  </div>
</template>

<script setup lang="ts">
import { computed, watch, ref } from 'vue'
import { NForm, NDivider, NEmpty } from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'

import SectionCollapsible from './SectionCollapsible.vue'
import FormFieldRenderer from './FormFieldRenderer.vue'
import ConditionRenderer from './ConditionRenderer.vue'
import GroupRepeater from './GroupRepeater.vue'

import type { FlowSchema, FormField } from '@/types/flow'
import { buildValidationRules } from './validation'
import { getDefaultValuesFromSchema } from './utils'

const props = defineProps<{
  schema: FlowSchema | null
  projectId: string
  flowId: string
  modelValue: Record<string, any>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: Record<string, any>): void
}>()

const formRef = ref<FormInst>()

// ── 表单数据（本地副本 + 同步父组件） ──
const formData = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

// ── 校验规则 ──
const formRules = computed<FormRules>(() => {
  if (!props.schema) return {}
  return buildValidationRules(props.schema)
})

// ── schema 变化时重置默认值 ──
watch(
  () => props.schema,
  (newSchema) => {
    if (newSchema) {
      const defaults = getDefaultValuesFromSchema(newSchema)
      emit('update:modelValue', { ...defaults, ...props.modelValue })
    }
  },
  { immediate: true }
)

// ── 字段变更回调（用于联动） ──
function onFieldChange(key: string, value: any) {
  // 触发条件渲染重新计算
  // 由 ConditionRenderer 内部通过 watch formData 处理
}

// ── 公开方法：校验 ──
async function validate(): Promise<boolean> {
  try {
    await formRef.value?.validate()
    return true
  } catch {
    return false
  }
}

// ── 公开方法：获取纯净数据 ──
function getCleanValues(): Record<string, any> {
  // 移除内部辅助字段
  const cleaned: Record<string, any> = {}
  if (!props.schema) return cleaned

  for (const section of props.schema.sections) {
    for (const field of section.fields) {
      if (field.key in formData.value) {
        cleaned[field.key] = formData.value[field.key]
      }
    }
  }
  return cleaned
}

defineExpose({ validate, getCleanValues })
</script>

<style scoped lang="scss">
.dynamic-form {
  &__header {
    margin-bottom: 20px;

    h3 { font-size: 18px; font-weight: 600; margin-bottom: 4px; }
    .text-secondary { color: var(--text-secondary); font-size: 14px; }
  }
}
</style>
```

### 3.4 FormFieldRenderer.vue — 字段渲染器（根据 type 分发）

```typescript
// src/components/dynamic-form/FormFieldRenderer.vue
// 该组件根据字段类型自动分发到对应的渲染组件

import type { FormField } from '@/types/flow'

// 支持的字段类型映射
export const FIELD_TYPE_MAP: Record<string, string> = {
  // 基础输入
  'string': 'StringField',
  'text': 'TextField',          // 多行文本
  'number': 'NumberField',
  'integer': 'IntegerField',
  'float': 'FloatField',
  'boolean': 'BooleanField',     // 开关

  // 选择类
  'select': 'SelectField',       // 单选下拉
  'multi-select': 'MultiSelectField',
  'radio': 'RadioField',         // 单选按钮组
  'checkbox': 'CheckboxField',   // 多选框组

  // 文件/样本
  'file': 'FileField',           // 文件选择（从项目文件中选）
  'file-upload': 'FileUploadField', // 本地上传
  'sample': 'SampleField',       // 样本选择
  'sample-sheet': 'SampleSheetField', // 样本表上传/编辑

  // 范围/数组
  'range': 'RangeField',         // 数值范围
  'array': 'ArrayField',         // 字符串数组

  // 特殊
  'ref': 'RefField',             // 引用其他参数
  'group': 'GroupField',         // 嵌套组（内联）
  'divider': 'DividerField',     // 仅显示分隔线
  'info': 'InfoField',           // 仅显示提示文本
}
```

```vue
<!-- src/components/dynamic-form/FormFieldRenderer.vue -->
<template>
  <div class="form-field-renderer">
    <!-- 动态分发到具体组件 -->
    <component
      :is="fieldComponent"
      v-model="modelValue"
      :field="field"
      :form-data="formData"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { FormField } from '@/types/flow'

import StringField from './fields/StringField.vue'
import TextField from './fields/TextField.vue'
import NumberField from './fields/NumberField.vue'
import BooleanField from './fields/BooleanField.vue'
import SelectField from './fields/SelectField.vue'
import MultiSelectField from './fields/MultiSelectField.vue'
import RadioField from './fields/RadioField.vue'
import CheckboxField from './fields/CheckboxField.vue'
import FileField from './fields/FileField.vue'
import FileUploadField from './fields/FileUploadField.vue'
import SampleField from './fields/SampleField.vue'
import SampleSheetField from './fields/SampleSheetField.vue'
import RangeField from './fields/RangeField.vue'
import ArrayField from './fields/ArrayField.vue'
import RefField from './fields/RefField.vue'
import GroupField from './fields/GroupField.vue'
import DividerField from './fields/DividerField.vue'
import InfoField from './fields/InfoField.vue'

const props = defineProps<{
  modelValue: any
  field: FormField
  formData: Record<string, any>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: any): void
}>()

// v-model 双向绑定
const modelValue = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

// 根据字段类型分发组件
const fieldComponent = computed(() => {
  const map: Record<string, any> = {
    'string': StringField,
    'text': TextField,
    'number': NumberField,
    'integer': NumberField,
    'float': NumberField,
    'boolean': BooleanField,
    'select': SelectField,
    'multi-select': MultiSelectField,
    'radio': RadioField,
    'checkbox': CheckboxField,
    'file': FileField,
    'file-upload': FileUploadField,
    'sample': SampleField,
    'sample-sheet': SampleSheetField,
    'range': RangeField,
    'array': ArrayField,
    'ref': RefField,
    'group': GroupField,
    'divider': DividerField,
    'info': InfoField,
  }
  return map[props.field.type] || StringField
})
</script>
```

### 3.5 任务详情页（TaskDetailView.vue）— 核心页面

```vue
<!-- src/views/task/TaskDetailView.vue -->
<template>
  <div class="task-detail-view">
    <!-- 页面加载中 -->
    <n-spin v-if="loading" size="large" style="display: block; text-align: center; padding: 60px">
      <template #description>加载任务信息...</template>
    </n-spin>

    <template v-else-if="task">
      <!-- 任务头部 -->
      <TaskDetailHeader
        :task="task"
        @cancel="handleCancel"
        @retry="handleRetry"
        @delete="handleDelete"
      />

      <!-- 进度条（运行中时显示） -->
      <TaskProgressBar
        v-if="['queued', 'running', 'cancelling'].includes(task.status)"
        :status="task.status"
        :progress="task.progress"
        :step="task.current_step"
        :total-steps="task.total_steps"
        :start-time="task.started_at"
      />

      <!-- 标签页 -->
      <n-tabs v-model:value="activeTab" type="line" animated class="task-tabs">
        <!-- 概览 -->
        <n-tab-pane name="overview" tab="概览">
          <TaskOverviewTab :task="task" />
        </n-tab-pane>

        <!-- 日志（WebSocket 实时） -->
        <n-tab-pane name="logs" tab="日志">
          <TaskLogViewer :task-id="taskId" :status="task.status" />
        </n-tab-pane>

        <!-- 结果 -->
        <n-tab-pane name="results" tab="结果">
          <TaskResultViewer
            :task-id="taskId"
            :output-dir="task.output_dir"
            :status="task.status"
          />
        </n-tab-pane>

        <!-- 参数 -->
        <n-tab-pane name="params" tab="参数">
          <TaskParamsTab
            :params="task.params"
            :flow-id="task.flow_id"
          />
        </n-tab-pane>
      </n-tabs>
    </template>

    <!-- 错误状态 -->
    <n-result
      v-else
      status="404"
      title="任务不存在"
      description="该任务可能已被删除或您无权查看"
    >
      <template #footer>
        <n-button @click="$router.push({ name: 'TaskList' })">返回任务列表</n-button>
      </template>
    </n-result>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NTabs, NTabPane, NSpin, NResult, NButton } from 'naive-ui'

import TaskDetailHeader from '@/components/task/detail/TaskDetailHeader.vue'
import TaskProgressBar from '@/components/task/detail/TaskProgressBar.vue'
import TaskOverviewTab from '@/components/task/detail/TaskOverviewTab.vue'
import TaskLogViewer from '@/components/task/detail/TaskLogViewer.vue'
import TaskResultViewer from '@/components/task/detail/TaskResultViewer.vue'
import TaskParamsTab from '@/components/task/detail/TaskParamsTab.vue'

import { useTaskStore } from '@/stores/modules/task'
import { useChatStore } from '@/stores/modules/chat'
import { message } from '@/utils/naiveMessage'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const chatStore = useChatStore()

const taskId = computed(() => route.params.id as string)
const task = computed(() => taskStore.currentTask)
const loading = ref(false)
const activeTab = ref('overview')

// ── 轮询状态（运行中时） ──
let pollTimer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => {
    if (['running', 'queued', 'cancelling'].includes(task.value?.status || '')) {
      taskStore.fetchTaskDetail(taskId.value)
    } else {
      stopPolling()
    }
  }, 3000) // 3 秒轮询
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ── 操作 ──
async function handleCancel() {
  try {
    await taskStore.cancelTask(taskId.value)
    message.success('任务已取消')
  } catch (err: any) {
    message.error('取消失败: ' + err.message)
  }
}

async function handleRetry() {
  try {
    const newTaskId = await taskStore.retryTask(taskId.value)
    message.success('已重新提交任务')
    router.push({ name: 'TaskDetail', params: { id: newTaskId } })
  } catch (err: any) {
    message.error('重试失败: ' + err.message)
  }
}

async function handleDelete() {
  try {
    await taskStore.deleteTask(taskId.value)
    message.success('任务已删除')
    router.push({ name: 'TaskList' })
  } catch (err: any) {
    message.error('删除失败: ' + err.message)
  }
}

// ── 生命周期 ──
onMounted(async () => {
  loading.value = true
  try {
    await taskStore.fetchTaskDetail(taskId.value)
    // 设置 AI 上下文
    chatStore.setCurrentTask(taskId.value)
    // 启动轮询
    startPolling()
  } catch (err: any) {
    message.error('加载失败: ' + err.message)
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  stopPolling()
  taskStore.clearCurrentTask()
  chatStore.clearCurrentTask()
})
</script>

<style scoped lang="scss">
.task-detail-view {
  .task-tabs {
    margin-top: 16px;
  }
}
</style>
```

### 3.6 TaskLogViewer.vue — 实时日志查看器

```vue
<!-- src/components/task/detail/TaskLogViewer.vue -->
<template>
  <div class="task-log-viewer">
    <!-- 工具栏 -->
    <div class="log-toolbar">
      <n-space>
        <!-- 日志级别筛选 -->
        <n-select
          v-model:value="levelFilter"
          :options="levelOptions"
          size="small"
          style="width: 120px"
          placeholder="日志级别"
          clearable
        />
        <!-- 搜索 -->
        <n-input
          v-model:value="searchKeyword"
          size="small"
          placeholder="搜索日志..."
          clearable
          style="width: 200px"
        >
          <template #prefix><n-icon><SearchOutlined /></n-icon></template>
        </n-input>
      </n-space>

      <n-space>
        <!-- 自动滚动开关 -->
        <n-tooltip>
          <template #trigger>
            <n-button
              text
              :type="autoScroll ? 'primary' : 'default'"
              @click="autoScroll = !autoScroll"
            >
              <template #icon><n-icon><ToBottomOutlined /></n-icon></template>
            </n-button>
          </template>
          自动滚动
        </n-tooltip>

        <!-- 清空 -->
        <n-tooltip>
          <template #trigger>
            <n-button text @click="logs = []">
              <template #icon><n-icon><DeleteOutlined /></n-icon></template>
            </n-button>
          </template>
          清空
        </n-tooltip>

        <!-- 下载 -->
        <n-tooltip>
          <template #trigger>
            <n-button text @click="downloadLogs">
              <template #icon><n-icon><DownloadOutlined /></n-icon></template>
            </n-button>
          </template>
          下载日志
        </n-tooltip>
      </n-space>
    </div>

    <!-- 日志内容区 -->
    <div ref="logContainerRef" class="log-container" @scroll="handleScroll">
      <!-- WebSocket 连接状态 -->
      <div v-if="!wsConnected" class="log-status-bar" :class="wsStatusClass">
        <n-icon size="14"><WifiOutlined /></n-icon>
        <span>{{ wsStatusText }}</span>
        <n-button text size="tiny" @click="reconnect">重连</n-button>
      </div>

      <!-- 日志行 -->
      <div
        v-for="(log, index) in filteredLogs"
        :key="index"
        class="log-line"
        :class="`log-level-${log.level}`"
      >
        <span class="log-timestamp">{{ formatTime(log.timestamp) }}</span>
        <span class="log-level-tag" :class="`tag-${log.level}`">{{ log.level }}</span>
        <span class="log-message" v-html="renderAnsi(log.message)" />
      </div>

      <!-- 空状态 -->
      <n-empty v-if="filteredLogs.length === 0" description="暂无日志" />

      <!-- 实时指示器 -->
      <div v-if="isReceiving" class="log-live-indicator">
        <span class="live-dot"></span>
        实时接收中...
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import {
  NSelect, NInput, NButton, NIcon, NTooltip, NSpace, NEmpty,
} from 'naive-ui'
import {
  SearchOutlined, ToBottomOutlined, DeleteOutlined,
  DownloadOutlined, WifiOutlined,
} from '@vicons/antd'
import { useTaskLogWebSocket } from '@/composables/useTaskLogWebSocket'
import { formatTime } from '@/utils/time'
import { renderAnsi } from '@/utils/ansi'

const props = defineProps<{
  taskId: string
  status: string
}>()

// ── 状态 ──
const logContainerRef = ref<HTMLDivElement>()
const logs = ref<LogEntry[]>([])
const levelFilter = ref<string | null>(null)
const searchKeyword = ref('')
const autoScroll = ref(true)
const isReceiving = ref(false)
let receiveTimer: ReturnType<typeof setTimeout> | null = null

// ── WebSocket ──
const { connect, disconnect, connected: wsConnected, status: wsStatus } = useTaskLogWebSocket({
  onMessage: (entry: LogEntry) => {
    logs.value.push(entry)
    isReceiving.value = true
    // 防抖显示接收指示器
    if (receiveTimer) clearTimeout(receiveTimer)
    receiveTimer = setTimeout(() => { isReceiving.value = false }, 500)
  },
  onOpen: () => {
    // 连接成功后发送订阅消息
    sendSubscribe()
  },
})

function sendSubscribe() {
  const ws = (useTaskLogWebSocket as any)._ws
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'subscribe', task_id: props.taskId }))
  }
}

function reconnect() {
  disconnect()
  connect(`/api/v1/ws/tasks/${props.taskId}/logs`)
}

// ── 筛选 ──
const levelOptions = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'CRITICAL', value: 'CRITICAL' },
]

const filteredLogs = computed(() => {
  let result = logs.value
  if (levelFilter.value) {
    result = result.filter(l => l.level === levelFilter.value)
  }
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    result = result.filter(l => l.message.toLowerCase().includes(kw))
  }
  return result
})

// ── WebSocket 状态文本 ──
const wsStatusText = computed(() => {
  if (wsConnected.value) return '已连接'
  if (wsStatus.value === 'connecting') return '连接中...'
  return '连接断开'
})

const wsStatusClass = computed(() => ({
  'status-connected': wsConnected.value,
  'status-connecting': wsStatus.value === 'connecting',
  'status-disconnected': !wsConnected.value && wsStatus.value !== 'connecting',
}))

// ── 自动滚动 ──
watch(filteredLogs, async () => {
  if (autoScroll.value) {
    await nextTick()
    scrollToBottom()
  }
}, { deep: true })

function scrollToBottom() {
  const el = logContainerRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function handleScroll() {
  const el = logContainerRef.value
  if (!el) return
  // 用户手动滚动时暂停自动滚动
  const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
  autoScroll.value = isAtBottom
}

// ── 下载 ──
function downloadLogs() {
  const content = logs.value.map(l =>
    `[${l.timestamp}] [${l.level}] ${l.message}`
  ).join('\n')
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `task-${props.taskId}-logs.txt`
  a.click()
  URL.revokeObjectURL(url)
}

// ── 生命周期 ──
onMounted(() => {
  connect(`/api/v1/ws/tasks/${props.taskId}/logs`)
})

onUnmounted(() => {
  disconnect()
  if (receiveTimer) clearTimeout(receiveTimer)
})

// ── 类型 ──
interface LogEntry {
  timestamp: string
  level: string
  message: string
  source?: string
}
</script>

<style scoped lang="scss">
.task-log-viewer {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 280px);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;

  .log-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color);
    background: var(--toolbar-bg);
    flex-shrink: 0;
  }

  .log-container {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.7;
    background: var(--log-bg, #0d1117);
  }

  .log-status-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    margin: -12px -12px 8px;
    font-size: 12px;

    &.status-connected { background: rgba(16, 185, 129, 0.1); color: #10b981; }
    &.status-connecting { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }
    &.status-disconnected { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
  }

  .log-line {
    display: flex;
    gap: 10px;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255,255,255,0.03);

    .log-timestamp {
      color: #6b7280;
      flex-shrink: 0;
      width: 84px;
    }

    .log-level-tag {
      flex-shrink: 0;
      width: 60px;
      text-align: center;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 600;
      padding: 0 4px;

      &.tag-DEBUG { background: rgba(107, 114, 128, 0.2); color: #9ca3af; }
      &.tag-INFO { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
      &.tag-WARNING { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
      &.tag-ERROR { background: rgba(239, 68, 68, 0.2); color: #f87171; }
      &.tag-CRITICAL { background: rgba(185, 28, 28, 0.3); color: #fca5a5; }
    }

    .log-message {
      flex: 1;
      word-break: break-all;
      color: #e5e7eb;
    }
  }

  .log-live-indicator {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 0;
    color: #10b981;
    font-size: 12px;

    .live-dot {
      width: 8px; height: 8px;
      background: #10b981;
      border-radius: 50%;
      animation: pulse 1.5s ease infinite;
    }
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
```

### 3.7 TaskResultViewer.vue — 结果查看器

```vue
<!-- src/components/task/detail/TaskResultViewer.vue -->
<template>
  <div class="task-result-viewer">
    <!-- 文件浏览器侧边栏 + 预览区 -->
    <n-split direction="horizontal" :max="0.5" :min="0.2" default-size="0.28">
      <!-- 文件树 -->
      <template #1>
        <div class="file-tree-panel">
          <n-input
            v-model:value="fileSearch"
            size="small"
            placeholder="搜索文件..."
            clearable
          >
            <template #prefix><n-icon><SearchOutlined /></n-icon></template>
          </n-input>

          <n-spin :show="loadingFiles">
            <n-tree
              :data="fileTree"
              :pattern="fileSearch"
              :render-prefix="renderFileIcon"
              selectable
              block-line
              @update:selected-keys="onFileSelect"
            />
          </n-spin>
        </div>
      </template>

      <!-- 预览区 -->
      <template #2>
        <div class="preview-panel">
          <template v-if="selectedFile">
            <!-- 工具栏 -->
            <div class="preview-toolbar">
              <span class="file-name">{{ selectedFile.name }}</span>
              <n-space>
                <n-button size="small" @click="copyPath">复制路径</n-button>
                <n-button size="small" type="primary" @click="downloadFile">
                  <template #icon><n-icon><DownloadOutlined /></n-icon></template>
                  下载
                </n-button>
              </n-space>
            </div>

            <!-- 根据类型选择预览组件 -->
            <div class="preview-content">
              <CsvTablePreview
                v-if="isCsvFile"
                :task-id="taskId"
                :file-path="selectedFile.path"
              />
              <ImagePreview
                v-else-if="isImageFile"
                :task-id="taskId"
                :file-path="selectedFile.path"
              />
              <HtmlReportPreview
                v-else-if="isHtmlFile"
                :task-id="taskId"
                :file-path="selectedFile.path"
              />
              <TextPreview
                v-else-if="isTextFile"
                :task-id="taskId"
                :file-path="selectedFile.path"
              />
              <n-empty v-else description="该文件类型暂不支持在线预览">
                <template #extra>
                  <n-button @click="downloadFile">下载查看</n-button>
                </template>
              </n-empty>
            </div>
          </template>

          <n-empty v-else description="请选择左侧文件进行预览" />
        </div>
      </template>
    </n-split>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  NSplit, NInput, NIcon, NTree, NSpin, NButton, NSpace, NEmpty,
} from 'naive-ui'
import { SearchOutlined, DownloadOutlined } from '@vicons/antd'
import CsvTablePreview from './previews/CsvTablePreview.vue'
import ImagePreview from './previews/ImagePreview.vue'
import HtmlReportPreview from './previews/HtmlReportPreview.vue'
import TextPreview from './previews/TextPreview.vue'
import { useTaskResult } from '@/composables/useTaskResult'

const props = defineProps<{
  taskId: string
  outputDir: string
  status: string
}>()

const fileSearch = ref('')
const selectedFile = ref<ResultFile | null>(null)
const { fileTree, loading: loadingFiles, fetchFileList } = useTaskResult()

// ── 文件类型判断 ──
const fileExt = computed(() => selectedFile.value?.name.split('.').pop()?.toLowerCase() || '')
const isCsvFile = computed(() => ['csv', 'tsv', 'txt'].includes(fileExt.value))
const isImageFile = computed(() => ['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(fileExt.value))
const isHtmlFile = computed(() => ['html', 'htm'].includes(fileExt.value))
const isTextFile = computed(() => ['log', 'md', 'json', 'yaml', 'yml'].includes(fileExt.value))

// ── 方法 ──
function onFileSelect(keys: string[]) {
  const key = keys[0]
  if (!key) { selectedFile.value = null; return }
  // 从 fileTree 中查找文件节点
  selectedFile.value = findFileByKey(fileTree.value, key)
}

function findFileByKey(nodes: FileTreeNode[], key: string): ResultFile | null {
  for (const node of nodes) {
    if (node.key === key && node.isLeaf) {
      return { name: node.label, path: node.key, size: node.size }
    }
    if (node.children) {
      const found = findFileByKey(node.children, key)
      if (found) return found
    }
  }
  return null
}

function renderFileIcon({ option }: { option: FileTreeNode }) {
  // 根据文件类型返回不同图标
}

function copyPath() {
  if (!selectedFile.value) return
  navigator.clipboard.writeText(selectedFile.value.path)
}

function downloadFile() {
  if (!selectedFile.value) return
  // 调用下载 API
}

onMounted(() => {
  fetchFileList(props.taskId)
})

// ── 类型 ──
interface FileTreeNode {
  key: string
  label: string
  isLeaf?: boolean
  children?: FileTreeNode[]
  size?: number
}
interface ResultFile {
  name: string
  path: string
  size?: number
}
</script>

<style scoped lang="scss">
.task-result-viewer {
  height: calc(100vh - 280px);

  .file-tree-panel {
    height: 100%;
    padding: 12px;
    overflow: auto;
  }

  .preview-panel {
    height: 100%;
    display: flex;
    flex-direction: column;

    .preview-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border-color);

      .file-name {
        font-weight: 500;
        font-family: monospace;
      }
    }

    .preview-content {
      flex: 1;
      overflow: auto;
      padding: 12px;
    }
  }
}
</style>
```

### 3.8 流程市场页（FlowMarketView.vue）

```vue
<!-- src/views/flow/FlowMarketView.vue -->
<template>
  <div class="flow-market-view">
    <!-- 搜索与筛选 -->
    <div class="flow-market-toolbar">
      <n-input
        v-model:value="searchQuery"
        placeholder="搜索流程名称、描述..."
        clearable
        style="width: 320px"
      >
        <template #prefix><n-icon><SearchOutlined /></n-icon></template>
      </n-input>

      <n-space>
        <n-select
          v-model:value="categoryFilter"
          :options="categoryOptions"
          placeholder="全部分类"
          clearable
          style="width: 160px"
        />
        <n-select
          v-model:value="sortBy"
          :options="sortOptions"
          style="width: 140px"
        />
      </n-space>
    </div>

    <!-- 流程卡片网格 -->
    <n-spin :show="loading">
      <n-empty v-if="filteredFlows.length === 0" description="暂无匹配的流程" />

      <n-grid v-else :cols="3" :x-gap="16" :y-gap="16" responsive="screen">
        <n-grid-item v-for="flow in filteredFlows" :key="flow.id">
          <FlowCard
            :flow="flow"
            @click="$router.push({ name: 'FlowDetail', params: { id: flow.id } })"
            @use="handleUseFlow(flow)"
          />
        </n-grid-item>
      </n-grid>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NInput, NSelect, NSpace, NSpin, NEmpty, NGrid, NGridItem, NIcon } from 'naive-ui'
import { SearchOutlined } from '@vicons/antd'
import FlowCard from '@/components/flow/FlowCard.vue'
import { useFlowStore } from '@/stores/modules/flow'
import type { FlowSummary } from '@/types/flow'

const router = useRouter()
const flowStore = useFlowStore()

const searchQuery = ref('')
const categoryFilter = ref<string | null>(null)
const sortBy = ref('popular')
const loading = ref(false)

const categoryOptions = [
  { label: '基因组学', value: 'genomics' },
  { label: '转录组学', value: 'transcriptomics' },
  { label: '蛋白质组学', value: 'proteomics' },
  { label: '代谢组学', value: 'metabolomics' },
  { label: '表观遗传学', value: 'epigenomics' },
  { label: '宏基因组学', value: 'metagenomics' },
  { label: '单细胞', value: 'single-cell' },
  { label: '数据预处理', value: 'preprocessing' },
]

const sortOptions = [
  { label: '最热', value: 'popular' },
  { label: '最新', value: 'newest' },
  { label: '名称', value: 'name' },
]

const filteredFlows = computed(() => {
  let result = [...flowStore.flowList]

  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(f =>
      f.name.toLowerCase().includes(q) ||
      f.description?.toLowerCase().includes(q)
    )
  }

  if (categoryFilter.value) {
    result = result.filter(f => f.category === categoryFilter.value)
  }

  switch (sortBy.value) {
    case 'popular': result.sort((a, b) => b.use_count - a.use_count); break
    case 'newest': result.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()); break
    case 'name': result.sort((a, b) => a.name.localeCompare(b.name)); break
  }

  return result
})

function handleUseFlow(flow: FlowSummary) {
  router.push({
    name: 'TaskSubmit',
    query: { flow: flow.id },
  })
}

onMounted(() => {
  flowStore.fetchFlowList()
})
</script>

<style scoped lang="scss">
.flow-market-view {
  .flow-market-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
  }
}
</style>
```

### 3.9 项目管理页（ProjectsView.vue）

```vue
<!-- src/views/project/ProjectsView.vue -->
<template>
  <div class="projects-view">
    <!-- 工具栏 -->
    <div class="projects-toolbar">
      <n-button type="primary" @click="showCreateModal = true">
        <template #icon><n-icon><PlusOutlined /></n-icon></template>
        新建项目
      </n-button>

      <n-input
        v-model:value="searchQuery"
        placeholder="搜索项目..."
        clearable
        style="width: 280px"
      >
        <template #prefix><n-icon><SearchOutlined /></n-icon></template>
      </n-input>
    </div>

    <!-- 项目列表 -->
    <n-data-table
      :columns="columns"
      :data="filteredProjects"
      :loading="loading"
      :pagination="pagination"
      @update:page="pagination.page = $event"
    />

    <!-- 创建项目弹窗 -->
    <CreateProjectModal v-model:show="showCreateModal" @created="onProjectCreated" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NInput, NDataTable, NIcon, NSpace, NPopconfirm, NTag,
} from 'naive-ui'
import { PlusOutlined, SearchOutlined, DeleteOutlined, EnterOutlined } from '@vicons/antd'
import type { DataTableColumns } from 'naive-ui'
import CreateProjectModal from '@/components/project/CreateProjectModal.vue'
import { useProjectStore } from '@/stores/modules/project'
import { useAuthStore } from '@/stores/modules/auth'
import type { Project } from '@/types/project'
import { formatDate } from '@/utils/time'
import { message } from '@/utils/naiveMessage'

const router = useRouter()
const projectStore = useProjectStore()
const authStore = useAuthStore()

const searchQuery = ref('')
const loading = ref(false)
const showCreateModal = ref(false)
const pagination = ref({ page: 1, pageSize: 10 })

const filteredProjects = computed(() => {
  if (!searchQuery.value) return projectStore.projectList
  const q = searchQuery.value.toLowerCase()
  return projectStore.projectList.filter(p =>
    p.name.toLowerCase().includes(q) ||
    p.description?.toLowerCase().includes(q)
  )
})

const columns: DataTableColumns<Project> = [
  { title: '项目名称', key: 'name', sorter: 'default' },
  { title: '描述', key: 'description', ellipsis: { tooltip: true } },
  {
    title: '样本数',
    key: 'sample_count',
    width: 90,
    render: (row) => row.sample_count ?? '-',
  },
  {
    title: '任务数',
    key: 'task_count',
    width: 90,
    render: (row) => row.task_count ?? '-',
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 170,
    render: (row) => formatDate(row.created_at),
  },
  {
    title: '操作',
    key: 'actions',
    width: 180,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, {
          size: 'small', type: 'primary', ghost: true,
          onClick: () => router.push({ name: 'ProjectDetail', params: { id: row.id } }),
        }, { default: () => '进入', icon: () => h(EnterOutlined) }),
        h(NPopconfirm, {
          onPositiveClick: () => handleDelete(row.id),
        }, {
          trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, {
            default: () => '删除',
            icon: () => h(DeleteOutlined),
          }),
          default: () => '确定删除此项目？项目下的所有数据将被删除！',
        }),
      ],
    }),
  },
]

async function handleDelete(id: string) {
  try {
    await projectStore.deleteProject(id)
    message.success('项目已删除')
  } catch (err: any) {
    message.error('删除失败: ' + err.message)
  }
}

function onProjectCreated() {
  projectStore.fetchProjectList()
}

onMounted(() => {
  projectStore.fetchProjectList()
})
</script>

<style scoped lang="scss">
.projects-view {
  .projects-toolbar {
    display: flex;
    justify-content: space-between;
    margin-bottom: 20px;
  }
}
</style>
```



---

## 4. Pinia Store 设计

### 4.1 目录结构

```
src/stores/
├── index.ts              # Pinia 实例创建 & 模块导出
├── types.ts              # Store 共享类型定义
└── modules/
    ├── auth.ts           # 认证状态（token, user, login, logout）
    ├── user.ts           # 用户信息
    ├── project.ts        # 项目数据（列表、当前项目、CRUD）
    ├── flow.ts           # 流程数据（列表、当前流程定义、YAML 解析缓存）
    ├── task.ts           # 任务数据（列表、当前任务、提交、取消）
    ├── chat.ts           # AI 对话状态（会话列表、当前会话、消息、WebSocket 连接）
    ├── mcp.ts            # MCP 状态（Server 列表、工具目录）
    ├── notification.ts   # 全局通知（Toast、消息中心）
    ├── theme.ts          # 主题状态（暗黑/亮色模式）
    └── tab.ts            # 标签页/缓存视图管理
```

### 4.2 Store 入口（index.ts）

```typescript
// src/stores/index.ts
import { createPinia } from 'pinia'

// 导出 Pinia 实例
export const pinia = createPinia()

// ── 模块导出 ──
export { useAuthStore } from './modules/auth'
export { useUserStore } from './modules/user'
export { useProjectStore } from './modules/project'
export { useFlowStore } from './modules/flow'
export { useTaskStore } from './modules/task'
export { useChatStore } from './modules/chat'
export { useMCPStore } from './modules/mcp'
export { useNotificationStore } from './modules/notification'
export { useThemeStore } from './modules/theme'
export { useTabStore } from './modules/tab'

export default pinia
```

### 4.3 Auth Store — 认证状态

```typescript
// src/stores/modules/auth.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '@/api/auth'
import { useThemeStore } from './theme'

/** 用户信息 */
export interface UserInfo {
  id: string
  username: string
  email: string
  display_name: string
  avatar?: string
  role: 'user' | 'admin'
  created_at: string
}

/** Token 对 */
interface TokenPair {
  access_token: string
  refresh_token: string
  expires_in: number
}

export const useAuthStore = defineStore('auth', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const accessToken = ref<string>(localStorage.getItem('access_token') || '')
  const refreshToken = ref<string>(localStorage.getItem('refresh_token') || '')
  const user = ref<UserInfo | null>(null)
  const lastVisitedRoute = ref<string>(localStorage.getItem('last_route') || '/')

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const isLoggedIn = computed(() => Boolean(accessToken.value && user.value))
  const isAdmin = computed(() => user.value?.role === 'admin')
  const tokenHeader = computed(() => ({
    Authorization: `Bearer ${accessToken.value}`,
  }))

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  /** 登录 */
  async function login(credentials: { username: string; password: string }) {
    const resp: TokenPair = await authApi.login(credentials)
    setTokens(resp)
    // 获取用户信息
    await fetchUserInfo()
    return true
  }

  /** 注册 */
  async function register(data: {
    username: string; password: string; email: string; display_name?: string
  }) {
    await authApi.register(data)
    return true
  }

  /** 登出 */
  async function logout() {
    try {
      if (refreshToken.value) {
        await authApi.logout(refreshToken.value)
      }
    } catch {
      // 忽略登出 API 错误
    } finally {
      clearTokens()
      user.value = null
      // 重置主题
      const themeStore = useThemeStore()
      themeStore.$reset()
      // 跳转到登录页
      const router = useRouter()
      router.push({ name: 'Login' })
    }
  }

  /** 获取用户信息 */
  async function fetchUserInfo() {
    try {
      const info = await authApi.getMe()
      user.value = info
      return info
    } catch {
      // Token 失效，尝试刷新
      const refreshed = await tryRefreshToken()
      if (refreshed) {
        return fetchUserInfo()
      }
      throw new Error('获取用户信息失败')
    }
  }

  /** 尝试刷新 Token */
  async function tryRefreshToken(): Promise<boolean> {
    if (!refreshToken.value) return false
    try {
      const resp: TokenPair = await authApi.refreshToken(refreshToken.value)
      setTokens(resp)
      return true
    } catch {
      clearTokens()
      return false
    }
  }

  /** 更新用户资料 */
  async function updateProfile(data: Partial<UserInfo>) {
    const updated = await authApi.updateProfile(data)
    user.value = { ...user.value, ...updated } as UserInfo
    return updated
  }

  /** 设置最后访问路由 */
  function setLastVisitedRoute(path: string) {
    lastVisitedRoute.value = path
    localStorage.setItem('last_route', path)
  }

  // ── 私有方法 ──
  function setTokens(tokens: TokenPair) {
    accessToken.value = tokens.access_token
    refreshToken.value = tokens.refresh_token
    localStorage.setItem('access_token', tokens.access_token)
    localStorage.setItem('refresh_token', tokens.refresh_token)
  }

  function clearTokens() {
    accessToken.value = ''
    refreshToken.value = ''
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  // ═══════════════════════════════════
  // 导出
  // ═══════════════════════════════════
  return {
    accessToken, refreshToken, user, lastVisitedRoute,
    isLoggedIn, isAdmin, tokenHeader,
    login, register, logout, fetchUserInfo, tryRefreshToken,
    updateProfile, setLastVisitedRoute,
  }
})
```

### 4.4 Task Store — 任务数据（核心 Store）

```typescript
// src/stores/modules/task.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { taskApi } from '@/api/task'
import type { Task, TaskStatus, TaskListParams, TaskStats } from '@/types/task'

export const useTaskStore = defineStore('task', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const taskList = ref<Task[]>([])
  const currentTask = ref<Task | null>(null)
  const taskStats = ref<TaskStats>({
    runningTasks: 0, completedTasks: 0, failedTasks: 0, queuedTasks: 0,
  })
  const listLoading = ref(false)
  const detailLoading = ref(false)
  const submitLoading = ref(false)

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const recentTasks = computed(() =>
    [...taskList.value].sort((a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    ).slice(0, 10)
  )

  const tasksByStatus = computed(() => (status: TaskStatus) =>
    taskList.value.filter(t => t.status === status)
  )

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  /** 获取任务列表 */
  async function fetchTaskList(params?: TaskListParams) {
    listLoading.value = true
    try {
      const resp = await taskApi.list(params)
      taskList.value = resp.items
      return resp
    } finally {
      listLoading.value = false
    }
  }

  /** 获取任务详情 */
  async function fetchTaskDetail(taskId: string) {
    detailLoading.value = true
    try {
      const task = await taskApi.getDetail(taskId)
      currentTask.value = task
      // 同步更新列表中的该任务
      const idx = taskList.value.findIndex(t => t.id === taskId)
      if (idx >= 0) {
        taskList.value[idx] = task
      }
      return task
    } finally {
      detailLoading.value = false
    }
  }

  /** 提交任务 */
  async function submitTask(data: {
    flow_id: string
    project_id: string
    params: Record<string, any>
    description?: string
  }): Promise<string> {
    submitLoading.value = true
    try {
      const resp = await taskApi.submit(data)
      // 乐观更新：添加到列表头部
      taskList.value.unshift(resp)
      return resp.id
    } finally {
      submitLoading.value = false
    }
  }

  /** 取消任务 */
  async function cancelTask(taskId: string) {
    await taskApi.cancel(taskId)
    if (currentTask.value?.id === taskId) {
      currentTask.value.status = 'cancelled'
    }
  }

  /** 重试任务 */
  async function retryTask(taskId: string): Promise<string> {
    const resp = await taskApi.retry(taskId)
    return resp.id
  }

  /** 删除任务 */
  async function deleteTask(taskId: string) {
    await taskApi.delete(taskId)
    taskList.value = taskList.value.filter(t => t.id !== taskId)
    if (currentTask.value?.id === taskId) {
      currentTask.value = null
    }
  }

  /** 获取统计数据 */
  async function fetchStats(): Promise<TaskStats> {
    const stats = await taskApi.getStats()
    taskStats.value = stats
    return stats
  }

  /** 清除当前任务 */
  function clearCurrentTask() {
    currentTask.value = null
  }

  // ═══════════════════════════════════
  return {
    taskList, currentTask, taskStats,
    listLoading, detailLoading, submitLoading,
    recentTasks, tasksByStatus,
    fetchTaskList, fetchTaskDetail, submitTask,
    cancelTask, retryTask, deleteTask, fetchStats,
    clearCurrentTask,
  }
})
```

### 4.5 Flow Store — 流程数据

```typescript
// src/stores/modules/flow.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { flowApi } from '@/api/flow'
import type { Flow, FlowSummary, FlowSchema, FlowCategory } from '@/types/flow'

export const useFlowStore = defineStore('flow', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const flowList = ref<FlowSummary[]>([])
  const currentFlow = ref<Flow | null>(null)
  const currentSchema = ref<FlowSchema | null>(null)
  const schemaCache = ref<Map<string, FlowSchema>>(new Map()) // YAML 解析缓存
  const categories = ref<FlowCategory[]>([])
  const loading = ref(false)

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const popularFlows = computed(() =>
    [...flowList.value].sort((a, b) => b.use_count - a.use_count).slice(0, 5)
  )

  const flowsByCategory = computed(() => (category: string) =>
    flowList.value.filter(f => f.category === category)
  )

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  /** 获取流程列表 */
  async function fetchFlowList() {
    loading.value = true
    try {
      const resp = await flowApi.list()
      flowList.value = resp.items
      return resp
    } finally {
      loading.value = false
    }
  }

  /** 获取流程详情 */
  async function fetchFlowDetail(flowId: string) {
    const flow = await flowApi.getDetail(flowId)
    currentFlow.value = flow
    return flow
  }

  /** 获取流程 Schema（带缓存） */
  async function fetchFlowSchema(flowId: string): Promise<FlowSchema> {
    // 先查缓存
    const cached = schemaCache.value.get(flowId)
    if (cached) {
      currentSchema.value = cached
      return cached
    }

    const schema = await flowApi.getSchema(flowId)
    schemaCache.value.set(flowId, schema)
    currentSchema.value = schema
    return schema
  }

  /** 从 Schema 提取默认值 */
  function getDefaultValues(schema: FlowSchema): Record<string, any> {
    const values: Record<string, any> = {}
    for (const section of schema.sections) {
      for (const field of section.fields) {
        if (field.default !== undefined) {
          values[field.key] = field.default
        } else if (field.type === 'boolean') {
          values[field.key] = false
        } else if (field.type === 'multi-select' || field.type === 'checkbox') {
          values[field.key] = []
        } else if (field.type === 'number' || field.type === 'integer' || field.type === 'float') {
          values[field.key] = field.min ?? 0
        } else {
          values[field.key] = ''
        }
      }
    }
    return values
  }

  /** 清除 Schema 缓存 */
  function clearSchemaCache(flowId?: string) {
    if (flowId) {
      schemaCache.value.delete(flowId)
    } else {
      schemaCache.value.clear()
    }
  }

  /** 获取分类列表 */
  async function fetchCategories() {
    const cats = await flowApi.getCategories()
    categories.value = cats
    return cats
  }

  // ═══════════════════════════════════
  return {
    flowList, currentFlow, currentSchema, categories, loading,
    popularFlows, flowsByCategory,
    fetchFlowList, fetchFlowDetail, fetchFlowSchema,
    getDefaultValues, clearSchemaCache, fetchCategories,
  }
})
```

### 4.6 Project Store — 项目数据

```typescript
// src/stores/modules/project.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { projectApi } from '@/api/project'
import type { Project, ProjectCreateParams, Sample } from '@/types/project'

export const useProjectStore = defineStore('project', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const projectList = ref<Project[]>([])
  const currentProject = ref<Project | null>(null)
  const currentSamples = ref<Sample[]>([])
  const loading = ref(false)

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const projectOptions = computed(() =>
    projectList.value.map(p => ({
      label: p.name,
      value: p.id,
    }))
  )

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  async function fetchProjectList() {
    loading.value = true
    try {
      const resp = await projectApi.list()
      projectList.value = resp.items
      return resp
    } finally {
      loading.value = false
    }
  }

  async function fetchProjectDetail(projectId: string) {
    const project = await projectApi.getDetail(projectId)
    currentProject.value = project
    return project
  }

  async function createProject(params: ProjectCreateParams) {
    const project = await projectApi.create(params)
    projectList.value.unshift(project)
    return project
  }

  async function deleteProject(projectId: string) {
    await projectApi.delete(projectId)
    projectList.value = projectList.value.filter(p => p.id !== projectId)
    if (currentProject.value?.id === projectId) {
      currentProject.value = null
    }
  }

  async function fetchSamples(projectId: string) {
    const samples = await projectApi.getSamples(projectId)
    currentSamples.value = samples
    return samples
  }

  async function uploadSampleSheet(projectId: string, file: File) {
    const result = await projectApi.uploadSampleSheet(projectId, file)
    await fetchSamples(projectId)
    return result
  }

  function setCurrentProject(projectId: string | null) {
    if (!projectId) {
      currentProject.value = null
      return
    }
    const p = projectList.value.find(p => p.id === projectId)
    currentProject.value = p || null
  }

  // ═══════════════════════════════════
  return {
    projectList, currentProject, currentSamples, loading,
    projectOptions,
    fetchProjectList, fetchProjectDetail, createProject,
    deleteProject, fetchSamples, uploadSampleSheet,
    setCurrentProject,
  }
})
```

### 4.7 Chat Store — AI 对话状态（核心 Store）

```typescript
// src/stores/modules/chat.ts
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { chatApi } from '@/api/chat'
import { useAuthStore } from './auth'
import type {
  ChatSession, ChatMessage, WebSocketMessage,
  ChatContext, ToolCall, AIModelConfig,
} from '@/types/chat'

/** 消息角色类型 */
type MessageRole = 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result' | 'mcp_result'

export const useChatStore = defineStore('chat', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const panelVisible = ref(true)
  const unreadCount = ref(0)
  const isLoading = ref(false)          // AI 正在响应
  const isStreaming = ref(false)        // 流式接收中
  const streamingContent = ref('')      // 流式累积内容
  const wsStatus = ref<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle')
  const currentModel = ref<string>('gpt-4')
  const availableModels = ref<AIModelConfig[]>([])

  // 上下文感知
  const currentContext = ref<ChatContext>({
    page: '',
    routeParams: {},
    routeQuery: {},
    projectId: null,
    flowId: null,
    taskId: null,
  })

  // WebSocket 实例
  let ws: WebSocket | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  const MAX_RECONNECT = 5

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentSessionId.value) || null
  )

  const currentMessages = computed(() => messages.value)

  const isPanelOpen = computed(() => panelVisible.value)

  const wsConnected = computed(() => wsStatus.value === 'connected')

  // ═══════════════════════════════════
  // Actions — 会话管理
  // ═══════════════════════════════════

  /** 获取会话列表 */
  async function fetchSessions() {
    const resp = await chatApi.listSessions()
    sessions.value = resp.items
    return resp
  }

  /** 创建新会话 */
  async function createSession(title?: string): Promise<string> {
    const session = await chatApi.createSession({
      title: title || '新会话',
      model: currentModel.value,
    })
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    messages.value = []
    return session.id
  }

  /** 切换当前会话 */
  async function switchSession(sessionId: string) {
    currentSessionId.value = sessionId
    // 加载历史消息
    const resp = await chatApi.getMessages(sessionId)
    messages.value = resp.items
  }

  /** 删除会话 */
  async function deleteSession(sessionId: string) {
    await chatApi.deleteSession(sessionId)
    sessions.value = sessions.value.filter(s => s.id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
    }
  }

  /** 重命名会话 */
  async function renameSession(sessionId: string, title: string) {
    await chatApi.updateSession(sessionId, { title })
    const s = sessions.value.find(s => s.id === sessionId)
    if (s) s.title = title
  }

  // ═══════════════════════════════════
  // Actions — 消息发送
  // ═══════════════════════════════════

  /** 发送消息 */
  async function sendMessage(content: string) {
    if (!currentSessionId.value) {
      await createSession()
    }
    const sessionId = currentSessionId.value!

    // 1. 添加用户消息到本地
    const userMessage: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: sessionId,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMessage)

    // 2. 发送给后端（通过 WebSocket）
    isLoading.value = true
    isStreaming.value = false
    streamingContent.value = ''

    try {
      sendWsMessage({
        type: 'chat.message',
        session_id: sessionId,
        content,
        context: { ...currentContext.value },
        model: currentModel.value,
      })
    } catch (err: any) {
      // 降级到 HTTP API
      await sendViaHttp(sessionId, content)
    }
  }

  /** HTTP 降级发送 */
  async function sendViaHttp(sessionId: string, content: string) {
    try {
      const resp = await chatApi.sendMessage(sessionId, {
        content,
        context: currentContext.value,
      })
      appendAssistantMessage(resp)
    } catch (err: any) {
      appendErrorMessage(err.message)
    } finally {
      isLoading.value = false
    }
  }

  /** 追加助手消息 */
  function appendAssistantMessage(data: { content: string; tool_calls?: ToolCall[] }) {
    const msg: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'assistant',
      content: data.content,
      tool_calls: data.tool_calls,
      created_at: new Date().toISOString(),
    }
    messages.value.push(msg)
    isLoading.value = false
    isStreaming.value = false
  }

  /** 追加错误消息 */
  function appendErrorMessage(errorText: string) {
    const msg: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'assistant',
      content: `❌ **错误**: ${errorText}`,
      is_error: true,
      created_at: new Date().toISOString(),
    }
    messages.value.push(msg)
    isLoading.value = false
  }

  // ═══════════════════════════════════
  // Actions — 工具调用确认
  // ═══════════════════════════════════

  /** 确认执行工具调用 */
  async function confirmToolCall(toolCall: ToolCall) {
    // 添加 "用户已确认" 消息
    messages.value.push({
      id: `local-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'tool_result',
      content: `已确认执行: ${toolCall.function.name}`,
      tool_call_id: toolCall.id,
      created_at: new Date().toISOString(),
    })

    // 发送确认到后端
    sendWsMessage({
      type: 'chat.tool_confirm',
      session_id: currentSessionId.value,
      tool_call_id: toolCall.id,
      confirmed: true,
    })
  }

  /** 拒绝工具调用 */
  async function rejectToolCall(toolCall: ToolCall) {
    messages.value.push({
      id: `local-${Date.now()}`,
      session_id: currentSessionId.value!,
      role: 'tool_result',
      content: `已拒绝执行: ${toolCall.function.name}`,
      tool_call_id: toolCall.id,
      created_at: new Date().toISOString(),
    })

    sendWsMessage({
      type: 'chat.tool_confirm',
      session_id: currentSessionId.value,
      tool_call_id: toolCall.id,
      confirmed: false,
    })
  }

  // ═══════════════════════════════════
  // Actions — WebSocket 管理
  // ═══════════════════════════════════

  /** 连接 WebSocket */
  function connectWebSocket() {
    if (ws?.readyState === WebSocket.OPEN) return

    wsStatus.value = 'connecting'
    const authStore = useAuthStore()
    const token = authStore.accessToken
    const wsUrl = `${import.meta.env.VITE_WS_BASE_URL}/ws/chat?token=${token}`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      wsStatus.value = 'connected'
      reconnectAttempts = 0
      startHeartbeat()
    }

    ws.onmessage = (event) => {
      try {
        const msg: WebSocketMessage = JSON.parse(event.data)
        handleWsMessage(msg)
      } catch {
        console.warn('[Chat WS] Invalid message:', event.data)
      }
    }

    ws.onclose = () => {
      wsStatus.value = 'disconnected'
      stopHeartbeat()
      attemptReconnect()
    }

    ws.onerror = (err) => {
      console.error('[Chat WS] Error:', err)
      wsStatus.value = 'disconnected'
    }
  }

  /** 断开 WebSocket */
  function disconnectWebSocket() {
    stopHeartbeat()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    ws?.close()
    ws = null
    wsStatus.value = 'idle'
  }

  /** 重连 */
  function attemptReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) {
      console.warn('[Chat WS] Max reconnect attempts reached')
      return
    }
    reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
    reconnectTimer = setTimeout(() => {
      console.log(`[Chat WS] Reconnecting... (attempt ${reconnectAttempts})`)
      connectWebSocket()
    }, delay)
  }

  /** 心跳 */
  function startHeartbeat() {
    heartbeatTimer = setInterval(() => {
      sendWsMessage({ type: 'ping' })
    }, 30000)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  /** 发送 WS 消息 */
  function sendWsMessage(msg: Record<string, any>) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    } else {
      throw new Error('WebSocket not connected')
    }
  }

  /** 处理收到的 WS 消息 */
  function handleWsMessage(msg: WebSocketMessage) {
    switch (msg.type) {
      case 'pong':
        // 心跳响应，无需处理
        break

      case 'chat.message_chunk':
        // 流式消息片段
        if (!isStreaming.value) {
          isStreaming.value = true
          streamingContent.value = ''
        }
        streamingContent.value += msg.chunk || ''
        break

      case 'chat.message_end':
        // 流式消息结束
        appendAssistantMessage({
          content: streamingContent.value || msg.content || '',
          tool_calls: msg.tool_calls,
        })
        streamingContent.value = ''
        isStreaming.value = false
        isLoading.value = false
        break

      case 'chat.tool_call_request':
        // AI 请求工具调用 → 渲染确认卡片
        messages.value.push({
          id: `local-${Date.now()}`,
          session_id: currentSessionId.value!,
          role: 'tool_call',
          content: '',
          tool_calls: msg.tool_calls,
          created_at: new Date().toISOString(),
        })
        isLoading.value = false
        break

      case 'chat.tool_result':
        // 工具执行结果
        messages.value.push({
          id: `local-${Date.now()}`,
          session_id: currentSessionId.value!,
          role: 'tool_result',
          content: msg.content || JSON.stringify(msg.result),
          tool_call_id: msg.tool_call_id,
          created_at: new Date().toISOString(),
        })
        break

      case 'chat.mcp_result':
        // MCP 工具结果
        messages.value.push({
          id: `local-${Date.now()}`,
          session_id: currentSessionId.value!,
          role: 'mcp_result',
          content: msg.content || '',
          mcp_server: msg.mcp_server,
          tool_name: msg.tool_name,
          result: msg.result,
          created_at: new Date().toISOString(),
        })
        break

      case 'error':
        appendErrorMessage(msg.message || '未知错误')
        break

      default:
        console.warn('[Chat WS] Unknown message type:', msg.type)
    }
  }

  // ═══════════════════════════════════
  // Actions — 上下文管理
  // ═══════════════════════════════════

  /** 从路由自动收集上下文 */
  function collectRouteContext(
    path: string,
    params: Record<string, string>,
    query: Record<string, string>,
  ) {
    const context: ChatContext = {
      page: path,
      routeParams: params,
      routeQuery: query,
    }

    // 路由 → 上下文推断
    if (path.startsWith('/projects/') && params.id) {
      context.projectId = params.id
    }
    if (path.startsWith('/flows/') && params.id) {
      context.flowId = params.id
    }
    if (path.startsWith('/tasks/') && params.id) {
      context.taskId = params.id
    }
    // 新建任务页从 query 获取
    if (path === '/tasks/new') {
      if (query.flow) context.flowId = query.flow
      if (query.project) context.projectId = query.project
    }

    currentContext.value = context
  }

  /** 手动设置上下文 */
  function setContext(updates: Partial<ChatContext>) {
    currentContext.value = { ...currentContext.value, ...updates }
  }

  function setCurrentProject(projectId: string | null) {
    currentContext.value.projectId = projectId
  }
  function setCurrentFlow(flowId: string | null) {
    currentContext.value.flowId = flowId
  }
  function setCurrentTask(taskId: string | null) {
    currentContext.value.taskId = taskId
  }
  function clearCurrentTask() {
    currentContext.value.taskId = null
  }

  // ═══════════════════════════════════
  // Actions — 面板控制
  // ═══════════════════════════════════

  function togglePanel(force?: boolean) {
    panelVisible.value = force !== undefined ? force : !panelVisible.value
  }

  /** 获取可用模型列表 */
  async function fetchModels() {
    const resp = await chatApi.listModels()
    availableModels.value = resp.items
    if (!availableModels.value.find(m => m.id === currentModel.value)) {
      currentModel.value = availableModels.value[0]?.id || 'gpt-4'
    }
    return resp
  }

  // ═══════════════════════════════════
  // Watch — 自动连接/断开 WebSocket
  // ═══════════════════════════════════
  watch(
    () => panelVisible.value,
    (visible) => {
      if (visible) {
        connectWebSocket()
      } else {
        disconnectWebSocket()
      }
    }
  )

  // ═══════════════════════════════════
  return {
    sessions, currentSessionId, messages,
    panelVisible, unreadCount, isLoading, isStreaming,
    streamingContent, wsStatus, currentModel, availableModels,
    currentContext, currentSession, currentMessages,
    isPanelOpen, wsConnected,
    fetchSessions, createSession, switchSession, deleteSession, renameSession,
    sendMessage, confirmToolCall, rejectToolCall,
    connectWebSocket, disconnectWebSocket,
    collectRouteContext, setContext,
    setCurrentProject, setCurrentFlow, setCurrentTask, clearCurrentTask,
    togglePanel, fetchModels,
  }
})
```

### 4.8 MCP Store — MCP Server 管理

```typescript
// src/stores/modules/mcp.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { mcpApi } from '@/api/mcp'
import type { MCPServer, MCPTool } from '@/types/mcp'

export const useMCPStore = defineStore('mcp', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const servers = ref<MCPServer[]>([])
  const currentServer = ref<MCPServer | null>(null)
  const toolCatalog = ref<MCPTool[]>([])
  const loading = ref(false)

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const activeServers = computed(() => servers.value.filter(s => s.status === 'active'))
  const activeTools = computed(() => toolCatalog.value.filter(t => t.available))

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  async function fetchServers() {
    loading.value = true
    try {
      const resp = await mcpApi.listServers()
      servers.value = resp.items
      return resp
    } finally {
      loading.value = false
    }
  }

  async function fetchServerDetail(serverId: string) {
    const server = await mcpApi.getServerDetail(serverId)
    currentServer.value = server
    return server
  }

  async function fetchToolCatalog() {
    const resp = await mcpApi.listTools()
    toolCatalog.value = resp.items
    return resp
  }

  /** 创建 MCP Server */
  async function createServer(data: {
    name: string; url: string; description?: string; icon?: string
  }) {
    const server = await mcpApi.createServer(data)
    servers.value.push(server)
    return server
  }

  /** 删除 MCP Server */
  async function deleteServer(serverId: string) {
    await mcpApi.deleteServer(serverId)
    servers.value = servers.value.filter(s => s.id !== serverId)
    if (currentServer.value?.id === serverId) {
      currentServer.value = null
    }
  }

  /** 测试连接 */
  async function testConnection(serverId: string) {
    return mcpApi.testConnection(serverId)
  }

  // ═══════════════════════════════════
  return {
    servers, currentServer, toolCatalog, loading,
    activeServers, activeTools,
    fetchServers, fetchServerDetail, fetchToolCatalog,
    createServer, deleteServer, testConnection,
  }
})
```

### 4.9 Theme Store — 主题状态

```typescript
// src/stores/modules/theme.ts
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { darkTheme, lightTheme } from 'naive-ui'
import type { GlobalTheme } from 'naive-ui'

export type ThemeMode = 'dark' | 'light' | 'system'

export const useThemeStore = defineStore('theme', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const themeMode = ref<ThemeMode>(
    (localStorage.getItem('theme_mode') as ThemeMode) || 'system'
  )

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const isDark = computed(() => {
    if (themeMode.value === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches
    }
    return themeMode.value === 'dark'
  })

  const naiveTheme = computed<GlobalTheme | null>(() =>
    isDark.value ? darkTheme : null // null = light (default)
  )

  const naiveThemeOverrides = computed(() => ({
    common: {
      primaryColor: '#6366f1',
      primaryColorHover: '#818cf8',
      primaryColorPressed: '#4f46e5',
      primaryColorSuppl: '#818cf8',
    },
  }))

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  function setTheme(mode: ThemeMode) {
    themeMode.value = mode
    localStorage.setItem('theme_mode', mode)
    applyTheme()
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  function applyTheme() {
    const root = document.documentElement
    if (isDark.value) {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }

  /** 立即应用主题（防止闪烁，在路由守卫中调用） */
  function applyThemeImmediately() {
    const saved = (localStorage.getItem('theme_mode') as ThemeMode) || 'system'
    const dark = saved === 'dark' || (saved === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
    const root = document.documentElement
    if (dark) root.classList.add('dark')
    else root.classList.remove('dark')
  }

  // ── 监听系统主题变化 ──
  if (window.matchMedia) {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', () => {
      if (themeMode.value === 'system') {
        applyTheme()
      }
    })
  }

  // ── 监听 store 变化 ──
  watch(() => themeMode.value, applyTheme, { immediate: true })

  // ═══════════════════════════════════
  return {
    themeMode, isDark, naiveTheme, naiveThemeOverrides,
    setTheme, toggleTheme, applyTheme, applyThemeImmediately,
  }
})
```

### 4.10 Notification Store — 全局通知

```typescript
// src/stores/modules/notification.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { NotificationType } from 'naive-ui'

export interface AppNotification {
  id: string
  type: NotificationType
  title: string
  content: string
  read: boolean
  created_at: string
  link?: string
}

export const useNotificationStore = defineStore('notification', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const notifications = ref<AppNotification[]>([])
  const unreadCount = ref(0)

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  /** 添加通知 */
  function add(notification: Omit<AppNotification, 'id' | 'created_at' | 'read'>) {
    const item: AppNotification = {
      ...notification,
      id: `notif-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      read: false,
      created_at: new Date().toISOString(),
    }
    notifications.value.unshift(item)
    unreadCount.value++
    return item.id
  }

  /** 标记已读 */
  function markAsRead(id: string) {
    const n = notifications.value.find(x => x.id === id)
    if (n && !n.read) {
      n.read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  }

  /** 标记全部已读 */
  function markAllRead() {
    notifications.value.forEach(n => { n.read = true })
    unreadCount.value = 0
  }

  /** 清除所有 */
  function clearAll() {
    notifications.value = []
    unreadCount.value = 0
  }

  /** 从 WebSocket 推送接收 */
  function handlePush(data: { title: string; content: string; type?: NotificationType; link?: string }) {
    add({
      type: data.type || 'info',
      title: data.title,
      content: data.content,
      link: data.link,
    })
  }

  // ═══════════════════════════════════
  return {
    notifications, unreadCount,
    add, markAsRead, markAllRead, clearAll, handlePush,
  }
})
```

### 4.11 Tab Store — 标签页与缓存管理

```typescript
// src/stores/modules/tab.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface TabItem {
  name: string
  title: string
  path: string
  keepAlive?: boolean
}

export const useTabStore = defineStore('tab', () => {
  // ═══════════════════════════════════
  // State
  // ═══════════════════════════════════
  const tabs = ref<TabItem[]>([])
  const activeTab = ref<string>('')

  // ═══════════════════════════════════
  // Getters
  // ═══════════════════════════════════
  const cachedViews = computed(() =>
    tabs.value.filter(t => t.keepAlive).map(t => t.name)
  )

  // ═══════════════════════════════════
  // Actions
  // ═══════════════════════════════════

  function addTab(tab: TabItem) {
    const exists = tabs.value.find(t => t.path === tab.path)
    if (!exists) {
      tabs.value.push(tab)
    }
    activeTab.value = tab.path
  }

  function removeTab(path: string) {
    tabs.value = tabs.value.filter(t => t.path !== path)
    if (activeTab.value === path && tabs.value.length > 0) {
      activeTab.value = tabs.value[tabs.value.length - 1].path
    }
  }

  function setActiveTab(path: string) {
    activeTab.value = path
  }

  // ═══════════════════════════════════
  return {
    tabs, activeTab, cachedViews,
    addTab, removeTab, setActiveTab,
  }
})
```



---

## 5. AI 对话面板架构（重点）

### 5.1 总体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MainLayout 主布局                                    │
│  ┌────────────────┐  ┌──────────────────────────────────┐  ┌──────────────┐ │
│  │                │  │                                  │  │  AIChatPanel  │ │
│  │  AppSidebar    │  │         主内容区                  │  │   (380px)    │ │
│  │   (220px)      │  │                                  │  │              │ │
│  │                │  │   RouterView                     │  │  ChatHeader  │ │
│  │  仪表盘         │  │   ┌─────────────────────────┐   │  │  ChatMsgList │ │
│  │  项目管理       │  │   │ DashboardView /         │   │  │  ChatInput   │ │
│  │  流程市场       │  │   │ TaskDetailView / ...    │   │  │  ContextBar  │ │
│  │  任务中心       │  │   │                         │   │  │              │ │
│  │                │  │   │                         │   │  └──────────────┘ │
│  │                │  │   │                         │   │                  │
│  │                │  │   └─────────────────────────┘   │                  │
│  │                │  │                                  │                  │
│  └────────────────┘  └──────────────────────────────────┘                  │
│                                                                             │
│  (折叠时显示 AIChatFab 浮动按钮)                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 AIChatPanel.vue — 主面板容器

```vue
<!-- src/components/ai-chat/AIChatPanel.vue -->
<template>
  <div class="ai-chat-panel" :class="{ dark: themeStore.isDark }">
    <!-- 头部 -->
    <ChatHeader
      :current-model="chatStore.currentModel"
      :models="chatStore.availableModels"
      :current-session="chatStore.currentSession"
      @model-change="chatStore.currentModel = $event"
      @new-session="chatStore.createSession()"
      @toggle-panel="chatStore.togglePanel(false)"
      @show-sessions="showSessionDrawer = true"
    />

    <!-- 上下文指示条 -->
    <ChatContextBar
      :context="chatStore.currentContext"
      :project-name="currentProjectName"
      :flow-name="currentFlowName"
      :task-status="currentTask?.status"
      @clear-context="clearContext"
    />

    <!-- 消息列表 -->
    <div ref="messageListRef" class="ai-chat-panel__messages">
      <ChatMessageList
        :messages="displayMessages"
        :is-streaming="chatStore.isStreaming"
        :streaming-content="chatStore.streamingContent"
        :is-loading="chatStore.isLoading"
        @confirm-tool="chatStore.confirmToolCall"
        @reject-tool="chatStore.rejectToolCall"
      />
    </div>

    <!-- 快捷操作栏（可展开） -->
    <ChatQuickActions
      :context="chatStore.currentContext"
      @action="handleQuickAction"
    />

    <!-- 输入区 -->
    <ChatInputArea
      :disabled="chatStore.isLoading"
      :placeholder="inputPlaceholder"
      @send="handleSendMessage"
      @stop="handleStopGeneration"
    />

    <!-- 会话列表面板 -->
    <SessionDrawer
      v-model:show="showSessionDrawer"
      :sessions="chatStore.sessions"
      :current-id="chatStore.currentSessionId"
      @select="chatStore.switchSession"
      @delete="chatStore.deleteSession"
      @rename="chatStore.renameSession"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'

import ChatHeader from './ChatHeader.vue'
import ChatContextBar from './ChatContextBar.vue'
import ChatMessageList from './ChatMessageList.vue'
import ChatQuickActions from './ChatQuickActions.vue'
import ChatInputArea from './ChatInputArea.vue'
import SessionDrawer from './SessionDrawer.vue'

import { useChatStore } from '@/stores/modules/chat'
import { useProjectStore } from '@/stores/modules/project'
import { useFlowStore } from '@/stores/modules/flow'
import { useTaskStore } from '@/stores/modules/task'
import { useThemeStore } from '@/stores/modules/theme'

const chatStore = useChatStore()
const projectStore = useProjectStore()
const flowStore = useFlowStore()
const taskStore = useTaskStore()
const themeStore = useThemeStore()

const messageListRef = ref<HTMLDivElement>()
const showSessionDrawer = ref(false)

// ── 显示的消息（合并流式内容） ──
const displayMessages = computed(() => {
  const msgs = [...chatStore.currentMessages]
  if (chatStore.isStreaming && chatStore.streamingContent) {
    // 追加一个临时的流式消息
    msgs.push({
      id: 'streaming',
      session_id: chatStore.currentSessionId || '',
      role: 'assistant',
      content: chatStore.streamingContent,
      is_streaming: true,
      created_at: new Date().toISOString(),
    } as any)
  }
  return msgs
})

// ── 上下文名称解析 ──
const currentProjectName = computed(() => {
  const ctx = chatStore.currentContext
  if (!ctx.projectId) return null
  const p = projectStore.projectList.find(x => x.id === ctx.projectId)
  return p?.name || null
})

const currentFlowName = computed(() => {
  const ctx = chatStore.currentContext
  if (!ctx.flowId) return null
  const f = flowStore.flowList.find(x => x.id === ctx.flowId)
  return f?.name || null
})

const currentTask = computed(() => {
  const ctx = chatStore.currentContext
  if (!ctx.taskId) return null
  return taskStore.taskList.find(t => t.id === ctx.taskId) || null
})

// ── 输入框占位符 ──
const inputPlaceholder = computed(() => {
  const ctx = chatStore.currentContext
  if (ctx.taskId) return '询问关于此任务的问题...'
  if (ctx.flowId) return '询问关于此流程的问题...'
  if (ctx.projectId) return '询问关于此项目的问题...'
  return '给 AI 助手发送消息...'
})

// ── 发送消息 ──
async function handleSendMessage(content: string) {
  await chatStore.sendMessage(content)
}

// ── 停止生成 ──
function handleStopGeneration() {
  chatStore.sendWsMessage({
    type: 'chat.stop',
    session_id: chatStore.currentSessionId,
  })
  chatStore.isLoading = false
  chatStore.isStreaming = false
}

// ── 快捷操作 ──
function handleQuickAction(action: string) {
  const ctx = chatStore.currentContext
  switch (action) {
    case 'explain_task':
      if (ctx.taskId) {
        chatStore.sendMessage(`请解释这个任务当前的状态和进度`)
      }
      break
    case 'check_errors':
      if (ctx.taskId) {
        chatStore.sendMessage(`请帮我分析任务日志中的错误`)
      }
      break
    case 'view_results':
      if (ctx.taskId) {
        chatStore.sendMessage(`请总结这个结果文件的内容`)
      }
      break
    case 'flow_params':
      if (ctx.flowId) {
        chatStore.sendMessage(`请解释这个流程的参数配置`)
      }
      break
    default:
      break
  }
}

function clearContext() {
  chatStore.setContext({
    projectId: null,
    flowId: null,
    taskId: null,
  })
}

// ── 自动滚动到最新消息 ──
watch(
  () => displayMessages.value.length,
  async () => {
    await nextTick()
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  }
)

// ── 初始化 ──
chatStore.fetchModels()
chatStore.connectWebSocket()
</script>

<style scoped lang="scss">
.ai-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--chat-bg);
  position: relative;

  &__messages {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 12px;
  }
}
</style>
```

### 5.3 ChatHeader.vue — 面板头部

```vue
<!-- src/components/ai-chat/ChatHeader.vue -->
<template>
  <div class="chat-header">
    <!-- 左侧：会话标题 + 模型选择 -->
    <div class="chat-header__left">
      <div class="chat-title" @click="$emit('show-sessions')">
        <n-icon size="18" class="title-icon"><MessageOutlined /></n-icon>
        <span class="title-text">{{ currentSession?.title || 'AI 助手' }}</span>
        <n-icon size="14" class="chevron-icon"><DownOutlined /></n-icon>
      </div>

      <n-dropdown
        :options="modelOptions"
        trigger="click"
        @select="handleModelSelect"
      >
        <n-tag size="small" :bordered="false" type="info" class="model-tag">
          {{ currentModelLabel }}
          <n-icon size="12"><DownOutlined /></n-icon>
        </n-tag>
      </n-dropdown>
    </div>

    <!-- 右侧操作 -->
    <div class="chat-header__right">
      <n-tooltip placement="bottom">
        <template #trigger>
          <n-button text circle size="small" @click="$emit('new-session')">
            <template #icon><n-icon><PlusOutlined /></n-icon></template>
          </n-button>
        </template>
        新会话
      </n-tooltip>

      <n-tooltip placement="bottom">
        <template #trigger>
          <n-button text circle size="small" @click="$emit('toggle-panel')">
            <template #icon><n-icon><RightOutlined /></n-icon></template>
          </n-button>
        </template>
        收起面板
      </n-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NIcon, NTag, NDropdown, NTooltip } from 'naive-ui'
import { MessageOutlined, DownOutlined, PlusOutlined, RightOutlined } from '@vicons/antd'
import type { ChatSession, AIModelConfig } from '@/types/chat'
import type { DropdownOption } from 'naive-ui'

const props = defineProps<{
  currentModel: string
  models: AIModelConfig[]
  currentSession: ChatSession | null
}>()

defineEmits<{
  (e: 'model-change', modelId: string): void
  (e: 'new-session'): void
  (e: 'toggle-panel'): void
  (e: 'show-sessions'): void
}>()

const modelOptions = computed<DropdownOption[]>(() =>
  props.models.map(m => ({
    label: m.name,
    key: m.id,
  }))
)

const currentModelLabel = computed(() => {
  const m = props.models.find(x => x.id === props.currentModel)
  return m?.name || props.currentModel
})

function handleModelSelect(key: string) {
  emitModelChange(key)
}

function emitModelChange(key: string) {
  // handled via template $emit
}
</script>

<style scoped lang="scss">
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;

  &__left {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;

    .chat-title {
      display: flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 6px;
      transition: background 0.2s;

      &:hover { background: var(--hover-bg); }

      .title-text {
        font-weight: 600;
        font-size: 14px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 140px;
      }

      .title-icon { color: var(--primary-color); }
      .chevron-icon { color: var(--text-secondary); }
    }

    .model-tag {
      cursor: pointer;
      font-size: 11px;
    }
  }

  &__right {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
}
</style>
```

### 5.4 ChatMessageList.vue — 消息列表（虚拟滚动优化）

```vue
<!-- src/components/ai-chat/ChatMessageList.vue -->
<template>
  <div class="chat-message-list">
    <!-- 欢迎语（无消息时显示） -->
    <ChatWelcome v-if="messages.length === 0" />

    <!-- 消息列表 -->
    <template v-for="(msg, index) in messages" :key="msg.id">
      <!-- 日期分隔线 -->
      <div v-if="showDateDivider(index)" class="date-divider">
        <span>{{ formatDateDivider(msg.created_at) }}</span>
      </div>

      <!-- 用户消息 -->
      <ChatMessageUser
        v-if="msg.role === 'user'"
        :content="msg.content"
        :timestamp="msg.created_at"
      />

      <!-- 助手消息 -->
      <ChatMessageAssistant
        v-else-if="msg.role === 'assistant'"
        :content="msg.content"
        :timestamp="msg.created_at"
        :is-error="msg.is_error"
        :is-streaming="msg.is_streaming"
      />

      <!-- 工具调用确认卡片 -->
      <ChatMessageToolCall
        v-else-if="msg.role === 'tool_call' && msg.tool_calls"
        :tool-calls="msg.tool_calls"
        :timestamp="msg.created_at"
        @confirm="$emit('confirm-tool', $event)"
        @reject="$emit('reject-tool', $event)"
      />

      <!-- 工具结果 -->
      <ChatMessageToolResult
        v-else-if="msg.role === 'tool_result'"
        :content="msg.content"
        :tool-call-id="msg.tool_call_id"
        :timestamp="msg.created_at"
      />

      <!-- MCP 工具结果 -->
      <ChatMessageMCPResult
        v-else-if="msg.role === 'mcp_result'"
        :content="msg.content"
        :mcp-server="msg.mcp_server"
        :tool-name="msg.tool_name"
        :result="msg.result"
        :timestamp="msg.created_at"
      />
    </template>

    <!-- 输入中动画 -->
    <TypingIndicator v-if="isLoading && !isStreaming" />

    <!-- 底部占位 -->
    <div ref="bottomAnchor" style="height: 1px"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

import ChatWelcome from './ChatWelcome.vue'
import ChatMessageUser from './ChatMessageUser.vue'
import ChatMessageAssistant from './ChatMessageAssistant.vue'
import ChatMessageToolCall from './ChatMessageToolCall.vue'
import ChatMessageToolResult from './ChatMessageToolResult.vue'
import ChatMessageMCPResult from './ChatMessageMCPResult.vue'
import TypingIndicator from './TypingIndicator.vue'

import type { ChatMessage, ToolCall } from '@/types/chat'
import { formatDateDivider, shouldShowDateDivider } from '@/utils/time'

const props = defineProps<{
  messages: ChatMessage[]
  isStreaming: boolean
  streamingContent: string
  isLoading: boolean
}>()

defineEmits<{
  (e: 'confirm-tool', toolCall: ToolCall): void
  (e: 'reject-tool', toolCall: ToolCall): void
}>()

const bottomAnchor = ref<HTMLDivElement>()

function showDateDivider(index: number): boolean {
  if (index === 0) return true
  return shouldShowDateDivider(
    props.messages[index - 1].created_at,
    props.messages[index].created_at,
  )
}

// 自动滚动到底部
watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    bottomAnchor.value?.scrollIntoView({ behavior: 'smooth' })
  }
)
</script>

<style scoped lang="scss">
.chat-message-list {
  display: flex;
  flex-direction: column;
  gap: 16px;

  .date-divider {
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 8px 0;

    span {
      font-size: 11px;
      color: var(--text-tertiary);
      background: var(--divider-bg);
      padding: 2px 12px;
      border-radius: 10px;
    }
  }
}
</style>
```

### 5.5 ChatMessageAssistant.vue — AI 消息渲染（Markdown + 代码高亮）

```vue
<!-- src/components/ai-chat/ChatMessageAssistant.vue -->
<template>
  <div class="chat-message-assistant" :class="{ 'is-error': isError, 'is-streaming': isStreaming }">
    <!-- AI 头像 -->
    <div class="assistant-avatar">
      <div class="avatar-ring">
        <n-icon size="16"><RobotOutlined /></n-icon>
      </div>
    </div>

    <!-- 消息内容 -->
    <div class="assistant-content">
      <!-- Markdown 渲染 -->
      <div class="markdown-body" v-html="renderedContent" />

      <!-- 操作栏 -->
      <div class="assistant-actions">
        <n-tooltip v-for="action in actions" :key="action.key">
          <template #trigger>
            <n-button text size="tiny" @click="action.handler">
              <template #icon><n-icon size="14"><component :is="action.icon" /></n-icon></template>
            </n-button>
          </template>
          {{ action.tooltip }}
        </n-tooltip>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NIcon, NTooltip } from 'naive-ui'
import { RobotOutlined, CopyOutlined, SyncOutlined, ThumbsUpOutlined, ThumbsDownOutlined } from '@vicons/antd'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'

const props = defineProps<{
  content: string
  timestamp: string
  isError?: boolean
  isStreaming?: boolean
}>()

// ── Markdown 渲染 ──
const renderedContent = computed(() => {
  if (!props.content) return ''

  // 配置 marked
  marked.setOptions({
    breaks: true,
    gfm: true,
  })

  const rawHtml = marked.parse(props.content)
  return DOMPurify.sanitize(rawHtml as string)
})

// ── 操作按钮 ──
const actions = [
  {
    key: 'copy',
    icon: CopyOutlined,
    tooltip: '复制内容',
    handler: () => {
      navigator.clipboard.writeText(props.content)
    },
  },
  {
    key: 'regenerate',
    icon: SyncOutlined,
    tooltip: '重新生成',
    handler: () => { /* 重新生成 */ },
  },
  {
    key: 'like',
    icon: ThumbsUpOutlined,
    tooltip: '有帮助',
    handler: () => { /* 反馈 */ },
  },
  {
    key: 'dislike',
    icon: ThumbsDownOutlined,
    tooltip: '无帮助',
    handler: () => { /* 反馈 */ },
  },
]
</script>

<style scoped lang="scss">
.chat-message-assistant {
  display: flex;
  gap: 10px;
  align-items: flex-start;

  &.is-error {
    .markdown-body { color: #ef4444; }
  }

  &.is-streaming {
    .markdown-body::after {
      content: '▊';
      animation: blink 1s infinite;
      margin-left: 2px;
      color: var(--primary-color);
    }
  }

  .assistant-avatar {
    flex-shrink: 0;

    .avatar-ring {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
    }
  }

  .assistant-content {
    flex: 1;
    min-width: 0;

    .markdown-body {
      font-size: 13.5px;
      line-height: 1.7;
      color: var(--text-primary);

      :deep(h1, h2, h3, h4) {
        margin: 12px 0 8px;
        font-weight: 600;
      }
      :deep(p) { margin: 6px 0; }
      :deep(code) {
        background: var(--code-bg);
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 12px;
        font-family: 'JetBrains Mono', monospace;
      }
      :deep(pre) {
        background: var(--code-block-bg);
        padding: 12px;
        border-radius: 8px;
        overflow-x: auto;
        margin: 8px 0;

        code {
          background: none;
          padding: 0;
          font-size: 12px;
        }
      }
      :deep(ul, ol) {
        margin: 6px 0;
        padding-left: 20px;
      }
      :deep(li) { margin: 2px 0; }
      :deep(table) {
        border-collapse: collapse;
        margin: 8px 0;
        font-size: 12px;

        th, td {
          border: 1px solid var(--border-color);
          padding: 6px 10px;
        }
        th {
          background: var(--table-header-bg);
          font-weight: 600;
        }
      }
      :deep(a) {
        color: var(--primary-color);
        text-decoration: none;

        &:hover { text-decoration: underline; }
      }
    }

    .assistant-actions {
      display: flex;
      gap: 4px;
      margin-top: 6px;
      opacity: 0;
      transition: opacity 0.2s;
    }

    &:hover .assistant-actions {
      opacity: 1;
    }
  }
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
```

### 5.6 ChatMessageToolCall.vue — 工具调用确认卡片

```vue
<!-- src/components/ai-chat/ChatMessageToolCall.vue -->
<template>
  <div class="chat-message-tool-call">
    <div class="tool-call-card">
      <!-- 头部 -->
      <div class="tool-call-header">
        <n-icon size="16" class="tool-icon"><ToolOutlined /></n-icon>
        <span class="tool-title">工具调用请求</span>
        <n-tag size="tiny" type="warning" :bordered="false">待确认</n-tag>
      </div>

      <!-- 工具列表 -->
      <div class="tool-list">
        <div v-for="tc in toolCalls" :key="tc.id" class="tool-item">
          <div class="tool-name">
            <n-icon size="14"><ApiOutlined /></n-icon>
            <code>{{ tc.function.name }}</code>
          </div>
          <pre class="tool-args">{{ formatArgs(tc.function.arguments) }}</pre>
        </div>
      </div>

      <!-- 提示 -->
      <n-alert type="warning" :show-icon="true" size="small" style="margin-top: 8px">
        <template #header>权限确认</template>
        此操作将调用后端 API 并可能修改数据。请确认是否允许执行？
      </n-alert>

      <!-- 操作按钮 -->
      <div class="tool-actions">
        <n-button size="small" @click="handleRejectAll">
          <template #icon><n-icon><CloseOutlined /></n-icon></template>
          拒绝
        </n-button>
        <n-button size="small" type="primary" @click="handleConfirmAll">
          <template #icon><n-icon><CheckOutlined /></n-icon></template>
          确认执行
        </n-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { NIcon, NTag, NAlert, NButton } from 'naive-ui'
import { ToolOutlined, ApiOutlined, CheckOutlined, CloseOutlined } from '@vicons/antd'
import type { ToolCall } from '@/types/chat'

const props = defineProps<{
  toolCalls: ToolCall[]
  timestamp: string
}>()

const emit = defineEmits<{
  (e: 'confirm', toolCall: ToolCall): void
  (e: 'reject', toolCall: ToolCall): void
}>()

function formatArgs(args: string): string {
  try {
    const parsed = JSON.parse(args)
    return JSON.stringify(parsed, null, 2)
  } catch {
    return args
  }
}

function handleConfirmAll() {
  props.toolCalls.forEach(tc => emit('confirm', tc))
}

function handleRejectAll() {
  props.toolCalls.forEach(tc => emit('reject', tc))
}
</script>

<style scoped lang="scss">
.chat-message-tool-call {
  display: flex;
  gap: 10px;
  align-items: flex-start;

  &::before {
    content: '';
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: #f59e0b;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .tool-call-card {
    flex: 1;
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 12px;

    .tool-call-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;

      .tool-icon { color: #f59e0b; }
      .tool-title { font-weight: 600; font-size: 13px; flex: 1; }
    }

    .tool-list {
      display: flex;
      flex-direction: column;
      gap: 8px;

      .tool-item {
        background: var(--code-bg);
        border-radius: 6px;
        padding: 8px 10px;

        .tool-name {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 4px;

          code {
            font-weight: 600;
            font-size: 13px;
          }
        }

        .tool-args {
          margin: 0;
          padding: 6px 8px;
          background: var(--code-block-bg);
          border-radius: 4px;
          font-size: 11px;
          font-family: monospace;
          overflow-x: auto;
          white-space: pre-wrap;
          word-break: break-all;
        }
      }
    }

    .tool-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 10px;
    }
  }
}
</style>
```

### 5.7 ChatInputArea.vue — 输入区域

```vue
<!-- src/components/ai-chat/ChatInputArea.vue -->
<template>
  <div class="chat-input-area">
    <!-- 附件预览 -->
    <div v-if="attachments.length > 0" class="attachments-bar">
      <n-tag
        v-for="(file, i) in attachments"
        :key="i"
        closable
        size="small"
        @close="removeAttachment(i)"
      >
        {{ file.name }}
      </n-tag>
    </div>

    <!-- 输入框 -->
    <div class="input-row">
      <n-input
        ref="inputRef"
        v-model:value="inputText"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 6 }"
        :placeholder="placeholder"
        :disabled="disabled"
        @keydown.enter.prevent="handleEnter"
      />

      <div class="input-actions">
        <!-- 附件按钮 -->
        <n-tooltip>
          <template #trigger>
            <n-button text circle size="small" :disabled="disabled">
              <template #icon><n-icon><PaperClipOutlined /></n-icon></template>
            </n-button>
          </template>
          添加附件
        </n-tooltip>

        <!-- 发送/停止按钮 -->
        <n-button
          v-if="!disabled"
          type="primary"
          circle
          size="small"
          :disabled="!canSend"
          @click="handleSend"
        >
          <template #icon><n-icon><SendOutlined /></n-icon></template>
        </n-button>

        <n-button
          v-else
          type="error"
          circle
          size="small"
          @click="$emit('stop')"
        >
          <template #icon><n-icon><StopOutlined /></n-icon></template>
        </n-button>
      </div>
    </div>

    <!-- 底部提示 -->
    <div class="input-footer">
      <span class="hint-text">Enter 发送 / Shift+Enter 换行</span>
      <span class="context-hint" v-if="contextHint">
        <n-icon size="10"><LinkOutlined /></n-icon>
        {{ contextHint }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NInput, NButton, NIcon, NTag, NTooltip } from 'naive-ui'
import {
  SendOutlined, StopOutlined, PaperClipOutlined, LinkOutlined,
} from '@vicons/antd'

const props = defineProps<{
  disabled: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'send', content: string): void
  (e: 'stop'): void
}>()

const inputText = ref('')
const inputRef = ref<InstanceType<typeof NInput>>()
const attachments = ref<File[]>([])
const contextHint = ref('') // 上下文提示

const canSend = computed(() => inputText.value.trim().length > 0)

function handleSend() {
  const content = inputText.value.trim()
  if (!content) return
  emit('send', content)
  inputText.value = ''
}

function handleEnter(e: KeyboardEvent) {
  if (e.shiftKey) {
    // Shift+Enter = 换行（默认行为）
    return
  }
  // Enter = 发送
  handleSend()
}

function removeAttachment(index: number) {
  attachments.value.splice(index, 1)
}
</script>

<style scoped lang="scss">
.chat-input-area {
  border-top: 1px solid var(--border-color);
  padding: 10px 12px;
  flex-shrink: 0;
  background: var(--chat-bg);

  .attachments-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }

  .input-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;

    :deep(.n-input) {
      flex: 1;
      min-width: 0;
    }

    .input-actions {
      display: flex;
      align-items: center;
      gap: 4px;
      flex-shrink: 0;
    }
  }

  .input-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 6px;

    .hint-text {
      font-size: 10px;
      color: var(--text-tertiary);
    }

    .context-hint {
      font-size: 10px;
      color: var(--primary-color);
      display: flex;
      align-items: center;
      gap: 4px;
    }
  }
}
</style>
```

### 5.8 ChatContextBar.vue — 上下文指示器

```vue
<!-- src/components/ai-chat/ChatContextBar.vue -->
<template>
  <div v-if="hasContext" class="chat-context-bar">
    <div class="context-items">
      <n-tag
        v-if="context.projectId"
        size="tiny"
        type="success"
        closable
        @close="$emit('clear-context', 'project')"
      >
        <template #icon><n-icon><FolderOutlined /></n-icon></template>
        {{ projectName || '项目' }}
      </n-tag>

      <n-tag
        v-if="context.flowId"
        size="tiny"
        type="info"
        closable
        @close="$emit('clear-context', 'flow')"
      >
        <template #icon><n-icon><ApartmentOutlined /></n-icon></template>
        {{ flowName || '流程' }}
      </n-tag>

      <n-tag
        v-if="context.taskId"
        size="tiny"
        :type="taskTagType"
        closable
        @close="$emit('clear-context', 'task')"
      >
        <template #icon><n-icon><ExperimentOutlined /></n-icon></template>
        任务 {{ context.taskId.slice(0, 8) }}
        <span v-if="taskStatus" class="status-dot">{{ taskStatus }}</span>
      </n-tag>
    </div>

    <n-tooltip placement="top">
      <template #trigger>
        <n-icon size="12" class="context-info-icon"><InfoCircleOutlined /></n-icon>
      </template>
      AI 助手已自动获取当前页面上下文，可据此提供精准回答
    </n-tooltip>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NTag, NIcon, NTooltip } from 'naive-ui'
import { FolderOutlined, ApartmentOutlined, ExperimentOutlined, InfoCircleOutlined } from '@vicons/antd'
import type { ChatContext } from '@/types/chat'

const props = defineProps<{
  context: ChatContext
  projectName: string | null
  flowName: string | null
  taskStatus: string | undefined
}>()

const emit = defineEmits<{
  (e: 'clear-context', type: 'project' | 'flow' | 'task' | 'all'): void
}>()

const hasContext = computed(() =>
  props.context.projectId || props.context.flowId || props.context.taskId
)

const taskTagType = computed(() => {
  switch (props.taskStatus) {
    case 'completed': return 'success'
    case 'failed': return 'error'
    case 'running': return 'warning'
    default: return 'default'
  }
})
</script>

<style scoped lang="scss">
.chat-context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--context-bar-bg);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;

  .context-items {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;

    .status-dot {
      margin-left: 4px;
      opacity: 0.8;
    }
  }

  .context-info-icon {
    color: var(--text-tertiary);
    cursor: help;
  }
}
</style>
```

### 5.9 AI Agent 内部工具定义

```typescript
// src/types/chat.ts — 工具定义类型

/** Tool Call 结构 */
export interface ToolCall {
  id: string
  type: 'function'
  function: {
    name: string
    arguments: string // JSON 字符串
  }
}

/** 前端可调用的内部 API 工具定义 */
export interface InternalTool {
  name: string
  description: string
  parameters: Record<string, {
    type: string
    description: string
    required?: boolean
    enum?: string[]
  }>
  handler: (args: Record<string, any>) => Promise<any>
}

/** 前端内部工具注册表 */
export const INTERNAL_TOOLS: InternalTool[] = [
  {
    name: 'submit_job',
    description: '提交一个分析任务',
    parameters: {
      flow_id: { type: 'string', description: '流程 ID', required: true },
      project_id: { type: 'string', description: '项目 ID', required: true },
      params: { type: 'object', description: '任务参数', required: true },
      description: { type: 'string', description: '任务描述' },
    },
    handler: async (args) => {
      const { taskApi } = await import('@/api/task')
      return taskApi.submit(args)
    },
  },
  {
    name: 'query_samples',
    description: '查询项目中的样本列表',
    parameters: {
      project_id: { type: 'string', description: '项目 ID', required: true },
    },
    handler: async (args) => {
      const { projectApi } = await import('@/api/project')
      return projectApi.getSamples(args.project_id)
    },
  },
  {
    name: 'list_projects',
    description: '列出当前用户可访问的项目',
    parameters: {
      keyword: { type: 'string', description: '搜索关键词' },
    },
    handler: async (args) => {
      const { projectApi } = await import('@/api/project')
      return projectApi.list(args)
    },
  },
  {
    name: 'get_task_status',
    description: '获取任务的详细状态和进度',
    parameters: {
      task_id: { type: 'string', description: '任务 ID', required: true },
    },
    handler: async (args) => {
      const { taskApi } = await import('@/api/task')
      return taskApi.getDetail(args.task_id)
    },
  },
  {
    name: 'query_flow_params',
    description: '查询流程的参数说明',
    parameters: {
      flow_id: { type: 'string', description: '流程 ID', required: true },
    },
    handler: async (args) => {
      const { flowApi } = await import('@/api/flow')
      return flowApi.getSchema(args.flow_id)
    },
  },
  {
    name: 'preview_result',
    description: '预览结果文件的内容',
    parameters: {
      task_id: { type: 'string', description: '任务 ID', required: true },
      file_path: { type: 'string', description: '文件路径', required: true },
      max_lines: { type: 'integer', description: '最大行数', required: false },
    },
    handler: async (args) => {
      const { taskApi } = await import('@/api/task')
      return taskApi.previewResult(args.task_id, args.file_path, args.max_lines)
    },
  },
]

/** 工具调用确认中间件 */
export async function executeWithConfirmation(
  toolCall: ToolCall,
  onConfirm: () => void,
  onReject: () => void,
): Promise<any> {
  // 所有工具调用都必须经过用户确认
  // 此函数由前端 UI 调用（在用户点击确认按钮后）
  const tool = INTERNAL_TOOLS.find(t => t.name === toolCall.function.name)
  if (!tool) {
    throw new Error(`未知工具: ${toolCall.function.name}`)
  }

  let args: Record<string, any>
  try {
    args = JSON.parse(toolCall.function.arguments)
  } catch {
    throw new Error('工具参数解析失败')
  }

  return tool.handler(args)
}
```

### 5.10 WebSocket 消息处理流程图

```
┌──────────────────┐
│  WebSocket 收到消息 │
└────────┬─────────┘
         │
    ┌────▼────┐
    │ 解析 type  │
    └────┬────┘
         │
    ┌────▼────────────┐
    │ chat.message_chunk │ ──→ 追加到 streamingContent，触发 UI 更新
    └─────────────────┘
         │
    ┌────▼────────────┐
    │ chat.message_end   │ ──→ 组装完整消息，添加到 messages 列表
    └─────────────────┘
         │
    ┌────▼────────────────┐
    │ chat.tool_call_request │ ──→ 渲染 ToolConfirmCard.vue，等待用户确认
    └─────────────────────┘
         │
    ┌────▼────────────────┐
    │ chat.tool_result       │ ──→ 渲染工具执行结果卡片
    └─────────────────────┘
         │
    ┌────▼────────────────┐
    │ chat.mcp_result        │ ──→ 渲染 MCP 工具结果特殊卡片
    └─────────────────────┘
         │
    ┌────▼────┐
    │    error   │ ──→ 渲染错误消息
    └─────────┘
         │
    ┌────▼────┐
    │    pong    │ ──→ 心跳响应（无 UI 操作）
    └─────────┘
```



---

## 6. 暗黑模式实现

### 6.1 Naive UI ConfigProvider 配置

Naive UI 的暗黑模式通过 `ConfigProvider` 的 `theme` 属性控制：

```typescript
// Naive UI 主题切换逻辑
import { darkTheme, lightTheme } from 'naive-ui'

// Dark: 传入 darkTheme 对象
<n-config-provider :theme="darkTheme">

// Light: 传入 null（默认就是亮色）
<n-config-provider :theme="null">
```

已在 `MainLayout.vue`、`AdminLayout.vue`、`BlankLayout.vue` 中通过 `themeStore.naiveTheme` 统一注入。

### 6.2 CSS 变量切换方案

```scss
// src/styles/variables.scss
// ═══════════════════════════════════════════
// 亮色模式（默认）
// ═══════════════════════════════════════════
:root {
  // 主色
  --primary-color: #6366f1;
  --primary-hover: #818cf8;
  --primary-pressed: #4f46e5;

  // 背景
  --bg-base: #ffffff;
  --bg-elevated: #fafafa;
  --content-bg: #f5f5f7;
  --chat-bg: #ffffff;
  --card-bg: #ffffff;
  --hover-bg: rgba(0, 0, 0, 0.04);
  --code-bg: rgba(0, 0, 0, 0.05);
  --code-block-bg: #1e1e2e;
  --context-bar-bg: #fafafa;
  --table-header-bg: #f0f0f0;
  --toolbar-bg: #fafafa;

  // 文字
  --text-primary: #1f2937;
  --text-secondary: #6b7280;
  --text-tertiary: #9ca3af;

  // 边框
  --border-color: #e5e7eb;
  --divider-bg: #f0f0f0;

  // 日志
  --log-bg: #0d1117;

  // 状态色
  --success-color: #10b981;
  --warning-color: #f59e0b;
  --error-color: #ef4444;
  --info-color: #3b82f6;
}

// ═══════════════════════════════════════════
// 暗黑模式
// ═══════════════════════════════════════════
.dark {
  // 主色（保持不变，primary 是品牌色）
  --primary-color: #818cf8;
  --primary-hover: #a5b4fc;
  --primary-pressed: #6366f1;

  // 背景
  --bg-base: #0f0f23;
  --bg-elevated: #1a1a2e;
  --content-bg: #13131f;
  --chat-bg: #16162a;
  --card-bg: #1e1e32;
  --hover-bg: rgba(255, 255, 255, 0.05);
  --code-bg: rgba(255, 255, 255, 0.08);
  --code-block-bg: #13131f;
  --context-bar-bg: #1a1a2e;
  --table-header-bg: #252540;
  --toolbar-bg: #1a1a2e;

  // 文字
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-tertiary: #64748b;

  // 边框
  --border-color: #2e2e4a;
  --divider-bg: #2e2e4a;

  // 日志
  --log-bg: #0a0a14;

  // 状态色（提高暗色下饱和度）
  --success-color: #34d399;
  --warning-color: #fbbf24;
  --error-color: #f87171;
  --info-color: #60a5fa;
}

// ═══════════════════════════════════════════
// 平滑过渡
// ═══════════════════════════════════════════
*, *::before, *::after {
  transition: background-color 0.3s ease,
              border-color 0.3s ease,
              color 0.3s ease;
}

// 排除不需要动画的元素
.no-theme-transition,
.no-theme-transition * {
  transition: none !important;
}
```

### 6.3 ThemeToggle.vue — 主题切换按钮

```vue
<!-- src/components/common/ThemeToggle.vue -->
<template>
  <n-tooltip placement="bottom">
    <template #trigger>
      <n-button text circle size="small" @click="themeStore.toggleTheme()">
        <template #icon>
          <n-icon size="18">
            <SunnyOutlined v-if="themeStore.isDark" />
            <MoonOutlined v-else />
          </n-icon>
        </template>
      </n-button>
    </template>
    {{ themeStore.isDark ? '切换到亮色模式' : '切换到暗黑模式' }}
  </n-tooltip>
</template>

<script setup lang="ts">
import { NButton, NIcon, NTooltip } from 'naive-ui'
import { SunnyOutlined, MoonOutlined } from '@vicons/antd'
import { useThemeStore } from '@/stores/modules/theme'

const themeStore = useThemeStore()
</script>
```

### 6.4 防止 FOUC（Flash of Unstyled Content）

```html
<!-- index.html —— 在 head 中添加内联脚本，在页面渲染前执行 -->
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" href="/favicon.ico" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>OmicsHub</title>

    <!-- 主题防闪烁脚本（必须在最前面执行） -->
    <script>
      (function() {
        const saved = localStorage.getItem('theme_mode') || 'system'
        const isDark = saved === 'dark' || (saved === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
        if (isDark) {
          document.documentElement.classList.add('dark')
        }
      })()
    </script>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

### 6.5 main.ts — 应用入口

```typescript
// src/main.ts
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import pinia from './stores'

// Naive UI 全局样式
import 'naive-ui/es/message/style/css'
import 'naive-ui/es/dialog/style/css'
import 'naive-ui/es/notification/style/css'
import 'naive-ui/es/loading-bar/style/css'

// 全局样式
import '@/styles/variables.scss'
import '@/styles/global.scss'

const app = createApp(App)

app.use(pinia)
app.use(router)

app.mount('#app')
```

---

## 7. 文件目录结构总览

### 7.1 完整目录树

```
src/
├── App.vue                          # 根组件（仅挂载 RouterView）
├── main.ts                          # 入口
├── env.d.ts                         # 环境类型声明
│
├── api/                             # API 请求层
│   ├── request.ts                   # Axios 封装（拦截器、错误处理）
│   ├── auth.ts                      # 认证 API
│   ├── task.ts                      # 任务 API
│   ├── flow.ts                      # 流程 API
│   ├── project.ts                   # 项目 API
│   ├── chat.ts                      # AI 对话 API
│   ├── mcp.ts                       # MCP API
│   └── types.ts                     # API 类型
│
├── assets/                          # 静态资源
│   ├── logo.svg
│   └── icons/
│
├── components/                      # 组件
│   ├── ai-chat/                     # AI 对话面板
│   │   ├── AIChatPanel.vue          # 主面板容器
│   │   ├── AIChatFab.vue            # 折叠浮动按钮
│   │   ├── ChatHeader.vue           # 面板头部
│   │   ├── ChatContextBar.vue       # 上下文指示器
│   │   ├── ChatMessageList.vue      # 消息列表
│   │   ├── ChatMessageUser.vue      # 用户消息
│   │   ├── ChatMessageAssistant.vue # AI 消息（Markdown）
│   │   ├── ChatMessageToolCall.vue  # 工具调用确认卡片
│   │   ├── ChatMessageToolResult.vue# 工具结果卡片
│   │   ├── ChatMessageMCPResult.vue # MCP 结果卡片
│   │   ├── ChatInputArea.vue        # 输入区域
│   │   ├── ChatQuickActions.vue     # 快捷操作
│   │   ├── ChatWelcome.vue          # 欢迎界面
│   │   ├── TypingIndicator.vue      # 输入中动画
│   │   └── SessionDrawer.vue        # 会话列表面板
│   │
│   ├── common/                      # 通用组件
│   │   ├── ThemeToggle.vue          # 主题切换
│   │   ├── StatCard.vue             # 统计卡片
│   │   └── EmptyState.vue           # 空状态
│   │
│   ├── dashboard/                   # 仪表盘
│   │   ├── StatCard.vue
│   │   └── QuickStartItem.vue
│   │
│   ├── dynamic-form/                # 动态表单（核心）
│   │   ├── DynamicForm.vue          # 动态表单主组件
│   │   ├── FormFieldRenderer.vue    # 字段渲染分发器
│   │   ├── ConditionRenderer.vue    # 条件渲染控制器
│   │   ├── GroupRepeater.vue        # 可重复组
│   │   ├── SectionCollapsible.vue   # 折叠区域
│   │   ├── validation.ts            # 校验规则构建
│   │   ├── utils.ts                 # 工具函数
│   │   └── fields/                  # 具体字段组件
│   │       ├── StringField.vue
│   │       ├── TextField.vue
│   │       ├── NumberField.vue
│   │       ├── BooleanField.vue
│   │       ├── SelectField.vue
│   │       ├── MultiSelectField.vue
│   │       ├── RadioField.vue
│   │       ├── CheckboxField.vue
│   │       ├── FileField.vue
│   │       ├── FileUploadField.vue
│   │       ├── SampleField.vue
│   │       ├── SampleSheetField.vue
│   │       ├── RangeField.vue
│   │       ├── ArrayField.vue
│   │       ├── RefField.vue
│   │       ├── GroupField.vue
│   │       ├── DividerField.vue
│   │       └── InfoField.vue
│   │
│   ├── flow/                        # 流程市场
│   │   ├── FlowCard.vue             # 流程卡片
│   │   └── FlowDetailModal.vue      # 流程详情弹窗
│   │
│   ├── layout/                      # 布局组件
│   │   ├── AppSidebar.vue           # 左侧导航
│   │   ├── AppHeader.vue            # 顶部 Header
│   │   ├── AppBreadcrumb.vue        # 面包屑
│   │   ├── UserDropdown.vue         # 用户下拉菜单
│   │   └── NotificationBell.vue     # 通知铃铛
│   │
│   ├── project/                     # 项目
│   │   ├── CreateProjectModal.vue   # 创建项目弹窗
│   │   ├── FileManager.vue          # 文件管理器
│   │   └── SampleTable.vue          # 样本表
│   │
│   └── task/                        # 任务
│       ├── TaskTableLite.vue        # 精简任务表格
│       ├── submit/                  # 任务提交
│       │   ├── FlowSelector.vue     # 流程选择器
│       │   ├── ProjectSelector.vue  # 项目选择器
│       │   └── TaskSubmitPreview.vue# 提交预览
│       ├── detail/                  # 任务详情
│       │   ├── TaskDetailHeader.vue # 任务头部
│       │   ├── TaskProgressBar.vue  # 进度条
│       │   ├── TaskOverviewTab.vue  # 概览标签
│       │   ├── TaskLogViewer.vue    # 日志查看器
│       │   ├── TaskResultViewer.vue # 结果查看器
│       │   ├── TaskParamsTab.vue    # 参数标签
│       │   └── previews/            # 预览组件
│       │       ├── CsvTablePreview.vue
│       │       ├── ImagePreview.vue
│       │       ├── HtmlReportPreview.vue
│       │       └── TextPreview.vue
│       └── detail.ts                # 详情页类型
│
├── composables/                     # 组合式函数
│   ├── useTaskLogWebSocket.ts       # 任务日志 WebSocket
│   ├── useTaskResult.ts             # 任务结果获取
│   ├── useChatWebSocket.ts          # 聊天 WebSocket
│   ├── useTheme.ts                  # 主题 Hook
│   └── usePermission.ts             # 权限 Hook
│
├── layouts/                         # 布局
│   ├── BlankLayout.vue              # 空布局（登录/注册）
│   ├── MainLayout.vue               # 主布局（工作区 + AI 面板）
│   └── AdminLayout.vue              # 管理后台布局
│
├── router/                          # 路由
│   ├── index.ts                     # 路由实例
│   ├── routes.ts                    # 路由表定义
│   ├── guard.ts                     # 路由守卫
│   └── types.ts                     # 路由类型扩展
│
├── stores/                          # Pinia 状态管理
│   ├── index.ts                     # Pinia 实例
│   └── modules/
│       ├── auth.ts                  # 认证
│       ├── user.ts                  # 用户
│       ├── project.ts               # 项目
│       ├── flow.ts                  # 流程
│       ├── task.ts                  # 任务
│       ├── chat.ts                  # AI 对话
│       ├── mcp.ts                   # MCP
│       ├── notification.ts          # 通知
│       ├── theme.ts                 # 主题
│       └── tab.ts                   # 标签页
│
├── styles/                          # 样式
│   ├── variables.scss               # CSS 变量
│   ├── global.scss                  # 全局样式
│   ├── naive-overrides.scss         # Naive UI 样式覆盖
│   └── markdown.scss                # Markdown 渲染样式
│
├── types/                           # 全局类型
│   ├── auth.ts
│   ├── task.ts
│   ├── flow.ts
│   ├── project.ts
│   ├── chat.ts
│   ├── mcp.ts
│   └── common.ts
│
├── utils/                           # 工具函数
│   ├── time.ts                      # 时间格式化
│   ├── ansi.ts                      # ANSI 颜色解析
│   ├── naiveMessage.ts             # Naive UI message 封装
│   ├── validators.ts               # 表单校验
│   └── file.ts                     # 文件操作
│
└── views/                           # 页面视图
    ├── auth/                        # 认证
    │   ├── LoginView.vue
    │   └── RegisterView.vue
    ├── dashboard/                   # 仪表盘
    │   └── DashboardView.vue
    ├── project/                     # 项目
    │   ├── ProjectsView.vue
    │   ├── ProjectDetailView.vue
    │   ├── ProjectSamplesView.vue
    │   └── ProjectFilesView.vue
    ├── flow/                        # 流程市场
    │   ├── FlowMarketView.vue
    │   └── FlowDetailView.vue
    ├── task/                        # 任务
    │   ├── TaskListView.vue
    │   ├── TaskSubmitView.vue
    │   └── TaskDetailView.vue
    ├── admin/                       # 管理后台
    │   ├── AdminFlowManager.vue
    │   ├── AdminUserManager.vue
    │   ├── AdminMCPManager.vue
    │   └── AdminSystemSettings.vue
    ├── profile/                     # 个人设置
    │   └── ProfileView.vue
    └── error/                       # 错误页
        └── NotFoundView.vue
```

### 7.2 组件依赖关系图

```
App.vue
  └─ <router-view>
      ├─ BlankLayout
      │   └─ LoginView / RegisterView / NotFoundView
      │
      ├─ MainLayout
      │   ├─ AppSidebar
      │   ├─ AppHeader (ThemeToggle, UserDropdown, NotificationBell)
      │   ├─ AppBreadcrumb
      │   ├─ <router-view>
      │   │   ├─ DashboardView (StatCard, QuickStartItem, TaskTableLite)
      │   │   ├─ ProjectsView (CreateProjectModal)
      │   │   ├─ ProjectDetailView (SampleTable, FileManager)
      │   │   ├─ FlowMarketView (FlowCard)
      │   │   ├─ TaskListView (TaskTableLite)
      │   │   ├─ TaskSubmitView ── DynamicForm ── FormFieldRenderer
      │   │   │                      │               └─ *Field.vue x 18
      │   │   │                      ├─ ConditionRenderer
      │   │   │                      ├─ GroupRepeater
      │   │   │                      └─ SectionCollapsible
      │   │   └─ TaskDetailView
      │   │       ├─ TaskDetailHeader
      │   │       ├─ TaskProgressBar
      │   │       ├─ TaskOverviewTab
      │   │       ├─ TaskLogViewer (WebSocket)
      │   │       ├─ TaskResultViewer
      │   │       │   ├─ CsvTablePreview
      │   │       │   ├─ ImagePreview
      │   │       │   ├─ HtmlReportPreview
      │   │       │   └─ TextPreview
      │   │       └─ TaskParamsTab
      │   │
      │   ├─ AIChatPanel
      │   │   ├─ ChatHeader
      │   │   ├─ ChatContextBar
      │   │   ├─ ChatMessageList
      │   │   │   ├─ ChatWelcome
      │   │   │   ├─ ChatMessageUser
      │   │   │   ├─ ChatMessageAssistant (Markdown)
      │   │   │   ├─ ChatMessageToolCall (确认卡片)
      │   │   │   ├─ ChatMessageToolResult
      │   │   │   ├─ ChatMessageMCPResult
      │   │   │   └─ TypingIndicator
      │   │   ├─ ChatQuickActions
      │   │   ├─ ChatInputArea
      │   │   └─ SessionDrawer
      │   │
      │   └─ AIChatFab (折叠时)
      │
      └─ AdminLayout
          ├─ AdminSidebar (menu)
          └─ <router-view>
              ├─ AdminFlowManager
              ├─ AdminUserManager
              ├─ AdminMCPManager
              └─ AdminSystemSettings
```

---

## 附录 A：技术决策记录

### A.1 为什么选择 Naive UI 为主？

| 特性 | Naive UI | Element Plus | 结论 |
|------|----------|--------------|------|
| Vue 3 原生支持 | 优 | 良 | Naive 从 0 开始为 Vue 3 设计 |
| TypeScript 体验 | 优 | 良 | Naive 的类型推断更完善 |
| 暗黑模式 | 内置 ConfigProvider | 需手动配置 | Naive 一行代码切换 |
| 样式定制 | CSS Variables + Theme Editor | SCSS 变量 | Naive 更灵活 |
| 组件丰富度 | 良 | 优 | Element Plus 组件更多，但 Naive 覆盖核心场景 |
| 体积 | 较小（tree-shaking） | 较大 | Naive 按需引入更轻量 |
| 社区生态 | 国内活跃 | 全球更大 | 两者都足够 |

**决策**：以 Naive UI 为主，仅在 Naive UI 不满足需求时使用 Element Plus 补充（如 Complex Table、Cascader 等）。

### A.2 WebSocket 连接策略

| 页面 | 连接时机 | 断开时机 | 说明 |
|------|----------|----------|------|
| AI 对话面板 | 面板展开时 | 面板折叠时 | 用户不需要 AI 时不浪费连接 |
| 任务日志 | 进入任务详情页时 | 离开页面时 | 仅运行中任务需要实时日志 |
| 全局通知 | 登录后 | 登出时 | 全局推送，始终保持 |

### A.3 状态管理策略

| Store 模块 | 数据持久化 | 实时同步 | 说明 |
|-----------|-----------|---------|------|
| auth | localStorage（token） | 无 | token 需持久化 |
| theme | localStorage | 无 | 主题偏好持久化 |
| chat | 无（纯内存） | WebSocket | 会话数据后端存储 |
| task | 无（纯内存） | 轮询 + WS | 每次进入页面重新获取 |
| flow | 无（纯内存） | 无 | Schema 有内存缓存 |
| project | 无（纯内存） | 无 | 每次获取最新列表 |

---

## 附录 B：关键接口类型定义

```typescript
// ═══════════════════════════════════════════
// src/types/flow.ts — 流程相关类型
// ═══════════════════════════════════════════

export interface FlowSummary {
  id: string
  name: string
  description?: string
  category: string
  version: string
  use_count: number
  icon?: string
  created_at: string
}

export interface Flow extends FlowSummary {
  yaml_content: string
  author: string
  params_schema: FlowSchema
  input_types: string[]
  output_types: string[]
}

export interface FlowSchema {
  title: string
  description?: string
  sections: FlowSection[]
}

export interface FlowSection {
  key: string
  title: string
  description?: string
  collapsed?: boolean
  repeatable?: boolean
  fields: FormField[]
}

export interface FormField {
  key: string
  label: string
  type: string
  description?: string
  required?: boolean
  default?: any
  options?: Array<{ label: string; value: any }>
  min?: number
  max?: number
  step?: number
  placeholder?: string
  // 条件渲染
  condition?: {
    field: string
    operator: 'eq' | 'ne' | 'gt' | 'lt' | 'contains' | 'in'
    value: any
  }
  // 验证规则
  validation?: {
    pattern?: string
    minLength?: number
    maxLength?: number
    custom?: string
  }
}

// ═══════════════════════════════════════════
// src/types/task.ts — 任务相关类型
// ═══════════════════════════════════════════

export type TaskStatus =
  | 'pending' | 'queued' | 'running'
  | 'completed' | 'failed' | 'cancelled' | 'cancelling'

export interface Task {
  id: string
  flow_id: string
  project_id: string
  status: TaskStatus
  progress: number          // 0-100
  current_step?: string
  total_steps?: number
  params: Record<string, any>
  description?: string
  output_dir?: string
  error_message?: string
  created_at: string
  started_at?: string
  finished_at?: string
  created_by: string
}

export interface TaskStats {
  runningTasks: number
  completedTasks: number
  failedTasks: number
  queuedTasks: number
}

// ═══════════════════════════════════════════
// src/types/chat.ts — AI 对话相关类型
// ═══════════════════════════════════════════

export interface ChatSession {
  id: string
  title: string
  model: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result' | 'mcp_result'
  content: string
  tool_calls?: ToolCall[]
  tool_call_id?: string
  mcp_server?: string
  tool_name?: string
  result?: any
  is_error?: boolean
  is_streaming?: boolean
  created_at: string
}

export interface ChatContext {
  page: string
  routeParams: Record<string, string>
  routeQuery: Record<string, string>
  projectId: string | null
  flowId: string | null
  taskId: string | null
}

export interface WebSocketMessage {
  type: string
  [key: string]: any
}

export interface AIModelConfig {
  id: string
  name: string
  description?: string
  max_tokens: number
}

// ═══════════════════════════════════════════
// src/types/project.ts — 项目相关类型
// ═══════════════════════════════════════════

export interface Project {
  id: string
  name: string
  description?: string
  sample_count?: number
  task_count?: number
  created_by: string
  created_at: string
}

export interface Sample {
  id: string
  project_id: string
  name: string
  type: string
  metadata: Record<string, any>
  file_path?: string
  created_at: string
}

// ═══════════════════════════════════════════
// src/types/mcp.ts — MCP 相关类型
// ═══════════════════════════════════════════

export interface MCPServer {
  id: string
  name: string
  url: string
  description?: string
  icon?: string
  status: 'active' | 'inactive' | 'error'
  tool_count: number
  created_at: string
}

export interface MCPTool {
  name: string
  server_id: string
  server_name: string
  description: string
  parameters: Record<string, any>
  available: boolean
}
```

---

> **本文档结束** — 以上涵盖了 OmicsHub 前端架构的完整路由设计、三种布局系统、核心页面组件（动态表单、任务详情/日志/结果）、9 个 Pinia Store 模块、AI 对话面板的完整组件树与交互协议、以及暗黑模式实现方案。

