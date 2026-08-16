<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NButton, NCard, NDataTable, NSpace, NSelect, NInput, NTag, NIcon,
  NAvatar, NEmpty, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  AddOutline, SearchOutline, WarningOutline, DocumentTextOutline, CashOutline,
} from '@vicons/ionicons5'
import { useAdminCookieStore, type AdminCookieAccount, type AdminCookieTxn } from '@/stores/adminCookie'
import CookieStatsDashboard from '@/components/admin-cookie/CookieStatsDashboard.vue'
import RechargeModal from '@/components/admin-cookie/RechargeModal.vue'
import CookieTransactionDrawer from '@/components/admin-cookie/CookieTransactionDrawer.vue'
import PageHeader from '@/components/PageHeader.vue'
import { displayName } from '@/utils/displayName'

withDefaults(defineProps<{ embedded?: boolean }>(), {
  embedded: false,
})

const message = useMessage()
const store = useAdminCookieStore()

// ===== 弹窗 / 抽屉状态 =====
const showRecharge = ref(false)
const presetUserId = ref<string | null>(null)
const showDrawer = ref(false)
const drawerAccount = ref<AdminCookieAccount | null>(null)
const drawerTxns = ref<AdminCookieTxn[]>([])
const drawerLoading = ref(false)

const statusOptions = [
  { label: '全部', value: 'all' },
  { label: '正常', value: 'active' },
  { label: '冻结', value: 'frozen' },
]

function openRechargeAlloc() {
  presetUserId.value = null
  showRecharge.value = true
}

function openRechargeRow(row: AdminCookieAccount) {
  presetUserId.value = row.user_id
  showRecharge.value = true
}

async function openDrawer(row: AdminCookieAccount) {
  drawerAccount.value = row
  drawerTxns.value = []
  showDrawer.value = true
  drawerLoading.value = true
  try {
    drawerTxns.value = await store.fetchUserTxns(row.user_id)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '流水加载失败')
  } finally {
    drawerLoading.value = false
  }
}

async function onRechargeSuccess() {
  try {
    await Promise.all([store.fetchAccounts(), store.fetchStats()])
    if (drawerAccount.value) {
      drawerTxns.value = await store.fetchUserTxns(drawerAccount.value.user_id)
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '刷新账户数据失败')
  }
}

function commitSearch() {
  store.fetchAccounts()
}

const columns: DataTableColumns<AdminCookieAccount> = [
  {
    title: '用户信息', key: 'username', width: 240,
    render: (row) =>
      h('div', { class: 'user-cell' }, [
        h(NAvatar, { round: true, size: 34, style: { background: 'var(--arco-primary)' } },
          { default: () => displayName(row).slice(0, 1).toUpperCase() }),
        h('div', { class: 'user-meta' }, [
          h('div', { class: 'user-name' }, displayName(row)),
          h('div', { class: 'user-email' }, row.email),
        ]),
      ]),
  },
  {
    title: '所属课题组', key: 'lab_group', width: 140,
    render: (row) => row.lab_group
      ? h(NTag, { size: 'small', round: true, bordered: false }, { default: () => row.lab_group })
      : h('span', { class: 'muted' }, '—'),
  },
  {
    title: '系统角色', key: 'role', width: 100,
    render: (row) => h(NTag, { size: 'small', round: true, type: row.role === 'admin' ? 'success' : 'default' },
      { default: () => (row.role === 'admin' ? '管理员' : '用户') }),
  },
  {
    title: '当前余额', key: 'balance', width: 130,
    render: (row) => {
      const low = row.balance < 50
      return h('span', { class: ['balance', { danger: row.balance < 0, warn: low && row.balance >= 0 }] }, [
        low ? h(NIcon, { component: WarningOutline, style: { marginRight: '4px' } }) : null,
        `${row.balance} 🥫`,
      ])
    },
  },
  { title: '累计消耗', key: 'total_spent', width: 120, render: (row) => `${row.total_spent} 🥫` },
  {
    title: '账户状态', key: 'status', width: 110,
    render: (row) => {
      if (row.status === 'frozen') return h(NTag, { type: 'error', size: 'small', round: true }, { default: () => '🔴 冻结' })
      if (row.balance < 0) return h(NTag, { type: 'error', size: 'small', round: true }, { default: () => '🔴 欠费' })
      return h(NTag, { type: 'success', size: 'small', round: true }, { default: () => '🟢 正常' })
    },
  },
  {
    title: '操作', key: 'actions', width: 200, fixed: 'right',
    render: (row) =>
      h(NSpace, { size: 0 }, {
        default: () => [
          h(NButton, { text: true, type: 'primary', onClick: () => openRechargeRow(row) },
            { default: () => [h(NIcon, { component: CashOutline }), ' 变更余额'] }),
          h(NButton, { text: true, type: 'info', onClick: () => openDrawer(row) },
            { default: () => [h(NIcon, { component: DocumentTextOutline }), ' 资产流水'] }),
        ],
      }),
  },
]

