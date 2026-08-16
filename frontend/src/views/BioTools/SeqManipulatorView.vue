<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NDataTable,
  NIcon,
  NInput,
  NInputNumber,
  NSelect,
  NStatistic,
  NTabPane,
  NTabs,
  NTag,
  NTooltip,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import {
  AnalyticsOutline,
  BarChartOutline,
  BrushOutline,
  CalculatorOutline,
  ChatbubbleEllipsesOutline,
  CopyOutline,
  DownloadOutline,
  GitNetworkOutline,
  HardwareChipOutline,
  LinkOutline,
  PulseOutline,
  RefreshOutline,
  SearchOutline,
  SparklesOutline,
  SwapHorizontalOutline,
} from '@vicons/ionicons5'
import PageHeader from '@/components/PageHeader.vue'
import OrfPanel from '@/components/sequence-studio/OrfPanel.vue'
import ResultViewerPanel from '@/components/sequence-studio/ResultViewerPanel.vue'
import SequenceInputPanel from '@/components/sequence-studio/SequenceInputPanel.vue'
import SequenceViewer from '@/components/sequence-studio/SequenceViewer.vue'
import { findMotifs, findOrfs } from '@/engine/analysis/orfFinder'
import { generateSequenceAiPrompt } from '@/engine/ai/aiAssistant'
import { calculateStats, reverseComplement, reverseTranscribe, transcribe } from '@/engine/dna/dna'
import { storeSequenceHandoff } from '@/engine/ecosystemLinks'
import { cleanSequence, formatToFasta, parseFasta } from '@/engine/parser/fastaParser'
import { CODON_TABLES, reverseTranslate, translateSequence } from '@/engine/protein/translator'
import type {
  FastaRecord,
  MotifMatch,
  OrfMatch,
  SequenceResultItem,
  SequenceStats,
} from '@/engine/types'

const router = useRouter()
const message = useMessage()

type OperationKey = 'reverse-complement' | 'transcribe' | 'reverse-transcribe' | 'translate'
  | 'reverse-translate' | 'statistics' | 'clean' | 'orf' | 'motif'
type AnalysisTab = 'statistics' | 'orf' | 'viewer' | 'ai'

interface OperationItem {
  key: OperationKey
  label: string
  description: string
  icon: Component
  accepts: Array<FastaRecord['type']>
}

interface OperationGroup {
  title: string
  items: OperationItem[]
}

const operationGroups: OperationGroup[] = [
  {
    title: 'DNA / RNA 操作',
    items: [
      { key: 'reverse-complement', label: '反向互补', description: '支持完整 IUPAC 简并碱基', icon: RefreshOutline, accepts: ['dna', 'rna', 'unknown'] },
      { key: 'transcribe', label: 'DNA → RNA', description: '转录并保留字符大小写', icon: SwapHorizontalOutline, accepts: ['dna', 'unknown'] },
      { key: 'reverse-transcribe', label: 'RNA → cDNA', description: '将 U 转换为 T', icon: SwapHorizontalOutline, accepts: ['rna', 'unknown'] },
      { key: 'clean', label: '序列清理', description: '按识别类型过滤无效字符', icon: BrushOutline, accepts: ['dna', 'rna', 'protein', 'unknown'] },
    ],
  },
  {
    title: '蛋白与翻译',
    items: [
      { key: 'translate', label: '六框翻译', description: '支持多密码子表', icon: CalculatorOutline, accepts: ['dna', 'rna', 'unknown'] },
      { key: 'reverse-translate', label: '蛋白反向翻译', description: '生成确定性代表密码子', icon: HardwareChipOutline, accepts: ['protein'] },
    ],
  },
  {
    title: '统计与高级搜索',
    items: [
      { key: 'statistics', label: '序列统计', description: 'GC、AT、N 与分子量', icon: BarChartOutline, accepts: ['dna', 'rna', 'protein', 'unknown'] },
      { key: 'orf', label: 'ORF Finder', description: '扫描正反链六个读码框', icon: PulseOutline, accepts: ['dna', 'rna', 'unknown'] },
      { key: 'motif', label: 'Motif Search', description: '支持 IUPAC 模式匹配', icon: SearchOutline, accepts: ['dna', 'rna', 'unknown'] },
    ],
  },
]

