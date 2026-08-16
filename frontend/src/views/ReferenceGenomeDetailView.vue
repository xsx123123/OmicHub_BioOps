<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NButtonGroup,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NIcon,
  NInput,
  NSelect,
  NSpin,
  NStatistic,
  NTabPane,
  NTabs,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import {
  CopyOutline,
  DownloadOutline,
  SearchOutline,
  SwapHorizontalOutline,
} from '@vicons/ionicons5'
import {
  fetchVersionDetail,
  fetchSpecies,
  searchGenes,
  fetchGeneDetail,
  fetchGeneSequence,
  fetchGoTerms,
  fetchKeggPathways,
  mapIds,
} from '@/api/referenceGenomes'
import type {
  ApiGene,
  BuildStatus,
  Chromosome,
  DataFileType,
  DatabaseDataFile,
  GeneDetail,
  GeneTypeStat,
  GoTermItem,
  KeggPathwayItem,
  SequenceResult,
  SpeciesDatabase,
  VersionDetailResponse,
} from '@/types/referenceGenomes'
import PageHeader from '@/components/PageHeader.vue'

use([CanvasRenderer, PieChart, TooltipComponent, LegendComponent])

const route = useRoute()
const router = useRouter()
const message = useMessage()

const versionId = computed(() => route.params.id as string)

/* ────── Core data ────── */
const loading = ref(false)
const versionDetail = ref<VersionDetailResponse | null>(null)
const species = ref<SpeciesDatabase | null>(null)
let speciesCache: SpeciesDatabase[] = []

const activeTab = ref<'overview' | 'genes' | 'annotations' | 'mapping' | 'files'>('overview')
const selectedChrom = ref('')

/* ────── Genes tab ────── */
const searchField = ref<'all' | 'geneId' | 'geneSymbol' | 'description'>('all')
const searchQuery = ref('')
const genePage = ref(1)
const geneTotal = ref(0)
const geneData = ref<ApiGene[]>([])
const geneLoading = ref(false)
let geneSearchTimer: ReturnType<typeof setTimeout> | null = null

/* ────── Drawer ────── */
const drawerVisible = ref(false)
const drawerGene = ref<GeneDetail | null>(null)
const drawerLoading = ref(false)
const seqType = ref<'genomic' | 'cds' | 'protein'>('genomic')
const seqData = ref<SequenceResult | null>(null)
const seqLoading = ref(false)

/* ────── Mapping ────── */
const mapInput = ref('')
const mapResult = ref<{ input: string; output: string | null; status: 'success' | 'fail' }[]>([])
const mappingDirection = ref<'forward' | 'reverse'>('forward')

/* ────── Annotations tab ────── */
const goTerms = ref<GoTermItem[]>([])
const keggPathways = ref<KeggPathwayItem[]>([])

/* ────── Computed ────── */
const version = computed(() => versionDetail.value)

const versionSelect = computed({
  get: () => versionId.value,
  set: (next: string) => router.push(`/database/${next}`),
})

const versionOptions = computed(() =>
  species.value?.genomeVersions.map((item) => ({
    label: `${item.versionName} · ${item.assemblyName}`,
    value: item.versionId,
  })) ?? [],
)

const currentMapping = computed(() => species.value?.versionMappings[0])

const mappingDirLabel = computed(() => {
  const m = currentMapping.value
  if (!m) return { forward: '', reverse: '' }
  return {
    forward: `${m.source} → ${m.target}`,
    reverse: `${m.target} → ${m.source}`,
  }
})

const chromosomes = computed<Chromosome[]>(() => versionDetail.value?.chromosomes ?? [])
const geneTypeStats = computed<GeneTypeStat[]>(() => versionDetail.value?.geneTypeStats ?? [])
const dataFiles = computed<DatabaseDataFile[]>(() => {
  if (!versionDetail.value) return []
  const df = versionDetail.value.dataFiles
  return (['fasta', 'gff', 'go', 'kegg'] as DataFileType[])
    .map((key) => df[key])
    .filter((f): f is DatabaseDataFile => Boolean(f))
})

const maxChromLength = computed(() =>
  chromosomes.value.length ? Math.max(...chromosomes.value.map((c) => c.length)) : 1,
)

const pieOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0, textStyle: { color: '#86909c', fontSize: 12 } },
  series: [
    {
      type: 'pie',
      radius: ['45%', '70%'],
      avoidLabelOverlap: false,
      label: { show: false },
      data: geneTypeStats.value.map((item) => ({
        name: item.name,
        value: item.value,
        itemStyle: { color: item.color },
      })),
    },
  ],
}))

const seqAvailable = computed(() => {
  const sa = drawerGene.value?.sequenceAvailable
  return {
    genomic: sa?.genomic ?? true,
    cds: sa?.cds ?? false,
    protein: sa?.protein ?? false,
  }
})

/* ────── Data loading ────── */
onMounted(async () => {
  try {
    const res = await fetchSpecies()
    speciesCache = res.species
  } catch {
    speciesCache = []
  }
  await loadVersionData()
})

