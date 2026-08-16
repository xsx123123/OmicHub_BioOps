<script setup lang="ts">
import type { FlowDefinition } from '@/types'
import apiClient from '@/api/client'
import { useApi } from '@/composables/useApi'
import AppLoading from '@/components/AppLoading.vue'
import PageHeader from '@/components/PageHeader.vue'
import { NButton, NIcon } from 'naive-ui'
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Component } from 'vue'
import {
  AnalyticsOutline,
  BeakerOutline,
  ClipboardOutline,
  CodeSlashOutline,
  DocumentTextOutline,
  FlameOutline,
  FlaskOutline,
  GlobeOutline,
  LogoGithub,
  MagnetOutline,
  FolderOutline,
  SettingsOutline,
  StatsChartOutline,
} from '@vicons/ionicons5'

interface Pipeline {
  id: string
  name: string
  desc: string
  icon: Component | string
  colorVar: string
  tags: string[]
  version: string
  githubUrl: string | null
  isReady: boolean
}

const route = useRoute()
const router = useRouter()

const activeType = computed(() => (route.query.type as string) || '')

const {
  data: flows,
  loading,
  execute: fetchFlows,
} = useApi<FlowDefinition[]>(
  async () => {
    const res = await apiClient.get<{ items: FlowDefinition[]; total: number }>('/flows')
    return res.data.items
  },
  { initialData: [] },
)

const typeLabels: Record<string, string> = {
  'rna-seq': 'RNA-seq 分析',
  'atac-seq': 'ATAC-seq 分析',
  'sc-rna': '单细胞分析',
  'spatial': '空间转录组',
  'chip-seq': 'ChIP-seq 分析',
  'hic': 'Hi-C 三维基因组',
  'methylation': '甲基化分析',
  '16s-amplicon': '扩增子分析',
  'metagenomics': '宏基因组分析',
  'proteomics': '蛋白质组分析',
  'metabolomics': '代谢组分析',
  'multi-omics': '多组学联合',
  'denovo-assembly': '基因组组装',
  'wgs': '全基因组测序',
  'wes': '全外显子测序',
  'gwas': 'GWAS 分析',
}

/** 流程图标兜底映射（兼容旧 YAML 中 icon 为字符串 key 的情况） */
const FALLBACK_MAP: Record<string, Component> = {
  rna: BeakerOutline,
  atac: FlaskOutline,
  scrna: AnalyticsOutline,
  chip: MagnetOutline,
  wgs: FolderOutline,
  wes: FolderOutline,
  jbrowse: GlobeOutline,
  proteomics: FlaskOutline,
  metabolomics: FlaskOutline,
  default: StatsChartOutline,
}

/** 将历史流程元数据中的常见 Emoji 图标迁移到稳定的矢量图标；未知自定义图标仍原样展示。 */
const LEGACY_ICON_MAP: Record<string, Component> = {
  '🧬': BeakerOutline,
  '🧪': FlaskOutline,
  '🔬': AnalyticsOutline,
  '🧲': MagnetOutline,
  '🗂️': FolderOutline,
  '🌐': GlobeOutline,
  '🧫': FlaskOutline,
  '⚗️': FlaskOutline,
  '⚙️': SettingsOutline,
}

/** 按 category 动态主题色 key */
const CATEGORY_COLOR_MAP: Record<string, string> = {
  transcriptomics: 'chart-1',
  epigenomics: 'chart-4',
  genomics: 'chart-3',
  'single-cell': 'chart-2',
  visualization: 'chart-6',
  proteomics: 'chart-5',
  metabolomics: 'chart-6',
  default: 'chart-1',
}

const COLOR_LIST = ['chart-1', 'chart-2', 'chart-3', 'chart-4', 'chart-5', 'chart-6']

function flowIcon(flow: FlowDefinition): Component | string {
  const icon = flow.icon
  if (icon && icon.trim().length > 0) {
    if (LEGACY_ICON_MAP[icon]) return LEGACY_ICON_MAP[icon]
    if (/[^\x00-\x7F]/.test(icon)) return icon
    return FALLBACK_MAP[icon.toLowerCase()] || FALLBACK_MAP[flow.category] || FALLBACK_MAP.default
  }
  return FALLBACK_MAP[flow.category] || FALLBACK_MAP.default
}