const inputText = ref('')
const selectedRecordId = ref('')
const selectedOperation = ref<OperationKey>('reverse-complement')
const resultTitle = ref('运算结果')
const resultItems = ref<SequenceResultItem[]>([])
const durationMs = ref(0)
const activeAnalysisTab = ref<AnalysisTab>('statistics')
const codonTableId = ref('1')
const initMet = ref(true)
const minimumOrfLength = ref(30)
const motifPattern = ref('ATG')
const orfRows = ref<OrfMatch[]>([])
const motifRows = ref<MotifMatch[]>([])
const selectedOrf = ref<OrfMatch | null>(null)

const records = computed(() => parseFasta(inputText.value))
const selectedRecord = computed(() => records.value.find((record) => record.id === selectedRecordId.value) || records.value[0] || null)
const selectedStats = computed<SequenceStats | null>(() => selectedRecord.value ? calculateStats(selectedRecord.value.sequence) : null)
const activeOperation = computed(() => operationGroups.flatMap((group) => group.items).find((item) => item.key === selectedOperation.value))
const codonTableOptions = CODON_TABLES.map((table) => ({ label: table.name, value: table.id }))
const recordOptions = computed(() => records.value.map((record) => ({ label: `${record.id} · ${record.length.toLocaleString()} ${record.type === 'protein' ? 'aa' : 'nt'}`, value: record.id })))
const operationAllowed = computed(() => {
  if (!selectedRecord.value || !activeOperation.value) return false
  return activeOperation.value.accepts.includes(selectedRecord.value.type)
})
const aiPrompt = computed(() => selectedRecord.value && selectedStats.value
  ? generateSequenceAiPrompt(selectedRecord.value, selectedStats.value, orfRows.value.length)
  : '')
const viewerSequence = computed(() => selectedOrf.value?.dnaSequence || selectedRecord.value?.sequence || '')
const viewerHighlights = computed(() => {
  if (selectedOrf.value) return [{ start: 1, end: selectedOrf.value.lengthNt, color: 'color-mix(in srgb, var(--arco-success) 20%, transparent)', label: selectedOrf.value.id }]
  if (orfRows.value.length) return orfRows.value.slice(0, 24).map((orf) => ({ start: orf.start, end: orf.end, color: 'color-mix(in srgb, var(--arco-primary) 18%, transparent)', label: `${orf.id} · frame ${orf.frame}` }))
  return motifRows.value.slice(0, 100).map((motif) => ({ start: motif.start, end: motif.end, color: 'color-mix(in srgb, var(--arco-warning) 24%, transparent)', label: `${motif.name} · ${motif.strand}` }))
})

const motifColumns: DataTableColumns<MotifMatch> = [
  { title: 'Motif', key: 'name', width: 120, ellipsis: { tooltip: true } },
  { title: 'Pattern', key: 'pattern', width: 120, align: 'center' },
  { title: 'Start', key: 'start', width: 90, align: 'center' },
  { title: 'End', key: 'end', width: 90, align: 'center' },
  { title: 'Strand', key: 'strand', width: 90, align: 'center' },
]

watch(records, (nextRecords) => {
  if (!nextRecords.some((record) => record.id === selectedRecordId.value)) {
    selectedRecordId.value = nextRecords[0]?.id || ''
  }
}, { immediate: true })

function loadSample() {
  inputText.value = `>rice_ACTB_fragment
ATGGCAGACGCAGATGAGATCAAGGCCAAGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGATGGCAGACGCAGATGAGATCAAGGCCAAGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGGCGTAA
>arabidopsis_motif_demo
ATGAAACCCGGGTTTATGCGCATGTTTGGGCCCTAA`
  message.success('已载入两条示例 DNA 序列')
}

function requireRecords(): FastaRecord[] | null {
  if (!records.value.length) {
    message.warning('请先输入或上传序列')
    return null
  }
  return records.value
}

function toResult(record: FastaRecord, sequence: string, suffix: string, type = record.type): SequenceResultItem {
  return {
    id: `${record.id}_${suffix}`,
    header: `${record.header} | ${suffix}`,
    sequence,
    type,
  }
}

