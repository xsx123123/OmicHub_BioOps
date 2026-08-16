<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NGrid, NGi, NIcon, NStatistic } from 'naive-ui'
import {
  TrendingUpOutline,
  FlashOutline,
  CalendarOutline,
  PeopleOutline,
} from '@vicons/ionicons5'
import type { AdminCookieStats } from '@/stores/adminCookie'

const props = defineProps<{ stats: AdminCookieStats | null; loading?: boolean }>()

const cards = computed(() => {
  const s = props.stats
  return [
    {
      label: '流通总余额',
      value: s?.total_balance ?? 0,
      icon: TrendingUpOutline,
      color: 'var(--arco-primary)',
      bg: 'var(--arco-primary-light)',
      suffix: '🥫',
    },
    {
      label: '累计发放',
      value: s?.total_earned ?? 0,
      icon: FlashOutline,
      color: 'var(--arco-success)',
      bg: 'var(--arco-success-light)',
      suffix: '🥫',
    },
    {
      label: '累计消耗',
      value: s?.total_spent ?? 0,
      icon: CalendarOutline,
      color: 'var(--arco-warning, #FF7D00)',
      bg: 'var(--arco-warning-light, #FFF7E8)',
      suffix: '🥫',
    },
    {
      label: '活跃账户数',
      value: s?.active_accounts ?? 0,
      icon: PeopleOutline,
      color: 'var(--arco-primary)',
      bg: 'var(--arco-primary-light)',
      suffix: '户',
    },
  ]
})

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN')
}
</script>

<template>
  <NGrid :x-gap="20" :y-gap="20" :cols="4" responsive="screen" item-responsive>
    <NGi v-for="c in cards" :key="c.label" :span="4" :md="2" :lg="1">
      <NCard :bordered="false" class="metric-card" :class="{ 'is-loading': loading }">
        <div class="metric-body">
          <div class="metric-icon" :style="{ background: c.bg, color: c.color }">
            <NIcon :component="c.icon" :size="22" />
          </div>
          <div class="metric-content">
            <div class="metric-label">{{ c.label }}</div>
            <div class="metric-value">
              <NStatistic :value="fmt(c.value)" tabular-nums>
                <template #suffix>
                  <span class="metric-suffix">{{ c.suffix }}</span>
                </template>
              </NStatistic>
            </div>
          </div>
        </div>
      </NCard>
    </NGi>
  </NGrid>
</template>

<style scoped>
.metric-card {
  border-radius: 12px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.metric-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}
.metric-card.is-loading {
  opacity: 0.7;
}
.metric-body {
  display: flex;
  align-items: center;
  gap: 16px;
}
.metric-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.metric-label {
  font-size: 13px;
  color: var(--neutral-text-2, #86909c);
  margin-bottom: 4px;
}
.metric-value :deep(.n-statistic-value__content) {
  font-size: 26px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}
.metric-suffix {
  font-size: 14px;
  margin-left: 4px;
  color: var(--neutral-text-2, #86909c);
}
.metric-trend {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  margin-top: 6px;
  font-weight: 500;
}
.metric-trend.up {
  color: var(--arco-success);
}
.metric-trend-text {
  color: var(--neutral-text-3, #c9cdd4);
  font-weight: 400;
}
</style>