let loadCounter = 0
async function loadVersionData() {
  const myCounter = ++loadCounter
  loading.value = true
  versionDetail.value = null
  species.value = null
  try {
    const detail = await fetchVersionDetail(versionId.value)
    if (myCounter !== loadCounter) return
    versionDetail.value = detail
    species.value = speciesCache.find((s) => s.id === detail.speciesId) ?? null
    await Promise.all([loadAnnotations(), searchGenesApi(1), loadAutoOpenGene()])
  } catch {
    if (myCounter === loadCounter) {
      versionDetail.value = null
      species.value = null
    }
  } finally {
    if (myCounter === loadCounter) loading.value = false
  }
}

watch(versionId, () => {
  genePage.value = 1
  searchQuery.value = ''
  selectedChrom.value = ''
  loadVersionData()
})

async function loadAnnotations() {
  try {
    const [go, kegg] = await Promise.all([
      fetchGoTerms(versionId.value, { page: 1 }).catch(() => ({ total: 0, items: [] })),
      fetchKeggPathways(versionId.value, {}).catch(() => ({ total: 0, items: [] })),
    ])
    goTerms.value = go.items.slice(0, 50)
    keggPathways.value = kegg.items.slice(0, 50)
  } catch {
    goTerms.value = []
    keggPathways.value = []
  }
}

/* ────── Gene search ────── */
const searchFieldOptions = [
  { label: '全部字段', value: 'all' },
  { label: 'Gene ID', value: 'geneId' },
  { label: 'Symbol', value: 'geneSymbol' },
  { label: '功能描述', value: 'description' },
]

const FIELD_MAP: Record<string, 'all' | 'gene_id' | 'gene_name' | 'annotation' | 'go' | 'kegg'> = {
  all: 'all',
  geneId: 'gene_id',
  geneSymbol: 'gene_name',
  description: 'annotation',
}

async function searchGenesApi(page = 1) {
  if (!versionId.value) return
  geneLoading.value = true
  try {
    const field = searchFieldOverride.value ?? (FIELD_MAP[searchField.value] ?? 'all')
    const res = await searchGenes(versionId.value, {
      field,
      q: searchQuery.value.trim() || undefined,
      chromosome: selectedChrom.value || undefined,
      page,
      page_size: 10,
    })
    geneData.value = res.items
    geneTotal.value = res.total
    genePage.value = page
  } catch {
    geneData.value = []
    geneTotal.value = 0
  } finally {
    geneLoading.value = false
  }
}

watch([searchField, selectedChrom], () => {
  searchFieldOverride.value = null  // 用户手动切换字段 → 取消 GO/KEGG 反查 override
  genePage.value = 1
  searchGenesApi(1)
})

watch(searchQuery, () => {
  if (!searchQuery.value.trim()) searchFieldOverride.value = null  // 清空查询 → 回到普通模式
  if (geneSearchTimer) clearTimeout(geneSearchTimer)
  geneSearchTimer = setTimeout(() => {
    genePage.value = 1
    searchGenesApi(1)
  }, 300)
})

function onGenePageChange(page: number) {
  searchGenesApi(page)
}

const sourceLabel: Record<DataFileType, string> = {
  fasta: 'FASTA',
  gff: 'GFF',
  go: 'GO',
  kegg: 'KEGG',
}

/* ────── Gene table columns ────── */
const geneColumns: DataTableColumns<ApiGene> = [
  {
    title: 'Gene ID',
    key: 'geneId',
    width: 130,
    render: (gene) => h('button', { class: 'gene-link', onClick: () => openGeneDetail(gene.geneId) }, gene.geneId),
  },
  { title: 'Symbol', key: 'geneName', width: 110 },
  {
    title: '位置',
    key: 'location',
    width: 210,
    render: (gene) => h('span', { class: 'mono' }, `${gene.chromosome}:${gene.start.toLocaleString()}-${gene.end.toLocaleString()} (${gene.strand})`),
  },
  { title: '类型', key: 'geneType', width: 110, render: (gene) => geneTypeText(gene.geneType) },
  { title: '长度', key: 'length', width: 90, render: (gene) => `${gene.length.toLocaleString()} bp` },
  { title: '功能描述', key: 'annotation', ellipsis: { tooltip: true } },
  {
    title: '操作',
    key: 'actions',
    width: 96,
    render: (gene) => h(NButton, { size: 'tiny', tertiary: true, onClick: () => openGeneDetail(gene.geneId) }, { default: () => '详情' }),
  },
]

/* ────── Gene drawer ────── */
async function openGeneDetail(geneId: string) {
  drawerLoading.value = true
  drawerGene.value = null
  seqData.value = null
  drawerVisible.value = true
  try {
    const detail = await fetchGeneDetail(versionId.value, geneId)
    drawerGene.value = detail
    const sa = detail.sequenceAvailable
    seqType.value = sa.genomic ? 'genomic' : sa.cds ? 'cds' : 'protein'
    await loadSequence()
  } catch {
    message.error('加载基因详情失败')
  } finally {
    drawerLoading.value = false
  }
}

