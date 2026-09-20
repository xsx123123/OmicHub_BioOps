<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NIcon } from 'naive-ui'
import {
  RocketOutline, BarChartOutline,
  CheckmarkCircleOutline, SparklesOutline,
} from '@vicons/ionicons5'
import apiClient from '@/api/client'
import { festivalApi } from '@/api/festival'
import { useAuthStore } from '@/stores/auth'
import OmicBackgroundAnimation from '@/components/OmicBackgroundAnimation.vue'
import AnnouncementBanner from '@/components/AnnouncementBanner.vue'
import FestivalPopup from '@/components/FestivalPopup.vue'
import type { SiteContent } from '@/types/site-content'
import type { HomeQuickEntry, SiteSettings } from '@/types'
import type { FestivalConfig } from '@/types/festival'
import {
  normalizeHomeQuickEntries,
  quickEntryBgColors,
  quickEntryIconColors,
  resolveHomeQuickEntryIcon,
} from '@/config/homeQuickEntries'
import { isFestivalEffectsEnabled } from '@/utils/interfacePreferences'
import { displayName as getDisplayName } from '@/utils/displayName'

// 默认文案兜底：API 拉取失败时保证首页仍可正常渲染
const DEFAULT_CONTENT: SiteContent = {
  hero: {
    title: '欢迎使用 CygnusX',
    description: '华中农业大学园艺林学学院私有化多组学分析平台。从数据上传、流程分析到结果交付，一站式完成您的组学研究。',
  },
  quick_entries: [
    { key: 'rna-seq', title: 'RNA-seq 分析', desc: '转录组差异表达分析' },
    { key: 'atac-seq', title: 'ATAC-seq 分析', desc: '染色质开放性分析' },
    { key: 'files', title: '数据管理', desc: '上传与管理样本数据' },
    { key: 'ai', title: '星尘AI', desc: '对话式生信分析与结果解读' },
    { key: 'tasks', title: '任务中心', desc: '查看分析任务进度' },
  ],
  guide_steps: [
    { title: '上传样本数据', desc: '将 FASTQ / BAM 等原始数据上传至数据管理' },
    { title: '选择分析流程', desc: '在分析中心选择 RNA-seq 或 ATAC-seq 流程' },
    { title: '查看分析结果', desc: '任务完成后在报告中心查看与下载结果' },
  ],
}

const router = useRouter()
const authStore = useAuthStore()

// 展示名：优先昵称，未设置或为空则降级为用户名
const displayName = computed(() => getDisplayName(authStore.user))
const isAdmin = computed(() => authStore.user?.role === 'admin')

// 根据当前时段返回问候语
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

interface QuickEntry extends HomeQuickEntry {
  iconComponent: ReturnType<typeof resolveHomeQuickEntryIcon>
}

const content = ref<SiteContent>(DEFAULT_CONTENT)
const configuredQuickEntries = ref<HomeQuickEntry[] | null>(null)
const todayFestival = ref<FestivalConfig | null>(null)
const festivalClaimed = ref(false)

const showFestivalPopup = computed(() => {
  if (!isFestivalEffectsEnabled()) return false
  if (!todayFestival.value) return false
  const seen = localStorage.getItem(`festival_seen_${todayFestival.value.id}`) === '1'
  return !seen
})

const quickEntries = computed<QuickEntry[]>(() => {
  const source = configuredQuickEntries.value?.length
    ? configuredQuickEntries.value
    : content.value.quick_entries
  return normalizeHomeQuickEntries(source).map((entry) => ({
    ...entry,
    iconComponent: resolveHomeQuickEntryIcon(entry.icon),
  }))
})

const guideSteps = computed(() => content.value.guide_steps)

// 三步引导卡对应的站内页面：数据管理 → 分析中心 → 结果报告中心
const guideStepLinks = ['/files', '/flows', '/reports']

function goTo(path: string) {
  router.push(path)
}

