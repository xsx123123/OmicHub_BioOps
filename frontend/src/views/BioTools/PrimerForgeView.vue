<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert, NButton, NCollapse, NCollapseItem, NDataTable, NDrawer, NDrawerContent,
  NEmpty, NIcon, NInput, NInputNumber, NRadioButton, NRadioGroup, NSelect, NSlider,
  NSpace, NStatistic, NSwitch, NTag, NUpload, useMessage,
  type DataTableColumns, type UploadFileInfo,
} from 'naive-ui'
import {
  ArrowBackOutline, CopyOutline, DownloadOutline, GitNetworkOutline, HammerOutline,
  MailOutline, RefreshOutline, SaveOutline, SparklesOutline,
} from '@vicons/ionicons5'
import {
  SYNTHESIS_COMPANIES,
  cleanDnaSequence,
  defaultAdvancedParameters,
  defaultPrimerParameters,
  defaultProbeParameters,
  defaultThermodynamicParameters,
  designPrimers,
  exportPrimerReportHtml,
  formatPrimerLocation,
  genPrimerSampleSeq,
  generateSynthesisOrderDraft,
  getSequenceStats,
  parseFastaInput,
  parseRegionRanges,
  type PrimerDesignInput,
  type PrimerDesignResult,
  type PrimerInfo,
  type PrimerPair,
  type PrimerTaskType,
} from '@/utils/primerForgeProcessor'
import PageHeader from '@/components/PageHeader.vue'
import { consumeSequenceHandoff } from '@/engine/ecosystemLinks'

const router = useRouter()
const message = useMessage()

const sequenceText = ref('')
const sequenceId = ref('')
const targetText = ref('')
const excludedText = ref('')
const taskType = ref<PrimerTaskType>('qPCR')
const designing = ref(false)
const designResult = ref<PrimerDesignResult | null>(null)
const selectedRank = ref<number | null>(null)

const primerParameters = reactive(defaultPrimerParameters(taskType.value))
const thermodynamicParameters = reactive(defaultThermodynamicParameters())
const advanced = reactive(defaultAdvancedParameters())
const probeParameters = reactive(defaultProbeParameters())
probeParameters.enabled = true

const taskOptions: { label: string; value: PrimerTaskType }[] = [
  { label: 'PCR', value: 'PCR' },
  { label: 'qPCR', value: 'qPCR' },
  { label: '测序', value: 'sequencing' },
  { label: '克隆', value: 'cloning' },
]

const saltCorrectionOptions = [
  { label: 'SantaLucia', value: 'santalucia' },
  { label: 'Owczarzy', value: 'owczarzy' },
  { label: 'Von Ahsen', value: 'von_ahsen' },
]
const saltCorrection = ref('santalucia')

const fluorophoreOptions = ['FAM', 'VIC', 'HEX', 'ROX', 'CY5'].map((value) => ({ label: value, value }))
const quencherOptions = ['BHQ1', 'BHQ2', 'TAMRA', 'MGB'].map((value) => ({ label: value, value }))

onMounted(() => {
  const handoff = consumeSequenceHandoff('primer')
  if (!handoff) return
  sequenceText.value = `>${handoff.record.header}\n${handoff.record.sequence}`
  sequenceId.value = handoff.record.id
  message.success('已从序列魔术师载入模板序列')
})
const purificationOptions = ['STD', 'HPLC', 'PAGE'].map((value) => ({ label: value, value }))
const scaleOptions = ['25 nmol', '50 nmol', '100 nmol', '250 nmol'].map((value) => ({ label: value, value }))
const deliveryOptions = ['冻干粉', 'TE 溶液', '无核酸酶水溶解'].map((value) => ({ label: value, value }))
const companyOptions = SYNTHESIS_COMPANIES.map((company) => ({ label: company.name, value: company.id }))

watch(taskType, (next) => {
  Object.assign(primerParameters, defaultPrimerParameters(next))
  probeParameters.enabled = next === 'qPCR'
})

const parsed = computed(() => parseFastaInput(sequenceText.value))
const cleanSequence = computed(() => cleanDnaSequence(sequenceText.value))
const sequenceStats = computed(() => getSequenceStats(sequenceText.value))
const targetRegions = computed(() => parseRegionRanges(targetText.value))
const excludedRegions = computed(() => parseRegionRanges(excludedText.value))
const pairs = computed(() => designResult.value?.primerPairs ?? [])
const selectedPair = computed(() => pairs.value.find((pair) => pair.rank === selectedRank.value) ?? pairs.value[0])
const bestScore = computed(() => pairs.value[0]?.qualityScore ?? 0)
const avgTm = computed(() => {
  const values = pairs.value.flatMap((pair) => [pair.forwardPrimer.tm, pair.reversePrimer.tm])
  return values.length ? +(values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1) : 0
})
const avgGc = computed(() => {
  const values = pairs.value.flatMap((pair) => [pair.forwardPrimer.gcPercent, pair.reversePrimer.gcPercent])
  return values.length ? +(values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1) : 0
})

