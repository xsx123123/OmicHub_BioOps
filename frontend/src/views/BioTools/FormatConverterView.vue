<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NCheckbox, NIcon, NInput, NSelect, NTabs, NTabPane, NTag, useMessage,
} from 'naive-ui'
import {
  ArrowBackOutline, CopyOutline, DownloadOutline, SparklesOutline, SwapHorizontalOutline,
} from '@vicons/ionicons5'
import {
  emitRecords, extractFastaByIds, formatFasta, formatIdMap, genSampleFasta, genSampleGff,
  parseIdMap, parseRecords,
  type SourceFormat, type TargetFormat,
} from '@/utils/formatConverterProcessor'
import PageHeader from '@/components/PageHeader.vue'

const router = useRouter()
const message = useMessage()

const activeTab = ref<'convert' | 'fasta' | 'idmap'>('convert')

// ===== 模式 1：GFF/GTF/BED 互转 =====
const convertInput = ref('')
const sourceFormat = ref<SourceFormat>('gff3')
const targetFormat = ref<TargetFormat>('bed6')
const featureFilter = ref('')
const convertResult = ref('')

const sourceOptions = [
  { label: 'GFF3', value: 'gff3' },
  { label: 'GTF', value: 'gtf' },
  { label: 'BED', value: 'bed' },
]
const targetOptions = [
  { label: 'GFF3', value: 'gff3' },
  { label: 'GTF', value: 'gtf' },
  { label: 'BED3', value: 'bed3' },
  { label: 'BED6', value: 'bed6' },
  { label: 'BED12', value: 'bed12' },
]
const featureOptions = [
  { label: '全部（不过滤）', value: '' },
  { label: 'gene', value: 'gene' },
  { label: 'mRNA', value: 'mRNA' },
  { label: 'exon', value: 'exon' },
  { label: 'CDS', value: 'CDS' },
  { label: 'region', value: 'region' },
]

function runConvert() {
  if (!convertInput.value.trim()) {
    message.warning('把格式混乱的文件丢给我，还你一个清清爽爽的标准格式 ✨')
    return
  }
  try {
    const records = parseRecords(sourceFormat.value, convertInput.value)
    if (!records.length) {
      message.error('未解析到任何记录，检查源格式是否选对、是否漏了 tab 分隔符')
      return
    }
    const feature = featureFilter.value || undefined
    convertResult.value = emitRecords(targetFormat.value, records, feature)
    const outLines = convertResult.value.split('\n').length
    message.success(`转换完成！${records.length} 行 → ${outLines} 行`)
  } catch (e) {
    message.error('转换失败：' + (e as Error).message)
  }
}

// ===== 模式 2：FASTA 序列提取 =====
const fastaInput = ref('')
const idList = ref('')
const partialMatch = ref(false)
const fastaResult = ref('')
const fastaCount = ref(0)

function runExtract() {
  if (!fastaInput.value.trim()) {
    message.warning('请先输入或上传 FASTA 内容')
    return
  }
  if (!idList.value.trim()) {
    message.warning('请输入要提取的 ID 列表（每行一个）')
    return
  }
  const records = extractFastaByIds(fastaInput.value, idList.value, partialMatch.value)
  if (!records.length) {
    message.warning('未匹配到任何序列，试试开启「部分匹配」')
    fastaResult.value = ''
    fastaCount.value = 0
    return
  }
  fastaResult.value = formatFasta(records)
  fastaCount.value = records.length
  const bp = records.reduce((s, r) => s + r.seq.length, 0)
  message.success(`成功提取 ${records.length} 条序列，共 ${bp} bp`)
}

// ===== 模式 3：ID 映射表 =====
const idmapInput = ref('')
const idmapDelimiter = ref<'tab' | 'comma'>('tab')
const idmapFormat = ref<'json' | 'tsv'>('json')
const idmapResult = ref('')

const delimiterOptions = [
  { label: 'Tab 分隔（TSV）', value: 'tab' },
  { label: '逗号分隔（CSV）', value: 'comma' },
]
const idmapFormatOptions = [
  { label: 'JSON', value: 'json' },
  { label: 'TSV', value: 'tsv' },
]

function runIdmap() {
  if (!idmapInput.value.trim()) {
    message.warning('请输入两列映射数据')
    return
  }
  const map = parseIdMap(idmapInput.value, idmapDelimiter.value)
  if (!Object.keys(map).length) {
    message.error('未解析到映射，检查分隔符是否选对')
    return
  }
  idmapResult.value = formatIdMap(map, idmapFormat.value)
  message.success(`已生成 ${Object.keys(map).length} 条映射`)
}

// ===== 公共：复制 / 下载 / 示例 =====
function currentResult(): string {
  if (activeTab.value === 'convert') return convertResult.value
  if (activeTab.value === 'fasta') return fastaResult.value
  return idmapResult.value
}

