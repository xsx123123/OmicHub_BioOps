import { computed, ref } from 'vue'
import type { Ref } from 'vue'

// ===== 类型定义（与后端 CookieAccount/CookieTransaction 对齐，便于后续替换为真实接口） =====
export type AccountStatus = 'active' | 'frozen'

export interface CookieAccountRow {
  user_id: string
  username: string
  email: string
  avatar_color: string
  group: string
  balance: number
  total_spent: number
  status: AccountStatus
}

export type TxnSource = 'flow' | 'ai' | 'admin' | 'signup'

export interface CookieTxn {
  id: number
  user_id: string
  date: string // ISO yyyy-mm-dd
  description: string
  amount: number // 正数=增加，负数=消耗
  balance_after: number
  source: TxnSource
}

export type StatusFilter = 'all' | 'active' | 'insufficient'

export interface CookieMetrics {
  circulatingTotal: number // 流通总饼干数（历史累计发放）
  todayTotalSpend: number // 今日总消耗
  monthTotalSpend: number // 本月总消耗
  activeRechargeAccounts: number // 本月有过增加代币记录的账户数
  circulatingTrend: number // 环比趋势百分比
}

// 课题组池
const GROUPS = ['王鑫课题组', '作物遗传实验室', '张鹏课题组', '基因组学小组', '蛋白组学小组']
// 头像背景色池（与 --arco-* 主色系协调）
const AVATAR_COLORS = ['#165DFF', '#00B42A', '#FF7D00', '#722ED1', '#0FC6C2', '#F53F3F']

const USERS: Omit<CookieAccountRow, 'avatar_color' | 'group'>[] = [
  { user_id: 'u_zhangjian', username: 'Zhang Jian', email: 'zhangjian@cygnusx.cn', balance: 1280, total_spent: 3420, status: 'active' },
  { user_id: 'u_lisi', username: '李四', email: 'lisi@cygnusx.cn', balance: 35, total_spent: 880, status: 'active' },
  { user_id: 'u_wangwu', username: '王五', email: 'wangwu@cygnusx.cn', balance: 0, total_spent: 2100, status: 'frozen' },
  { user_id: 'u_zhaoliu', username: '赵六', email: 'zhaoliu@cygnusx.cn', balance: 642, total_spent: 1560, status: 'active' },
  { user_id: 'u_qianqi', username: '钱七', email: 'qianqi@cygnusx.cn', balance: 48, total_spent: 520, status: 'active' },
  { user_id: 'u_sunba', username: '孙八', email: 'sunba@cygnusx.cn', balance: 2310, total_spent: 4870, status: 'active' },
  { user_id: 'u_zhoujiu', username: '周九', email: 'zhoujiu@cygnusx.cn', balance: 156, total_spent: 1340, status: 'active' },
  { user_id: 'u_wushi', username: '吴十', email: 'wushi@cygnusx.cn', balance: 12, total_spent: 980, status: 'frozen' },
  { user_id: 'u_zhengshen', username: '郑深', email: 'zhengshen@cygnusx.cn', balance: 880, total_spent: 670, status: 'active' },
  { user_id: 'u_fengxue', username: '冯雪', email: 'fengxue@cygnusx.cn', balance: 524, total_spent: 1090, status: 'active' },
  { user_id: 'u_chenchen', username: '陈晨', email: 'chenchen@cygnusx.cn', balance: 3120, total_spent: 7250, status: 'active' },
  { user_id: 'u_weiyi', username: '魏一', email: 'weiyi@cygnusx.cn', balance: 42, total_spent: 360, status: 'active' },
  { user_id: 'u_jiangshan', username: '蒋珊', email: 'jiangshan@cygnusx.cn', balance: 730, total_spent: 2210, status: 'active' },
]

// 用确定性 hash 给用户分配头像色与课题组，避免每次刷新跳变
function hash(str: string): number {
  let h = 0
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0
  return Math.abs(h)
}

function buildAccounts(): CookieAccountRow[] {
  return USERS.map((u, idx) => ({
    ...u,
    group: GROUPS[idx % GROUPS.length],
    avatar_color: AVATAR_COLORS[hash(u.user_id) % AVATAR_COLORS.length],
  }))
}