async function loadSequence() {
  if (!drawerGene.value) return
  seqLoading.value = true
  try {
    seqData.value = await fetchGeneSequence(versionId.value, drawerGene.value.gene.geneId, {
      type: seqType.value,
      format: 'json',
    })
  } catch {
    seqData.value = null
  } finally {
    seqLoading.value = false
  }
}

function onSeqTypeChange(type: 'genomic' | 'cds' | 'protein') {
  seqType.value = type
  loadSequence()
}

function downloadFasta() {
  if (!seqData.value || !drawerGene.value) return
  const content = `>${seqData.value.header}\n${seqData.value.sequence}`
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${drawerGene.value.gene.geneId}_${seqType.value}.fa`
  a.click()
  URL.revokeObjectURL(url)
}

async function loadAutoOpenGene() {
  const geneId = route.query.gene as string | undefined
  if (geneId) await openGeneDetail(geneId)
}

/* ────── Annotations tab interactions ────── */
// GO/KEGG 条目点击 → 基因 Tab 反查：用 override 强制后端 field=go/kegg
const searchFieldOverride = ref<'go' | 'kegg' | null>(null)

function clickGoTerm(goId: string) {
  searchFieldOverride.value = 'go'
  searchQuery.value = goId
  activeTab.value = 'genes'
}

function clickKeggPathway(pathwayId: string) {
  searchFieldOverride.value = 'kegg'
  searchQuery.value = pathwayId
  activeTab.value = 'genes'
}

function clearSearchOverride() {
  searchFieldOverride.value = null
  searchQuery.value = ''
}

/* ────── Mapping ────── */
async function runMap() {
  const ids = mapInput.value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)
  if (!ids.length) {
    message.warning('请输入要转换的基因 ID')
    return
  }
  const m = currentMapping.value
  if (!m) {
    message.warning('当前版本暂无映射配置')
    return
  }
  const targetVersionId = mappingDirection.value === 'forward' ? m.target : m.source
  try {
    const res = await mapIds(versionId.value, { targetVersionId, ids })
    mapResult.value = res.results.map((r) => ({
      input: r.input,
      output: r.output ?? null,
      status: (r.status === 'success' ? 'success' : 'fail') as 'success' | 'fail',
    }))
    message.success(`映射完成：${res.successCount}/${res.totalCount} 成功`)
  } catch {
    message.error('映射失败')
  }
}

function swapDirection() {
  mappingDirection.value = mappingDirection.value === 'forward' ? 'reverse' : 'forward'
  mapInput.value = ''
  mapResult.value = []
}

function downloadMap() {
  const content = mapResult.value.map((row) => `${row.input}\t${row.output || 'N/A'}\t${row.status}`).join('\n')
  const blob = new Blob([`input\toutput\tstatus\n${content}`], { type: 'text/tsv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${species.value?.id || 'database'}_mapping.tsv`
  a.click()
  URL.revokeObjectURL(url)
}

/* ────── Helpers ────── */
function buildStatusType(status: BuildStatus): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'ready') return 'success'
  if (status === 'building') return 'warning'
  if (status === 'error') return 'error'
  return 'default'
}

function buildStatusText(status: BuildStatus) {
  if (status === 'ready') return '就绪'
  if (status === 'building') return '构建中'
  if (status === 'missing') return '缺失'
  return '异常'
}

function geneTypeText(type: string) {
  if (type === 'protein_coding') return '蛋白编码'
  if (type === 'lncRNA') return 'lncRNA'
  if (type === 'pseudogene') return '假基因'
  if (type === 'transposable_element') return '转座元件'
  return '其他'
}

function selectChrom(name: string) {
  selectedChrom.value = selectedChrom.value === name ? '' : name
  if (selectedChrom.value) activeTab.value = 'genes'
}

function goNamespaceLabel(namespace: 'BP' | 'MF' | 'CC') {
  if (namespace === 'BP') return '生物过程'
  if (namespace === 'MF') return '分子功能'
  return '细胞组分'
}

async function copyText(text: string, label = '内容') {
  try {
    await navigator.clipboard.writeText(text)
    message.success(`${label}已复制`)
  } catch {
    message.error('复制失败')
  }
}
</script>