function runOperation(operation: OperationKey = selectedOperation.value) {
  selectedOperation.value = operation
  const allRecords = requireRecords()
  if (!allRecords) return
  if (!operationAllowed.value && operation !== 'clean' && operation !== 'statistics') {
    message.warning(`${activeOperation.value?.label || '当前操作'}不适用于 ${selectedRecord.value?.type.toUpperCase()}`)
    return
  }

  const startedAt = performance.now()
  selectedOrf.value = null
  const availableRecords = operation === 'clean' || operation === 'statistics'
    ? allRecords
    : allRecords.filter((record) => activeOperation.value?.accepts.includes(record.type))
  if (!availableRecords.length && operation !== 'orf' && operation !== 'motif') {
    message.warning('没有与当前操作兼容的序列')
    return
  }

  if (operation === 'reverse-complement') {
    resultTitle.value = '反向互补结果'
    resultItems.value = availableRecords.map((record) => toResult(record, reverseComplement(record.sequence, record.type === 'rna'), 'reverse_complement'))
    activeAnalysisTab.value = 'viewer'
  } else if (operation === 'transcribe') {
    resultTitle.value = 'DNA → RNA'
    resultItems.value = availableRecords.map((record) => toResult(record, transcribe(record.sequence), 'transcribed', 'rna'))
  } else if (operation === 'reverse-transcribe') {
    resultTitle.value = 'RNA → cDNA'
    resultItems.value = availableRecords.map((record) => toResult(record, reverseTranscribe(record.sequence), 'cdna', 'dna'))
  } else if (operation === 'translate') {
    resultTitle.value = '六框翻译结果'
    resultItems.value = availableRecords.flatMap((record) => Object.entries(translateSequence(record.sequence, {
      codonTableId: codonTableId.value,
      frame: 'all',
      initMet: initMet.value,
    })).map(([frame, sequence]) => toResult(record, sequence, `frame_${Number(frame) > 0 ? '+' : ''}${frame}`, 'protein')))
  } else if (operation === 'reverse-translate') {
    resultTitle.value = '蛋白反向翻译结果'
    resultItems.value = availableRecords.map((record) => toResult(record, reverseTranslate(record.sequence), 'reverse_translated', 'dna'))
  } else if (operation === 'clean') {
    resultTitle.value = '清理后序列'
    resultItems.value = availableRecords.map((record) => {
      const allowedType = record.type === 'rna' || record.type === 'protein' ? record.type : 'dna'
      return toResult(record, cleanSequence(record.sequence, allowedType), 'cleaned', record.type)
    })
  } else if (operation === 'statistics') {
    resultTitle.value = '序列统计输入'
    resultItems.value = availableRecords.map((record) => toResult(record, record.sequence, 'statistics'))
    activeAnalysisTab.value = 'statistics'
  } else if (operation === 'orf') {
    const record = selectedRecord.value
    if (!record) return
    orfRows.value = findOrfs(record.sequence, minimumOrfLength.value)
    resultTitle.value = 'ORF 预测结果'
    resultItems.value = orfRows.value.map((orf) => ({ id: orf.id, header: `${record.id} | ${orf.id} | frame ${orf.frame}`, sequence: orf.proteinSequence, type: 'protein' }))
    activeAnalysisTab.value = 'orf'
  } else if (operation === 'motif') {
    const record = selectedRecord.value
    if (!record || !motifPattern.value.trim()) {
      message.warning('请输入 Motif 模式')
      return
    }
    motifRows.value = findMotifs(record.sequence, motifPattern.value.trim(), motifPattern.value.trim().toUpperCase())
    resultTitle.value = 'Motif 搜索结果'
    resultItems.value = motifRows.value.map((motif, index) => ({
      id: `motif_${index + 1}`,
      header: `${record.id} | ${motif.pattern} | ${motif.strand}:${motif.start}-${motif.end}`,
      sequence: record.sequence.slice(motif.start - 1, motif.end),
      type: record.type,
    }))
    activeAnalysisTab.value = 'viewer'
  }

  durationMs.value = performance.now() - startedAt
  message.success(`${activeOperation.value?.label || '分析'}完成，共生成 ${resultItems.value.length} 条结果`)
}

function resultRecords(): FastaRecord[] {
  return resultItems.value.map((item) => ({
    id: item.id,
    header: item.header,
    sequence: item.sequence,
    type: item.type,
    length: item.sequence.length,
  }))
}