// 为每个用户构造流水（含本月及今日记录，便于看板统计）
const FLOW_TEMPLATES = [
  { desc: '执行 RNAFlow 转录组流程', amount: -50, source: 'flow' as TxnSource },
  { desc: '执行 DNAFlow 变异检测流程', amount: -120, source: 'flow' as TxnSource },
  { desc: '调用 AI 助手解释代码', amount: -2, source: 'ai' as TxnSource },
  { desc: '调用 AI 助手生成分析报告', amount: -8, source: 'ai' as TxnSource },
  { desc: '沙箱环境按量计费', amount: -15, source: 'flow' as TxnSource },
]
const RECHARGE_TEMPLATES = [
  { desc: '管理员后台充值', amount: 500, source: 'admin' as TxnSource },
  { desc: '注册赠送新用户礼包', amount: 200, source: 'signup' as TxnSource },
  { desc: '人工调账补偿', amount: 300, source: 'admin' as TxnSource },
]

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function dateStr(daysAgo: number): string {
  // 以"今天"为基准回推，daysAgo=0 即今日；不使用 Date.now() 之外的随机性
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function buildTxns(accounts: CookieAccountRow[]): Map<string, CookieTxn[]> {
  const map = new Map<string, CookieTxn[]>()
  let id = 1
  for (const acc of accounts) {
    const list: CookieTxn[] = []
    // 起点：注册赠送（月初之前）
    let balance = 0
    const signupDate = dateStr(28)
    const signup = RECHARGE_TEMPLATES[1]
    balance += signup.amount
    list.push({ id: id++, user_id: acc.user_id, date: signupDate, description: signup.desc, amount: signup.amount, balance_after: balance, source: signup.source })

    // 历史流水：最近 25 天内若干条
    for (let d = 25; d >= 0; d--) {
      // 每隔几天产生一条消耗
      if ((hash(acc.user_id) + d) % 3 === 0) {
        const t = FLOW_TEMPLATES[(hash(acc.user_id) + d) % FLOW_TEMPLATES.length]
        balance += t.amount
        list.push({ id: id++, user_id: acc.user_id, date: dateStr(d), description: t.desc, amount: t.amount, balance_after: balance, source: t.source })
      }
      // 本月内随机一次充值（保证"活跃充值账户数"有数据）
      if (d <= 25 && (hash(acc.user_id) * 7 + d) % 11 === 0) {
        const r = RECHARGE_TEMPLATES[(hash(acc.user_id) + d) % RECHARGE_TEMPLATES.length]
        balance += r.amount
        list.push({ id: id++, user_id: acc.user_id, date: dateStr(d), description: r.desc, amount: r.amount, balance_after: balance, source: r.source })
      }
    }

    // 保证至少有一条"今日"记录用于看板"今日总消耗"
    if (!list.some(t => t.date === dateStr(0))) {
      const t = FLOW_TEMPLATES[hash(acc.user_id) % FLOW_TEMPLATES.length]
      balance += t.amount
      list.push({ id: id++, user_id: acc.user_id, date: dateStr(0), description: t.desc, amount: t.amount, balance_after: balance, source: t.source })
    }
    map.set(acc.user_id, list.reverse()) // 最新在前
  }
  return map
}

export function useCookieAccounts() {
  const accounts: Ref<CookieAccountRow[]> = ref(buildAccounts())
  const txnsMap = buildTxns(accounts.value)

  // ===== 过滤状态 =====
  const statusFilter = ref<StatusFilter>('all')
  const keyword = ref('')
  const searchInput = ref('') // 输入框双向绑定，失焦/回车才同步到 keyword

  const today = dateStr(0)
  const thisMonth = today.slice(0, 7)

  function isInsufficient(acc: CookieAccountRow): boolean {
    return acc.balance < 50
  }

  const filteredAccounts = computed<CookieAccountRow[]>(() => {
    const kw = keyword.value.trim().toLowerCase()
    return accounts.value.filter((acc) => {
      if (statusFilter.value === 'active' && acc.status !== 'active') return false
      if (statusFilter.value === 'insufficient' && !isInsufficient(acc)) return false
      if (kw) {
        const hit = acc.username.toLowerCase().includes(kw) || acc.group.toLowerCase().includes(kw) || acc.email.toLowerCase().includes(kw)
        if (!hit) return false
      }
      return true
    })
  })

  // ===== 大盘统计 =====
  const metrics = computed<CookieMetrics>(() => {
    let circulatingTotal = 0
    let todayTotalSpend = 0
    let monthTotalSpend = 0
    const rechargersThisMonth = new Set<string>()

    for (const acc of accounts.value) {
      // 流通总饼干数 = 当前余额 + 历史累计消耗 ≈ 历史累计发放
      circulatingTotal += acc.balance + acc.total_spent
    }
    for (const [uid, list] of txnsMap) {
      for (const t of list) {
        if (t.amount < 0) {
          if (t.date === today) todayTotalSpend += -t.amount
          if (t.date.startsWith(thisMonth)) monthTotalSpend += -t.amount
        } else if (t.date.startsWith(thisMonth)) {
          rechargersThisMonth.add(uid)
        }
      }
    }
    return {
      circulatingTotal,
      todayTotalSpend,
      monthTotalSpend,
      activeRechargeAccounts: rechargersThisMonth.size,
      circulatingTrend: 12.6,
    }
  })

  function getTxns(userId: string): CookieTxn[] {
    return txnsMap.get(userId) ?? []
  }

  function applyAdjust(payload: { userId: string; type: 'add' | 'deduct'; amount: number; remark: string }) {
    const acc = accounts.value.find(a => a.user_id === payload.userId)
    if (!acc) return
    const delta = payload.type === 'add' ? payload.amount : -payload.amount
    acc.balance = Math.max(0, acc.balance + delta)
    if (payload.type === 'deduct') acc.total_spent += payload.amount
    // 欠费自动冻结 / 充值解冻
    if (acc.balance <= 0) acc.status = 'frozen'
    else if (acc.status === 'frozen' && payload.type === 'add') acc.status = 'active'

    const list = txnsMap.get(payload.userId) ?? []
    list.unshift({
      id: (list[0]?.id ?? 0) + 1,
      user_id: payload.userId,
      date: today,
      description: payload.remark || (payload.type === 'add' ? '管理员后台充值' : '管理员扣除'),
      amount: delta,
      balance_after: acc.balance,
      source: 'admin',
    })
  }

  function commitSearch() {
    keyword.value = searchInput.value
  }

  return {
    accounts,
    filteredAccounts,
    statusFilter,
    keyword,
    searchInput,
    metrics,
    isInsufficient,
    getTxns,
    applyAdjust,
    commitSearch,
  }
}