function flowColor(flow: FlowDefinition): string {
  if (flow.color) return flow.color
  return CATEGORY_COLOR_MAP[flow.category] || CATEGORY_COLOR_MAP.default
}

function isGithubUrl(url?: string | null): boolean {
  return !!url && url.includes('github.com')
}

function resolveGithubUrl(flow: FlowDefinition): string | null {
  if (isGithubUrl(flow.github_url)) return flow.github_url as string
  if (isGithubUrl(flow.docs_url)) return flow.docs_url as string
  return null
}

const pipelines = computed<Pipeline[]>(() => {
  return (flows.value || []).map((f, index) => ({
    id: f.id,
    name: f.name,
    desc: f.description,
    icon: flowIcon(f),
    colorVar: `var(--kimi-${flowColor(f)})`,
    tags: f.tags?.length ? f.tags : [f.category],
    version: f.version,
    githubUrl: resolveGithubUrl(f),
    isReady: true,
  }))
})

const filteredPipelines = computed(() => {
  if (!activeType.value) return pipelines.value
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '')
  const target = norm(activeType.value)
  return pipelines.value.filter((p) => {
    const key = norm(`${p.id} ${p.tags.join(' ')}`)
    return key.includes(target)
  })
})

const featuredPipeline = computed(() =>
  filteredPipelines.value.find((p) => p.id === 'rna_seq') ||
  filteredPipelines.value.find((p) => p.id.includes('rna')) ||
  filteredPipelines.value[0],
)

const gridPipelines = computed(() => {
  if (activeType.value) return filteredPipelines.value
  return filteredPipelines.value.filter((p) => p.id !== featuredPipeline.value?.id)
})

function handleCardClick(p: Pipeline) {
  router.push({ name: 'flow-submit', params: { flowId: p.id } })
}

function openGithub(e: Event, url: string) {
  e.stopPropagation()
  window.open(url, '_blank', 'noopener,noreferrer')
}

watch(() => route.query.type, fetchFlows)
onMounted(fetchFlows)
</script>