async function copyResult() {
  const r = currentResult()
  if (!r) {
    message.warning('暂无结果可复制')
    return
  }
  try {
    await navigator.clipboard.writeText(r)
    message.success('已复制到剪贴板')
  } catch {
    message.error('复制失败')
  }
}

function downloadResult() {
  const r = currentResult()
  if (!r) {
    message.warning('暂无结果可下载')
    return
  }
  const ext = activeTab.value === 'fasta' ? 'fasta'
    : (activeTab.value === 'idmap' && idmapFormat.value === 'json' ? 'json' : 'txt')
  const blob = new Blob([r], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${activeTab.value}_result.${ext}`
  a.click()
  URL.revokeObjectURL(url)
}

function loadSample() {
  if (activeTab.value === 'convert') {
    convertInput.value = genSampleGff()
    sourceFormat.value = 'gff3'
    targetFormat.value = 'bed6'
    message.info('已载入 GFF3 示例')
  } else if (activeTab.value === 'fasta') {
    fastaInput.value = genSampleFasta()
    idList.value = 'gene01\ngene03'
    message.info('已载入 FASTA 示例（提取 gene01、gene03）')
  } else {
    idmapInput.value = 'transcript01\tgene01\ntranscript02\tgene02\ntranscript03\tgene03'
    message.info('已载入 ID 映射示例')
  }
}
</script>

<template>
  <div class="format-page">
    <PageHeader title="格式轻量转换器" subtitle="在浏览器本地完成常用生信格式转换，数据不会上传服务器" back-to="/tools" back-label="返回工具箱">
      <template #actions>
        <NButton size="small" quaternary @click="loadSample">
          <template #icon><NIcon><SparklesOutline /></NIcon></template>
          示例数据
        </NButton>
      </template>
    </PageHeader>

    <NTabs v-model:value="activeTab" type="line" animated size="medium">
      <!-- ===== Tab 1：GFF/GTF/BED 互转 ===== -->
      <NTabPane name="convert" tab="🗂️ GFF / GTF / BED 互转">
        <div class="tab-layout">
          <aside class="param-panel">
            <span class="panel-title">输入内容</span>
            <NInput
              v-model:value="convertInput"
              type="textarea"
              :autosize="{ minRows: 10, maxRows: 20 }"
              placeholder="粘贴 GFF3 / GTF / BED 内容，或拖拽文件..."
              class="mono-input"
            />

            <div class="convert-settings">
              <div class="convert-row">
                <div class="field">
                  <label>源格式</label>
                  <NSelect v-model:value="sourceFormat" :options="sourceOptions" size="small" />
                </div>
                <NIcon :size="18" class="arrow-icon"><SwapHorizontalOutline /></NIcon>
                <div class="field">
                  <label>目标格式</label>
                  <NSelect v-model:value="targetFormat" :options="targetOptions" size="small" />
                </div>
              </div>
              <div class="field">
                <label>Feature 类型过滤</label>
                <NSelect v-model:value="featureFilter" :options="featureOptions" size="small" />
              </div>
            </div>

            <NButton size="small" type="primary" block class="run-btn" @click="runConvert">
              <template #icon><NIcon><SwapHorizontalOutline /></NIcon></template>开始转换
            </NButton>
          </aside>

          <main class="result-card">
            <div class="result-header">
              <span class="panel-title">转换结果</span>
              <NTag v-if="convertResult" size="small" type="success">{{ targetFormat.toUpperCase() }}</NTag>
              <div class="result-actions">
                <NButton size="tiny" tertiary @click="copyResult"><template #icon><NIcon><CopyOutline /></NIcon></template>复制</NButton>
                <NButton size="tiny" tertiary @click="downloadResult"><template #icon><NIcon><DownloadOutline /></NIcon></template>下载</NButton>
              </div>
            </div>
            <pre v-if="convertResult" class="result-output">{{ convertResult }}</pre>
            <div v-else class="empty-state">
              <p>把格式混乱的文件丢给我，还你一个清清爽爽的标准格式 ✨</p>
            </div>
          </main>
        </div>
      </NTabPane>

      <!-- ===== Tab 2：FASTA 序列提取 ===== -->
      <NTabPane name="fasta" tab="🎯 FASTA 序列提取">
        <div class="tab-layout">
          <aside class="param-panel">
            <span class="panel-title">FASTA 输入</span>
            <NInput
              v-model:value="fastaInput"
              type="textarea"
              :autosize="{ minRows: 6, maxRows: 12 }"
              placeholder="粘贴 FASTA 内容（支持大文件，前端流式解析，不上传服务器）"
              class="mono-input"
            />
            <span class="panel-title" style="margin-top: 12px;">ID 列表（每行一个）</span>
            <NInput
              v-model:value="idList"
              type="textarea"
              :autosize="{ minRows: 4, maxRows: 8 }"
              placeholder="gene01&#10;gene02&#10;..."
              class="mono-input"
            />
            <div class="options">
              <NCheckbox v-model:checked="partialMatch">允许部分匹配（ID 前缀/包含）</NCheckbox>
            </div>
            <NButton size="small" type="primary" block class="run-btn" @click="runExtract">
              <template #icon><NIcon><SwapHorizontalOutline /></NIcon></template>提取序列
            </NButton>
          </aside>

          <main class="result-card">
            <div class="result-header">
              <span class="panel-title">提取结果</span>
              <NTag v-if="fastaCount" size="small" type="success">{{ fastaCount }} 条</NTag>
              <div class="result-actions">
                <NButton size="tiny" tertiary @click="copyResult"><template #icon><NIcon><CopyOutline /></NIcon></template>复制</NButton>
                <NButton size="tiny" tertiary @click="downloadResult"><template #icon><NIcon><DownloadOutline /></NIcon></template>下载 FASTA</NButton>
              </div>
            </div>
            <pre v-if="fastaResult" class="result-output">{{ fastaResult }}</pre>
            <div v-else class="empty-state">
              <p>输入 FASTA 与 ID 列表，按 ID 一键提取序列 🎯</p>
            </div>
          </main>
        </div>
      </NTabPane>

      <!-- ===== Tab 3：ID 映射表 ===== -->
      <NTabPane name="idmap" tab="📋 ID 映射表">
        <div class="tab-layout">
          <aside class="param-panel">
            <span class="panel-title">输入两列映射（如 Transcript ID → Gene ID）</span>
            <NInput
              v-model:value="idmapInput"
              type="textarea"
              :autosize="{ minRows: 10, maxRows: 18 }"
              placeholder="transcript01	gene01&#10;transcript02	gene02&#10;..."
              class="mono-input"
            />
            <div class="convert-row" style="margin-top: 12px;">
              <div class="field">
                <label>输入分隔符</label>
                <NSelect v-model:value="idmapDelimiter" :options="delimiterOptions" size="small" />
              </div>
              <div class="field">
                <label>输出格式</label>
                <NSelect v-model:value="idmapFormat" :options="idmapFormatOptions" size="small" />
              </div>
            </div>
            <NButton size="small" type="primary" block class="run-btn" @click="runIdmap">
              <template #icon><NIcon><SwapHorizontalOutline /></NIcon></template>生成映射表
            </NButton>
          </aside>

          <main class="result-card">
            <div class="result-header">
              <span class="panel-title">映射结果（{{ idmapFormat.toUpperCase() }}）</span>
              <div class="result-actions">
                <NButton size="tiny" tertiary @click="copyResult"><template #icon><NIcon><CopyOutline /></NIcon></template>复制</NButton>
                <NButton size="tiny" tertiary @click="downloadResult"><template #icon><NIcon><DownloadOutline /></NIcon></template>下载</NButton>
              </div>
            </div>
            <pre v-if="idmapResult" class="result-output">{{ idmapResult }}</pre>
            <div v-else class="empty-state">
              <p>两列 TSV/CSV 粘贴进来，一键转 JSON 或 TSV 📋</p>
            </div>
          </main>
        </div>
      </NTabPane>
    </NTabs>
  </div>
</template>

<style scoped>
.format-page {
  padding: 16px;
  min-height: 100%;
}
.page-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0;
  flex: 1;
}
.page-subtitle {
  font-size: 13px;
  color: var(--neutral-text-3);
  margin: 0 0 12px;
}
.tab-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
  margin-top: 12px;
}
.param-panel,
.result-card {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 12px;
}
.panel-title {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin-bottom: 8px;
}
.mono-input :deep(textarea) {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}
.convert-settings {
  margin-top: 12px;
}
.convert-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.convert-row .field {
  flex: 1;
}
.field {
  margin-bottom: 10px;
}
.field label {
  display: block;
  font-size: 12px;
  color: var(--neutral-text-2);
  margin-bottom: 4px;
}
.arrow-icon {
  color: var(--neutral-text-3);
  margin-bottom: 8px;
  flex-shrink: 0;
}
.options {
  margin: 10px 0;
  font-size: 12px;
}
.run-btn {
  margin-top: 8px;
}
.result-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.result-header .panel-title {
  margin-bottom: 0;
  flex: 1;
}
.result-actions {
  display: flex;
  gap: 6px;
}
.result-output {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--neutral-text-1);
  background: var(--neutral-bg);
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  padding: 10px;
  margin: 0;
  max-height: calc(100vh - 320px);
  overflow: auto;
  white-space: pre;
}
.empty-state {
  padding: 48px 16px;
  text-align: center;
  color: var(--neutral-text-3);
  font-size: 14px;
}
@media (max-width: 1200px) {
  .tab-layout { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .format-page { padding: 12px; }
  .convert-row { flex-direction: column; align-items: stretch; }
  .arrow-icon { display: none; }
}
</style>
