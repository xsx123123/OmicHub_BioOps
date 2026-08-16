<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import {
  NAlert, NButton, NDataTable, NDivider, NIcon, NInput, NRadioButton, NRadioGroup,
  NSelect, NTag, useMessage,
  type DataTableColumns,
} from 'naive-ui'
import {
  CopyOutline, DownloadOutline, SparklesOutline, TrashOutline,
} from '@vicons/ionicons5'
import {
  buildConvertRows, detectListType, extractColumn, parseIdList, rowsToDelimited,
  setOperate, SET_OP_LABEL, STATUS_LABEL,
  type ConvertRow, type ConvertStatus, type SetOp,
} from '@/utils/idConverterProcessor'
import {
  getGeneMapSync, loadGeneMap, lookupEntries,
  type IdType, type Species,
} from '@/utils/geneIdMap'
import PageHeader from '@/components/PageHeader.vue'

const message = useMessage()

/* ---------- 物种与 ID 类型 ---------- */

const species = ref<Species>('human')
const speciesOptions = [
  { label: '人 (Homo sapiens)', value: 'human' },
  { label: '小鼠 (Mus musculus)', value: 'mouse' },
  { label: '水稻（即将上线）', value: 'rice', disabled: true },
  { label: '番茄（即将上线）', value: 'tomato', disabled: true },
  { label: '拟南芥（即将上线）', value: 'arabidopsis', disabled: true },
  { label: '生菜（即将上线）', value: 'lettuce', disabled: true },
]

type TypeMode = 'auto' | IdType
const typeMode = ref<TypeMode>('auto')

/* ---------- 输入解析 ---------- */

const inputText = ref('')
const parsed = computed(() => parseIdList(inputText.value))
const detected = computed(() => detectListType(parsed.value.uniqueIds))
const effectiveType = computed<IdType>(() =>
  typeMode.value === 'auto' ? detected.value.type : typeMode.value,
)

const TYPE_TAG_TEXT: Record<IdType, string> = {
  symbol: 'Symbol',
  ensembl: 'Ensembl',
  entrez: 'Entrez',
  uniprot: 'UniProt',
}

/* ---------- 映射查询 ---------- */

// 物种映射表加载版本号：loadGeneMap 完成后 +1 触发 computed 重算
const mapVersion = ref(0)
watch(species, async (sp) => {
  await loadGeneMap(sp)
  mapVersion.value += 1
}, { immediate: true })

const rows = computed<ConvertRow[]>(() => {
  void mapVersion.value // 依赖加载完成事件
  const map = getGeneMapSync(species.value)
  if (!map || parsed.value.uniqueIds.length === 0) return []
  return buildConvertRows(lookupEntries(map, parsed.value.uniqueIds, effectiveType.value))
})

const stats = computed(() => ({
  parsed: parsed.value.ids.length,
  unique: parsed.value.uniqueIds.length,
  success: rows.value.filter((r) => r.status === 'success').length,
  multi: rows.value.filter((r) => r.status === 'multi').length,
  unmatched: rows.value.filter((r) => r.status === 'unmatched').length,
}))

/* ---------- 结果表格 ---------- */

function renderMulti(values: string[]) {
  if (values.length === 0) return h('span', { class: 'cell-empty' }, '—')
  return h('div', { class: 'cell-multi' }, values.map((v) => h('div', { key: v }, v)))
}

const STATUS_TAG_TYPE: Record<ConvertStatus, 'success' | 'error' | 'warning'> = {
  success: 'success',
  unmatched: 'error',
  multi: 'warning',
}

const columns: DataTableColumns<ConvertRow> = [
  { title: '原始 ID', key: 'input', sorter: (a, b) => a.input.localeCompare(b.input), width: 140 },
  { title: 'Symbol', key: 'symbols', render: (r) => renderMulti(r.symbols) },
  { title: 'Ensembl', key: 'ensembls', render: (r) => renderMulti(r.ensembls) },
  { title: 'Entrez', key: 'entrezs', render: (r) => renderMulti(r.entrezs), width: 110 },
  { title: 'UniProt', key: 'uniprots', render: (r) => renderMulti(r.uniprots), width: 110 },
  {
    title: '状态',
    key: 'status',
    width: 100,
    sorter: (a, b) => a.status.localeCompare(b.status),
    render: (r) => h(NTag, { size: 'small', type: STATUS_TAG_TYPE[r.status] }, { default: () => STATUS_LABEL[r.status] }),
  },
]

/* ---------- 导出与复制 ---------- */

