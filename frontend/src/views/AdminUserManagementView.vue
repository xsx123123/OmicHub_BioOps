<script setup lang="ts">
import apiClient from '@/api/client'
import {
  NButton,
  NCard,
  NDataTable,
  NDropdown,
  NIcon,
  NModal,
  NSpace,
  NSpin,
  NTag,
  NTooltip,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  EllipsisHorizontal,
  CreateOutline,
  ServerOutline,
  PersonOutline,
  TrashOutline,
  CashOutline,
  DocumentTextOutline,
  LockClosedOutline,
  CheckmarkCircle,
  CloseCircleOutline,
} from '@vicons/ionicons5'
import { h, computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AddUserModal from '@/components/AddUserModal.vue'
import QuotaEditModal from '@/components/QuotaEditModal.vue'
import NoteEditModal from '@/components/NoteEditModal.vue'
import ModulePermissionsModal from '@/components/ModulePermissionsModal.vue'
import AdminTOTPConfirmModal from '@/components/AdminTOTPConfirmModal.vue'
import RechargeModal from '@/components/admin-cookie/RechargeModal.vue'
import { useAuthStore } from '@/stores/auth'
import { useModulesStore } from '@/stores/modules'
import { displayName } from '@/utils/displayName'
import PageHeader from '@/components/PageHeader.vue'

interface AdminUser {
  id: string
  username: string
  nickname?: string | null
  email: string
  role: string
  status: string
  created_at: string
  last_login_at: string | null
  storage_quota: number
  used_storage: number
  admin_note?: string | null
  lab_group?: string | null
  cookie_balance?: number | null
  cookie_status?: string | null
  disabled_modules?: string[]
}

const message = useMessage()
const authStore = useAuthStore()
const modulesStore = useModulesStore()
const router = useRouter()
const users = ref<AdminUser[]>([])
const loading = ref(false)

// 快捷充值弹窗（与「饼干账户管理」共用同一组件）
const showRecharge = ref(false)
const rechargeUserId = ref<string | null>(null)

// 添加用户弹窗
const addUserModalVisible = ref(false)

// 调整配额弹窗
const quotaModalVisible = ref(false)
const quotaTarget = ref<AdminUser | null>(null)

// 编辑备注弹窗
const noteModalVisible = ref(false)
const noteTarget = ref<AdminUser | null>(null)

// 模块权限弹窗
const modulePermModalVisible = ref(false)
const modulePermTarget = ref<AdminUser | null>(null)

// 高敏感操作：TOTP 二次确认弹窗
const totpModalVisible = ref(false)
const totpTargetId = ref<string | null>(null)
const totpTargetUsername = ref('')
const totpLoading = ref(false)

const statusTag = (status: string) => {
  const map: Record<string, 'success' | 'warning' | 'error' | 'default'> = {
    active: 'success',
    pending: 'warning',
    rejected: 'error',
    inactive: 'default',
  }
  return map[status] || 'default'
}

/** "更多▾"下拉菜单：低频/破坏性操作收纳于此 */
function buildMoreOptions(row: AdminUser) {
  const opts: any[] = [
    { label: '编辑备注', key: 'note', icon: () => h(NIcon, null, { default: () => h(CreateOutline) }) },
    { label: '修改配额', key: 'quota', icon: () => h(NIcon, null, { default: () => h(ServerOutline) }) },
    { label: '💰 快捷充值饼干', key: 'recharge', icon: () => h(NIcon, null, { default: () => h(CashOutline) }) },
    { label: '📄 查看资产流水', key: 'txns', icon: () => h(NIcon, null, { default: () => h(DocumentTextOutline) }) },
    // 模块权限：管理员行禁用（防自锁），tooltip 说明原因
    {
      label: () =>
        row.role === 'admin'
          ? h(
              NTooltip,
              { placement: 'left' },
              {
                trigger: () => h('span', '模块权限'),
                default: () => '管理员默认拥有全部模块权限',
              },
            )
          : '模块权限',
      key: 'module-permissions',
      disabled: row.role === 'admin',
      icon: () => h(NIcon, null, { default: () => h(LockClosedOutline) }),
    },
  ]
  // 升降管理员：仅 active 用户可调权（已拒绝账号调权无意义）
  if (row.status === 'active') {
    opts.push({
      label: row.role === 'admin' ? '降为用户' : '升为管理员',
      key: 'role',
      icon: () => h(NIcon, null, { default: () => h(PersonOutline) }),
    })
  }
  return opts
}

/** 下拉菜单选中处理（删除不在此处理，走 TOTP 二次确认弹窗） */
function handleMoreSelect(key: string, row: AdminUser) {
  if (key === 'note') openNoteModal(row)
  else if (key === 'quota') openQuotaModal(row)
  else if (key === 'role') toggleRole(row)
  else if (key === 'recharge') openRecharge(row)
  else if (key === 'txns') viewTxns(row)
  else if (key === 'module-permissions') openModulePermissions(row)
}

function openRecharge(row: AdminUser) {
  rechargeUserId.value = row.id
  showRecharge.value = true
}

function viewTxns(row: AdminUser) {
  router.push({ name: 'admin-cookies-transactions', query: { user_id: row.id } })
}

const columns: DataTableColumns<AdminUser> = [
  {
    title: '用户',
    key: 'username',
    render: (row) => displayName(row),
  },
  { title: '邮箱', key: 'email', ellipsis: { tooltip: true } },
  {
    title: '角色',
    key: 'role',
    render: (row) =>
      h(
        NTag,
        { type: row.role === 'admin' ? 'success' : 'default', size: 'small', round: true },
        { default: () => (row.role === 'admin' ? '管理员' : '用户') },
      ),
  },
  {
    title: '状态',
    key: 'status',
    render: (row) => {
      const tags: any[] = [
        h(NTag, { type: statusTag(row.status), size: 'small', round: true }, { default: () => row.status }),
      ]
      // 资产穿透：饼干余额为负 → 红色「欠费」Tag
      if (typeof row.cookie_balance === 'number' && row.cookie_balance < 0) {
        tags.push(h(NTag, { type: 'error', size: 'small', round: true }, { default: () => '欠费' }))
      }
      return h(NSpace, { size: 4, align: 'center' }, { default: () => tags })
    },
  },
  {
    title: '备注',
    key: 'admin_note',
    ellipsis: { tooltip: true },
    render: (row) =>
      row.admin_note
        ? h('span', { class: 'note-cell' }, row.admin_note)
        : h('span', { class: 'note-empty' }, '—'),
  },
  {
    title: '注册时间',
    key: 'created_at',
    render: (row) => (row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-'),
  },
  {
    title: '存储用量',
    key: 'storage',
    width: 160,
    render: (row) => {
      const usedGb = (row.used_storage || 0) / 1024 / 1024 / 1024
      const totalGb = (row.storage_quota || 0) / 1024 / 1024 / 1024
      const pct = totalGb > 0 ? Math.min(100, (usedGb / totalGb) * 100) : 0
      const color = pct >= 91 ? '#FF6B6B' : pct >= 71 ? '#FFC53D' : '#36CFC9'
      return h('div', { class: 'storage-cell' }, [
        h('div', { class: 'storage-bar' }, [
          h('div', { class: 'storage-bar-fill', style: { width: `${pct}%`, background: color } }),
        ]),
        h('span', { class: 'storage-text' }, `${usedGb.toFixed(1)} / ${totalGb.toFixed(0)} GiB`),
      ])
    },
  },
  {
    title: '当前饼干余额',
    key: 'cookie_balance',
    width: 120,
    render: (row) => {
      const bal = typeof row.cookie_balance === 'number' ? row.cookie_balance : 0
      const cls = bal < 0 ? 'cookie-danger' : bal < 50 ? 'cookie-warn' : 'cookie-normal'
      return h('span', { class: ['cookie-balance', cls] }, `${bal} 🥫`)
    },
  },
  {
    title: '最后登录',
    key: 'last_login_at',
    render: (row) => (row.last_login_at ? new Date(row.last_login_at).toLocaleString('zh-CN') : '从未登录'),
  },
  {
    title: '操作',
    key: 'actions',
    width: 200,
    fixed: 'right',
    render: (row) => {
      const primary: any[] = []

      // ===== 主操作：与状态最相关的核心动作，外露 =====
      if (row.status === 'pending') {
        primary.push(
          h(NButton, { size: 'small', type: 'success', onClick: () => approveUser(row.id) }, { default: () => '通过' }),
        )
        primary.push(
          h(NButton, { size: 'small', type: 'error', ghost: true, onClick: () => rejectUser(row.id) }, { default: () => '拒绝' }),
        )
      } else if (row.status === 'rejected') {
        // 已拒绝：提供"重新通过"捞回误拒用户
        primary.push(
          h(
            NButton,
            { size: 'small', type: 'success', ghost: true, onClick: () => approveUser(row.id) },
            { default: () => '重新通过' },
          ),
        )
      } else if (row.status === 'active' || row.status === 'inactive') {
        // 启用/禁用：不能禁用自己
        const isSelf = row.id === authStore.user?.id
        const disabling = row.status === 'active'
        primary.push(
          h(
            NButton,
            {
              size: 'small',
              type: 'warning',
              ghost: true,
              disabled: isSelf && disabling,
              title: isSelf && disabling ? '不能禁用当前登录账号' : '',
              onClick: () => toggleStatus(row),
            },
            { default: () => (disabling ? '禁用' : '启用') },
          ),
        )
      }

      // ===== 次要操作：收纳进"更多▾"下拉 =====
      const isSelf = row.id === authStore.user?.id
      const moreDropdown = h(
        NDropdown,
        {
          trigger: 'click',
          options: buildMoreOptions(row),
          onSelect: (key: string) => handleMoreSelect(key, row),
        },
        {
          default: () =>
            h(
              NButton,
              { size: 'small', quaternary: true },
              {
                default: () => '更多',
                icon: () => h(NIcon, null, { default: () => h(EllipsisHorizontal) }),
              },
            ),
        },
      )

      // 删除：高危，独立放最右，TOTP 二次确认弹窗
      const deleteBtn = h(
        NButton,
        {
          size: 'small',
          type: 'error',
          ghost: true,
          disabled: isSelf,
          title: isSelf ? '不能删除当前登录账号' : '删除该用户',
          onClick: () => openDeleteWithTotp(row),
        },
        { default: () => '删除' },
      )

      return h(NSpace, { size: 4, align: 'center' }, { default: () => [...primary, moreDropdown, deleteBtn] })
    },
  },
]

async function fetchUsers() {
  loading.value = true
  try {
    const res = await apiClient.get<AdminUser[]>('/admin/users')
    users.value = res.data
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '用户列表加载失败')
  } finally {
    loading.value = false
  }
}

async function approveUser(id: string) {
  await apiClient.put(`/admin/users/${id}/approve`)
  message.success('已审批通过')
  await fetchUsers()
}

async function rejectUser(id: string) {
  await apiClient.put(`/admin/users/${id}/reject`)
  message.success('已拒绝')
  await fetchUsers()
}

async function toggleRole(row: AdminUser) {
  const newRole = row.role === 'admin' ? 'user' : 'admin'
  await apiClient.put(`/admin/users/${row.id}/role`, null, { params: { role: newRole } })
  message.success(`已设为 ${newRole === 'admin' ? '管理员' : '用户'}`)
  await fetchUsers()
}

// 启用/禁用账号：禁用后用户登录被拒
async function toggleStatus(row: AdminUser) {
  const newStatus = row.status === 'active' ? 'inactive' : 'active'
  await apiClient.put(`/admin/users/${row.id}/status`, null, { params: { status: newStatus } })
  message.success(newStatus === 'active' ? '账号已启用' : '账号已禁用')
  await fetchUsers()
}

// 删除：先弹 TOTP 二次确认，再请求后端（带 X-TOTP-Code 请求头）
function openDeleteWithTotp(row: AdminUser) {
  totpTargetId.value = row.id
  totpTargetUsername.value = row.username
  totpModalVisible.value = true
}

async function handleTotpConfirm(code: string) {
  if (!totpTargetId.value) return
  totpLoading.value = true
  try {
    await deleteUser(totpTargetId.value, code)
    totpModalVisible.value = false
    totpTargetId.value = null
    totpTargetUsername.value = ''
  } finally {
    totpLoading.value = false
  }
}

async function deleteUser(id: string, totpCode: string) {
  try {
    await apiClient.delete(`/admin/users/${id}`, {
      headers: { 'X-TOTP-Code': totpCode },
    })
    message.success('用户已删除')
    await fetchUsers()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '删除失败')
  }
}

