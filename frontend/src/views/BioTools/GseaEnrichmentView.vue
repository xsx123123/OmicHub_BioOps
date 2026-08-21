<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NFormItem, NInput, NSelect, NSpace, NTag } from 'naive-ui'
import * as Plotly from 'plotly.js-dist-min'
import PageHeader from '@/components/PageHeader.vue'
import { downloadGseaResult, submitGsea, fetchGseaTask, type GseaTask } from '@/api/gsea'

const speciesId = ref('human')
const geneSet = ref('GO_BP')
const rankingText = ref('')
const status = ref<'idle' | 'ready' | 'queued' | 'running' | 'completed' | 'failed'>('idle')
const task = ref<GseaTask | null>(null)
const plotContainer = ref<HTMLDivElement | null>(null)
const exportDpi = ref<300 | 600 | 1000>(300)
const termColumns = [
  { title: 'ID', key: 'id' },
  { title: 'Description', key: 'description' },
  { title: 'NES', key: 'nes' },
  { title: 'p.adjust', key: 'p_adjust' },
]

const rankingCount = computed(() => rankingText.value.trim().split(/\r?\n/).filter(Boolean).length)
const canSubmit = computed(() => rankingCount.value >= 10)

function loadExample() {
  rankingText.value = [
    'gene_id\tscore',
    'TP53\t3.21',
    'BRCA1\t2.84',
    'EGFR\t1.96',
    'MYC\t1.42',
    'CDK1\t0.88',
    'GAPDH\t0.31',
    'ACTB\t-0.24',
    'PTEN\t-1.16',
    'FOXP3\t-2.08',
    'IL6\t-3.41',
  ].join('\n')
  status.value = 'ready'
}

async function renderPlot() {
  await nextTick()
  if (!plotContainer.value || !task.value?.running_score?.length) return
  await Plotly.react(plotContainer.value, [{ x: task.value.running_score.map(point => point.rank), y: task.value.running_score.map(point => point.score), type: 'scatter', mode: 'lines', line: { color: '#165DFF' } }], { title: { text: 'GSEA Running Enrichment Score' }, xaxis: { title: { text: 'Rank in Ordered Dataset' } }, yaxis: { title: { text: 'Running Enrichment Score' } }, margin: { t: 48, r: 20, b: 48, l: 56 } }, { responsive: true, displaylogo: false })
}

function exportPlot(format: 'png' | 'svg') {
  if (!plotContainer.value) return
  const options = {
    format,
    filename: `gsea_running_score_${exportDpi.value}dpi`,
    width: 1200,
    height: 720,
    scale: format === 'png' ? exportDpi.value / 96 : 1,
  }
  void Plotly.downloadImage(plotContainer.value, options as any)
}

watch(() => task.value?.running_score, renderPlot, { deep: true })
onBeforeUnmount(() => { if (plotContainer.value) Plotly.purge(plotContainer.value) })

async function markReady() {
  if (!canSubmit.value) return
  const payload = new FormData()
  payload.append('gene_ranking', rankingText.value)
  payload.append('species_id', speciesId.value)
  payload.append('gene_set', geneSet.value)
  try {
    task.value = await submitGsea(payload)
    status.value = task.value.status
    while (task.value.status === 'queued' || task.value.status === 'running') {
      await new Promise(resolve => setTimeout(resolve, 1500))
      task.value = await fetchGseaTask(task.value.task_id)
      status.value = task.value.status
    }
  } catch { status.value = 'failed' }
}
</script>

<template>
  <div class="gsea-page page-container">
    <PageHeader title="GSEA 富集分析" subtitle="基于全基因排序列表识别 GO / KEGG 富集趋势">
      <template #actions><NButton size="small" @click="loadExample">载入示例</NButton></template>
    </PageHeader>

    <div class="gsea-layout">
      <NCard title="分析输入" size="small">
        <NFormItem label="物种"><NInput v-model:value="speciesId" placeholder="例如 human" /></NFormItem>
        <NFormItem label="基因集">
          <NSelect v-model:value="geneSet" :options="['GO_BP', 'GO_MF', 'GO_CC', 'KEGG'].map(value => ({ label: value, value }))" />
        </NFormItem>
        <NFormItem label="排序基因列表">
          <NInput v-model:value="rankingText" type="textarea" :autosize="{ minRows: 14, maxRows: 24 }" placeholder="gene_id&#9;score&#10;TP53&#9;3.21" />
        </NFormItem>
        <NSpace justify="space-between" align="center">
          <NTag :type="rankingCount >= 10 ? 'success' : 'warning'">{{ rankingCount }} 行</NTag>
          <NButton type="primary" :disabled="!canSubmit" @click="markReady">提交分析</NButton>
        </NSpace>
      </NCard>

      <NCard title="任务与结果" size="small">
        <NAlert v-if="status === 'idle'" type="info" :show-icon="false">提交后将在这里显示 queued、running、completed 或 failed 状态，以及按来源分组的 running score 曲线与结果表。</NAlert>
        <NAlert v-else :type="status === 'failed' ? 'error' : status === 'completed' ? 'success' : 'info'" :show-icon="false">状态：{{ status }}。{{ task?.message || '任务处理中' }}<span v-if="task?.error_message"> {{ task.error_message }}</span></NAlert>
        <template v-if="task?.status === 'completed'">
          <div ref="plotContainer" class="gsea-plot" aria-label="GSEA running enrichment score curve" />
          <NSpace justify="space-between" align="center">
            <strong>Top terms</strong>
            <NSpace>
              <NSelect v-model:value="exportDpi" size="small" :options="[300, 600, 1000].map(value => ({ label: `${value} DPI`, value }))" style="width: 120px" />
              <NButton size="small" @click="exportPlot('png')">PNG</NButton>
              <NButton size="small" @click="exportPlot('svg')">SVG</NButton>
              <NButton size="small" @click="downloadGseaResult(task!.task_id)">CSV</NButton>
            </NSpace>
          </NSpace>
          <NDataTable :columns="termColumns" :data="task.top_terms" :bordered="false" size="small" />
        </template>
      </NCard>
    </div>
  </div>
</template>

<style scoped>
.gsea-page { display: flex; flex-direction: column; gap: 16px; }
.gsea-layout { display: grid; grid-template-columns: minmax(320px, 0.9fr) minmax(0, 1.1fr); gap: 16px; }
.gsea-plot { min-height: 280px; width: 100%; }
@media (max-width: 900px) { .gsea-layout { grid-template-columns: 1fr; } }
</style>
