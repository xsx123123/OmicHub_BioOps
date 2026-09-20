<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NCard, NDataTable, NEmpty, NIcon, NInput, NSkeleton, NSpin, useMessage,
} from 'naive-ui'
import { AddOutline, FolderOpenOutline, RefreshOutline, SearchOutline } from '@vicons/ionicons5'
import type { DataTableColumns } from 'naive-ui'
import PageHeader from '@/components/PageHeader.vue'
import CreateProjectModal from '@/components/project/CreateProjectModal.vue'
import { projectsApi, type ProjectItem } from '@/api/projects'

const router = useRouter()
const message = useMessage()

/** 首次进入用 NSkeleton；已加载后的局部刷新（新建成功回拉）用 NSpin（§5.4） */
const initialLoading = ref(true)
const refreshing = ref(false)
const projects = ref<ProjectItem[]>([])
const showCreate = ref(false)
const searchQuery = ref('')

const filteredProjects = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  if (!query) return projects.value
  return projects.value.filter((project) =>
    [project.name, project.slug, project.customer, project.description]
      .filter(Boolean)
      .some((value) => String(value).toLocaleLowerCase().includes(query)),
  )
})
const projectsWithDescription = computed(() => projects.value.filter((project) => project.description?.trim()).length)
const latestProject = computed(() => [...projects.value].sort((a, b) => {
  return new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime()
})[0])

function formatDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '—'
}

function mutedText(value: string | null | undefined) {
  return value
    ? value
    : h('span', { class: 'cell-muted' }, '—')
}

function openProject(row: ProjectItem) {
  router.push({ name: 'project-detail', params: { projectId: row.id } })
}

function shouldShowProjectSlug(row: ProjectItem) {
  return Boolean(row.slug && row.slug.trim() !== row.name.trim())
}

// 列全部固定宽（§33.2③），scroll-x = 列宽之和；长文本列省略 + tooltip（§5.4）
const columns: DataTableColumns<ProjectItem> = [
  {
    title: '项目名称',
    key: 'name',
    width: 240,
    ellipsis: { tooltip: true },
    render(row) {
      return h('div', { class: 'project-name-cell' }, [
        h('span', { class: 'project-name-icon' }, [h(NIcon, { size: 17 }, { default: () => h(FolderOpenOutline) })]),
        h('div', { class: 'project-name-copy' }, [
          h(NButton, { text: true, type: 'primary', class: 'project-name-link', onClick: () => openProject(row) }, { default: () => row.name }),
          shouldShowProjectSlug(row) ? h('span', { class: 'project-slug' }, row.slug) : null,
        ]),
      ])
    },
  },
  {
    title: '客户',
    key: 'customer',
    width: 160,
    align: 'center',
    ellipsis: { tooltip: true },
    render: (row) => mutedText(row.customer),
  },
  {
    title: '描述',
    key: 'description',
    width: 320,
    ellipsis: { tooltip: true },
    render: (row) => mutedText(row.description),
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 180,
    align: 'center',
    render: (row) => formatDate(row.created_at),
  },
  {
    title: '操作',
    key: 'actions',
    width: 110,
    align: 'center',
    render(row) {
      return h(
        NButton,
        { size: 'small', secondary: true, onClick: () => openProject(row) },
        { default: () => '查看详情' },
      )
    },
  },
]
const tableScrollX = columns.reduce((sum, col) => sum + (Number(col.width) || 0), 0)

async function loadProjects() {
  if (initialLoading.value) {
    // 首载
  } else {
    refreshing.value = true
  }
  try {
    projects.value = await projectsApi.listProjects()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载项目列表失败')
  } finally {
    initialLoading.value = false
    refreshing.value = false
  }
}

onMounted(loadProjects)
</script>

<template>
  <div class="projects-view">
    <PageHeader title="项目管理" subtitle="按项目浏览历史会话与分析运行记录">
      <template #actions>
        <NButton secondary :loading="refreshing" @click="loadProjects">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          刷新
        </NButton>
        <NButton type="primary" @click="showCreate = true">
          <template #icon><NIcon><AddOutline /></NIcon></template>
          新建项目
        </NButton>
      </template>
    </PageHeader>
    <CreateProjectModal v-model:show="showCreate" @created="loadProjects" />

    <section class="projects-overview" aria-label="项目概览">
      <div class="overview-intro">
        <div class="overview-icon"><NIcon :size="20"><FolderOpenOutline /></NIcon></div>
        <div>
          <span class="overview-eyebrow">PROJECT WORKSPACE</span>
          <h2>让每次分析都有清晰归属</h2>
          <p>项目会自动归集相关会话、分析运行与交付物，方便团队持续推进。</p>
        </div>
      </div>
      <div class="overview-metrics" aria-label="项目统计">
        <div class="overview-metric">
          <span class="metric-label">全部项目</span>
          <strong>{{ projects.length }}</strong>
          <span class="metric-hint">当前账号可见</span>
        </div>
        <div class="overview-metric">
          <span class="metric-label">已补充描述</span>
          <strong>{{ projectsWithDescription }}</strong>
          <span class="metric-hint">便于快速识别</span>
        </div>
        <div class="overview-metric overview-metric--latest">
          <span class="metric-label">最近更新</span>
          <strong>{{ latestProject?.name || '暂无项目' }}</strong>
          <span class="metric-hint">{{ latestProject ? formatDate(latestProject.updated_at || latestProject.created_at) : '创建第一个项目开始' }}</span>
        </div>
      </div>
    </section>

    <NCard :bordered="false" class="projects-card">
      <NSkeleton v-if="initialLoading" :repeat="6" height="44px" :sharp="false" style="margin-top: 4px" />
      <NSpin v-else :show="refreshing">
        <div v-if="projects.length" class="projects-toolbar">
          <div>
            <h2>项目列表 <span>{{ filteredProjects.length }}</span></h2>
            <p>选择项目进入详情，查看会话与历史分析记录</p>
          </div>
          <NInput v-model:value="searchQuery" clearable placeholder="搜索项目名称、客户或描述" class="project-search">
            <template #prefix><NIcon><SearchOutline /></NIcon></template>
          </NInput>
        </div>
        <NEmpty v-if="!projects.length" description="还没有项目，新建一个项目来归集会话与分析运行" class="projects-empty">
          <template #extra>
            <NButton type="primary" @click="showCreate = true">
              <template #icon><NIcon><AddOutline /></NIcon></template>
              新建项目
            </NButton>
          </template>
        </NEmpty>
        <NEmpty v-else-if="!filteredProjects.length" description="没有匹配的项目" class="projects-empty projects-empty--search" />
        <NDataTable v-else :columns="columns" :data="filteredProjects" :row-key="(row: ProjectItem) => row.id" :pagination="{ pageSize: 20 }" :bordered="false" :scroll-x="tableScrollX" />
      </NSpin>
    </NCard>
  </div>