function openQuotaModal(row: AdminUser) {
  quotaTarget.value = row
  quotaModalVisible.value = true
}

function openNoteModal(row: AdminUser) {
  noteTarget.value = row
  noteModalVisible.value = true
}

function openModulePermissions(row: AdminUser) {
  modulePermTarget.value = row
  modulePermModalVisible.value = true
}

// 备注保存成功后，本地同步更新该行备注（免一次全量拉取）
function onNoteSaved(userId: string, note: string) {
  const row = users.value.find((u) => u.id === userId)
  if (row) row.admin_note = note
}

/* ===== 模块权限矩阵（页面下半部分，表格样式） ===== */
// 可锁模块列：从注册表渲染（禁止写死模块名），AI 模块排前
const lockableModules = computed(() =>
  [...modulesStore.registry.filter((m) => m.lockable)].sort(
    (a, b) => Number(b.ai) - Number(a.ai),
  ),
)

// 单元格保存中状态：key = `${userId}:${moduleKey}`
const moduleCellSaving = ref<Record<string, boolean>>({})

// 管理员行彩蛋：点管理员的对号时弹出搞怪提示
const adminEggVisible = ref(false)
const adminEggQuips = [
  '权限结界生效中：管理员的模块一个都关不掉 ✨',
  '想关管理员？管理员笑而不语 🔒',
  '这枚对号被神秘力量焊死了，放弃吧 🛡️',
  '管理员：我就静静看着你点，反正关不掉 😼',
]
const adminEggQuip = ref(adminEggQuips[0])

