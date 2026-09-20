<script setup lang="ts">
/**
 * 数据库健康（管理员 · 只读观测）— 迁移版本同步状态、表数量、连接池占用、
 * 只读副本配置，以及 ORM metadata ↔ 数据库 schema 漂移对账明细。
 * 数据来自 /admin/database/health 与 /admin/database/drift，不做任何写操作。
 */
import { computed, h, onMounted, ref } from 'vue'
import {
  NAlert, NButton, NCard, NDataTable, NEmpty, NIcon, NSkeleton, NSpace, NTag,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import PageHeader from '@/components/PageHeader.vue'
import {
  adminDatabaseApi,
  type DatabaseHealth,
  type SchemaDrift,
} from '@/api/admin/database'

const message = useMessage()

const health = ref<DatabaseHealth | null>(null)
const drift = ref<SchemaDrift | null>(null)
const loading = ref(false)
const loadError = ref('')

async function fetchAll(options?: { silent?: boolean }) {
  loading.value = true
  loadError.value = ''
  try {
    const [h, d] = await Promise.all([
      adminDatabaseApi.getHealth(),
      adminDatabaseApi.getDrift(),
    ])
    health.value = h
    drift.value = d
    if (!options?.silent) message.success('数据库健康状态已刷新')
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || '加载数据库健康状态失败'
    message.error(loadError.value)
  } finally {
    loading.value = false
  }
}

onMounted(() => fetchAll({ silent: true }))

// ===== 概览状态（文字 + 颜色双重表达） =====
const syncStatus = computed(() => {
  if (!health.value) return null
  return health.value.version_in_sync
    ? { type: 'success' as const, label: '正常 · 已同步' }
    : { type: 'error' as const, label: '异常 · 版本不一致' }
})

const replicaStatus = computed(() => {
  if (!health.value) return null
  return health.value.readonly_replica_configured
    ? { type: 'success' as const, label: '已配置' }
    : { type: 'default' as const, label: '未配置（回退主库）' }
})

const poolUsageText = computed(() => {
  const pool = health.value?.pool
  if (!pool) return '—'
  if (pool.size === undefined) return `${pool.class}（无容量统计）`
  return `${pool.checked_out ?? 0} / ${pool.size} 已借出`
})

const poolStatus = computed(() => {
  const pool = health.value?.pool
  if (!pool || !pool.size) return { type: 'default' as const, label: '—' }
  const ratio = (pool.checked_out ?? 0) / pool.size
  if (ratio >= 0.9) return { type: 'error' as const, label: '紧张' }
  if (ratio >= 0.7) return { type: 'warning' as const, label: '偏高' }
  return { type: 'success' as const, label: '正常' }
})

// ===== 漂移明细表 =====
interface DriftRow {
  kind: '缺失表' | '缺失列' | '多余表'
  severity: 'error' | 'warning'
  name: string
  detail: string
}

const driftRows = computed<DriftRow[]>(() => {
  const d = drift.value
  if (!d) return []
  const rows: DriftRow[] = []
  for (const t of d.missing_tables) {
    rows.push({ kind: '缺失表', severity: 'error', name: t, detail: 'ORM metadata 需要，但数据库中不存在该表' })
  }
  for (const c of d.missing_columns) {
    rows.push({ kind: '缺失列', severity: 'error', name: c, detail: 'ORM metadata 需要，但数据库中不存在该列' })
  }
  for (const t of d.extra_tables) {
    rows.push({ kind: '多余表', severity: 'warning', name: t, detail: '数据库中存在但 metadata 未声明（仅告警，不影响判定）' })
  }
  return rows
})

const driftColumns: DataTableColumns<DriftRow> = [
  {
    title: '类型',
    key: 'kind',
    width: 110,
    align: 'center',
    render: (row) =>
      h(NTag, { size: 'small', type: row.severity, bordered: false }, { default: () => row.kind }),
  },
  {
    title: '对象',
    key: 'name',
    width: 420,
    ellipsis: { tooltip: true },
    render: (row) => h('span', { class: 'mono' }, row.name),
  },
  {
    title: '说明',
    key: 'detail',
    width: 460,
    ellipsis: { tooltip: true },
  },
]
const DRIFT_SCROLL_X = 110 + 420 + 460
</script>

<template>
  <div class="database-health">
    <PageHeader
      title="数据库健康"
      subtitle="只读观测：Alembic 迁移版本同步、表数量、连接池占用、只读副本配置，以及 ORM metadata ↔ 数据库 schema 漂移对账"
    >
      <template #actions>
        <NButton secondary :loading="loading" aria-label="刷新数据库健康状态" @click="fetchAll()">
          <template #icon><NIcon :component="RefreshOutline" /></template>
          刷新
        </NButton>
      </template>
    </PageHeader>

    <NAlert v-if="loadError" type="error" class="section-card" closable @close="loadError = ''">
      {{ loadError }}（以下展示最近一次成功的数据）
      <template #icon>
        <NButton size="small" tertiary :loading="loading" @click="fetchAll()">重试</NButton>
      </template>
    </NAlert>

    <section class="section-card" aria-label="数据库健康概览">
      <div v-if="loading && !health" class="overview-skeleton">
        <NSkeleton v-for="i in 4" :key="i" height="96px" :sharp="false" />
      </div>
      <div v-else-if="health" class="overview-grid">
        <NCard size="small" class="overview-item">
          <div class="overview-label">迁移版本同步</div>
          <div class="overview-value">
            <NTag v-if="syncStatus" :type="syncStatus.type" :bordered="false">{{ syncStatus.label }}</NTag>
          </div>
          <div class="overview-meta mono">
            库内 {{ health.alembic_db_version.join(', ') || '无' }} · 代码 head {{ health.alembic_head.join(', ') || '无' }}
          </div>
        </NCard>
        <NCard size="small" class="overview-item">
          <div class="overview-label">public 表数量</div>
          <div class="overview-value">{{ health.table_count }}</div>
          <div class="overview-meta">information_schema 实时统计</div>
        </NCard>
        <NCard size="small" class="overview-item">
          <div class="overview-label">连接池占用</div>
          <div class="overview-value">
            <NSpace align="center" :size="8" :wrap="false">
              <span>{{ poolUsageText }}</span>
              <NTag :type="poolStatus.type" size="small" :bordered="false">{{ poolStatus.label }}</NTag>
            </NSpace>
          </div>
          <div class="overview-meta">
            {{ health.pool.class }}<template v-if="health.pool.checked_in !== undefined">
              · 空闲 {{ health.pool.checked_in }} · 溢出 {{ health.pool.overflow ?? 0 }}
            </template>
          </div>
        </NCard>
        <NCard size="small" class="overview-item">
          <div class="overview-label">只读副本</div>
          <div class="overview-value">
            <NTag v-if="replicaStatus" :type="replicaStatus.type" :bordered="false">{{ replicaStatus.label }}</NTag>
          </div>
          <div class="overview-meta">服务：{{ health.service_name }}</div>
        </NCard>
      </div>
    </section>

    <section class="section-card" aria-label="Schema 漂移明细">
      <NCard size="small" class="table-card">
        <template #header>
          <span class="card-title">Schema 漂移明细</span>
        </template>
        <template #header-extra>
          <span class="card-count">
            方向：代码需要的，库里必须有；多余表仅告警
            <template v-if="drift"> · 共 {{ driftRows.length }} 条</template>
          </span>
        </template>
        <NEmpty
          v-if="drift && driftRows.length === 0"
          description="无漂移：ORM metadata 与数据库一致"
          class="drift-empty"
        />
        <NDataTable
          v-else
          :columns="driftColumns"
          :data="driftRows"
          :loading="loading"
          :row-key="(row: DriftRow) => `${row.kind}:${row.name}`"
          :scroll-x="DRIFT_SCROLL_X"
          :pagination="{ pageSize: 20 }"
          size="small"
        />
      </NCard>
    </section>
  </div>
</template>

<style scoped>
.database-health { display: flex; flex-direction: column; }
.section-card { margin-bottom: 24px; }

.overview-skeleton {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-md);
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-md);
}
.overview-item { border-radius: var(--radius-md); }
.overview-label { font-size: var(--font-caption-size); color: var(--neutral-text-3); margin-bottom: var(--space-sm); }
.overview-value {
  font-size: var(--font-card-title-size);
  font-weight: var(--font-card-title-weight);
  color: var(--neutral-text-1);
  min-height: 26px;
  display: flex;
  align-items: center;
}
.overview-meta {
  margin-top: 6px;
  font-size: var(--font-caption-size);
  color: var(--neutral-text-3);
  word-break: break-all;
}

.table-card { border-radius: var(--radius-md); width: 100%; }
.table-card :deep(.n-data-table) { width: 100%; }
.card-title { font-size: var(--font-card-title-size); font-weight: var(--font-card-title-weight); color: var(--neutral-text-1); }
.card-count { font-size: var(--font-caption-size); color: var(--neutral-text-3); font-variant-numeric: tabular-nums; }
.drift-empty { padding: var(--space-xl) 0; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
</style>