onMounted(async () => {
  const [contentResult, settingsResult, festivalResult] = await Promise.allSettled([
    apiClient.get<SiteContent>('/site-content'),
    apiClient.get<SiteSettings>('/site-settings'),
    festivalApi.getTodayFestival(),
  ])

  if (contentResult.status === 'fulfilled') {
    content.value = contentResult.value.data
  }

  if (settingsResult.status === 'fulfilled' && settingsResult.value.data.home_quick_entries?.length) {
    configuredQuickEntries.value = normalizeHomeQuickEntries(settingsResult.value.data.home_quick_entries)
  }

  if (festivalResult.status === 'fulfilled' && festivalResult.value.hasFestival && isFestivalEffectsEnabled()) {
    todayFestival.value = festivalResult.value.festival
    festivalClaimed.value = festivalResult.value.claimed
  }
})
</script>

<template>
  <div class="home-page" role="main" aria-label="CygnusX 首页">
    <!-- Hero 欢迎区 -->
    <section class="hero animate-fade-in-up">
      <OmicBackgroundAnimation context="hero" />
      <div class="hero-content">
        <p class="hero-greeting">{{ greeting }}{{ displayName ? '，' + displayName : '' }} 👋</p>
        <h1 class="hero-title">{{ content.hero.title }}</h1>
        <p class="hero-desc">
          {{ content.hero.description }}
        </p>
        <div class="hero-actions">
          <NButton size="large" class="hero-btn-primary" @click="goTo('/flows')">
            <template #icon>
              <NIcon><RocketOutline /></NIcon>
            </template>
            开始分析
          </NButton>
          <NButton size="large" class="hero-btn-secondary" @click="goTo('/dashboard')">
            <template #icon>
              <NIcon><BarChartOutline /></NIcon>
            </template>
            查看仪表板
          </NButton>
          <NButton size="large" class="hero-btn-secondary" @click="goTo('/ai')">
            ✨ 问问星尘AI
          </NButton>
        </div>
      </div>
    </section>

    <!-- 条幅通知（管理员后台配置，按优先级取最高一条） -->
    <AnnouncementBanner />

    <!-- 快捷入口 -->
    <section class="section animate-fade-in-up delay-100">
      <h2 class="section-label">快捷入口</h2>
      <div class="entry-grid">
        <div
          v-for="entry in quickEntries"
          :key="entry.key"
          class="entry-card arco-card arco-card-hover"
          @click="goTo(entry.to)"
        >
          <div
            class="entry-icon"
            :style="{ background: quickEntryBgColors[entry.icon_bg], color: quickEntryIconColors[entry.icon_bg] }"
          >
            <NIcon :size="24">
              <component :is="entry.iconComponent" />
            </NIcon>
          </div>
          <div class="entry-text">
            <h4 class="entry-title">{{ entry.title }}</h4>
            <p class="entry-desc">{{ entry.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- 使用引导 -->
    <section class="section animate-fade-in-up delay-200">
      <h2 class="section-label">三步开始你的分析</h2>
      <div class="guide-grid">
        <div
          v-for="(step, index) in guideSteps"
          :key="step.title"
          class="guide-card arco-card arco-card-hover"
          @click="goTo(guideStepLinks[index] || '/flows')"
        >
          <div class="guide-step">
            <span class="guide-number">{{ index + 1 }}</span>
            <NIcon v-if="index < guideSteps.length - 1" :size="16" class="guide-arrow">
              <CheckmarkCircleOutline />
            </NIcon>
          </div>
          <h4 class="guide-title">{{ step.title }}</h4>
          <p class="guide-desc">{{ step.desc }}</p>
        </div>
      </div>
      <!-- Agent 路径：与手动三步并列的替代路径，跳星尘AI 对话页 -->
      <div class="agent-banner" @click="goTo('/ai')">
        <div
          class="agent-icon"
          :style="{ background: quickEntryBgColors.violet, color: quickEntryIconColors.violet }"
        >
          <NIcon :size="22"><SparklesOutline /></NIcon>
        </div>
        <div class="agent-text">
          <h4 class="agent-title">交给星尘AI</h4>
          <p class="agent-desc">一句话描述需求，星尘AI 自动完成数据上传、流程执行与结果解读</p>
        </div>
        <NButton class="agent-cta" @click.stop="goTo('/ai')">开始对话</NButton>
      </div>
    </section>

    <!-- 管理员入口 -->
    <section v-if="isAdmin" class="section animate-fade-in-up delay-200">
      <div class="admin-banner" @click="goTo('/admin/users')">
        <div class="admin-icon">
          <NIcon :size="20"><BarChartOutline /></NIcon>
        </div>
        <div class="admin-text">
          <h4 class="admin-title">系统管理</h4>
          <p class="admin-desc">用户、AI 模型、饼干账户与资源中心管理</p>
        </div>
        <NButton class="admin-cta">进入管理</NButton>
      </div>
    </section>
    <!-- 节日彩蛋弹窗 -->
    <FestivalPopup
      v-if="todayFestival && showFestivalPopup"
      :festival="todayFestival"
      :already-claimed="festivalClaimed"
      @claimed="festivalClaimed = true"
      @close="todayFestival = null"
    />
  </div>
</template>

<style scoped>
.home-page {
  padding: 24px;
  min-height: 100%;
  background: var(--neutral-bg);
}

/* ===== Hero ===== */
.hero {
  position: relative;
  overflow: hidden;
  border-radius: 16px;
  padding: 40px 32px;
  margin-bottom: 24px;
  background: linear-gradient(135deg, #165DFF 0%, #6B8DD6 50%, #8E54E9 100%);
  color: #fff;
}

.hero-bg-icon {
  display: none;
}

.hero-content {
  position: relative;
  z-index: 2;
  max-width: 640px;
}

.hero-greeting {
  font-size: 14px;
  opacity: 0.9;
  margin: 0 0 8px;
}

.hero-title {
  font-size: 28px;
  font-weight: 600;
  line-height: 36px;
  margin: 0 0 12px;
}

.hero-desc {
  font-size: 14px;
  line-height: 22px;
  opacity: 0.85;
  margin: 0 0 24px;
}

.hero-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

/* Hero 渐变背景上的按钮：毛玻璃 + 高亮边框方案（规范见 ARCHITECTURE_DESIN/frontend.md §5.7）。
   注意：Naive 将 --n-* 变量内联在元素上，class 级变量覆盖无效；
   这里直接用 CSS 属性 + 双类选择器提高特异性覆盖。 */
.n-button.hero-btn-primary {
  background-color: rgba(255, 255, 255, 0.95);
  color: #4f46e5;
  height: auto;
  padding: 8px 20px;
  font-size: 14px;
  border: none;
  border-radius: 12px;
  font-weight: 700;
  letter-spacing: 0.3px;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.3), 0 4px 20px rgba(0, 0, 0, 0.2);
  transition: all 0.2s ease;
}
.n-button.hero-btn-primary:hover,
.n-button.hero-btn-primary:focus {
  background-color: #ffffff;
  color: #4f46e5;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.45), 0 6px 24px rgba(0, 0, 0, 0.22);
  transform: translateY(-1px);
}
/* Naive 的描边由 __border / __state-border 两个元素绘制，需一并隐藏，否则与外发光环叠成"两圈" */
.n-button.hero-btn-primary :deep(.n-button__border),
.n-button.hero-btn-primary :deep(.n-button__state-border) {
  display: none;
}
.n-button.hero-btn-primary :deep(.n-button__icon) {
  color: #4f46e5;
}

.n-button.hero-btn-secondary {
  background-color: rgba(255, 255, 255, 0.15);
  color: #fff;
  height: auto;
  padding: 8px 20px;
  font-size: 14px;
  border: 1.5px solid rgba(255, 255, 255, 0.6);
  border-radius: 12px;
  font-weight: 700;
  letter-spacing: 0.3px;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  /* 内高光制造玻璃厚度 */
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1);
  transition: all 0.2s ease;
}
.n-button.hero-btn-secondary:hover,
.n-button.hero-btn-secondary:focus {
  background-color: rgba(255, 255, 255, 0.25);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.8);
}
.n-button.hero-btn-secondary :deep(.n-button__border),
.n-button.hero-btn-secondary :deep(.n-button__state-border) {
  display: none;
}
.n-button.hero-btn-secondary :deep(.n-button__icon) {
  color: #fff;
}

