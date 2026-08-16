<script setup lang="ts">
import { NButton, NEmpty, NSpin, NTag } from 'naive-ui'
import type { BlastTaskListItem } from '@/types/blast'
import type { SequenceStats } from '@/utils/sequenceAnalysis'

defineProps<{
  sequenceStats: SequenceStats
  recentTasks: BlastTaskListItem[]
  loadingTasks: boolean
}>()

const emit = defineEmits<{
  selectTask: [task: BlastTaskListItem]
  rerunTask: [task: BlastTaskListItem]
}>()

const statusText: Record<string, string> = {
  queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消',
}
const statusType: Record<string, 'default' | 'success' | 'warning' | 'error'> = {
  queued: 'default', running: 'warning', completed: 'success', failed: 'error', cancelled: 'default',
}

function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString() : '-'
}
</script>

<template>
  <div class="right-panel">
    <section class="info-card">
      <div class="card-heading">
        <h3>序列实时分析</h3>
        <NTag
          size="small"
          :type="sequenceStats.type === 'nucl' ? 'success' : sequenceStats.type === 'prot' ? 'info' : 'default'"
        >
          {{ sequenceStats.type === 'nucl' ? '核酸' : sequenceStats.type === 'prot' ? '蛋白' : '待识别' }}
        </NTag>
      </div>
      <div class="stats-grid">
        <div><strong>{{ sequenceStats.length.toLocaleString() }}</strong><span>序列长度</span></div>
        <div><strong>{{ sequenceStats.gcContent.toFixed(1) }}%</strong><span>GC 含量</span></div>
        <div><strong>{{ sequenceStats.nContent.toFixed(1) }}%</strong><span>N/未知比例</span></div>
      </div>
      <div class="recommendation" :class="{ active: sequenceStats.recommendedProgram }">
        <strong>{{ sequenceStats.recommendedProgram || '算法推荐' }}</strong>
        <span>{{ sequenceStats.recommendationReason }}</span>
      </div>
    </section>

    <section class="info-card">
      <div class="card-heading"><h3>最近任务</h3><span>最近 5 条</span></div>
      <NSpin :show="loadingTasks">
        <NEmpty v-if="!recentTasks.length" size="small" description="暂无 BLAST 任务" />
        <div v-else class="task-list">
          <div v-for="task in recentTasks" :key="task.task_id" class="task-item" @click="emit('selectTask', task)">
            <div class="task-main">
              <div class="task-title">{{ task.query_title || task.task_id.slice(0, 12) }}</div>
              <div class="task-meta">{{ task.db_name }} · {{ formatTime(task.submitted_at) }}</div>
            </div>
            <NTag size="small" :type="statusType[task.status] || 'default'">{{ statusText[task.status] || task.status }}</NTag>
            <NButton size="tiny" quaternary @click.stop="emit('rerunTask', task)">重新运行</NButton>
          </div>
        </div>
      </NSpin>
    </section>
  </div>
</template>

<style scoped>
.right-panel { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.info-card { min-width: 0; padding: 14px; border: 1px solid var(--neutral-border); border-radius: 12px; background: var(--neutral-card); }
.card-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
.card-heading h3 { margin: 0; font-size: 13px; color: var(--neutral-text-1); }
.card-heading > span { font-size: 11px; color: var(--neutral-text-3); }
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.stats-grid div { display: flex; flex-direction: column; padding: 9px; border-radius: 8px; background: var(--neutral-bg); }
.stats-grid strong { font-size: 16px; color: var(--neutral-text-1); }
.stats-grid span { margin-top: 2px; font-size: 10px; color: var(--neutral-text-3); }
.recommendation { display: flex; flex-direction: column; gap: 3px; margin-top: 10px; padding: 9px; border-radius: 8px; background: var(--neutral-bg); }
.recommendation.active { background: rgba(24, 160, 88, .1); }
.recommendation strong { color: var(--primary-color); font-size: 12px; }
.recommendation span { color: var(--neutral-text-2); font-size: 11px; }
.task-list { display: flex; flex-direction: column; gap: 6px; }
.task-item { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 6px; padding: 7px; border-radius: 8px; cursor: pointer; }
.task-item:hover { background: var(--neutral-bg); }
.task-main { min-width: 0; }
.task-title, .task-meta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-title { color: var(--neutral-text-1); font-size: 12px; }
.task-meta { color: var(--neutral-text-3); font-size: 10px; }
dl { display: grid; gap: 7px; margin: 0; }
dl div { display: grid; grid-template-columns: 92px 1fr; gap: 6px; font-size: 11px; }
dt { font-weight: 600; color: var(--neutral-text-1); }
dd { margin: 0; color: var(--neutral-text-2); }
@media (max-width: 1200px) { .right-panel { grid-template-columns: 1fr 1fr; } }
@media (max-width: 700px) { .right-panel { grid-template-columns: 1fr; } }
</style>