async function copyResults(item?: SequenceResultItem) {
  if (!resultItems.value.length) return
  const content = item ? item.sequence : formatToFasta(resultRecords())
  try {
    await navigator.clipboard.writeText(content)
    message.success('结果已复制')
  } catch {
    message.error('复制失败，请手动选择文本')
  }
}

async function copyText(content: string, successText: string) {
  if (!content) return
  try {
    await navigator.clipboard.writeText(content)
    message.success(successText)
  } catch {
    message.error('复制失败，请手动选择文本')
  }
}

function downloadBlob(content: string, filename: string, mime = 'text/plain') {
  const url = URL.createObjectURL(new Blob([content], { type: mime }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function downloadResults(format: 'fasta' | 'txt' | 'json') {
  if (!resultItems.value.length) return
  const content = format === 'json'
    ? JSON.stringify(resultItems.value, null, 2)
    : format === 'fasta'
      ? formatToFasta(resultRecords())
      : resultItems.value.map((item) => `${item.header}\n${item.sequence}`).join('\n\n')
  downloadBlob(content, `sequence_studio_result.${format}`, format === 'json' ? 'application/json' : 'text/plain')
}

function exportOrf(row: OrfMatch, type: 'dna' | 'protein') {
  const sequence = type === 'dna' ? row.dnaSequence : row.proteinSequence
  downloadBlob(`>${row.id}_${type}\n${sequence}\n`, `${row.id}.${type === 'dna' ? 'fasta' : 'faa'}`)
}

function selectOrf(row: OrfMatch) {
  selectedOrf.value = row
  activeAnalysisTab.value = 'viewer'
}

async function shareStudio() {
  try {
    await navigator.clipboard.writeText(window.location.href)
    message.success('页面链接已复制')
  } catch {
    message.error('链接复制失败')
  }
}

function sendTo(target: 'blast' | 'primer') {
  const record = target === 'primer' && selectedOrf.value && selectedRecord.value
    ? {
        ...selectedRecord.value,
        id: `${selectedRecord.value.id}_${selectedOrf.value.id}`,
        header: `${selectedRecord.value.header} | ${selectedOrf.value.id}`,
        sequence: selectedOrf.value.dnaSequence,
        length: selectedOrf.value.lengthNt,
        type: 'dna' as const,
      }
    : selectedRecord.value
  if (!record) {
    message.warning('请先选择一条序列')
    return
  }
  if (target === 'primer' && record.type === 'protein') {
    message.warning('PrimerForge 需要 DNA/RNA 模板')
    return
  }
  storeSequenceHandoff(target, record)
  router.push({ name: target === 'blast' ? 'tools-blast' : 'tools-primer-forge', query: { source: 'sequence-studio' } })
}

async function openAiAssistant() {
  if (!aiPrompt.value) return
  try {
    await navigator.clipboard.writeText(aiPrompt.value)
    message.success('AI 分析提示词已复制，正在打开 AI 助手')
    router.push({ name: 'ai' })
  } catch {
    message.error('复制提示词失败')
  }
}

async function sendToPipeline() {
  const record = selectedRecord.value
  if (!record) return
  try {
    await navigator.clipboard.writeText(formatToFasta([record]))
    message.success('FASTA 已复制，可在分析流程中粘贴或保存后上传')
    router.push({ name: 'flows' })
  } catch {
    message.error('复制 FASTA 失败，请先使用页头的“导出输入”保存文件')
  }
}

function exportInputFasta() {
  if (!records.value.length) {
    message.warning('暂无输入序列可导出')
    return
  }
  downloadBlob(formatToFasta(records.value), 'sequence_studio_input.fasta')
}
</script>

<template>
  <div class="sequence-studio-page">
    <PageHeader
      title="序列魔术师"
      subtitle="Sequence Studio · 多 FASTA 清洗、转换、翻译、ORF 与序列探索均在浏览器本地完成"
      back-to="/tools"
      back-label="返回工具箱"
    >
      <template #actions>
        <NTag size="small" type="info" :bordered="false">v2.0</NTag>
        <NButton size="small" quaternary @click="loadSample">
          <template #icon><NIcon><SparklesOutline /></NIcon></template>
          加载示例
        </NButton>
        <NButton size="small" quaternary :disabled="!records.length" @click="exportInputFasta">
          <template #icon><NIcon><DownloadOutline /></NIcon></template>
          导出输入
        </NButton>
        <NButton size="small" quaternary @click="shareStudio">
          <template #icon><NIcon><LinkOutline /></NIcon></template>
          分享
        </NButton>
      </template>
    </PageHeader>

    <NAlert type="info" :bordered="false" class="local-notice">
      序列仅在当前浏览器内存中处理，不会上传到服务器。支持多 FASTA、IUPAC 简并碱基和长序列虚拟浏览。
    </NAlert>

    <div class="studio-shell">
      <aside class="tool-rail" aria-label="序列分析工具">
        <div class="rail-heading">
          <span>Toolbox</span>
          <strong>选择操作</strong>
        </div>
        <div v-for="group in operationGroups" :key="group.title" class="tool-group">
          <h2>{{ group.title }}</h2>
          <NTooltip v-for="item in group.items" :key="item.key" placement="right" :delay="300">
            <template #trigger>
              <button
                type="button"
                :class="['tool-button', { 'is-active': selectedOperation === item.key }]"
                :aria-pressed="selectedOperation === item.key"
                @click="runOperation(item.key)"
              >
                <NIcon :size="18"><component :is="item.icon" /></NIcon>
                <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
              </button>
            </template>
            {{ item.description }}
          </NTooltip>
        </div>

        <div class="tool-parameters">
          <template v-if="selectedOperation === 'translate'">
            <label>密码子表</label>
            <NSelect v-model:value="codonTableId" size="small" :options="codonTableOptions" />
            <NCheckbox v-model:checked="initMet" size="small">起始密码子按 Met 处理</NCheckbox>
          </template>
          <template v-else-if="selectedOperation === 'orf'">
            <label>最小 ORF 长度</label>
            <NInputNumber v-model:value="minimumOrfLength" size="small" :min="1" :max="10000">
              <template #suffix>aa</template>
            </NInputNumber>
          </template>
          <template v-else-if="selectedOperation === 'motif'">
            <label>Motif / IUPAC 模式</label>
            <NInput v-model:value="motifPattern" size="small" placeholder="如 ATG、GCN、TATAWA" />
          </template>
        </div>

        <NButton type="primary" block :disabled="!records.length || !operationAllowed" @click="runOperation()">
          <template #icon><NIcon><AnalyticsOutline /></NIcon></template>
          运行{{ activeOperation?.label }}
        </NButton>
      </aside>

      <main class="studio-workspace">
        <div class="workspace-split">
          <NCard :bordered="false" class="studio-card input-card">
            <SequenceInputPanel v-model="inputText" :records="records" @sample="loadSample" />
          </NCard>
          <NCard :bordered="false" class="studio-card result-card">
            <ResultViewerPanel
              :title="resultTitle"
              :items="resultItems"
              :duration-ms="durationMs"
              @copy="copyResults"
              @download="downloadResults"
            />
          </NCard>
        </div>

        <NCard :bordered="false" class="studio-card analysis-card">
          <div class="analysis-toolbar">
            <div>
              <span>Advanced workspace</span>
              <strong>深入分析与平台联动</strong>
            </div>
            <NSelect
              v-model:value="selectedRecordId"
              size="small"
              :options="recordOptions"
              placeholder="选择当前序列"
              class="record-select"
            />
          </div>

          <NTabs v-model:value="activeAnalysisTab" type="line" animated>
            <NTabPane name="statistics" tab="序列统计">
              <div v-if="selectedStats" class="statistics-grid">
                <div><NStatistic label="序列长度" :value="selectedStats.length" /></div>
                <div><NStatistic label="GC 含量" :value="selectedStats.gcContent" suffix="%" /></div>
                <div><NStatistic label="AT / AU 含量" :value="selectedStats.atContent" suffix="%" /></div>
                <div><NStatistic label="N 含量" :value="selectedStats.nContent" suffix="%" /></div>
                <div><NStatistic label="近似分子量" :value="selectedStats.molecularWeight || 0" suffix="Da" /></div>
                <div><NStatistic label="已预测 ORF" :value="orfRows.length" /></div>
              </div>
              <div v-if="selectedStats" class="base-composition">
                <span v-for="(count, base) in selectedStats.baseCounts" :key="base">
                  <strong>{{ base }}</strong>{{ count.toLocaleString() }}
                </span>
              </div>
            </NTabPane>

            <NTabPane name="orf" tab="ORF Finder">
              <div class="inline-settings">
                <NInputNumber v-model:value="minimumOrfLength" size="small" :min="1" :max="10000">
                  <template #suffix>aa</template>
                </NInputNumber>
                <NButton size="small" type="primary" :disabled="!selectedRecord" @click="runOperation('orf')">重新扫描</NButton>
              </div>
              <OrfPanel :rows="orfRows" @export="exportOrf" @select="selectOrf" />
            </NTabPane>

            <NTabPane name="viewer" tab="序列查看器">
              <div v-if="motifRows.length" class="motif-summary">
                <NTag type="warning" size="small">{{ motifRows.length }} 个 Motif 命中</NTag>
                <NDataTable
                  :columns="motifColumns"
                  :data="motifRows"
                  :pagination="motifRows.length > 8 ? { pageSize: 8 } : false"
                  :scroll-x="510"
                  size="small"
                  :bordered="false"
                />
              </div>
              <SequenceViewer v-if="viewerSequence" :sequence="viewerSequence" :highlights="viewerHighlights" />
            </NTabPane>

            <NTabPane name="ai" tab="AI 与下游工具">
              <div class="ecosystem-grid">
                <section class="ai-prompt-card">
                  <div class="ecosystem-heading">
                    <NIcon :size="20"><ChatbubbleEllipsesOutline /></NIcon>
                    <div><strong>序列 AI 分析</strong><span>基于当前统计与 ORF 生成结构化上下文</span></div>
                  </div>
                  <pre>{{ aiPrompt || '选择一条序列后生成 AI 分析上下文' }}</pre>
                  <div class="ecosystem-actions">
                    <NButton size="small" :disabled="!aiPrompt" @click="copyText(aiPrompt, 'AI 分析提示词已复制')">
                      <template #icon><NIcon><CopyOutline /></NIcon></template>复制 Prompt
                    </NButton>
                    <NButton size="small" type="primary" :disabled="!aiPrompt" @click="openAiAssistant">复制并打开 AI 助手</NButton>
                  </div>
                </section>
                <section class="handoff-card">
                  <div class="ecosystem-heading">
                    <NIcon :size="20"><GitNetworkOutline /></NIcon>
                    <div><strong>发送到 OmicHub</strong><span>当前序列通过本地会话安全传递</span></div>
                  </div>
                  <div class="handoff-list">
                    <button type="button" :disabled="!selectedRecord" @click="sendTo('blast')"><strong>运行 BLAST</strong><span>自动带入 FASTA 与查询名称</span></button>
                    <button type="button" :disabled="!selectedRecord || selectedRecord.type === 'protein'" @click="sendTo('primer')"><strong>发送到 PrimerForge</strong><span>作为引物设计模板序列</span></button>
                    <button type="button" :disabled="!selectedRecord" @click="sendToPipeline"><strong>进入多组学流程</strong><span>复制 FASTA 后选择分析流程</span></button>
                  </div>
                </section>
              </div>
            </NTabPane>
          </NTabs>
        </NCard>
      </main>
    </div>
  </div>
</template>

<style scoped>
.sequence-studio-page {
  min-height: 100%;
  padding: 16px;
  box-sizing: border-box;
}

.sequence-studio-page :deep(.page-header) {
  margin-bottom: 8px;
}

.local-notice {
  margin-bottom: 12px;
}

.studio-shell {
  display: grid;
  grid-template-columns: 228px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.tool-rail,
.studio-card {
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card, 12px);
  background: var(--neutral-card);
}

.tool-rail {
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: calc(100vh - 104px);
  padding: 12px;
  overflow-y: auto;
}

.rail-heading span,
.analysis-toolbar span {
  display: block;
  color: var(--primary-color, var(--arco-primary));
  font-size: var(--font-micro-size);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.rail-heading strong,
.analysis-toolbar strong {
  display: block;
  margin-top: 2px;
  color: var(--neutral-text-1);
  font-size: 14px;
}

.tool-group h2 {
  margin: 0 0 6px;
  color: var(--neutral-text-3);
  font-size: 11px;
  font-weight: 600;
}

.tool-button {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 8px;
  width: 100%;
  margin: 2px 0;
  padding: 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  color: var(--neutral-text-2);
  text-align: left;
  cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
}

.tool-button:hover {
  background: var(--neutral-hover);
  color: var(--neutral-text-1);
}

.tool-button.is-active {
  border-color: color-mix(in srgb, var(--primary-color, var(--arco-primary)) 34%, var(--neutral-border));
  background: color-mix(in srgb, var(--primary-color, var(--arco-primary)) 10%, var(--neutral-card));
  color: var(--primary-color, var(--arco-primary));
}

.tool-button:focus-visible,
.handoff-list button:focus-visible {
  outline: 2px solid var(--primary-color, var(--arco-primary));
  outline-offset: 2px;
}

.tool-button strong,
.tool-button small {
  display: block;
}

.tool-button strong {
  color: inherit;
  font-size: 12px;
  line-height: 1.4;
}

.tool-button small {
  margin-top: 2px;
  color: var(--neutral-text-3);
  font-size: 10px;
  line-height: 1.4;
}

.tool-parameters {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--neutral-border);
}

.tool-parameters label {
  color: var(--neutral-text-2);
  font-size: 11px;
  font-weight: 600;
}

.studio-workspace {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
}

.workspace-split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.studio-card :deep(.n-card__content) {
  padding: 14px;
}

.analysis-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
}

.record-select {
  width: min(100%, 340px);
}

.statistics-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(120px, 1fr));
  gap: 8px;
}

