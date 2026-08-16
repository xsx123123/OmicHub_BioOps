<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, NProgress, NSpin } from 'naive-ui'
import apiClient from '@/api/client'
import type { StudioUsage } from '@/types/stats'

const selectedDays = ref(7)
const loading = ref(false)
const usage = ref<StudioUsage | null>(null)
const tokenUnit = ref<'K' | 'M'>('K')

const maxDailyValue = computed(() => {
  const values = usage.value?.daily.flatMap((item) => [item.total_tokens, item.sandbox_runs * 1000]) ?? []
  return Math.max(1, ...values)
})

const trendDaily = computed(() =>
  [...(usage.value?.daily ?? [])].sort((left, right) => right.date.localeCompare(left.date)),
)

function formatTokens(value: number): string {
  if (tokenUnit.value === 'M') return `${(value / 1_000_000).toFixed(2)} M`
  return `${(value / 1000).toFixed(1)} K`
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.round(milliseconds / 1000)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`
}

function formatBytes(value: number): string {
  if (value <= 0) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** index).toFixed(index >= 3 ? 1 : 0)} ${units[index]}`
}

function barWidth(tokens: number, runs: number): string {
  return `${Math.max(3, Math.round(Math.max(tokens, runs * 1000) / maxDailyValue.value * 100))}%`
}

async function fetchUsage() {
  loading.value = true
  try {
    const response = await apiClient.get<StudioUsage>('/stats/studio', {
      params: { days: selectedDays.value },
    })
    usage.value = response.data
  } catch {
    usage.value = null
  } finally {
    loading.value = false
  }
}

watch(selectedDays, fetchUsage)
onMounted(fetchUsage)
</script>

<template>
  <section class="arco-card studio-usage-card animate-fade-in-up delay-100">
    <div class="arco-card-header">
      <div>
        <span class="arco-card-title">OmicStudio 用量</span>
        <p class="card-subtitle">AI 对话 Token、沙盒执行与当前存储配额汇总</p>
      </div>
      <div class="days-toggle">
        <NButton size="small" :type="selectedDays === 7 ? 'primary' : 'default'" ghost @click="selectedDays = 7">
          近 7 天
        </NButton>
        <NButton size="small" :type="selectedDays === 30 ? 'primary' : 'default'" ghost @click="selectedDays = 30">
          近 30 天
        </NButton>
      </div>
    </div>

    <NSpin :show="loading">
      <div v-if="usage" class="usage-layout">
        <div class="metric-grid">
          <div class="metric-item">
            <div class="metric-label-row">
              <span class="metric-label">Token</span>
              <div class="omichub-segmented-toggle unit-toggle" role="group" aria-label="Token 单位切换">
                <button type="button" :class="{ active: tokenUnit === 'K' }" :aria-pressed="tokenUnit === 'K'" @click="tokenUnit = 'K'">K</button>
                <button type="button" :class="{ active: tokenUnit === 'M' }" :aria-pressed="tokenUnit === 'M'" @click="tokenUnit = 'M'">M</button>
              </div>
            </div>
            <strong>{{ formatTokens(usage.summary.total_tokens) }}</strong>
            <small>输入 {{ formatTokens(usage.summary.input_tokens) }} · 输出 {{ formatTokens(usage.summary.output_tokens) }}</small>
            <small v-if="usage.cookie" class="cookie-equiv">
              ≈ {{ usage.cookie.cost.toFixed(1) }} 🥫 · {{ usage.cookie.rate_per_1k_tokens }} 🥫/1K tokens
            </small>
          </div>
          <div class="metric-item">
            <span class="metric-label">沙盒运行</span>
            <strong>{{ usage.summary.sandbox_runs }}</strong>
            <small>成功率 {{ usage.summary.sandbox_success_rate }}%</small>
          </div>
          <div class="metric-item">
            <span class="metric-label">执行时长</span>
            <strong>{{ formatDuration(usage.summary.sandbox_duration_ms) }}</strong>
            <small>长任务 {{ usage.summary.long_tasks }} 次</small>
          </div>
          <div class="metric-item">
            <span class="metric-label">工作产出</span>
            <strong>{{ usage.summary.artifacts }}</strong>
            <small>{{ usage.summary.sessions }} 个会话 · {{ usage.summary.messages }} 条消息</small>
          </div>
        </div>

        <div class="trend-panel">
          <div class="trend-heading">
            <span>最近 {{ trendDaily.length }} 天活跃度</span>
            <small>Token / 执行次数</small>
          </div>
          <div class="daily-bars" :class="{ 'daily-bars--month': selectedDays === 30 }">
            <div v-for="item in trendDaily" :key="item.date" class="daily-row">
              <span>{{ item.date.slice(5) }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: barWidth(item.total_tokens, item.sandbox_runs) }" />
              </div>
              <small>{{ formatTokens(item.total_tokens) }} / {{ item.sandbox_runs }}</small>
            </div>
          </div>
        </div>

        <div class="quota-panel">
          <div class="quota-heading">
            <span>存储配额</span>
            <strong>{{ formatBytes(usage.quota.storage_used) }} / {{ formatBytes(usage.quota.storage_quota) }}</strong>
          </div>
          <NProgress
            type="line"
            :percentage="Math.min(100, usage.quota.storage_used_percent)"
            :status="usage.quota.storage_used_percent >= 90 ? 'error' : usage.quota.storage_used_percent >= 75 ? 'warning' : 'success'"
            :height="10"
            :border-radius="5"
          />
          <small>剩余 {{ formatBytes(usage.quota.storage_available) }}</small>
        </div>
      </div>
      <NEmpty v-else-if="!loading" description="暂时无法读取 Studio 用量" />
    </NSpin>
  </section>