const pairOptions = computed(() => pairs.value.map((pair) => ({
  label: `#${pair.rank} · ${pair.productSize} bp · score ${pair.qualityScore}`,
  value: pair.rank,
})))

const sequenceWindow = computed(() => {
  const pair = selectedPair.value
  const seq = designResult.value?.sequenceTemplate || cleanSequence.value
  if (!pair || !seq) return null
  const start = Math.max(0, pair.productStart - 60)
  const end = Math.min(seq.length, pair.productEnd + 60)
  const bases = seq.slice(start, end).split('').map((base, offset) => {
    const index = start + offset
    return {
      index,
      base,
      type: baseType(index, pair),
    }
  })
  return { start, end, bases }
})

const columns: DataTableColumns<PrimerPair> = [
  {
    title: '#',
    key: 'rank',
    width: 54,
    render: (row) => h(NTag, { size: 'small', type: row.rank === 1 ? 'warning' : 'default' }, { default: () => row.rank }),
  },
  {
    title: '正向引物',
    key: 'forward',
    width: 190,
    render: (row) => h('span', { class: 'primer-seq' }, row.forwardPrimer.sequence),
  },
  {
    title: 'Tm / GC',
    key: 'forwardMetrics',
    width: 92,
    render: (row) => `${row.forwardPrimer.tm}°C / ${row.forwardPrimer.gcPercent}%`,
  },
  {
    title: '反向引物',
    key: 'reverse',
    width: 190,
    render: (row) => h('span', { class: 'primer-seq' }, row.reversePrimer.sequence),
  },
  {
    title: 'Tm / GC',
    key: 'reverseMetrics',
    width: 92,
    render: (row) => `${row.reversePrimer.tm}°C / ${row.reversePrimer.gcPercent}%`,
  },
  {
    title: '产物',
    key: 'productSize',
    width: 78,
    render: (row) => `${row.productSize} bp`,
  },
  {
    title: '评分',
    key: 'qualityScore',
    width: 78,
    render: (row) => h(NTag, { size: 'small', type: scoreType(row.qualityScore) }, { default: () => row.qualityScore }),
  },
  {
    title: '操作',
    key: 'actions',
    width: 82,
    render: (row) => h(
      NButton,
      {
        size: 'tiny',
        type: selectedRank.value === row.rank ? 'primary' : 'default',
        onClick: () => selectPair(row.rank),
      },
      { default: () => selectedRank.value === row.rank ? '已选' : '选择' },
    ),
  },
]

function buildInput(): PrimerDesignInput {
  return {
    sequenceId: sequenceId.value.trim() || parsed.value.id || 'primer_template',
    sequenceTemplate: parsed.value.sequence,
    taskType: taskType.value,
    targetRegions: targetRegions.value,
    excludedRegions: excludedRegions.value,
    primerParameters: { ...primerParameters },
    thermodynamicParameters: { ...thermodynamicParameters },
    advanced: { ...advanced },
    probeParameters: { ...probeParameters },
  }
}

let designTimer: number | null = null

function runDesign() {
  if (!parsed.value.sequence) {
    message.warning('请先输入 DNA 序列或上传 FASTA 文件')
    return
  }
  if (parsed.value.sequence.length < primerParameters.productMin + primerParameters.minSize) {
    message.warning('序列过短，无法满足当前最小产物长度')
    return
  }
  designing.value = true
  if (designTimer) clearTimeout(designTimer)
  designTimer = window.setTimeout(() => {
    const result = designPrimers(buildInput())
    designResult.value = result
    selectedRank.value = result.primerPairs[0]?.rank ?? null
    designing.value = false
    if (result.success) {
      message.success(`已返回 ${result.primerPairs.length} 组候选引物`)
    } else {
      message.warning('没有找到满足条件的引物对，请放宽参数后重试')
    }
  }, 30)
}

function loadSample() {
  sequenceText.value = genPrimerSampleSeq()
  const sample = parseFastaInput(sequenceText.value)
  sequenceId.value = sample.id || 'ACTB_qPCR_demo'
  targetText.value = '180,120'
  excludedText.value = ''
  taskType.value = 'qPCR'
  message.info('已载入 ACTB qPCR 示例序列')
}