/* 图标与文字间距统一 8px */
.hero-actions :deep(.n-button__icon) {
  margin-right: 8px;
}

/* ===== 通用 section ===== */
.section {
  margin-bottom: 24px;
}

.section-label {
  font-size: 18px;
  font-weight: 600;
  line-height: 26px;
  color: var(--neutral-text-1);
  margin: 0 0 16px;
}

/* ===== 快捷入口 ===== */
.entry-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.entry-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.entry-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.3s ease;
}

.entry-card:hover .entry-icon {
  transform: scale(1.06);
}

.entry-text {
  min-width: 0;
}

.entry-title {
  font-size: 15px;
  font-weight: 500;
  line-height: 22px;
  color: var(--neutral-text-1);
  margin: 0 0 4px;
}

.entry-desc {
  font-size: 13px;
  line-height: 20px;
  color: var(--neutral-text-3);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 使用引导 ===== */
.guide-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.guide-card {
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.guide-step {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.guide-number {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
}

.guide-arrow {
  color: var(--neutral-text-4);
}

.guide-title {
  font-size: 15px;
  font-weight: 500;
  line-height: 22px;
  color: var(--neutral-text-1);
  margin: 0 0 6px;
}

.guide-desc {
  font-size: 13px;
  line-height: 20px;
  color: var(--neutral-text-3);
  margin: 0;
}

/* ===== Agent 路径卡（白卡 + 左侧渐变竖条的次级高亮，避免大色块压过步骤卡） ===== */
.agent-banner {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 20px;
  padding: 20px;
  border-radius: var(--radius-card);
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: all 0.2s ease;
}

/* 左侧渐变竖条：与星尘AI hero 同源的品牌点缀 */
.agent-banner::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--agent-hero-gradient);
}

.agent-banner:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-card-hover);
}