<template>
  <div class="flows-page" role="main" aria-label="分析流程中心">
    <PageHeader
      class="animate-fade-in-up"
      :title="activeType ? typeLabels[activeType] || '分析流程' : '分析中心'"
      :subtitle="activeType ? '当前筛选的分析流程，点击卡片即可提交任务' : '选择适合您研究需求的分析流程，快速启动多组学分析'"
    >
      <template #actions>
        <div class="flows-header-actions">
        <NButton v-if="activeType" class="header-btn-secondary" @click="router.push('/flows')">
          查看全部流程
        </NButton>
        <NButton class="header-btn-secondary" tag="a" href="https://github.com" target="_blank">
          <template #icon><component :is="CodeSlashOutline" /></template>
          Github 开源代码
        </NButton>
        <NButton class="header-btn-secondary">
          <template #icon><component :is="DocumentTextOutline" /></template>
          开发者文档
        </NButton>
        </div>
      </template>
    </PageHeader>

    <!-- 加载态 -->
    <div v-if="loading && !pipelines.length" class="flows-loading">
      <AppLoading text="加载分析流程..." />
    </div>

    <template v-else-if="pipelines.length">
      <!-- 推荐流程 -->
      <section v-if="!activeType && featuredPipeline" class="featured-section animate-fade-in-up delay-100">
        <h2 class="section-label">
          <NIcon :component="FlameOutline" class="section-icon" aria-hidden="true" />
          推荐流程
        </h2>
        <div
          class="hero-card"
          :style="{ '--hero-accent': featuredPipeline.colorVar }"
          @click="handleCardClick(featuredPipeline)"
        >
          <div class="hero-inner">
            <div class="hero-icon" :style="{ background: `color-mix(in srgb, ${featuredPipeline.colorVar} 10%, transparent)` }">
              <NIcon v-if="typeof featuredPipeline.icon !== 'string'" :component="featuredPipeline.icon" :size="22" />
              <span v-else>{{ featuredPipeline.icon }}</span>
            </div>

          <div class="hero-body">
            <div class="hero-title-row">
              <h3 class="hero-title">{{ featuredPipeline.name }}</h3>
              <span class="recommended-badge">
                <NIcon :component="FlameOutline" aria-hidden="true" />
                推荐
              </span>
              <span class="version-badge">v{{ featuredPipeline.version }}</span>
            </div>
              <p class="hero-desc">{{ featuredPipeline.desc }}</p>
              <div class="hero-tags">
                <span
                  v-for="tag in featuredPipeline.tags"
                  :key="tag"
                  class="hero-tag"
                  :style="{ background: `color-mix(in srgb, ${featuredPipeline.colorVar} 12%, transparent)`, color: featuredPipeline.colorVar }"
                >
                  {{ tag }}
                </span>
              </div>
            </div>

            <button
              v-if="featuredPipeline.githubUrl"
              class="hero-github-link focus-ring"
              title="查看源码"
              @click="openGithub($event, featuredPipeline.githubUrl)"
            >
              <NIcon :size="20"><LogoGithub /></NIcon>
            </button>
          </div>
        </div>
      </section>

      <!-- 全部流程 -->
      <section class="all-flows-section animate-fade-in-up delay-200">
        <h2 class="section-label">
          <NIcon :component="ClipboardOutline" class="section-icon" aria-hidden="true" />
          {{ activeType ? '筛选结果' : '全部流程' }}
        </h2>

        <div v-animate-list class="flow-grid">
          <div
            v-for="p in gridPipelines"
            :key="p.id"
            class="flow-card"
            :style="{ '--flow-accent': p.colorVar }"
            @click="handleCardClick(p)"
          >
            <div class="flow-inner">
              <div
                class="flow-icon"
                :style="{ background: `color-mix(in srgb, ${p.colorVar} 10%, transparent)` }"
              >
                <NIcon v-if="typeof p.icon !== 'string'" :component="p.icon" :size="20" />
                <span v-else>{{ p.icon }}</span>
              </div>
              <div class="flow-body">
                <div class="flow-title-row">
                  <h4 class="flow-title">{{ p.name }}</h4>
                  <span class="flow-version">v{{ p.version }}</span>
                </div>
                <p class="flow-desc">{{ p.desc }}</p>
                <div class="flow-tags">
                  <span
                    v-for="tag in p.tags"
                    :key="tag"
                    class="flow-tag"
                    :style="{ background: `color-mix(in srgb, ${p.colorVar} 10%, transparent)`, color: p.colorVar }"
                  >
                    {{ tag }}
                  </span>
                </div>
              </div>
              <button
                v-if="p.githubUrl"
                class="flow-github-link focus-ring"
                title="查看源码"
                @click="openGithub($event, p.githubUrl)"
              >
                <NIcon :size="18"><LogoGithub /></NIcon>
              </button>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- 空状态 -->
    <div v-else-if="!loading && !pipelines.length" class="flows-empty">
      <NIcon :size="64" class="text-gray-300 mb-4"><FlaskOutline /></NIcon>
      <p class="text-sm font-medium text-gray-500 mb-1">暂无分析流程</p>
      <p class="text-xs text-gray-400">请联系管理员配置流程 YAML 文件</p>
    </div>
  </div>
</template>

<style scoped>
.flows-page {
  padding: 24px;
  min-height: 100%;
  background: var(--neutral-bg);
}

.flows-loading,
.flows-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 24px;
}

.flows-header-actions {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}

.header-btn-secondary {
  --n-text-color: var(--neutral-text-2);
  --n-text-color-hover: var(--neutral-text-2);
  --n-border: 1px solid var(--neutral-border);
  --n-border-hover: 1px solid var(--neutral-border);
  --n-color: var(--neutral-card);
  --n-color-hover: var(--neutral-hover);
}