function openAdminEgg() {
  adminEggQuip.value = adminEggQuips[Math.floor(Math.random() * adminEggQuips.length)]
  adminEggVisible.value = true
}

function isModuleEnabled(row: AdminUser, moduleKey: string): boolean {
  if (row.role === 'admin') return true
  return !(row.disabled_modules ?? []).includes(moduleKey)
}

function enabledCount(row: AdminUser): number {
  return lockableModules.value.filter((m) => isModuleEnabled(row, m.key)).length
}

// 开关 = 开通；切换即保存该用户的完整禁用列表，失败回滚（受控组件未改数据即回退）
async function toggleModule(row: AdminUser, moduleKey: string, enabled: boolean) {
  if (row.role === 'admin') return
  const cellKey = `${row.id}:${moduleKey}`
  moduleCellSaving.value[cellKey] = true
  const lockableKeys = lockableModules.value.map((m) => m.key)
  const disabled = new Set((row.disabled_modules ?? []).filter((k) => lockableKeys.includes(k)))
  if (enabled) disabled.delete(moduleKey)
  else disabled.add(moduleKey)
  try {
    const res = await apiClient.put(`/admin/users/${row.id}/modules`, {
      disabled_modules: [...disabled],
    })
    row.disabled_modules = res.data?.disabled_modules ?? [...disabled]
    message.success('模块权限已更新')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '保存失败')
  } finally {
    moduleCellSaving.value[cellKey] = false
  }
}