function resetParams() {
  Object.assign(primerParameters, defaultPrimerParameters(taskType.value))
  Object.assign(thermodynamicParameters, defaultThermodynamicParameters())
  Object.assign(advanced, defaultAdvancedParameters())
  Object.assign(probeParameters, defaultProbeParameters(), { enabled: taskType.value === 'qPCR' })
  message.info('参数已恢复为当前任务类型默认值')
}

function selectPair(rank: number) {
  selectedRank.value = rank
}

function handleSequenceUpload({ file }: { file: UploadFileInfo }) {
  const raw = file.file
  if (!raw) return
  const reader = new FileReader()
  reader.onload = () => {
    sequenceText.value = String(reader.result || '')
    const parsedFile = parseFastaInput(sequenceText.value)
    if (parsedFile.id && !sequenceId.value) sequenceId.value = parsedFile.id
    message.success(`已读取 ${parsedFile.sequence.length} bp 序列`)
  }
  reader.onerror = () => message.error('文件读取失败')
  reader.readAsText(raw)
}

function scoreType(score: number): 'success' | 'warning' | 'error' {
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'error'
}

function baseType(index: number, pair: PrimerPair): string {
  if (index >= pair.forwardPrimer.bindingStart && index < pair.forwardPrimer.bindingEnd) return 'forward'
  if (index >= pair.reversePrimer.bindingStart && index < pair.reversePrimer.bindingEnd) return 'reverse'
  if (pair.probe && index >= pair.probe.bindingStart && index < pair.probe.bindingEnd) return 'probe'
  if (index >= pair.productStart && index < pair.productEnd) return 'product'
  return 'plain'
}

function segmentStyle(start: number, end: number) {
  const length = Math.max(1, designResult.value?.sequenceTemplate.length || cleanSequence.value.length)
  return {
    left: `${Math.max(0, Math.min(100, start / length * 100))}%`,
    width: `${Math.max(0.6, Math.min(100, (end - start) / length * 100))}%`,
  }
}

async function copySelectedPrimers() {
  const pair = selectedPair.value
  if (!pair) {
    message.warning('暂无选中的引物对')
    return
  }
  const lines = [
    `F${pair.rank}\t${pair.forwardPrimer.sequence}`,
    `R${pair.rank}\t${pair.reversePrimer.sequence}`,
  ]
  if (pair.probe) lines.push(`P${pair.rank}\t${pair.probe.sequence}`)
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    message.success('已复制选中引物序列')
  } catch {
    message.error('复制失败，请手动复制')
  }
}