<template>
  <!-- 单根节点：DefaultLayout 用 <Transition mode="out-in"> 包裹路由组件，
       fragment（多根）会导致 SPA 跳转时组件不挂载（vuejs/core#6656）→ 空白页 -->
  <div class="database-detail-page" role="main" aria-label="参考基因组详情">
    <template v-if="version && species">
    <PageHeader
      :title="`${species.commonName} ${version.versionName}`"
      :subtitle="version.description"
      back-to="/database"
      back-label="返回数据库"
    >
      <template #actions>
        <NSelect v-model:value="versionSelect" :options="versionOptions" size="small" style="width: 260px" />
      </template>
    </PageHeader>

    <section class="detail-hero">
      <div class="species-icon" :style="{ background: species.gradient }">{{ species.icon }}</div>
      <div class="hero-info">
        <div class="hero-kicker">{{ species.scientificName }} · Taxonomy {{ species.taxonomyId }}</div>
        <p>{{ version.description }}</p>
      </div>
    </section>

    <div class="detail-layout">
      <aside class="info-panel">
        <div class="panel-section">
          <div class="section-title">版本摘要</div>
          <div class="stat-grid">
            <div class="stat-item"><NStatistic label="染色体" :value="version.stats.chromosomes" /></div>
            <div class="stat-item"><NStatistic label="基因" :value="version.stats.totalGenes" /></div>
            <div class="stat-item"><NStatistic label="蛋白编码" :value="version.stats.proteinCoding" /></div>
            <div class="stat-item"><NStatistic label="大小" :value="version.stats.genomeSize" /></div>
          </div>
        </div>

        <div class="panel-section">
          <div class="section-title">数据源状态</div>
          <div class="file-list compact">
            <div v-for="file in dataFiles" :key="file.type" class="file-item" @click="copyText(file.path, file.label)">
              <div>
                <div class="file-name">{{ sourceLabel[file.type] }}</div>
                <div class="file-meta">{{ file.format }} · {{ file.size }}</div>
              </div>
              <NTag size="tiny" :type="buildStatusType(file.buildStatus)" round>
                {{ buildStatusText(file.buildStatus) }}
              </NTag>
            </div>
          </div>
        </div>

        <div class="panel-section">
          <div class="section-title">版本映射</div>
          <div v-if="species.versionMappings.length" class="mapping-card-list">
            <div v-for="mapping in species.versionMappings" :key="`${mapping.source}-${mapping.target}`" class="mapping-card">
              <div class="mapping-pair">{{ mapping.source }} → {{ mapping.target }}</div>
              <div class="mapping-meta">{{ mapping.mappingTool }} · {{ mapping.mappedGenes.toLocaleString() }} genes · Q{{ mapping.averageQuality }}</div>
            </div>
          </div>
          <div v-else class="subtle-empty">暂无跨版本映射</div>
        </div>

        <div class="info-actions">
          <NButton size="small" type="primary" block @click="activeTab = 'genes'">浏览基因</NButton>
          <NButton size="small" block quaternary @click="activeTab = 'files'">查看文件路径</NButton>
        </div>
      </aside>

      <main class="main-content">
        <NTabs v-model:value="activeTab" type="line" animated size="medium">
          <NTabPane name="overview" tab="概览">
            <div class="overview-grid">
              <section class="content-block">
                <div class="block-title">
                  染色体长度
                  <span v-if="selectedChrom" class="filter-hint">
                    已筛选 {{ selectedChrom }}
                    <NButton size="tiny" quaternary @click="selectedChrom = ''">清除</NButton>
                  </span>
                </div>
                <div v-if="chromosomes.length" class="chrom-chart">
                  <div
                    v-for="chrom in chromosomes"
                    :key="chrom.name"
                    class="chrom-row"
                    :class="{ active: selectedChrom === chrom.name }"
                    @click="selectChrom(chrom.name)"
                  >
                    <span class="chrom-name">{{ chrom.name }}</span>
                    <div class="chrom-bar-track">
                      <div
                        class="chrom-bar"
                        :style="{ width: `${(chrom.length / maxChromLength) * 100}%`, background: chrom.color }"
                      />
                    </div>
                    <span class="chrom-length">{{ (chrom.length / 1e6).toFixed(1) }} Mb</span>
                  </div>
                </div>
                <NEmpty v-else description="暂无染色体数据" />
              </section>

              <section class="content-block">
                <div class="block-title">基因类型</div>
                <VChart v-if="geneTypeStats.length" :option="pieOption" autoresize style="height: 282px" />
                <NEmpty v-else description="暂无基因类型统计" />
              </section>
            </div>
          </NTabPane>

          <NTabPane name="genes" tab="基因">
            <div class="search-bar">
              <NSelect v-model:value="searchField" :options="searchFieldOptions" class="search-field" />
              <NInput
                v-model:value="searchQuery"
                clearable
                placeholder="搜索 Gene ID、Symbol、功能描述或别名"
                class="gene-search"
              >
                <template #prefix><NIcon><SearchOutline /></NIcon></template>
              </NInput>
            </div>

            <div v-if="selectedChrom" class="filter-hint standalone">
              已按 {{ selectedChrom }} 筛选
              <NButton size="tiny" quaternary @click="selectedChrom = ''">清除筛选</NButton>
            </div>

            <div v-if="searchFieldOverride" class="filter-hint standalone">
              {{ searchFieldOverride === 'go' ? 'GO' : 'KEGG' }} 反查：{{ searchQuery }}
              <NButton size="tiny" quaternary @click="clearSearchOverride">清除反查</NButton>
            </div>

            <NSpin :show="geneLoading">
              <div v-if="geneData.length || geneLoading" class="table-wrap">
                <div class="result-count">共 {{ geneTotal.toLocaleString() }} 条基因</div>
                <NDataTable
                  :columns="geneColumns"
                  :data="geneData"
                  :row-key="(row: ApiGene) => row.geneId"
                  :pagination="{
                    pageSize: 10,
                    itemCount: geneTotal,
                    page: genePage,
                    showSizePicker: false,
                    onUpdatePage: onGenePageChange,
                  }"
                  remote
                  size="small"
                  :bordered="false"
                  :max-height="440"
                />
              </div>
              <NEmpty v-else class="tab-empty" description="暂无匹配基因" />
            </NSpin>
          </NTabPane>

          <NTabPane name="annotations" tab="GO / KEGG">
            <div class="annotation-grid">
              <section class="content-block">
                <div class="block-title">GO 注释</div>
                <div v-if="goTerms.length" class="annotation-list">
                  <div
                    v-for="item in goTerms"
                    :key="item.goId"
                    class="annotation-row annotation-row-clickable"
                    @click="clickGoTerm(item.goId)"
                  >
                    <span class="mono strong">{{ item.goId }}</span>
                    <span>{{ item.name }}</span>
                    <NTag size="tiny" round>{{ goNamespaceLabel(item.aspect as 'BP' | 'MF' | 'CC') }}</NTag>
                    <span class="annotation-source">{{ item.geneCount }} genes</span>
                  </div>
                </div>
                <NEmpty v-else description="暂无 GO 注释" />
              </section>

              <section class="content-block">
                <div class="block-title">KEGG 通路</div>
                <div v-if="keggPathways.length" class="annotation-list">
                  <div
                    v-for="item in keggPathways"
                    :key="item.pathwayId"
                    class="annotation-row annotation-row-clickable"
                    @click="clickKeggPathway(item.pathwayId)"
                  >
                    <span class="mono strong">{{ item.pathwayId }}</span>
                    <span>{{ item.name }}</span>
                    <NTag size="tiny" type="info" round>pathway</NTag>
                    <span class="annotation-source">{{ item.geneCount }} genes</span>
                  </div>
                </div>
                <NEmpty v-else description="暂无 KEGG 注释" />
              </section>
            </div>
          </NTabPane>

          <NTabPane name="mapping" tab="版本映射">
            <section class="content-block">
              <div class="mapping-header">
                <div>
                  <div class="block-title">基因 ID 映射</div>
                  <p class="block-desc">{{ mappingDirection === 'forward' ? mappingDirLabel.forward : mappingDirLabel.reverse }}</p>
                </div>
                <NButton size="small" quaternary @click="swapDirection">
                  <template #icon><NIcon><SwapHorizontalOutline /></NIcon></template>
                  交换方向
                </NButton>
              </div>

              <div v-if="species.versionMappings.length" class="mapping-layout">
                <div class="mapping-side">
                  <div class="mapping-label">输入基因 ID（每行或逗号分隔）</div>
                  <NInput
                    v-model:value="mapInput"
                    type="textarea"
                    :autosize="{ minRows: 8, maxRows: 14 }"
                    placeholder="Lsat_v8_0001&#10;Lsat_v8_0002"
                    class="mono-input"
                  />
                  <NButton type="primary" size="small" block @click="runMap">
                    <template #icon><NIcon><SwapHorizontalOutline /></NIcon></template>
                    开始映射
                  </NButton>
                </div>

                <div class="mapping-side">
                  <div class="mapping-label">映射结果</div>
                  <div class="mapping-result">
                    <div v-if="!mapResult.length" class="mapping-empty">等待映射...</div>
                    <div
                      v-for="row in mapResult"
                      :key="row.input"
                      class="mapping-row"
                      :class="{ fail: row.status === 'fail' }"
                    >
                      <span class="mono">{{ row.input }}</span>
                      <span>→</span>
                      <button v-if="row.output" class="gene-link" @click="openGeneDetail(row.output)">{{ row.output }}</button>
                      <span v-else class="mono">未找到</span>
                      <NTag size="tiny" :type="row.status === 'success' ? 'success' : 'error'" round>
                        {{ row.status === 'success' ? '成功' : '失败' }}
                      </NTag>
                    </div>
                  </div>
                  <NButton v-if="mapResult.length" size="small" quaternary block @click="downloadMap">
                    <template #icon><NIcon><DownloadOutline /></NIcon></template>
                    导出结果
                  </NButton>
                </div>
              </div>
              <NEmpty v-else class="tab-empty" description="当前物种暂无跨版本映射" />
            </section>
          </NTabPane>

          <NTabPane name="files" tab="数据文件">
            <section class="content-block">
              <div class="block-title">数据文件</div>
              <div class="file-list">
                <div v-for="file in dataFiles" :key="file.type" class="file-row">
                  <div class="file-type">{{ sourceLabel[file.type] }}</div>
                  <div class="file-body">
                    <div class="file-path mono">{{ file.path }}</div>
                    <div class="file-meta">
                      {{ file.format }} · {{ file.size }} · {{ file.buildTool || 'custom' }}
                      <template v-if="file.indexPath"> · index: {{ file.indexPath }}</template>
                      <template v-if="file.dbPath"> · db: {{ file.dbPath }}</template>
                    </div>
                  </div>
                  <NTag size="small" :type="buildStatusType(file.buildStatus)" round>{{ buildStatusText(file.buildStatus) }}</NTag>
                  <NButton size="tiny" quaternary @click="copyText(file.path, file.label)">
                    <template #icon><NIcon><CopyOutline /></NIcon></template>
                  </NButton>
                </div>
              </div>
            </section>
          </NTabPane>
        </NTabs>
      </main>
    </div>

    <NDrawer v-model:show="drawerVisible" :width="560" placement="right">
      <NDrawerContent v-if="drawerGene" :title="drawerGene.gene.geneId" closable>
        <NSpin :show="drawerLoading">
          <div class="gene-drawer">
            <div class="gene-summary-card">
              <div>
                <div class="gene-symbol">{{ drawerGene.gene.geneName }}</div>
                <div class="gene-name">{{ drawerGene.gene.annotation }}</div>
              </div>
              <NTag size="small" type="success" round>{{ drawerGene.gene.geneType }}</NTag>
            </div>

            <NTabs type="segment" animated>
              <NTabPane name="summary" tab="Summary">
                <div class="detail-list">
                  <div><span>基因类型</span><strong>{{ geneTypeText(drawerGene.gene.geneType) }}</strong></div>
                  <div><span>位置</span><strong class="mono">{{ drawerGene.gene.chromosome }}:{{ drawerGene.gene.start.toLocaleString() }}-{{ drawerGene.gene.end.toLocaleString() }} ({{ drawerGene.gene.strand }})</strong></div>
                  <div><span>长度</span><strong>{{ drawerGene.gene.length.toLocaleString() }} bp</strong></div>
                </div>

                <div v-if="drawerGene.transcripts[0]?.exons" class="gene-structure-section">
                  <div class="drawer-section-title">外显子结构</div>
                  <div class="gene-structure">
                    <div class="strand-arrow">{{ drawerGene.gene.strand === '+' ? '→' : '←' }}</div>
                    <div class="exon-track">
                      <template v-for="exon in drawerGene.transcripts[0].exons" :key="exon.rank">
                        <div v-if="exon.rank > 1" class="intron" />
                        <div class="exon" :title="`E${exon.rank}`" />
                      </template>
                    </div>
                  </div>
                </div>
              </NTabPane>

              <NTabPane name="transcripts" tab="Transcripts">
                <div v-for="tx in drawerGene.transcripts" :key="tx.transcriptId" class="tx-row">
                  <div>
                    <div class="mono strong">{{ tx.transcriptId }}</div>
                    <div class="file-meta">{{ tx.biotype }} · {{ tx.length.toLocaleString() }} bp · {{ tx.exonCount }} exons</div>
                  </div>
                  <NTag v-if="tx.canonical" size="tiny" type="success" round>Canonical</NTag>
                </div>
                <NEmpty v-if="!drawerGene.transcripts.length" description="无转录本数据" />
              </NTabPane>

              <NTabPane name="go" tab="GO">
                <div v-for="namespace in (['MF', 'BP', 'CC'] as const)" :key="namespace" class="drawer-annotation-group">
                  <div class="drawer-section-title">{{ goNamespaceLabel(namespace) }}</div>
                  <div
                    v-if="drawerGene.go.filter((g) => g.namespace === namespace).length"
                    class="drawer-annotation-list"
                  >
                    <div
                      v-for="item in drawerGene.go.filter((g) => g.namespace === namespace)"
                      :key="item.goId"
                      class="drawer-annotation-row"
                    >
                      <span class="mono strong">{{ item.goId }}</span>
                      <span>{{ item.term }}</span>
                      <span class="annotation-source">{{ item.evidenceCode }} · {{ item.source }}</span>
                    </div>
                  </div>
                  <div v-else class="subtle-empty small">无记录</div>
                </div>
              </NTabPane>

              <NTabPane name="kegg" tab="KEGG">
                <div v-if="drawerGene.kegg.pathways.length" class="drawer-annotation-list">
                  <div
                    v-for="item in drawerGene.kegg.pathways"
                    :key="item.pathwayId"
                    class="drawer-annotation-row"
                  >
                    <span class="mono strong">{{ item.pathwayId }}</span>
                    <span>{{ item.name }}</span>
                    <span class="annotation-source">{{ item.geneCount }} genes</span>
                  </div>
                </div>
                <NEmpty v-else description="暂无 KEGG 注释" />
              </NTabPane>

              <NTabPane name="sequence" tab="Sequence">
                <div class="sequence-type-bar">
                  <NButtonGroup size="small">
                    <NButton
                      :type="seqType === 'genomic' ? 'primary' : 'default'"
                      :disabled="!seqAvailable.genomic"
                      @click="onSeqTypeChange('genomic')"
                    >Genomic</NButton>
                    <NButton
                      :type="seqType === 'cds' ? 'primary' : 'default'"
                      :disabled="!seqAvailable.cds"
                      @click="onSeqTypeChange('cds')"
                    >CDS</NButton>
                    <NButton
                      :type="seqType === 'protein' ? 'primary' : 'default'"
                      :disabled="!seqAvailable.protein"
                      @click="onSeqTypeChange('protein')"
                    >Protein</NButton>
                  </NButtonGroup>
                </div>
                <NSpin :show="seqLoading">
                  <div v-if="seqData" class="sequence-block">
                    <div class="drawer-section-title">FASTA 预览</div>
                    <pre>&gt;{{ seqData.header }}
{{ seqData.sequence }}</pre>
                    <div class="sequence-actions">
                      <NButton size="small" quaternary @click="copyText(seqData.sequence, '序列')">
                        <template #icon><NIcon><CopyOutline /></NIcon></template>
                        复制序列
                      </NButton>
                      <NButton size="small" quaternary @click="downloadFasta">
                        <template #icon><NIcon><DownloadOutline /></NIcon></template>
                        下载 FASTA
                      </NButton>
                    </div>
                  </div>
                  <div v-else-if="!seqLoading" class="sequence-block">
                    <div class="subtle-empty">该序列类型暂不可用</div>
                  </div>
                </NSpin>
              </NTabPane>
            </NTabs>
          </div>
        </NSpin>
      </NDrawerContent>
      <NDrawerContent v-else-if="drawerLoading" title="加载中" closable>
        <NSpin :show="true" style="min-height: 200px" />
      </NDrawerContent>
    </NDrawer>
    </template>

    <div v-else-if="!loading" class="not-found">
      <NEmpty description="未找到该数据库版本" />
      <NButton size="small" type="primary" @click="router.push('/database')">返回数据库</NButton>
    </div>
  </div>