</template>

<style scoped>
/* 页面容器：与配置中心同一条内容边界（width: min(100%, 1440px) 居中），padding 消费 --page-padding（§3.4/§4.3） */
.projects-view {
  width: min(100%, 1440px);
  margin-inline: auto;
  padding: var(--page-padding);
}

.projects-overview {
  display: grid;
  grid-template-columns: minmax(280px, 1.1fr) minmax(420px, 1fr);
  gap: 24px;
  align-items: stretch;
  margin-bottom: 20px;
  padding: 24px 28px;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
  background: linear-gradient(120deg, var(--neutral-card), color-mix(in srgb, var(--brand-primary-light) 34%, var(--neutral-card)));
}

.overview-intro { display: flex; align-items: flex-start; gap: 14px; }
.overview-icon { display: grid; flex: 0 0 auto; width: 42px; height: 42px; place-items: center; color: var(--arco-primary); border: 1px solid color-mix(in srgb, var(--arco-primary) 20%, var(--neutral-border)); border-radius: 12px; background: var(--brand-primary-light); }
.overview-eyebrow { color: var(--arco-primary); font-size: 11px; font-weight: 700; letter-spacing: 0.08em; }
.overview-intro h2 { margin: 5px 0 4px; color: var(--neutral-text-1); font-size: 18px; line-height: 26px; font-weight: 600; }
.overview-intro p { margin: 0; color: var(--neutral-text-2); font-size: 13px; line-height: 20px; }
.overview-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; align-items: center; }
.overview-metric { min-width: 0; padding-left: 20px; border-left: 1px solid var(--neutral-border); }
.metric-label, .metric-hint { display: block; color: var(--neutral-text-3); font-size: 12px; line-height: 18px; }
.overview-metric strong { display: block; overflow: hidden; margin: 4px 0 1px; color: var(--neutral-text-1); font-size: 21px; line-height: 28px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.overview-metric--latest strong { font-size: 16px; }

.projects-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: -2px 0 20px; padding-bottom: 18px; border-bottom: 1px solid var(--neutral-border); }
.projects-toolbar h2 { margin: 0; color: var(--neutral-text-1); font-size: 16px; line-height: 24px; font-weight: 600; }
.projects-toolbar h2 span { margin-left: 5px; color: var(--neutral-text-3); font-size: 13px; font-weight: 400; }
.projects-toolbar p { margin: 3px 0 0; color: var(--neutral-text-3); font-size: 12px; line-height: 18px; }
.project-search { width: min(100%, 320px); }
.project-name-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.project-name-icon { display: grid; flex: 0 0 auto; width: 30px; height: 30px; place-items: center; color: var(--arco-primary); border-radius: 8px; background: var(--brand-primary-light); }
.project-name-copy { display: flex; min-width: 0; flex-direction: column; align-items: flex-start; }
.project-name-link { max-width: 100%; padding: 0; font-size: 14px; font-weight: 500; }
.project-slug { max-width: 100%; overflow: hidden; color: var(--neutral-text-3); font-size: 11px; line-height: 17px; text-overflow: ellipsis; white-space: nowrap; }

/* 卡片内边距 24px 由 NCard 默认提供；空状态给足上下留白 */
.projects-empty {
  padding: var(--space-4xl) 0;
}

/* 空值占位 '—' 用辅助色弱化（§3.2 辅助文本） */
.cell-muted {
  color: var(--neutral-text-3);
}

@media (max-width: 768px) {
  .projects-view {
    padding: var(--space-lg);
  }
  .projects-overview { grid-template-columns: 1fr; gap: 20px; padding: 20px; }
  .overview-metrics { gap: 12px; }
  .overview-metric { padding-left: 12px; }
  .projects-toolbar { align-items: stretch; flex-direction: column; }
  .project-search { width: 100%; }
}

@media (max-width: 480px) {
  .overview-metrics { grid-template-columns: 1fr 1fr; }
  .overview-metric--latest { grid-column: 1 / -1; padding-top: 12px; padding-left: 0; border-top: 1px solid var(--neutral-border); border-left: none; }
}
</style>