function downloadText(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function exportTable(format: 'csv' | 'tsv') {
  if (rows.value.length === 0) {
    message.warning('暂无结果可导出')
    return
  }
  const delimiter = format === 'csv' ? ',' : '\t'
  downloadText(rowsToDelimited(rows.value, delimiter), `id_conversion.${format}`)
  message.success(`已导出 ${rows.value.length} 行`)
}

const copyColumn = ref<'input' | 'symbol' | 'ensembl' | 'entrez' | 'uniprot'>('symbol')
const copyColumnOptions = [
  { label: '原始 ID', value: 'input' },
  { label: 'Symbol', value: 'symbol' },
  { label: 'Ensembl', value: 'ensembl' },
  { label: 'Entrez', value: 'entrez' },
  { label: 'UniProt', value: 'uniprot' },
]

async function copyText(text: string, okMsg: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(okMsg)
  } catch {
    message.error('复制失败，请手动选择文本')
  }
}

async function copyColumnValues() {
  if (rows.value.length === 0) {
    message.warning('暂无结果可复制')
    return
  }
  const values = extractColumn(rows.value, copyColumn.value)
  if (values.length === 0) {
    message.warning('该列没有可复制的值')
    return
  }
  await copyText(values.join('\n'), `已复制 ${values.length} 条`)
}

/* ---------- 示例数据 ---------- */

function loadSample() {
  inputText.value = [
    'TP53', 'BRCA1', 'EGFR', 'GAPDH', 'ACTB',
    'MYC', 'KRAS', 'VEGFA', 'STAT3', 'JUN',
    'NOT_A_GENE_DEMO',
  ].join('\n')
  typeMode.value = 'auto'
  message.info('已载入示例基因列表（含 1 条演示未匹配）')
}

function clearAll() {
  inputText.value = ''
}

/* ---------- 集合运算 ---------- */

const listAText = ref('')
const listBText = ref('')
const listA = computed(() => parseIdList(listAText.value).uniqueIds)
const listB = computed(() => parseIdList(listBText.value).uniqueIds)
const setResult = ref<{ op: SetOp; items: string[] } | null>(null)

function runSetOp(op: SetOp) {
  if (listA.value.length === 0 || listB.value.length === 0) {
    message.warning('请先填写列表 A 和列表 B')
    return
  }
  setResult.value = { op, items: setOperate(listA.value, listB.value, op) }
}

function loadSetSample() {
  listAText.value = ['TP53', 'BRCA1', 'EGFR', 'MYC', 'KRAS', 'VEGFA', 'STAT3'].join('\n')
  listBText.value = ['EGFR', 'KRAS', 'NRAS', 'BRAF', 'PTEN', 'TP53', 'AKT1'].join('\n')
  setResult.value = null
  message.info('已载入集合运算示例')
}

async function copySetResult() {
  if (!setResult.value || setResult.value.items.length === 0) {
    message.warning('暂无集合运算结果')
    return
  }
  await copyText(setResult.value.items.join('\n'), `已复制 ${setResult.value.items.length} 条`)
}
</script>