.statistics-grid > div {
  padding: 12px;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  background: var(--neutral-bg);
}

.statistics-grid :deep(.n-statistic-value__content) {
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.base-composition {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.base-composition span {
  display: inline-flex;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 999px;
  background: var(--neutral-bg);
  color: var(--neutral-text-3);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.base-composition strong {
  color: var(--neutral-text-1);
}

.inline-settings {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.motif-summary {
  margin-bottom: 12px;
}

.motif-summary > .n-tag {
  margin-bottom: 8px;
}

.ecosystem-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
  gap: 12px;
}

.ai-prompt-card,
.handoff-card {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  background: var(--neutral-bg);
}

.ecosystem-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.ecosystem-heading .n-icon {
  color: var(--primary-color, var(--arco-primary));
}

.ecosystem-heading strong,
.ecosystem-heading span {
  display: block;
}

.ecosystem-heading strong {
  color: var(--neutral-text-1);
  font-size: 13px;
}

.ecosystem-heading span {
  color: var(--neutral-text-3);
  font-size: 11px;
}

.ai-prompt-card pre {
  max-height: 280px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border: 1px solid var(--neutral-border);
  border-radius: 6px;
  background: var(--neutral-card);
  color: var(--neutral-text-2);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.ecosystem-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.handoff-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.handoff-list button {
  padding: 10px;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  background: var(--neutral-card);
  text-align: left;
  cursor: pointer;
}

.handoff-list button:hover:not(:disabled) {
  border-color: var(--primary-color, var(--arco-primary));
  background: var(--neutral-hover);
}

.handoff-list button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.handoff-list strong,
.handoff-list span {
  display: block;
}

.handoff-list strong {
  color: var(--neutral-text-1);
  font-size: 12px;
}

.handoff-list span {
  margin-top: 2px;
  color: var(--neutral-text-3);
  font-size: 10px;
}

@media (max-width: 1280px) {
  .studio-shell {
    grid-template-columns: 1fr;
  }

  .tool-rail {
    position: static;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    max-height: none;
    overflow: visible;
  }

  .rail-heading,
  .tool-parameters,
  .tool-rail > .n-button {
    grid-column: 1 / -1;
  }

  .statistics-grid {
    grid-template-columns: repeat(3, minmax(120px, 1fr));
  }
}

@media (max-width: 900px) {
  .workspace-split,
  .ecosystem-grid {
    grid-template-columns: 1fr;
  }

  .tool-rail {
    grid-template-columns: 1fr;
  }

  .tool-group,
  .rail-heading,
  .tool-parameters,
  .tool-rail > .n-button {
    grid-column: auto;
  }
}

@media (max-width: 640px) {
  .sequence-studio-page {
    padding: 12px;
  }

  .analysis-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .record-select {
    width: 100%;
  }

  .statistics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (prefers-reduced-motion: reduce) {
  .tool-button {
    transition: none;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .tool-rail,
  .studio-card {
    background: var(--neutral-card);
  }
}
</style>