const moduleColumns = computed<DataTableColumns<AdminUser>>(() => {
  const cols: DataTableColumns<AdminUser> = [
    {
      title: '用户',
      key: 'username',
      width: 200,
      fixed: 'left',
      render: (row) =>
        h('div', { class: 'perm-user-cell' }, [
          h('div', { class: 'perm-user-name' }, displayName(row)),
          h('div', { class: 'perm-user-email' }, row.email),
        ]),
    },
    ...lockableModules.value.map((mod) => ({
      title: mod.name,
      key: `mod_${mod.key}`,
      width: 120,
      align: 'center' as const,
      render: (row: AdminUser) => {
        const cellKey = `${row.id}:${mod.key}`
        const isAdminRow = row.role === 'admin'
        const enabled = isModuleEnabled(row, mod.key)
        const body = moduleCellSaving.value[cellKey]
          ? h(NSpin, { size: 14 })
          : h(
              NIcon,
              { size: 18, class: enabled ? 'perm-icon-on' : 'perm-icon-off' },
              { default: () => h(enabled ? CheckmarkCircle : CloseCircleOutline) },
            )
        // 整格点击切换；管理员行只读，点击弹彩蛋
        return h(
          'span',
          {
            class: ['perm-cell', { 'perm-cell-readonly': isAdminRow }],
            title: isAdminRow ? '管理员默认拥有全部模块权限' : enabled ? '点击禁用该模块' : '点击开通该模块',
            onClick: () => {
              if (isAdminRow) openAdminEgg()
              else if (!moduleCellSaving.value[cellKey]) toggleModule(row, mod.key, !enabled)
            },
          },
          [body],
        )
      },
    })),
    {
      title: '已开通',
      key: 'enabled_count',
      width: 90,
      align: 'center' as const,
      render: (row: AdminUser) =>
        h(
          'span',
          { class: 'perm-count' },
          row.role === 'admin' ? '全部' : `${enabledCount(row)} / ${lockableModules.value.length}`,
        ),
    },
  ]
  return cols
})