<template>
  <div class="id-converter-page">
    <PageHeader title="ID 转换器" subtitle="基因 Symbol / Ensembl / Entrez / UniProt 互转与列表集合运算" back-to="/tools" back-label="返回工具箱">
      <template #actions>
        <NButton size="small" quaternary @click="loadSample">
          <template #icon><NIcon><SparklesOutline /></NIcon></template>
          示例数据
        </NButton>
      </template>
    </PageHeader>

    <NAlert type="info" class="local-alert" :bordered="false">
      纯本地运算，数据不离开浏览器。当前映射库为内置演示数据（人 / 小鼠常见基因）。
    </NAlert>

    <div class="id-converter-layout">
      <!-- 左：输入与参数 -->
      <aside class="param-panel">
        <div class="panel-header">
          <span class="panel-title">输入基因列表</span>
          <NTag v-if="stats.unique" size="small" type="primary">
            {{ TYPE_TAG_TEXT[effectiveType] }}{{ typeMode === 'auto' ? '（自动）' : '' }}
          </NTag>
        </div>
        <NInput
          v-model:value="inputText"
          type="textarea"
          :autosize="{ minRows: 10, maxRows: 18 }"
          placeholder="粘贴基因列表，支持换行 / 逗号 / 空格 / 分号 / Tab 混合分隔"
          class="id-input"
        />
        <p class="parse-hint">
          解析到 {{ stats.parsed }} 条 ID，去重后 {{ stats.unique }} 条
        </p>

        <div class="field">
          <span class="field-label">物种</span>
          <NSelect v-model:value="species" size="small" :options="speciesOptions" />
        </div>

        <div class="field">
          <span class="field-label">输入 ID 类型</span>
          <NRadioGroup v-model:value="typeMode" size="small">
            <NRadioButton value="auto">自动</NRadioButton>
            <NRadioButton value="symbol">Symbol</NRadioButton>
            <NRadioButton value="ensembl">Ensembl</NRadioButton>
            <NRadioButton value="entrez">Entrez</NRadioButton>
            <NRadioButton value="uniprot">UniProt</NRadioButton>
          </NRadioGroup>
        </div>

        <NButton size="small" quaternary block class="clear-btn" @click="clearAll">
          <template #icon><NIcon><TrashOutline /></NIcon></template>清空输入
        </NButton>
      </aside>

      <!-- 右：转换结果 -->
      <main class="work-area">
        <div class="result-card">
          <div class="result-header">
            <span class="panel-title">转换结果</span>
            <div class="result-stats">
              <NTag size="small" type="success">成功 {{ stats.success }}</NTag>
              <NTag size="small" type="warning">一对多 {{ stats.multi }}</NTag>
              <NTag size="small" type="error">未匹配 {{ stats.unmatched }}</NTag>
            </div>
          </div>

          <NDataTable
            :columns="columns"
            :data="rows"
            size="small"
            :pagination="{ pageSize: 15 }"
            :scroll-x="760"
            :max-height="440"
          />

          <div class="export-bar">
            <NButton size="tiny" secondary @click="exportTable('csv')">
              <template #icon><NIcon><DownloadOutline /></NIcon></template>CSV
            </NButton>
            <NButton size="tiny" secondary @click="exportTable('tsv')">
              <template #icon><NIcon><DownloadOutline /></NIcon></template>TSV
            </NButton>
            <NDivider vertical />
            <NSelect
              v-model:value="copyColumn"
              size="tiny"
              :options="copyColumnOptions"
              class="copy-col-select"
            />
            <NButton size="tiny" secondary @click="copyColumnValues">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制该列
            </NButton>
          </div>
        </div>

        <!-- 集合运算 -->
        <div class="result-card set-card">
          <div class="result-header">
            <span class="panel-title">列表集合运算</span>
            <NButton size="tiny" quaternary @click="loadSetSample">
              <template #icon><NIcon><SparklesOutline /></NIcon></template>示例
            </NButton>
          </div>
          <div class="set-inputs">
            <div class="set-input">
              <span class="field-label">列表 A（{{ listA.length }} 条）</span>
              <NInput
                v-model:value="listAText"
                type="textarea"
                :autosize="{ minRows: 5, maxRows: 10 }"
                placeholder="列表 A，每行一个 ID"
                class="id-input"
              />
            </div>
            <div class="set-input">
              <span class="field-label">列表 B（{{ listB.length }} 条）</span>
              <NInput
                v-model:value="listBText"
                type="textarea"
                :autosize="{ minRows: 5, maxRows: 10 }"
                placeholder="列表 B，每行一个 ID"
                class="id-input"
              />
            </div>
          </div>
          <div class="set-ops">
            <NButton
              v-for="op in (['intersect', 'union', 'aMinusB', 'bMinusA'] as SetOp[])"
              :key="op"
              size="small"
              secondary
              @click="runSetOp(op)"
            >
              {{ SET_OP_LABEL[op] }}
            </NButton>
          </div>

          <div v-if="setResult" class="set-result">
            <div class="result-header">
              <span class="panel-title">
                {{ SET_OP_LABEL[setResult.op] }}：{{ setResult.items.length }} 条
              </span>
              <NButton size="tiny" tertiary @click="copySetResult">
                <template #icon><NIcon><CopyOutline /></NIcon></template>复制
              </NButton>
            </div>
            <pre class="set-output">{{ setResult.items.join('\n') || '（空）' }}</pre>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.id-converter-page {
  padding: 16px;
  min-height: 100%;
}
.local-alert {
  margin-bottom: 12px;
}
.id-converter-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  align-items: start;
}
.param-panel,
.result-card {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 12px;
}
.panel-header,
.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  gap: 8px;
  flex-wrap: wrap;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}
.id-input :deep(textarea) {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.5;
}
.parse-hint {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  margin: 6px 0 0;
}
.field {
  margin-top: 12px;
}
.field-label {
  display: block;
  font-size: 12px;
  color: var(--neutral-text-2, #4e5969);
  margin-bottom: 6px;
}
.clear-btn {
  margin-top: 14px;
}
.result-stats {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.cell-multi {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
}
.cell-empty {
  color: var(--neutral-text-3, #86909c);
}
.export-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.copy-col-select {
  width: 120px;
}
.set-card {
  margin-top: 16px;
}
.set-inputs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.set-ops {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.set-result {
  margin-top: 12px;
}
.set-output {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--neutral-text-1, #1d2129);
  background: var(--neutral-bg, #f5f6fa);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 8px;
  padding: 10px;
  margin: 0;
  max-height: 220px;
  overflow: auto;
}
@media (max-width: 1200px) {
  .id-converter-layout { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .id-converter-page { padding: 12px; }
  .set-inputs { grid-template-columns: 1fr; }
}
</style>