onMounted(async () => {
  await Promise.all([store.fetchAccounts(), store.fetchStats()])
})
</script>

<template>
  <div class="page-container" :class="{ 'page-container--embedded': embedded }">
    <PageHeader v-if="!embedded" title="饼干账户管理" subtitle="查看用户余额、账户状态与交易明细" />

    <NSpace vertical :size="20">
      <CookieStatsDashboard :stats="store.stats" :loading="store.loading" />

      <NCard :bordered="false" class="arco-card toolbar-card">
        <div class="toolbar">
          <NButton type="primary" size="medium" @click="openRechargeAlloc">
            <template #icon><NIcon :component="AddOutline" /></template>
            主动分配 / 划拨饼干
          </NButton>
          <div class="toolbar-search">
            <NSelect v-model:value="store.statusFilter" :options="statusOptions" style="width: 140px" @update:value="commitSearch" />
            <NInput
              v-model:value="store.search"
              placeholder="用户名 / 邮箱 / 用户 ID"
              style="width: 300px"
              clearable
              @keyup.enter="commitSearch"
              @clear="commitSearch"
            >
              <template #prefix><NIcon :component="SearchOutline" /></template>
            </NInput>
            <NButton size="medium" @click="commitSearch">搜索</NButton>
          </div>
        </div>
      </NCard>

      <NCard :bordered="false" class="arco-card">
        <NDataTable
          :columns="columns"
          :data="store.accounts"
          :loading="store.loading"
          :pagination="{ pageSize: 10, showSizePicker: true, pageSizes: [10, 20, 50] }"
          :scroll-x="1000"
          :bordered="false"
          size="medium"
          :row-key="(r: AdminCookieAccount) => r.user_id"
        >
          <template #empty>
            <div class="table-empty">
              <NEmpty description="没有匹配的饼干账户">
                <template #extra>
                  <NButton size="small" @click="commitSearch">清除搜索条件</NButton>
                </template>
              </NEmpty>
            </div>
          </template>
        </NDataTable>
      </NCard>
    </NSpace>

    <RechargeModal
      v-model:show="showRecharge"
      :user-id="presetUserId"
      @success="onRechargeSuccess"
    />
    <CookieTransactionDrawer
      v-model:show="showDrawer"
      :account="drawerAccount"
      :txns="drawerTxns"
      :loading="drawerLoading"
    />
  </div>
</template>

<style scoped>
.page-container--embedded { padding: 0; background: transparent; }
.toolbar-card :deep(.n-card__content) { padding: 16px 20px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.toolbar-search { display: flex; align-items: center; gap: 12px; }
:deep(.user-cell) { display: flex; align-items: center; gap: 10px; }
:deep(.user-meta) { display: flex; flex-direction: column; }
:deep(.user-name) { font-size: 14px; font-weight: 500; color: var(--neutral-text-1, #1d2129); }
:deep(.user-email) { font-size: 12px; color: var(--neutral-text-2, #86909c); }
:deep(.muted) { color: var(--neutral-text-4, #c9cdd4); }
:deep(.balance) { font-weight: 600; display: inline-flex; align-items: center; }
:deep(.balance.danger) { color: var(--arco-danger); }
:deep(.balance.warn) { color: var(--arco-warning, #FF7D00); }
.table-empty { padding: 48px 0; }
</style>