const moduleScrollX = computed(() => 200 + lockableModules.value.length * 120 + 90)

onMounted(() => {
  fetchUsers()
  modulesStore.ensureLoaded()
})
</script>

<template>
  <div class="page-container">
    <PageHeader title="用户管理" subtitle="维护账号状态、配额与管理员备注">
      <template #actions>
        <NButton type="primary" @click="addUserModalVisible = true">添加用户</NButton>
      </template>
    </PageHeader>
    <NCard title="用户列表" :bordered="false" class="arco-card">
      <NDataTable
        :columns="columns"
        :data="users"
        :row-key="(row) => row.id"
        :loading="loading"
        :pagination="{ pageSize: 20 }"
        :bordered="false"
        size="small"
        :scroll-x="1400"
      />
    </NCard>

    <!-- 模块权限矩阵：行=用户，列=可锁模块（AI 模块排前），开关 = 开通，切换即保存 -->
    <NCard title="模块权限" :bordered="false" class="arco-card module-perm-card">
      <p class="module-perm-desc">
        对号 = 开通该模块，叉号 = 禁用（点击即可切换，即时保存）；禁用后用户侧显示锁定，接口同步拦截。管理员默认拥有全部模块权限。
      </p>
      <NDataTable
        :columns="moduleColumns"
        :data="users"
        :row-key="(row) => row.id"
        :loading="loading || !modulesStore.loaded"
        :pagination="{ pageSize: 20 }"
        :bordered="false"
        size="small"
        :scroll-x="moduleScrollX"
      />
    </NCard>
    <AddUserModal v-model:show="addUserModalVisible" @success="fetchUsers" />

    <!-- 调整存储配额弹窗 -->
    <QuotaEditModal v-model:show="quotaModalVisible" :user="quotaTarget" @success="fetchUsers" />

    <!-- 编辑管理员备注弹窗 -->
    <NoteEditModal
      v-model:show="noteModalVisible"
      :user="noteTarget"
      @success="(note: string) => onNoteSaved(noteTarget?.id || '', note)"
    />

    <!-- 模块权限弹窗 -->
    <ModulePermissionsModal
      v-model:show="modulePermModalVisible"
      :user="modulePermTarget"
      @success="fetchUsers"
    />

    <!-- 快捷充值饼干（与饼干账户管理共用同一全局组件） -->
    <RechargeModal
      v-model:show="showRecharge"
      :user-id="rechargeUserId"
      @success="fetchUsers"
    />
    <!-- 管理员模块权限彩蛋弹窗 -->
    <NModal v-model:show="adminEggVisible" :auto-focus="false" transform-origin="center">
      <div class="admin-egg">
        <div class="admin-egg-icon">
          <NIcon :size="30"><LockClosedOutline /></NIcon>
        </div>
        <h3 class="admin-egg-title">权限结界</h3>
        <p class="admin-egg-text">{{ adminEggQuip }}</p>
        <NButton type="primary" @click="adminEggVisible = false">知道啦</NButton>
      </div>
    </NModal>

    <!-- 删除用户 TOTP 二次确认弹窗 -->
    <AdminTOTPConfirmModal
      v-model:show="totpModalVisible"
      :title="`删除用户：${totpTargetUsername}`"
      :description="`确认彻底删除用户「${totpTargetUsername}」？此操作不可恢复，请输入当前 6 位 TOTP 验证码。`"
      confirm-text="确认删除"
      :loading="totpLoading"
      @confirm="handleTotpConfirm"
    />
  </div>