.agent-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-text {
  flex: 1;
  min-width: 0;
}

.agent-title {
  font-size: 16px;
  font-weight: 700;
  line-height: 24px;
  color: var(--neutral-text-1);
  margin: 0 0 4px;
}

.agent-desc {
  font-size: 13px;
  line-height: 20px;
  color: var(--neutral-text-3);
  margin: 0;
}

/* 通栏卡渐变 CTA：Agent 卡与系统管理卡同尺寸同样式，仅渐变色相不同；
   覆盖方式同 hero 按钮（见上方注释） */
.n-button.agent-cta,
.n-button.admin-cta {
  color: #ffffff;
  height: auto;
  padding: 8px 20px;
  font-size: 14px;
  border: none;
  border-radius: 12px;
  font-weight: 700;
  letter-spacing: 0.3px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: all 0.2s ease;
}
.n-button.agent-cta {
  background: var(--agent-hero-gradient);
}
.n-button.admin-cta {
  background: var(--admin-hero-gradient);
}
.n-button.agent-cta:hover,
.n-button.agent-cta:focus,
.n-button.admin-cta:hover,
.n-button.admin-cta:focus {
  color: #ffffff;
  opacity: 0.92;
  transform: translateY(-1px);
}
.n-button.agent-cta:hover,
.n-button.agent-cta:focus {
  background: var(--agent-hero-gradient);
}
.n-button.admin-cta:hover,
.n-button.admin-cta:focus {
  background: var(--admin-hero-gradient);
}
.n-button.agent-cta :deep(.n-button__border),
.n-button.agent-cta :deep(.n-button__state-border),
.n-button.admin-cta :deep(.n-button__border),
.n-button.admin-cta :deep(.n-button__state-border) {
  display: none;
}

/* ===== 管理员入口 ===== */
/* 不挂 arco-card 类：全局 .arco-card::before 是 opacity:0 的 hover 装饰条，会顶掉渐变竖条 */
.admin-banner {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border-radius: var(--radius-card);
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: all 0.2s ease;
}

/* 左侧渐变竖条：与 Agent 卡同构、蓝青色相区分 */
.admin-banner::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--admin-hero-gradient);
}

.admin-banner:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-card-hover);
}

.admin-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.admin-text {
  flex: 1;
  min-width: 0;
}

.admin-title {
  font-size: 15px;
  font-weight: 500;
  line-height: 22px;
  color: var(--neutral-text-1);
  margin: 0 0 4px;
}

.admin-desc {
  font-size: 13px;
  line-height: 20px;
  color: var(--neutral-text-3);
  margin: 0;
}

/* ===== 响应式 ===== */
@media (max-width: 1024px) {
  .entry-grid,
  .guide-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .home-page {
    padding: 16px;
  }

  .hero {
    padding: 28px 20px;
  }

  .hero-title {
    font-size: 22px;
  }

  .entry-grid,
  .guide-grid {
    grid-template-columns: 1fr;
  }

  .admin-banner,
  .agent-banner {
    flex-wrap: wrap;
  }
}
</style>