.section-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  line-height: 26px;
  color: var(--neutral-text-1);
  margin: 0 0 16px;
}

.section-icon {
  font-size: 20px;
  color: var(--brand-primary);
}

.featured-section {
  margin-bottom: 32px;
}

/* ===== Hero Card ===== */
.hero-card {
  position: relative;
  border: none;
  border-radius: var(--radius-card);
  padding: 20px;
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s ease;
}

.hero-card::before {
  content: '';
  position: absolute;
  top: 16px;
  bottom: 16px;
  left: 0;
  width: 4px;
  border-radius: 0 4px 4px 0;
  background: var(--brand-primary);
}

.hero-card:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-card-hover);
}

.hero-inner {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.hero-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}

.hero-body {
  flex: 1;
  min-width: 0;
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hero-title {
  font-size: 17px;
  font-weight: 500;
  color: var(--neutral-text-1);
  margin: 0;
}

.version-badge {
  font-size: 12px;
  color: var(--neutral-text-3);
  background: var(--neutral-hover);
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}

.recommended-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  color: var(--brand-primary);
  background: var(--brand-primary-light);
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
  white-space: nowrap;
}

.recommended-badge :deep(.n-icon) {
  font-size: 14px;
}

.hero-desc {
  font-size: 14px;
  color: var(--neutral-text-2);
  margin: 6px 0 12px 0;
  line-height: 1.5;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.hero-tag {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 6px;
  font-weight: 500;
}

.hero-github-link {
  flex-shrink: 0;
  color: var(--neutral-text-3);
  opacity: 0;
  transition: opacity 0.2s ease, color 0.2s ease;
  display: inline-flex;
  padding: 4px;
  border-radius: 6px;
  background: transparent;
  border: none;
  cursor: pointer;
}

.hero-card:hover .hero-github-link {
  opacity: 1;
}

.hero-github-link:hover {
  color: #24292f;
  animation: github-wiggle 0.5s ease-in-out;
}

@keyframes github-wiggle {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(-10deg); }
  75% { transform: rotate(10deg); }
}

/* ===== All Flows Grid ===== */
.all-flows-section {
  margin-bottom: 24px;
}

.flow-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}

.flow-card {
  position: relative;
  border: 1px solid var(--neutral-border);
  border-radius: 10px;
  padding: 16px;
  background: var(--neutral-card);
  cursor: pointer;
  transition: all 0.2s ease;
  overflow: hidden;
}

.flow-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 3px;
  height: 100%;
  background: var(--flow-accent);
  opacity: 0;
  transition: opacity 0.2s ease;
}

.flow-card:hover::before {
  opacity: 1;
}

.flow-card:hover {
  border-color: var(--neutral-text-1);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px color-mix(in srgb, var(--neutral-text-1) 6%, transparent);
}

.flow-github-link {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 1;
  color: var(--neutral-text-3);
  opacity: 0;
  transition: opacity 0.2s ease, color 0.2s ease;
  display: inline-flex;
  padding: 4px;
  border-radius: 6px;
  background: transparent;
  border: none;
  cursor: pointer;
}

.flow-card:hover .flow-github-link {
  opacity: 1;
}

.flow-card:hover .flow-version {
  opacity: 0;
}

.flow-github-link:hover {
  color: #24292f;
  animation: github-wiggle 0.5s ease-in-out;
}

.flow-inner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.flow-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.flow-body {
  flex: 1;
  min-width: 0;
}

.flow-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  gap: 8px;
}

.flow-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--neutral-text-1);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.flow-version {
  font-size: 11px;
  color: var(--neutral-text-3);
  flex-shrink: 0;
  transition: opacity 0.2s ease;
}

.flow-desc {
  font-size: 13px;
  color: var(--neutral-text-2);
  line-height: 1.45;
  margin: 0 0 10px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.flow-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.flow-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}

@media (max-width: 768px) {
  .flows-header-actions {
    width: 100%;
    flex-wrap: wrap;
  }
  .header-btn-secondary {
    flex: 1;
  }
  .flow-grid {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hero-github-link:hover {
    animation: none;
  }
}
</style>