</template>

<style scoped>
.arco-card {
  background: var(--neutral-card);
  border: none;
  border-radius: var(--radius-card);
  padding: 18px 20px;
  box-shadow: var(--shadow-card);
}

/* 与页面其他卡片保持统一的 24px 垂直间距 */
.studio-usage-card {
  margin-bottom: 24px;
}

.arco-card-header,
.trend-heading,
.quota-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.arco-card-header {
  margin-bottom: 18px;
}

.arco-card-title {
  color: var(--neutral-text-1);
  font-size: 15px;
  font-weight: 600;
}

.card-subtitle,
.metric-item small,
.trend-heading small,
.quota-panel small {
  color: var(--neutral-text-3);
  font-size: 12px;
}

.card-subtitle {
  margin: 4px 0 0;
}

.days-toggle {
  display: flex;
  gap: 6px;
}

.usage-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(280px, 1fr);
  gap: 18px 24px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.metric-item,
.trend-panel,
.quota-panel {
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 14px;
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.metric-label,
.trend-heading span,
.quota-heading span {
  color: var(--neutral-text-2);
  font-size: 12px;
}

.metric-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.metric-item .cookie-equiv {
  color: var(--arco-primary);
  font-weight: 500;
}

.metric-item strong {
  color: var(--neutral-text-1);
  font-size: 23px;
  line-height: 1.2;
}

.trend-panel {
  grid-row: span 2;
  display: flex;
  min-height: 0;
  flex-direction: column;
}

.daily-bars {
  display: grid;
  flex: 1;
  grid-template-rows: repeat(7, minmax(0, 1fr));
  min-height: 0;
  gap: 8px;
  margin-top: 12px;
}

.daily-bars--month {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: repeat(15, minmax(0, 1fr));
  column-gap: 14px;
  row-gap: 6px;
}

.daily-row {
  display: grid;
  grid-template-columns: 42px minmax(80px, 1fr) 74px;
  align-items: center;
  gap: 8px;
  color: var(--neutral-text-3);
  font-size: 11px;
}

.daily-row small {
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: right;
  white-space: nowrap;
}

.bar-track {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--neutral-fill-2);
}

.bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--arco-primary), #8b5cf6);
}

.quota-panel {
  grid-column: 1 / -1;
}

.quota-heading {
  margin-bottom: 10px;
}

.quota-heading strong {
  color: var(--neutral-text-1);
  font-size: 13px;
}

.quota-panel small {
  display: block;
  margin-top: 7px;
  text-align: right;
}

@media (max-width: 900px) {
  .usage-layout {
    grid-template-columns: 1fr;
  }

  .trend-panel {
    grid-row: auto;
  }

  .quota-panel {
    grid-column: auto;
  }
}

@media (max-width: 1180px) and (min-width: 901px) {
  .daily-bars--month {
    grid-template-columns: 1fr;
    grid-template-rows: repeat(30, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .arco-card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