function exportExcel() {
  if (!designResult.value?.primerPairs.length) {
    message.warning('暂无结果可导出')
    return
  }
  const html = exportPrimerReportHtml(designResult.value)
  const blob = new Blob([html], { type: 'application/vnd.ms-excel;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${designResult.value.sequenceId}_primerforge_report.xls`
  a.click()
  URL.revokeObjectURL(url)
}

function saveHistory() {
  if (!designResult.value?.primerPairs.length) {
    message.warning('暂无可保存的设计结果')
    return
  }
  const item = {
    designId: designResult.value.designId,
    sequenceId: designResult.value.sequenceId,
    taskType: designResult.value.taskType,
    createdAt: new Date().toISOString(),
    pairCount: designResult.value.primerPairs.length,
    bestScore: designResult.value.primerPairs[0]?.qualityScore,
  }
  const key = 'cygnusx_primerforge_history'
  const previous = JSON.parse(localStorage.getItem(key) || '[]') as unknown[]
  localStorage.setItem(key, JSON.stringify([item, ...previous].slice(0, 30)))
  message.success('已保存到本地历史记录')
}

onUnmounted(() => {
  if (designTimer) clearTimeout(designTimer)
})

const orderDrawerVisible = ref(false)
const orderPairRanks = ref<number[]>([])
const companyId = ref(SYNTHESIS_COMPANIES[0].id)
const purification = ref('STD')
const scale = ref('25 nmol')
const deliveryForm = ref('冻干粉')
const specialRequirements = ref('')
const contactName = ref('')
const labName = ref('')
const orderSubject = ref('')
const orderBody = ref('')

const selectedOrderPairs = computed(() => pairs.value.filter((pair) => orderPairRanks.value.includes(pair.rank)))
const selectedCompany = computed(() => SYNTHESIS_COMPANIES.find((company) => company.id === companyId.value) ?? SYNTHESIS_COMPANIES[0])

function openOrderAssistant() {
  if (!pairs.value.length) {
    message.warning('请先完成引物设计')
    return
  }
  orderPairRanks.value = selectedPair.value ? [selectedPair.value.rank] : [pairs.value[0].rank]
  refreshOrderDraft()
  orderDrawerVisible.value = true
}

function refreshOrderDraft() {
  const draft = generateSynthesisOrderDraft({
    pairs: selectedOrderPairs.value,
    company: selectedCompany.value,
    sequenceId: designResult.value?.sequenceId || sequenceId.value || 'primer_template',
    purification: purification.value,
    scale: scale.value,
    deliveryForm: deliveryForm.value,
    fluorophore: probeParameters.fluorophore,
    quencher: probeParameters.quencher,
    specialRequirements: specialRequirements.value,
    contactName: contactName.value,
    labName: labName.value,
  })
  orderSubject.value = draft.subject
  orderBody.value = draft.body
}

async function copyOrderDraft() {
  if (!orderBody.value) {
    message.warning('暂无订单文案')
    return
  }
  try {
    await navigator.clipboard.writeText(`Subject: ${orderSubject.value}\nTo: ${selectedCompany.value.email}\n\n${orderBody.value}`)
    message.success('已复制订单邮件草稿')
  } catch {
    message.error('复制失败')
  }
}

function primerDetail(primer: PrimerInfo, direction: 'forward' | 'reverse') {
  return [
    ['序列', primer.sequence],
    ['位置', formatPrimerLocation(primer, direction)],
    ['长度', `${primer.length} nt`],
    ['Tm', `${primer.tm}°C`],
    ['GC', `${primer.gcPercent}%`],
    ['自身互补', primer.selfAny],
    ["3'互补", primer.selfEnd],
    ['末端稳定性', `${primer.endStability} kcal/mol`],
  ]
}
</script>

<template>
  <div class="primer-page">
    <PageHeader title="PrimerForge 引物锻造工坊" subtitle="设计、筛选与导出 PCR / qPCR 引物候选对" back-to="/tools" back-label="返回工具箱">
      <template #actions>
        <NButton size="small" quaternary @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        示例数据
      </NButton>
      <NButton size="small" quaternary @click="resetParams">
        <template #icon><NIcon><RefreshOutline /></NIcon></template>
        重置参数
      </NButton>
      </template>
    </PageHeader>

    <div class="primer-layout">
      <aside class="param-panel">
        <NCollapse arrow-placement="left" :default-expanded-names="['sequence', 'task', 'primer']">
          <NCollapseItem title="序列输入" name="sequence">
            <div class="field">
              <label>序列标识符</label>
              <NInput v-model:value="sequenceId" size="small" placeholder="如 ACTB_gene" />
            </div>
            <NInput
              v-model:value="sequenceText"
              type="textarea"
              :autosize="{ minRows: 8, maxRows: 14 }"
              placeholder="粘贴 DNA 序列或 FASTA 内容，支持 A/T/G/C/N"
              class="mono-input"
            />
            <div class="sequence-meta">
              <NTag size="small" :type="sequenceStats.length ? 'success' : 'default'">{{ sequenceStats.length }} bp</NTag>
              <NTag size="small">GC {{ sequenceStats.gcPercent }}%</NTag>
              <NTag v-if="sequenceStats.nCount" size="small" type="warning">N {{ sequenceStats.nCount }}</NTag>
            </div>
            <NUpload :default-upload="false" :max="1" accept=".fa,.fasta,.fna,.txt" @change="handleSequenceUpload">
              <NButton size="small" block secondary>上传 FASTA / TXT</NButton>
            </NUpload>
            <div class="field compact">
              <label>目标区域 start,length</label>
              <NInput v-model:value="targetText" size="small" placeholder="如 100,120；多段用分号分隔" />
            </div>
            <div class="field compact">
              <label>排除区域 start,length</label>
              <NInput v-model:value="excludedText" size="small" placeholder="如 50,20" />
            </div>
          </NCollapseItem>

          <NCollapseItem title="任务类型" name="task">
            <NRadioGroup v-model:value="taskType" size="small">
              <NRadioButton v-for="option in taskOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </NRadioButton>
            </NRadioGroup>
            <NSwitch v-if="taskType === 'qPCR'" v-model:value="probeParameters.enabled" size="small" class="probe-switch">
              <template #checked>设计 TaqMan 探针</template>
              <template #unchecked>不设计探针</template>
            </NSwitch>
          </NCollapseItem>

          <NCollapseItem title="引物参数" name="primer">
            <div class="triple-grid">
              <div class="field"><label>长度最优</label><NInputNumber v-model:value="primerParameters.optSize" size="small" :show-button="false" /></div>
              <div class="field"><label>最小</label><NInputNumber v-model:value="primerParameters.minSize" size="small" :show-button="false" /></div>
              <div class="field"><label>最大</label><NInputNumber v-model:value="primerParameters.maxSize" size="small" :show-button="false" /></div>
            </div>
            <div class="triple-grid">
              <div class="field"><label>Tm 最优</label><NInputNumber v-model:value="primerParameters.optTm" size="small" :show-button="false" /></div>
              <div class="field"><label>最小</label><NInputNumber v-model:value="primerParameters.minTm" size="small" :show-button="false" /></div>
              <div class="field"><label>最大</label><NInputNumber v-model:value="primerParameters.maxTm" size="small" :show-button="false" /></div>
            </div>
            <div class="triple-grid">
              <div class="field"><label>GC 最优</label><NInputNumber v-model:value="primerParameters.optGc" size="small" :show-button="false" /></div>
              <div class="field"><label>最小</label><NInputNumber v-model:value="primerParameters.minGc" size="small" :show-button="false" /></div>
              <div class="field"><label>最大</label><NInputNumber v-model:value="primerParameters.maxGc" size="small" :show-button="false" /></div>
            </div>
            <div class="double-grid">
              <div class="field"><label>产物最小 bp</label><NInputNumber v-model:value="primerParameters.productMin" size="small" :show-button="false" /></div>
              <div class="field"><label>产物最大 bp</label><NInputNumber v-model:value="primerParameters.productMax" size="small" :show-button="false" /></div>
            </div>
            <div class="field">
              <label>返回引物对数：{{ primerParameters.numReturn }}</label>
              <NSlider v-model:value="primerParameters.numReturn" :min="1" :max="20" :step="1" />
            </div>
            <NSwitch v-model:value="primerParameters.gcClamp" size="small">
              <template #checked>启用 3' GC clamp</template>
              <template #unchecked>不限制 GC clamp</template>
            </NSwitch>
          </NCollapseItem>

          <NCollapseItem title="热力学参数" name="thermo">
            <div class="double-grid">
              <div class="field"><label>一价阳离子 mM</label><NInputNumber v-model:value="thermodynamicParameters.saltMonovalent" size="small" :show-button="false" /></div>
              <div class="field"><label>二价阳离子 mM</label><NInputNumber v-model:value="thermodynamicParameters.saltDivalent" size="small" :show-button="false" /></div>
              <div class="field"><label>dNTP mM</label><NInputNumber v-model:value="thermodynamicParameters.dntpConc" size="small" :show-button="false" /></div>
              <div class="field"><label>DNA nM</label><NInputNumber v-model:value="thermodynamicParameters.dnaConc" size="small" :show-button="false" /></div>
              <div class="field"><label>最大 Poly-X</label><NInputNumber v-model:value="thermodynamicParameters.maxPolyX" size="small" :show-button="false" /></div>
              <div class="field"><label>盐校正公式</label><NSelect v-model:value="saltCorrection" size="small" :options="saltCorrectionOptions" /></div>
            </div>
          </NCollapseItem>

          <NCollapseItem title="高级约束" name="advanced">
            <div class="double-grid">
              <div class="field"><label>自身任意互补</label><NInputNumber v-model:value="advanced.maxSelfAny" size="small" :show-button="false" /></div>
              <div class="field"><label>自身 3' 互补</label><NInputNumber v-model:value="advanced.maxSelfEnd" size="small" :show-button="false" /></div>
              <div class="field"><label>引物对任意互补</label><NInputNumber v-model:value="advanced.maxPairAny" size="small" :show-button="false" /></div>
              <div class="field"><label>引物对 3' 互补</label><NInputNumber v-model:value="advanced.maxPairEnd" size="small" :show-button="false" /></div>
            </div>
            <div class="field"><label>Tm 权重 {{ advanced.tmWeight }}</label><NSlider v-model:value="advanced.tmWeight" :min="0" :max="2" :step="0.1" /></div>
            <div class="field"><label>GC 权重 {{ advanced.gcWeight }}</label><NSlider v-model:value="advanced.gcWeight" :min="0" :max="2" :step="0.1" /></div>
            <div class="field"><label>互补性权重 {{ advanced.complWeight }}</label><NSlider v-model:value="advanced.complWeight" :min="0" :max="2" :step="0.1" /></div>
          </NCollapseItem>

          <NCollapseItem v-if="taskType === 'qPCR'" title="TaqMan 探针参数" name="probe">
            <div class="triple-grid">
              <div class="field"><label>长度最优</label><NInputNumber v-model:value="probeParameters.optSize" size="small" :show-button="false" /></div>
              <div class="field"><label>最小</label><NInputNumber v-model:value="probeParameters.minSize" size="small" :show-button="false" /></div>
              <div class="field"><label>最大</label><NInputNumber v-model:value="probeParameters.maxSize" size="small" :show-button="false" /></div>
            </div>
            <div class="triple-grid">
              <div class="field"><label>Tm 最优</label><NInputNumber v-model:value="probeParameters.optTm" size="small" :show-button="false" /></div>
              <div class="field"><label>最小</label><NInputNumber v-model:value="probeParameters.minTm" size="small" :show-button="false" /></div>
              <div class="field"><label>最大</label><NInputNumber v-model:value="probeParameters.maxTm" size="small" :show-button="false" /></div>
            </div>
            <div class="double-grid">
              <div class="field"><label>5' 荧光</label><NSelect v-model:value="probeParameters.fluorophore" size="small" :options="fluorophoreOptions" /></div>
              <div class="field"><label>3' 淬灭</label><NSelect v-model:value="probeParameters.quencher" size="small" :options="quencherOptions" /></div>
            </div>
            <NSwitch v-model:value="probeParameters.avoidFivePrimeG" size="small">
              <template #checked>探针 5' 端避免 G</template>
              <template #unchecked>允许 5' G</template>
            </NSwitch>
          </NCollapseItem>
        </NCollapse>

        <NButton type="primary" block class="run-btn" :loading="designing" @click="runDesign">
          <template #icon><NIcon><HammerOutline /></NIcon></template>
          开始设计
        </NButton>
      </aside>

      <main class="work-area">
        <section class="work-card sequence-card">
          <div class="card-header">
            <span class="panel-title">序列可视化</span>
            <NTag v-if="selectedPair" size="small" type="success">#{{ selectedPair.rank }} · {{ selectedPair.productSize }} bp</NTag>
          </div>

          <template v-if="selectedPair">
            <div class="sequence-map">
              <div class="map-track"></div>
              <button
                v-for="pair in pairs"
                :key="pair.rank"
                class="pair-product"
                :class="{ active: pair.rank === selectedPair.rank }"
                :style="segmentStyle(pair.productStart, pair.productEnd)"
                type="button"
                @click="selectPair(pair.rank)"
              >
                #{{ pair.rank }}
              </button>
              <span class="primer-marker forward" :style="segmentStyle(selectedPair.forwardPrimer.bindingStart, selectedPair.forwardPrimer.bindingEnd)">F</span>
              <span class="primer-marker reverse" :style="segmentStyle(selectedPair.reversePrimer.bindingStart, selectedPair.reversePrimer.bindingEnd)">R</span>
              <span
                v-if="selectedPair.probe"
                class="primer-marker probe"
                :style="segmentStyle(selectedPair.probe.bindingStart, selectedPair.probe.bindingEnd)"
              >
                P
              </span>
            </div>

            <div v-if="sequenceWindow" class="base-view">
              <span class="base-index">{{ sequenceWindow.start + 1 }}</span>
              <span
                v-for="base in sequenceWindow.bases"
                :key="base.index"
                class="base-cell"
                :class="`base-${base.type}`"
                :title="`${base.index + 1}: ${base.base}`"
              >
                {{ base.base }}
              </span>
              <span class="base-index">{{ sequenceWindow.end }}</span>
            </div>
          </template>

          <NEmpty v-else description="输入序列并开始设计后显示引物位置图" />
        </section>

        <section class="work-card result-card">
          <div class="card-header">
            <span class="panel-title">引物设计结果</span>
            <NSpace size="small">
              <NButton size="tiny" tertiary @click="copySelectedPrimers">
                <template #icon><NIcon><CopyOutline /></NIcon></template>
                复制选中
              </NButton>
              <NButton size="tiny" tertiary @click="exportExcel">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                导出 Excel
              </NButton>
            </NSpace>
          </div>
          <NDataTable
            v-if="pairs.length"
            :columns="columns"
            :data="pairs"
            :row-key="(row: PrimerPair) => row.rank"
            size="small"
            :pagination="{ pageSize: 8 }"
            :scroll-x="860"
          />
          <NEmpty v-else description="暂无候选引物对" />
        </section>
      </main>

      <aside class="side-panel">
        <div class="stats-grid">
          <div class="stat-card"><NStatistic label="候选对数" :value="pairs.length" /></div>
          <div class="stat-card"><NStatistic label="最佳评分" :value="bestScore" /></div>
          <div class="stat-card"><NStatistic label="平均 Tm" :value="avgTm" suffix="°C" /></div>
          <div class="stat-card"><NStatistic label="平均 GC" :value="avgGc" suffix="%" /></div>
          <div class="stat-card"><NStatistic label="耗时" :value="designResult?.runtimeMs ?? 0" suffix="ms" /></div>
        </div>

        <div v-if="designResult?.diagnostics.length" class="diagnostics">
          <NAlert v-for="item in designResult.diagnostics" :key="item" type="warning" size="small" :show-icon="false">
            {{ item }}
          </NAlert>
        </div>

        <div class="quick-actions">
          <NButton size="small" type="primary" block :disabled="!pairs.length" @click="openOrderAssistant">
            <template #icon><NIcon><MailOutline /></NIcon></template>
            合成助手
          </NButton>
          <NButton size="small" block :disabled="!pairs.length" @click="exportExcel">
            <template #icon><NIcon><DownloadOutline /></NIcon></template>
            导出 Excel 报告
          </NButton>
          <NButton size="small" block :disabled="!pairs.length" @click="saveHistory">
            <template #icon><NIcon><SaveOutline /></NIcon></template>
            保存历史
          </NButton>
        </div>

        <div v-if="selectedPair" class="detail-panel">
          <div class="panel-title">选中引物详情</div>
          <div class="detail-block">
            <NTag size="small" type="info">Forward</NTag>
            <div v-for="[key, value] in primerDetail(selectedPair.forwardPrimer, 'forward')" :key="key" class="detail-row">
              <span>{{ key }}</span><strong>{{ value }}</strong>
            </div>
          </div>
          <div class="detail-block">
            <NTag size="small" type="error">Reverse</NTag>
            <div v-for="[key, value] in primerDetail(selectedPair.reversePrimer, 'reverse')" :key="key" class="detail-row">
              <span>{{ key }}</span><strong>{{ value }}</strong>
            </div>
          </div>
          <div v-if="selectedPair.probe" class="detail-block">
            <NTag size="small" type="warning">Probe</NTag>
            <div class="detail-row"><span>序列</span><strong>{{ selectedPair.probe.sequence }}</strong></div>
            <div class="detail-row"><span>Tm / GC</span><strong>{{ selectedPair.probe.tm }}°C / {{ selectedPair.probe.gcPercent }}%</strong></div>
            <div class="detail-row"><span>标记</span><strong>{{ probeParameters.fluorophore }} / {{ probeParameters.quencher }}</strong></div>
          </div>
        </div>
      </aside>
    </div>

    <NDrawer v-model:show="orderDrawerVisible" width="720">
      <NDrawerContent title="引物合成助手">
        <div class="order-grid">
          <div class="field">
            <label>选择引物对</label>
            <NSelect v-model:value="orderPairRanks" multiple size="small" :options="pairOptions" />
          </div>
          <div class="field">
            <label>合成公司</label>
            <NSelect v-model:value="companyId" size="small" :options="companyOptions" />
          </div>
          <div class="field">
            <label>纯化方式</label>
            <NSelect v-model:value="purification" size="small" :options="purificationOptions" />
          </div>
          <div class="field">
            <label>合成规模</label>
            <NSelect v-model:value="scale" size="small" :options="scaleOptions" />
          </div>
          <div class="field">
            <label>交付形式</label>
            <NSelect v-model:value="deliveryForm" size="small" :options="deliveryOptions" />
          </div>
          <div class="field">
            <label>联系人</label>
            <NInput v-model:value="contactName" size="small" placeholder="姓名 / 电话" />
          </div>
          <div class="field full">
            <label>实验室</label>
            <NInput v-model:value="labName" size="small" placeholder="实验室或课题组名称" />
          </div>
          <div class="field full">
            <label>特殊要求</label>
            <NInput v-model:value="specialRequirements" size="small" placeholder="如 HPLC、板式交付、特殊修饰等" />
          </div>
        </div>

        <div class="company-note">
          <NIcon><GitNetworkOutline /></NIcon>
          {{ selectedCompany.fullName }} · {{ selectedCompany.priceHint }} · 交期 {{ selectedCompany.deliveryDays }} 天
        </div>

        <div class="order-actions">
          <NButton size="small" type="primary" @click="refreshOrderDraft">生成/刷新文案</NButton>
          <NButton size="small" @click="copyOrderDraft">
            <template #icon><NIcon><CopyOutline /></NIcon></template>
            复制邮件草稿
          </NButton>
        </div>

        <div class="field">
          <label>邮件主题</label>
          <NInput v-model:value="orderSubject" size="small" />
        </div>
        <div class="field">
          <label>邮件正文</label>
          <NInput v-model:value="orderBody" type="textarea" :autosize="{ minRows: 16, maxRows: 24 }" class="mono-input" />
        </div>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.primer-page {
  padding: 16px;
  min-height: 100%;
}
.page-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0;
  flex: 1;
}
.primer-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr) 292px;
  gap: 16px;
  align-items: start;
}
.param-panel,
.work-card,
.side-panel {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 12px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
}
.work-area {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.field {
  margin-bottom: 10px;
}
.field.compact {
  margin-top: 10px;
}
.field label {
  display: block;
  font-size: 12px;
  color: var(--neutral-text-2);
  margin-bottom: 4px;
}
.mono-input :deep(textarea),
.primer-seq {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
}
.sequence-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 8px 0;
}
.triple-grid,
.double-grid,
.order-grid {
  display: grid;
  gap: 8px;
}
.triple-grid {
  grid-template-columns: repeat(3, 1fr);
}
.double-grid,
.order-grid {
  grid-template-columns: repeat(2, 1fr);
}
.order-grid .full {
  grid-column: 1 / -1;
}
.probe-switch,
.run-btn {
  margin-top: 12px;
}
.sequence-card {
  min-height: 236px;
}
.sequence-map {
  position: relative;
  height: 74px;
  margin: 10px 2px 16px;
}
.map-track {
  position: absolute;
  left: 0;
  right: 0;
  top: 34px;
  height: 10px;
  border-radius: 999px;
  background: var(--neutral-bg);
  border: 1px solid var(--neutral-border);
}
.pair-product,
.primer-marker {
  position: absolute;
  border: 0;
  border-radius: 6px;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  white-space: nowrap;
}
.pair-product {
  top: 31px;
  height: 16px;
  color: #14532d;
  background: rgba(34, 197, 94, 0.22);
  cursor: pointer;
}
.pair-product.active {
  background: rgba(34, 197, 94, 0.5);
  box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.65);
}
.primer-marker {
  height: 18px;
  color: #fff;
  pointer-events: none;
}
.primer-marker.forward {
  top: 4px;
  background: #2563eb;
}
.primer-marker.reverse {
  bottom: 3px;
  background: #dc2626;
}
.primer-marker.probe {
  top: 4px;
  transform: translateY(24px);
  background: #d97706;
}
.base-view {
  display: flex;
  align-items: center;
  gap: 2px;
  overflow-x: auto;
  padding: 10px;
  background: var(--neutral-bg);
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
}
.base-index {
  flex: 0 0 auto;
  font-size: 11px;
  color: var(--neutral-text-3);
  margin: 0 4px;
}
.base-cell {
  flex: 0 0 13px;
  height: 22px;
  line-height: 22px;
  text-align: center;
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 11px;
  color: var(--neutral-text-1);
}
.base-product {
  background: rgba(34, 197, 94, 0.18);
}
.base-forward {
  background: #2563eb;
  color: #fff;
}
.base-reverse {
  background: #dc2626;
  color: #fff;
}
.base-probe {
  background: #f59e0b;
  color: #111827;
}
.result-card {
  min-height: 360px;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}
.stat-card {
  padding: 10px 8px;
  border-radius: 8px;
  background: var(--neutral-bg);
  text-align: center;
}
.diagnostics {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}
.quick-actions {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}
.detail-panel {
  margin-top: 14px;
}
.detail-block {
  padding: 10px 0;
  border-bottom: 1px solid var(--neutral-border);
}
.detail-row {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  margin-top: 6px;
  font-size: 12px;
}
.detail-row span {
  color: var(--neutral-text-3);
}
.detail-row strong {
  color: var(--neutral-text-1);
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-weight: 500;
  word-break: break-all;
}
.company-note {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--neutral-bg);
  color: var(--neutral-text-2);
  font-size: 12px;
  margin: 4px 0 12px;
}
.order-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
@media (max-width: 1200px) {
  .primer-layout {
    grid-template-columns: 1fr;
  }
  .param-panel,
  .side-panel {
    max-height: none;
  }
}
@media (max-width: 768px) {
  .primer-page {
    padding: 12px;
  }
  .page-toolbar {
    flex-wrap: wrap;
  }
  .triple-grid,
  .double-grid,
  .order-grid,
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
