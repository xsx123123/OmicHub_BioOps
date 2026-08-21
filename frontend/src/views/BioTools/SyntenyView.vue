<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NFormItem, NInput, NSpace, NTag } from 'naive-ui'
import * as Plotly from 'plotly.js-dist-min'
import PageHeader from '@/components/PageHeader.vue'
import { downloadSyntenyResult, submitSynteny, fetchSyntenyTask, type SyntenyTask } from '@/api/synteny'

const gff3Text = ref('')
const blastpText = ref('')
const chromosomeFilter = ref('')
const status = ref<'idle' | 'ready' | 'queued' | 'running' | 'completed' | 'failed'>('idle')
const task = ref<SyntenyTask | null>(null)
const plotContainer = ref<HTMLDivElement | null>(null)
const blockColumns = [
  { title: 'Block', key: 'block_id' },
  { title: 'Chromosome A', key: 'chromosome_a' },
  { title: 'Chromosome B', key: 'chromosome_b' },
  { title: 'Gene pairs', key: 'gene_pairs' },
]
const pairCount = computed(() => blastpText.value.trim().split(/\r?\n/).filter(Boolean).length)
const exceedsPointLimit = computed(() => pairCount.value > 50_000)
const canSubmit = computed(() => gff3Text.value.trim() && blastpText.value.trim() && !exceedsPointLimit.value)

function loadExample() {
  gff3Text.value = '##gff-version 3\nchr1\tOmicHub\tgene\t100\t500\t.\t+\t.\tID=geneA\nchr2\tOmicHub\tgene\t120\t480\t.\t+\t.\tID=geneB'
  blastpText.value = 'geneA\tgeneB\t98.0\t120\t0\t0\t1\t120\t1\t120\t1e-40\t220'
  status.value = 'ready'
}

async function markReady() {
  if (!canSubmit.value) return
  const payload = new FormData()
  payload.append('gff3_text', gff3Text.value)
  payload.append('blastp_text', blastpText.value)
  if (chromosomeFilter.value.trim()) payload.append('chromosome_filter', chromosomeFilter.value)
  try {
    task.value = await submitSynteny(payload)
    status.value = task.value.status
    while (task.value.status === 'queued' || task.value.status === 'running') {
      await new Promise(resolve => setTimeout(resolve, 1500))
      task.value = await fetchSyntenyTask(task.value.task_id)
      status.value = task.value.status
    }
  } catch { status.value = 'failed' }
}

async function renderPlot() {
  await nextTick()
  if (!plotContainer.value || !task.value?.points?.length) return
  await Plotly.react(plotContainer.value, [{ x: task.value.points.map(point => point.x), y: task.value.points.map(point => point.y), type: 'scattergl', mode: 'markers', text: task.value.points.map(point => `${point.query_gene} ↔ ${point.subject_gene}`), marker: { color: '#722ED1', size: 5, opacity: 0.72 } }], { title: { text: 'Genome Synteny Dot Plot' }, xaxis: { title: { text: 'Query genome coordinate' } }, yaxis: { title: { text: 'Subject genome coordinate' } }, margin: { t: 48, r: 20, b: 48, l: 64 } }, { responsive: true, displaylogo: false })
}

watch(() => task.value?.points, renderPlot, { deep: true })
onBeforeUnmount(() => { if (plotContainer.value) Plotly.purge(plotContainer.value) })
</script>

<template>
  <div class="synteny-page page-container">
    <PageHeader title="基因组共线性分析" subtitle="使用 GFF3 与 BLASTP outfmt6 识别共线性区块并渲染 dot plot">
      <template #actions><NButton size="small" @click="loadExample">载入示例</NButton></template>
    </PageHeader>
    <div class="synteny-layout">
      <NCard title="分析输入" size="small">
        <NFormItem label="GFF3 注释"><NInput v-model:value="gff3Text" type="textarea" :autosize="{ minRows: 8, maxRows: 14 }" placeholder="支持粘贴或聊天 upload:// 文件引用" /></NFormItem>
        <NFormItem label="BLASTP outfmt6"><NInput v-model:value="blastpText" type="textarea" :autosize="{ minRows: 8, maxRows: 14 }" placeholder="query&#9;subject&#9;identity ..." /></NFormItem>
        <NFormItem label="染色体过滤（可选）"><NInput v-model:value="chromosomeFilter" placeholder="例如 chr1,chr2" /></NFormItem>
        <NAlert v-if="exceedsPointLimit" type="warning" :show-icon="false">检测到超过 50,000 个基因对。请先按染色体过滤，再生成 scattergl dot plot。</NAlert>
        <NSpace justify="space-between" align="center"><NTag :type="exceedsPointLimit ? 'warning' : 'success'">{{ pairCount }} 基因对</NTag><NButton type="primary" :disabled="!canSubmit" @click="markReady">提交分析</NButton></NSpace>
      </NCard>
      <NCard title="任务与结果" size="small">
        <NAlert v-if="status === 'idle'" type="info" :show-icon="false">任务完成后展示交互式 scattergl dot plot、可点击区块表以及 TSV / JSON 导出。</NAlert>
        <NAlert v-else :type="status === 'failed' ? 'error' : status === 'completed' ? 'success' : 'info'" :show-icon="false">状态：{{ status }}。{{ task?.message || '任务处理中' }}<span v-if="task?.error_message"> {{ task.error_message }}</span></NAlert>
        <template v-if="task?.status === 'completed'">
          <div ref="plotContainer" class="synteny-plot" aria-label="Genome synteny dot plot" />
          <NSpace justify="space-between" align="center"><strong>共线性区块</strong><NButton size="small" @click="downloadSyntenyResult(task!.task_id)">导出 JSON</NButton></NSpace>
          <NDataTable :columns="blockColumns" :data="task.blocks" :bordered="false" size="small" />
        </template>
      </NCard>
    </div>
  </div>
</template>

<style scoped>
.synteny-page { display: flex; flex-direction: column; gap: 16px; }
.synteny-layout { display: grid; grid-template-columns: minmax(320px, 0.9fr) minmax(0, 1.1fr); gap: 16px; }
.synteny-plot { min-height: 300px; width: 100%; }
@media (max-width: 900px) { .synteny-layout { grid-template-columns: 1fr; } }
</style>
