import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useModulesStore } from '@/stores/modules'

// 首次部署配置状态缓存
let setupChecked = false
let setupRequired = false

export function resetSetupCheck() {
  setupChecked = false
  setupRequired = false
}

export function markSetupComplete() {
  setupChecked = true
  setupRequired = false
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', requiresAuth: false }
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { title: '注册', requiresAuth: false }
  },
  {
    path: '/setup',
    name: 'setup',
    component: () => import('@/views/SetupView.vue'),
    meta: { title: '首次配置', requiresAuth: false }
  },
  {
    path: '/studio/shared/:token',
    name: 'studio-shared',
    component: () => import('@/views/SharedStudioView.vue'),
    meta: { title: 'OmicStudio 只读分享', requiresAuth: false }
  },
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    children: [
      {
        path: '',
        name: 'home',
        component: () => import('@/views/HomeView.vue'),
        meta: { title: '首页', requiresAuth: true }
      },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '仪表板', requiresAuth: true }
      },
      {
        path: 'flows',
        name: 'flows',
        component: () => import('@/views/FlowsView.vue'),
        meta: { title: '分析中心', requiresAuth: true }
      },
      {
        path: 'flows/:flowId/submit',
        name: 'flow-submit',
        component: () => import('@/views/FlowSubmitView.vue'),
        meta: { title: '提交任务', requiresAuth: true }
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('@/views/TasksView.vue'),
        meta: { title: '任务管理', requiresAuth: true }
      },
      {
        path: 'workflow-monitor',
        name: 'workflow-monitor',
        component: () => import('@/views/WorkflowMonitorView.vue'),
        meta: { title: '流程监控', requiresAuth: true }
      },
      {
        path: 'tasks/:taskId',
        name: 'task-detail',
        component: () => import('@/views/TaskDetailView.vue'),
        meta: { title: '任务详情', requiresAuth: true }
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/ReportsView.vue'),
        meta: { title: '结果报告中心', requiresAuth: true }
      },
      {
        path: 'files',
        name: 'files',
        component: () => import('@/views/FilesView.vue'),
        meta: { title: '文件管理', requiresAuth: true, fullscreen: true }
      },
      {
        path: 'downloads',
        name: 'downloads',
        component: () => import('@/views/DownloadsView.vue'),
        meta: { title: '数据下载', requiresAuth: true }
      },
      {
        path: 'ai',
        name: 'ai',
        component: () => import('@/views/AIChatView.vue'),
        meta: { title: 'AI 助手', requiresAuth: true, fullscreen: true }
      },
      {
        path: 'agent-capabilities',
        name: 'agent-capabilities',
        component: () => import('@/views/AgentCapabilitiesView.vue'),
        meta: { title: '我的 Agent 能力', requiresAuth: true }
      },
      {
        path: 'agent-teams/room',
        name: 'agent-teams-room',
        component: () => import('@/views/AgentTeamsRoomView.vue'),
        meta: { title: '团队协作室', requiresAuth: true, fullscreen: true, autoCollapseSidebar: true }
      },
      {
        path: 'agent-teams/cases/:caseId',
        name: 'agent-teams-case',
        component: () => import('@/views/AgentTeamsCaseView.vue'),
        meta: { title: '协作案例', requiresAuth: true }
      },
      {
        path: 'studio/:sessionId?',
        name: 'studio',
        component: () => import('@/views/StudioView.vue'),
        meta: { title: 'AI 工作台', requiresAuth: true, fullscreen: true }
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('@/views/ProfileView.vue'),
        meta: { title: '个人中心', requiresAuth: true }
      },
      {
        path: 'profile/memories',
        name: 'profile-memories',
        component: () => import('@/views/MemoryView.vue'),
        meta: { title: '我的记忆', requiresAuth: true }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '设置', requiresAuth: true }
      },
      {
        path: 'cookies',
        name: 'cookies',
        component: () => import('@/views/CookieAccountView.vue'),
        meta: { title: '饼干账户', requiresAuth: true }
      },
      {
        path: 'about',
        name: 'about',
        component: () => import('@/views/AboutView.vue'),
        meta: { title: '关于', requiresAuth: true, autoCollapseSidebar: true }
      },
      {
        path: 'knowledge',
        name: 'knowledge',
        component: () => import('@/views/KnowledgeView.vue'),
        meta: { title: '实验室知识库', requiresAuth: true, fullscreen: true, autoCollapseSidebar: true }
      },
      {
        path: 'knowledge/:docId',
        name: 'knowledge-doc',
        component: () => import('@/views/KnowledgeView.vue'),
        meta: { title: '实验室知识库', requiresAuth: true, fullscreen: true, autoCollapseSidebar: true }
      },
      {
        path: 'sandbox',
        redirect: '/tools/terminal'
      },
      {
        path: 'tools',
        name: 'tools',
        component: () => import('@/views/BioTools/ToolsHubView.vue'),
        meta: { title: '生信工具箱', requiresAuth: true }
      },
      {
        path: 'tools/fastq-qc',
        name: 'tools-fastq-qc',
        component: () => import('@/views/BioTools/FastqQCView.vue'),
        meta: { title: 'FASTQ 质控', requiresAuth: true }
      },
      {
        path: 'tools/jbrowse',
        name: 'tools-jbrowse',
        component: () => import('@/views/BioTools/JBrowseViewer.vue'),
        meta: { title: '基因组浏览器', requiresAuth: true, fullscreen: true }
      },
      {
        path: 'tools/blast',
        name: 'tools-blast',
        component: () => import('@/views/BioTools/BlastSearchView.vue'),
        meta: { title: '序列检索', requiresAuth: true }
      },
      {
        path: 'tools/blast/tasks',
        name: 'tools-blast-tasks',
        component: () => import('@/views/BioTools/BlastTaskHistoryView.vue'),
        meta: { title: 'BLAST 任务中心', requiresAuth: true }
      },
      {
        path: 'tools/plot',
        name: 'tools-plot',
        component: () => import('@/views/BioTools/PlotWorkshopView.vue'),
        meta: { title: '绘图工坊', requiresAuth: true }
      },
      {
        path: 'tools/volcano',
        name: 'tools-volcano',
        component: () => import('@/views/BioTools/VolcanoPlotView.vue'),
        meta: { title: '火山图绘制', requiresAuth: true }
      },
      {
        path: 'tools/kegg-enrichment',
        name: 'tools-kegg-enrichment',
        component: () => import('@/views/BioTools/KeggEnrichmentView.vue'),
        meta: { title: 'GO / KEGG 富集分析', requiresAuth: true }
      },
      {
        path: 'tools/gsea-enrichment',
        name: 'tools-gsea-enrichment',
        component: () => import('@/views/BioTools/GseaEnrichmentView.vue'),
        meta: { title: 'GSEA 富集分析', requiresAuth: true }
      },
      {
        path: 'tools/synteny',
        name: 'tools-synteny',
        component: () => import('@/views/BioTools/SyntenyView.vue'),
        meta: { title: '基因组共线性分析', requiresAuth: true }
      },
      {
        path: 'tools/deg-analysis',
        name: 'tools-deg-analysis',
        component: () => import('@/views/BioTools/DegAnalysisView.vue'),
        meta: { title: 'DEG 差异表达分析', requiresAuth: true }
      },
      {
        path: 'tools/seq-manipulator',
        name: 'tools-seq-manipulator',
        component: () => import('@/views/BioTools/SeqManipulatorView.vue'),
        meta: { title: '序列魔术师', requiresAuth: true }
      },
      {
        path: 'tools/primer-forge',
        name: 'tools-primer-forge',
        component: () => import('@/views/BioTools/PrimerForgeView.vue'),
        meta: { title: 'PrimerForge 引物锻造工坊', requiresAuth: true }
      },
      {
        path: 'tools/format-converter',
        name: 'tools-format-converter',
        component: () => import('@/views/BioTools/FormatConverterView.vue'),
        meta: { title: '格式轻量转换器', requiresAuth: true }
      },
      {
        path: 'tools/id-converter',
        name: 'tools-id-converter',
        component: () => import('@/views/BioTools/IdConverterView.vue'),
        meta: { title: 'ID 转换器', requiresAuth: true }
      },
      {
        path: 'tools/wetlab-calculators',
        name: 'tools-wetlab-calculators',
        component: () => import('@/views/BioTools/WetLabCalculatorsView.vue'),
        meta: { title: '湿实验计算器', requiresAuth: true }
      },
      {
        path: 'tools/venn-upset',
        name: 'tools-venn-upset',
        component: () => import('@/views/BioTools/VennUpsetView.vue'),
        meta: { title: '韦恩图 / UpSet 图', requiresAuth: true }
      },
      {
        path: 'tools/terminal',
        name: 'tools-terminal',
        component: () => import('@/views/BioTools/TerminalView.vue'),
        meta: { title: '云端沙盒终端', requiresAuth: true, fullscreen: true }
      },
      {
        path: 'tools/phylogenetic-tree',
        name: 'tools-phylogenetic-tree',
        component: () => import('@/views/BioTools/PhylogeneticTreeView.vue'),
        meta: { title: '系统发育树构建', requiresAuth: true }
      },
      {
        path: 'tools/gene-expression-explorer',
        name: 'tools-gene-expression-explorer',
        component: () => import('@/views/BioTools/GeneExpressionExplorerView.vue'),
        meta: { title: '基因表达矩阵 Explorer', requiresAuth: true }
      },
      {
        path: 'tools/manhattan',
        name: 'tools-manhattan',
        component: () => import('@/views/BioTools/ManhattanPlotView.vue'),
        meta: { title: '曼哈顿图绘制', requiresAuth: true }
      },
      {
        path: 'database',
        name: 'database',
        component: () => import('@/views/ReferenceGenomesView.vue'),
        meta: { title: '数据库', requiresAuth: true }
      },
      {
        path: 'database/:id',
        name: 'database-detail',
        component: () => import('@/views/ReferenceGenomeDetailView.vue'),
        meta: { title: '数据库详情', requiresAuth: true }
      },
      {
        path: 'reference-genomes',
        name: 'reference-genomes',
        component: () => import('@/views/ReferenceGenomesView.vue'),
        meta: { title: '数据库', requiresAuth: true }
      },
      {
        path: 'reference-genomes/:id',
        name: 'reference-genome-detail',
        component: () => import('@/views/ReferenceGenomeDetailView.vue'),
        meta: { title: '数据库详情', requiresAuth: true }
      },
      {
        path: 'admin/cookies/accounts',
        name: 'admin-cookies-accounts',
        redirect: { name: 'admin-biscuits-accounts' },
      },
      {
        path: 'admin/cookies/transactions',
        name: 'admin-cookies-transactions',
        component: () => import('@/views/AdminCookieTransactionsView.vue'),
        meta: { title: '交易流水审计', requiresAuth: true }
      },
      {
        path: 'admin/cookies/pricing',
        name: 'admin-cookies-pricing',
        redirect: { name: 'admin-biscuits-pricing' },
      },
      {
        path: 'admin/users',
        name: 'admin-users',
        component: () => import('@/views/AdminUserManagementView.vue'),
        meta: { title: '用户管理', requiresAuth: true }
      },
      {
        path: 'admin/memory',
        name: 'admin-memory',
        component: () => import('@/views/AdminMemoryView.vue'),
        meta: { title: '记忆审计', requiresAuth: true }
      },
      {
        path: 'admin/session-logs',
        name: 'admin-session-logs',
        component: () => import('@/views/AdminSessionLogsView.vue'),
        meta: { title: '会话日志排查', requiresAuth: true }
      },
      {
        path: 'admin/ai-metrics',
        name: 'admin-ai-metrics',
        component: () => import('@/views/AdminAiMetricsView.vue'),
        meta: { title: 'AI 指标仪表盘', requiresAuth: true }
      },
      {
        path: 'admin/home-quick-entries',
        name: 'admin-home-quick-entries',
        component: () => import('@/views/AdminHomeQuickEntriesView.vue'),
        meta: { title: '首页入口管理', requiresAuth: true }
      },
      {
        path: 'admin/biscuits/accounts',
        name: 'admin-biscuits-accounts',
        component: () => import('@/views/AdminBiscuitsCenterView.vue'),
        meta: { title: '饼干中心 · 账户管理', requiresAuth: true }
      },
      {
        path: 'admin/biscuits/pricing',
        name: 'admin-biscuits-pricing',
        component: () => import('@/views/AdminBiscuitsCenterView.vue'),
        meta: { title: '饼干中心 · 定价管理', requiresAuth: true }
      },
      {
        path: 'admin/ai-providers',
        name: 'admin-ai-providers',
        redirect: { name: 'admin-ai-config-providers' },
      },
      {
        path: 'admin/ai-resources',
        name: 'admin-ai-resources',
        redirect: { name: 'admin-ai-config-resources' },
      },
      {
        path: 'admin/ai-config/providers',
        name: 'admin-ai-config-providers',
        component: () => import('@/views/AdminAIConfigCenterView.vue'),
        meta: { title: 'AI 配置中心 · 模型配置', requiresAuth: true }
      },
      {
        path: 'admin/ai-config/resources',
        name: 'admin-ai-config-resources',
        component: () => import('@/views/AdminAIConfigCenterView.vue'),
        meta: { title: 'AI 配置中心 · 资源中心', requiresAuth: true }
      },
      {
        path: 'admin/announcements',
        name: 'admin-announcements',
        component: () => import('@/views/AdminAnnouncementsView.vue'),
        meta: { title: '通知公告', requiresAuth: true }
      },
      {
        path: 'admin/terminals',
        name: 'admin-terminals',
        component: () => import('@/views/AdminTerminalManagementView.vue'),
        meta: { title: '沙盒终端管理', requiresAuth: true }
      },
      {
        path: 'admin/blast-databases',
        name: 'admin-blast-databases',
        component: () => import('@/views/AdminBlastDatabasesView.vue'),
        meta: { title: 'BLAST 数据库管理', requiresAuth: true }
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '404', requiresAuth: false }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()
  const isLoggedIn = !!localStorage.getItem('access_token')

  // 首次部署：检查是否已配置 root 管理员
  if (!setupChecked) {
    try {
      setupRequired = await authStore.checkSetupRequired()
      setupChecked = true
    } catch {
      // 接口失败时不阻塞用户，允许继续访问
      setupRequired = false
      setupChecked = true
    }
  }

  if (setupRequired && to.name !== 'setup') {
    next('/setup')
    return
  }

  if (!setupRequired && to.name === 'setup') {
    next(isLoggedIn ? '/' : '/login')
    return
  }

  if (to.meta.requiresAuth && !isLoggedIn) {
    // 需要登录但未登录（含 token 被清除的情况）
    next({ path: '/login', query: { redirect: to.fullPath } })
  } else if ((to.name === 'login' || to.name === 'register') && isLoggedIn) {
    // 已登录且访问登录/注册页
    next('/')
  } else {
    // 已登录访问受限页面：确保用户信息与模块注册表就绪，
    // 保证 DefaultLayout 的模块锁定判断首跳即生效（拉取失败不阻塞导航）
    if (isLoggedIn && to.meta.requiresAuth) {
      if (!authStore.user) {
        await authStore.fetchUser().catch(() => {})
      }
      // ensureLoaded 内部已捕获异常，永不 reject
      await useModulesStore().ensureLoaded()
    }
    // 设置页面标题
    if (to.meta.title) {
      document.title = `${to.meta.title} - OmicHub`
    } else {
      document.title = 'OmicHub'
    }
    next()
  }
})

export default router