</template>

<style scoped>
.user-mgmt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.user-mgmt-header .page-title {
  margin: 0;
}
.note-cell {
  color: var(--neutral-text-2, #4e5969);
  font-size: 13px;
}
.module-perm-card {
  margin-top: 16px;
}
/* 模块列表头不换行（长模块名由列宽与横向滚动兜底） */
.module-perm-card :deep(.n-data-table-th) {
  white-space: nowrap;
}
.module-perm-desc {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
}
/* 注意：矩阵单元格是 h() 渲染函数创建、由 NDataTable 内部渲染，
   元素不会带本组件的 scoped 属性，必须经 :deep() 从容器穿透 */
.module-perm-card :deep(.perm-user-cell) {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.module-perm-card :deep(.perm-user-name) {
  font-size: 13px;
  color: var(--neutral-text-1, #1d2129);
}
.module-perm-card :deep(.perm-user-email) {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}
.module-perm-card :deep(.perm-count) {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}
.module-perm-card :deep(.perm-cell) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.module-perm-card :deep(.perm-cell:hover) {
  background: var(--neutral-hover, #f2f3f5);
}
.module-perm-card :deep(.perm-cell-readonly) {
  cursor: pointer;
}
.admin-egg {
  width: 360px;
  max-width: calc(100vw - 32px);
  background: var(--neutral-card, #fff);
  border-radius: 12px;
  padding: 28px 24px 24px;
  box-sizing: border-box;
  text-align: center;
}
.admin-egg-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto 12px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f0ff;
  color: #8b5cf6;
  animation: admin-egg-shake 0.5s ease;
}
.admin-egg-title {
  margin: 0 0 8px;
  font-size: 17px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}
.admin-egg-text {
  margin: 0 0 20px;
  font-size: 14px;
  line-height: 22px;
  color: var(--neutral-text-3, #86909c);
}
/* 一次性抖动，彩蛋打开时执行一次 */
@keyframes admin-egg-shake {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(-12deg); }
  50% { transform: rotate(10deg); }
  75% { transform: rotate(-6deg); }
}
.module-perm-card :deep(.perm-icon-on) {
  color: var(--arco-success, #00b42a);
}
.module-perm-card :deep(.perm-icon-off) {
  color: var(--arco-danger, #f53f3f);
}
.note-empty {
  color: var(--neutral-text-4, #c9cdd4);
}
.storage-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.storage-bar {
  height: 6px;
  border-radius: 3px;
  background: var(--neutral-fill, #e5e6eb);
  overflow: hidden;
}
.storage-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}
.storage-text {
  font-size: 11px;
  color: var(--neutral-text-3, #86909c);
}
.cookie-balance {
  font-weight: 600;
  font-size: 13px;
}
.cookie-balance.cookie-normal {
  color: var(--arco-success, #00B42A);
}
.cookie-balance.cookie-warn {
  color: var(--arco-warning, #FF7D00);
}
.cookie-balance.cookie-danger {
  color: var(--arco-danger, #F53F3F);
}
</style>
