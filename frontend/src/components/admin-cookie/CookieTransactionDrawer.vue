<script setup lang="ts">
/**
 * 用户资产详情抽屉 — 头部展示角色/注册时间/存储用量，下方为饼干消耗时间线。
 * 数据来自真实 /admin/cookies/transactions/filtered?user_id=（由父组件异步拉取后传入）。
 */
import { computed } from 'vue'
import {
  NDrawer, NDrawerContent, NTimeline, NTimelineItem, NTag, NEmpty,
  NSpace, NStatistic, NIcon, NAvatar, NSpin,
} from 'naive-ui'
import {
  FlaskOutline, ChatbubbleEllipsesOutline, CashOutline, GiftOutline, PulseOutline,
} from '@vicons/ionicons5'
import type { AdminCookieAccount, AdminCookieTxn } from '@/stores/adminCookie'
import { displayName } from '@/utils/displayName'

const props = defineProps<{
  show: boolean
  account: AdminCookieAccount | null
  txns: AdminCookieTxn[]
  loading?: boolean
}>()

const emit = defineEmits<{ (e: 'update:show', v: boolean): void }>()

// source_type → 展示元数据（后端 source_type: task / sandbox / admin / signup / ...）
const sourceMeta: Record<string, { label: string; icon: any; color: string }> = {
  task: { label: '流程算力', icon: FlaskOutline, color: 'var(--arco-primary)' },
  sandbox: { label: '沙盒', icon: PulseOutline, color: 'var(--arco-warning, #FF7D00)' },
  ai: { label: 'AI 调用', icon: ChatbubbleEllipsesOutline, color: 'var(--arco-warning, #FF7D00)' },
  admin: { label: '管理员', icon: CashOutline, color: 'var(--arco-success)' },
  signup: { label: '注册赠送', icon: GiftOutline, color: 'var(--arco-primary)' },
}
function metaOf(src: string) {
  return sourceMeta[src] || { label: src || '其他', icon: PulseOutline, color: 'var(--arco-primary)' }
}

const totalRecharge = computed(() => props.txns.filter((t) => t.amount > 0).reduce((s, t) => s + t.amount, 0))
const totalSpend = computed(() => props.txns.filter((t) => t.amount < 0).reduce((s, t) => s + -t.amount, 0))

function itemType(amount: number): 'success' | 'error' | 'default' {
  if (amount > 0) return 'success'
  if (amount < 0) return 'error'
  return 'default'
}

function fmtDate(s: string | null): string {
  return s ? new Date(s).toLocaleString('zh-CN') : ''
}

function usedGb(bytes: number): string {
  return (bytes / 1024 / 1024 / 1024).toFixed(1)
}
</script>

<template>
  <NDrawer :show="show" @update:show="(v) => emit('update:show', v)" :width="460" placement="right">
    <NDrawerContent title="用户资产详情" closable>
      <template v-if="account">
        <!-- 用户概要 -->
        <div class="acct-head">
          <NAvatar round :size="44" :style="{ background: 'var(--arco-primary)' }">
            {{ displayName(account).slice(0, 1).toUpperCase() }}
          </NAvatar>
          <div class="acct-meta">
            <div class="acct-name">{{ displayName(account) }}</div>
            <div class="acct-email">{{ account.email }}</div>
            <NSpace :size="6">
              <NTag size="tiny" round :type="account.role === 'admin' ? 'success' : 'default'">
                {{ account.role === 'admin' ? '管理员' : '用户' }}
              </NTag>
              <NTag v-if="account.lab_group" size="tiny" round>{{ account.lab_group }}</NTag>
              <NTag v-if="account.user_status" size="tiny" round :type="account.user_status === 'active' ? 'success' : 'warning'">
                {{ account.user_status }}
              </NTag>
            </NSpace>
          </div>
        </div>

        <!-- 身份与存储 -->
        <div class="info-row">
          <span>注册时间</span><span>{{ fmtDate(account.user_created_at) || '—' }}</span>
        </div>
        <div class="info-row">
          <span>存储用量</span><span>{{ usedGb(account.used_storage) }} / {{ usedGb(account.storage_quota) }} GiB</span>
        </div>

        <NSpace :size="24" class="acct-stats">
          <NStatistic label="当前余额" :value="account.balance"><template #suffix>🥫</template></NStatistic>
          <NStatistic label="累计充值" :value="totalRecharge"><template #suffix>🥫</template></NStatistic>
          <NStatistic label="累计消耗" :value="totalSpend"><template #suffix>🥫</template></NStatistic>
        </NSpace>

        <!-- 时间线 -->
        <div class="txn-section">
          <div class="section-title">消耗时间线</div>
          <NSpin v-if="loading" size="small" />
          <NTimeline v-else-if="txns.length">
            <NTimelineItem v-for="(t, i) in txns" :key="t.id ?? t.created_at ?? i" :type="itemType(t.amount)">
              <template #icon>
                <NIcon :component="metaOf(t.source_type).icon" />
              </template>
              <div class="txn-row">
                <div class="txn-top">
                  <span class="txn-desc">{{ t.description || t.txn_type }}</span>
                  <span class="txn-amount" :class="t.amount >= 0 ? 'plus' : 'minus'">
                    {{ t.amount >= 0 ? '+' : '' }}{{ t.amount }} 🥫
                  </span>
                </div>
                <div class="txn-foot">
                  <NTag size="tiny" :bordered="false">{{ metaOf(t.source_type).label }}</NTag>
                  <span class="txn-date">{{ fmtDate(t.created_at) }}</span>
                  <span class="txn-after">余额 {{ t.balance_after }} 🥫</span>
                </div>
              </div>
            </NTimelineItem>
          </NTimeline>
          <NEmpty v-else description="该用户暂无账单流水" />
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.acct-head { display: flex; align-items: center; gap: 12px; padding: 4px 0 16px; border-bottom: 1px solid var(--neutral-border, #e5e6eb); }
.acct-meta { display: flex; flex-direction: column; gap: 4px; }
.acct-name { font-size: 16px; font-weight: 600; color: var(--neutral-text-1, #1d2129); }
.acct-email { font-size: 12px; color: var(--neutral-text-2, #86909c); }
.info-row { display: flex; justify-content: space-between; font-size: 13px; padding: 6px 0; color: var(--neutral-text-2, #4e5969); }
.acct-stats { padding: 12px 0; border-bottom: 1px solid var(--neutral-border, #e5e6eb); }
.acct-stats :deep(.n-statistic-value__content) { font-size: 20px; font-weight: 600; }
.txn-section { padding-top: 16px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--neutral-text-1, #1d2129); margin-bottom: 16px; }
.txn-row { display: flex; flex-direction: column; gap: 6px; }
.txn-top { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.txn-desc { font-size: 13px; color: var(--neutral-text-1, #1d2129); }
.txn-amount { font-size: 14px; font-weight: 600; white-space: nowrap; }
.txn-amount.plus { color: var(--arco-success); }
.txn-amount.minus { color: var(--arco-danger); }
.txn-foot { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--neutral-text-2, #86909c); }
</style>