</template>

<style scoped>
.database-detail-page {
  --db-primary: #165dff;
  --db-purple: #722ed1;
  --db-text: #1d2129;
  --db-subtext: #4e5969;
  --db-muted: #86909c;
  --db-border: #e5e6eb;
  --db-soft: #f7f8fa;
  --db-card: #fff;
  min-height: 100%;
}

.detail-hero {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 16px;
  align-items: center;
  min-height: 150px;
  padding: 22px;
  margin-bottom: 16px;
  border-radius: 8px;
  color: #fff;
  background: linear-gradient(135deg, #0f1f4a 0%, #165dff 58%, #722ed1 100%);
}

.species-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 58px;
  height: 58px;
  border-radius: 8px;
  font-size: 30px;
}

.hero-info {
  min-width: 0;
}

.hero-kicker {
  color: rgba(255, 255, 255, 0.74);
  font-size: 12px;
  font-weight: 700;
}

.detail-hero p {
  margin: 0;
  color: rgba(255, 255, 255, 0.82);
  font-size: 13px;
  line-height: 1.5;
}

.detail-layout {
  display: grid;
  grid-template-columns: 330px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.info-panel,
.main-content,
.content-block {
  border: 1px solid var(--db-border);
  border-radius: 8px;
  background: var(--db-card);
}

.info-panel {
  position: sticky;
  top: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}

.panel-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-title,
.block-title,
.drawer-section-title {
  color: var(--db-text);
  font-size: 14px;
  font-weight: 800;
}

.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.stat-item {
  padding: 10px 8px;
  text-align: center;
  border-radius: 8px;
  background: var(--db-soft);
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.file-list.compact {
  gap: 6px;
}

.file-item,
.file-row,
.mapping-card,
.tx-row,
.annotation-row,
.drawer-annotation-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  border-radius: 8px;
  background: var(--db-soft);
}

.file-item {
  justify-content: space-between;
  padding: 9px 10px;
  cursor: pointer;
}

.file-name,
.file-type {
  color: var(--db-text);
  font-size: 13px;
  font-weight: 800;
}

.file-meta,
.block-desc,
.annotation-source,
.mapping-meta,
.subtle-empty {
  color: var(--db-muted);
  font-size: 12px;
  line-height: 1.45;
}

.mapping-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mapping-card {
  align-items: flex-start;
  flex-direction: column;
  padding: 10px;
}

.mapping-pair {
  color: var(--db-text);
  font-size: 12px;
  font-weight: 800;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.info-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.main-content {
  padding: 16px;
  min-width: 0;
}

.overview-grid,
.annotation-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: 16px;
}

.content-block {
  padding: 16px;
}

.block-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.filter-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--db-muted);
  font-size: 12px;
  font-weight: 400;
}

.filter-hint.standalone {
  margin-bottom: 10px;
}

.chrom-chart {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chrom-row {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) 72px;
  gap: 10px;
  align-items: center;
  padding: 5px 6px;
  border-radius: 6px;
  cursor: pointer;
}

.chrom-row:hover,
.chrom-row.active {
  background: var(--db-soft);
}

.chrom-row.active {
  box-shadow: inset 0 0 0 1px rgba(22, 93, 255, 0.25);
}

.chrom-name,
.chrom-length,
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.chrom-name,
.chrom-length {
  color: var(--db-subtext);
  font-size: 12px;
}

.chrom-length {
  text-align: right;
}

.chrom-bar-track {
  height: 18px;
  border-radius: 4px;
  background: #eef0f4;
  overflow: hidden;
}

.chrom-bar {
  height: 100%;
  border-radius: 4px;
}

.search-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.search-field {
  width: 132px;
}

.gene-search {
  flex: 1;
}

.result-count {
  margin-bottom: 8px;
  color: var(--db-muted);
  font-size: 12px;
}

:deep(.gene-link),
.gene-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--db-primary);
  font: inherit;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  cursor: pointer;
}

:deep(.mono) {
  font-size: 12px;
}

.strong {
  font-weight: 800;
}

.annotation-list,
.drawer-annotation-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.annotation-row,
.drawer-annotation-row {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) auto auto;
  padding: 9px 10px;
  font-size: 12px;
}

.annotation-row-clickable {
  cursor: pointer;
  transition: background 0.15s;
}

.annotation-row-clickable:hover {
  background: #eef0f4;
}

.mapping-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.mapping-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}

.mapping-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mapping-label {
  color: var(--db-subtext);
  font-size: 12px;
  font-weight: 700;
}

.mono-input :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.mapping-result {
  min-height: 230px;
  max-height: 300px;
  padding: 8px;
  overflow-y: auto;
  border: 1px solid var(--db-border);
  border-radius: 8px;
}

.mapping-empty,
.tab-empty {
  padding: 48px 16px;
}

.mapping-row {
  flex-wrap: wrap;
  justify-content: space-between;
  padding: 8px 10px;
  margin-bottom: 6px;
  font-size: 12px;
}

.mapping-row.fail {
  opacity: 0.68;
}

.file-row {
  padding: 11px 12px;
}

.file-type {
  width: 64px;
  flex: 0 0 auto;
}

.file-body {
  flex: 1;
  min-width: 0;
}

.file-path {
  color: var(--db-text);
  font-size: 12px;
  word-break: break-all;
}

.gene-drawer {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.gene-summary-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  border-radius: 8px;
  background: linear-gradient(135deg, #e8f3ff 0%, #f1e8ff 100%);
}

.gene-symbol {
  color: var(--db-text);
  font-size: 20px;
  font-weight: 800;
}

.gene-name,
.gene-description {
  color: var(--db-subtext);
  font-size: 13px;
  line-height: 1.55;
}

.detail-list {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
}

.detail-list > div {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 12px;
  font-size: 13px;
}

.detail-list span {
  color: var(--db-muted);
}

.detail-list strong {
  min-width: 0;
  color: var(--db-text);
  word-break: break-word;
}

.gene-structure-section {
  padding: 14px;
  border-radius: 8px;
  background: var(--db-soft);
}

.gene-structure {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.strand-arrow {
  color: var(--db-muted);
  font-size: 20px;
}

.exon-track {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  height: 28px;
}

.exon {
  flex: 0 0 30px;
  height: 20px;
  border-radius: 4px;
  background: linear-gradient(135deg, #165dff, #722ed1);
}

.intron {
  flex: 1;
  min-width: 16px;
  height: 2px;
  margin: 0 3px;
  background: #c9cdd4;
}

.tx-row,
.drawer-annotation-row {
  justify-content: space-between;
  padding: 10px;
}

.drawer-annotation-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: start;
}

.drawer-annotation-group + .drawer-annotation-group {
  margin-top: 14px;
}

.sequence-type-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.sequence-block {
  margin-top: 0;
}

.sequence-block pre {
  white-space: pre-wrap;
  word-break: break-all;
  padding: 12px;
  border-radius: 8px;
  color: #1d2129;
  background: #f7f8fa;
  font-size: 12px;
  line-height: 1.6;
}

.sequence-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.subtle-empty.small {
  padding: 8px 0;
}

.not-found {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-items: center;
  padding: 80px 24px;
}

@media (max-width: 1100px) {
  .detail-layout,
  .overview-grid,
  .annotation-grid,
  .mapping-layout {
    grid-template-columns: 1fr;
  }

  .info-panel {
    position: static;
  }
}

@media (max-width: 720px) {
  .detail-hero {
    grid-template-columns: 1fr;
  }

  .search-bar,
  .file-row {
    align-items: stretch;
    flex-direction: column;
  }

  .search-field {
    width: 100%;
  }

  .stat-grid {
    grid-template-columns: 1fr;
  }

  .annotation-row,
  .drawer-annotation-row {
    grid-template-columns: 1fr;
  }
}
</style>
