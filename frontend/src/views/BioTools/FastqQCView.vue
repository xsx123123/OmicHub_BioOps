<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import {
  NAlert,
  NButton,
  NIcon,
  NRadioButton,
  NRadioGroup,
  NSlider,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import {
  ArrowBackOutline,
  CheckmarkCircleOutline,
  CloudUploadOutline,
  DocumentTextOutline,
  FolderOpenOutline,
  InformationCircleOutline,
  LayersOutline,
  SparklesOutline,
} from '@vicons/ionicons5'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import FilePickerModal from '@/components/FilePickerModal.vue'
import type { FilePickerItem } from '@/types'

use([CanvasRenderer, GridComponent, LegendComponent, LineChart, TooltipComponent])

type LibraryType = 'single' | 'paired'
type ReadTarget = 'read1' | 'read2'

const router = useRouter()
const message = useMessage()
const libraryType = ref<LibraryType>('single')
const read1 = ref<FilePickerItem | null>(null)
const read2 = ref<FilePickerItem | null>(null)
const filePickerVisible = ref(false)
const filePickerTarget = ref<ReadTarget>('read1')
const qualityThreshold = ref(19)
const trimLength = ref(0)
const adapterTrim = ref(true)
const hasPreparedPreview = ref(false)

const hasInput = computed(
  () => Boolean(read1.value) && (libraryType.value === 'single' || Boolean(read2.value)),
)
const libraryLabel = computed(() => (libraryType.value === 'single' ? '单端测序（SE）' : '双端测序（PE）'))
const trimDescription = computed(() => (trimLength.value ? `统一截断到 ${trimLength.value} bp` : '不截断'))
const processingSummary = computed(() => [
  `Q${qualityThreshold.value} 质量过滤`,
  trimLength.value ? `${trimLength.value} bp 截断` : '保留原始长度',
  adapterTrim.value ? '接头去除已开启' : '接头去除未开启',
])

const qualityChartOption = computed(() => {
  const positions = Array.from({ length: 120 }, (_, index) => index + 1)
  const before = positions.map((position) => {
    if (position < 9) return 30.2 + position * 0.42
    if (position < 82) return 36.4 - Math.sin(position / 7) * 0.45
    return 36 - (position - 82) * 0.24
  })
  const after = positions.map((position, index) => Math.min(39.2, before[index] + (position < 10 ? 1.3 : 2.2)))
  const count = trimLength.value || positions.length

  return {
    animationDuration: 300,
    tooltip: { trigger: 'axis' as const },
    legend: { data: ['质控前', '质控后'], right: 4, top: 0 },
    grid: { top: 48, right: 18, bottom: 38, left: 45 },
    xAxis: {
      type: 'category' as const,
      data: positions.slice(0, count).map(String),
      boundaryGap: false,
      axisLabel: { color: '#86909c', interval: 19 },
      axisLine: { lineStyle: { color: '#e5e6eb' } },
    },
    yAxis: {
      type: 'value' as const,
      min: 20,
      max: 42,
      name: 'Phred',
      nameTextStyle: { color: '#86909c' },
      axisLabel: { color: '#86909c' },
      splitLine: { lineStyle: { color: '#f2f3f5' } },
    },
    series: [
      {
        name: '质控前',
        type: 'line' as const,
        data: before.slice(0, count).map((value) => Number(value.toFixed(1))),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#a9b4c4', width: 2 },
      },
      {
        name: '质控后',
        type: 'line' as const,
        data: after.slice(0, count).map((value) => Number(value.toFixed(1))),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#4c6fff', width: 2.5 },
        areaStyle: { color: 'rgba(76, 111, 255, 0.09)' },
      },
    ],
  }
})

function openWorkspacePicker(target: ReadTarget) {
  filePickerTarget.value = target
  filePickerVisible.value = true
}

function selectWorkspaceFile(files: FilePickerItem[]) {
  const selected = files[0]
  if (!selected) return
  if (filePickerTarget.value === 'read1') read1.value = selected
  else read2.value = selected
}

function clearRead(target: ReadTarget) {
  if (target === 'read1') read1.value = null
  else read2.value = null
}

function formatFileSize(bytes: number) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const unitIndex = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / 1024 ** unitIndex).toFixed(unitIndex ? 1 : 0)} ${units[unitIndex]}`
}

function openDataManagement() {
  router.push('/files')
}

function prepareTask() {
  if (!hasInput.value) {
    message.warning(libraryType.value === 'paired' ? '请先选择 R1 和 R2 文件' : '请先选择 R1 FASTQ 文件')
    return
  }
  if (libraryType.value === 'paired' && read1.value?.id === read2.value?.id) {
    message.warning('R1 与 R2 必须选择两个不同的 FASTQ 文件')
    return
  }
  hasPreparedPreview.value = true
  message.info('任务创建 API 正在接入；当前已完成输入与参数预检。')
}
</script>

<template>
  <div class="fastq-page">
    <PageHeader title="FASTQ 极速质控" subtitle="使用 fastp 与 MultiQC 完成测序数据质控与汇总" back-to="/tools" back-label="返回工具箱">
      <template #actions>
        <NTag round size="small" type="info">fastp + MultiQC</NTag>
      </template>
    </PageHeader>

    <NAlert type="info" :show-icon="true" class="tool-alert">
      从数据管理选择已上传至 workspace 的 FASTQ 文件；任务将按样本运行 fastp 并汇总 MultiQC 报告。
    </NAlert>

    <div class="fastq-layout">
      <section class="input-section">
        <div class="input-card">
          <h3 class="section-title">测序类型</h3>
          <NRadioGroup v-model:value="libraryType" size="small" name="library-type">
            <NRadioButton value="single">单端 SE</NRadioButton>
            <NRadioButton value="paired">双端 PE</NRadioButton>
          </NRadioGroup>
          <p class="control-hint">{{ libraryLabel }}</p>
        </div>

        <div class="input-card">
          <h3 class="section-title">输入 FASTQ 文件</h3>
          <div class="input-grid" :class="{ paired: libraryType === 'paired' }">
            <div
              class="fastq-dropzone cygnusx-selectable-card"
              :class="{ selected: read1, 'is-selected': read1 }"
              :data-selected="read1 ? 'true' : 'false'"
              role="button"
              tabindex="0"
              @click="openWorkspacePicker('read1')"
              @keydown.enter.prevent="openWorkspacePicker('read1')"
              @keydown.space.prevent="openWorkspacePicker('read1')"
            >
              <NIcon :size="22"><DocumentTextOutline /></NIcon>
              <strong>{{ read1?.original_name || '选择 Read 1 文件' }}</strong>
              <span v-if="read1">{{ read1.directory || '根目录' }} · {{ formatFileSize(read1.size) }}</span>
              <span v-else>从数据管理选择 FASTQ / FQ / GZ</span>
              <NButton v-if="read1" text size="tiny" class="remove-file" @click.stop="clearRead('read1')">移除</NButton>
              <NButton v-else text size="tiny" class="choose-file"><template #icon><NIcon><FolderOpenOutline /></NIcon></template>选择 workspace 文件</NButton>
            </div>
            <div
              v-if="libraryType === 'paired'"
              class="fastq-dropzone cygnusx-selectable-card"
              :class="{ selected: read2, 'is-selected': read2 }"
              :data-selected="read2 ? 'true' : 'false'"
              role="button"
              tabindex="0"
              @click="openWorkspacePicker('read2')"
              @keydown.enter.prevent="openWorkspacePicker('read2')"
              @keydown.space.prevent="openWorkspacePicker('read2')"
            >
              <NIcon :size="22"><LayersOutline /></NIcon>
              <strong>{{ read2?.original_name || '选择 Read 2 文件' }}</strong>
              <span v-if="read2">{{ read2.directory || '根目录' }} · {{ formatFileSize(read2.size) }}</span>
              <span v-else>选择与 R1 配对的 workspace 文件</span>
              <NButton v-if="read2" text size="tiny" class="remove-file" @click.stop="clearRead('read2')">移除</NButton>
              <NButton v-else text size="tiny" class="choose-file"><template #icon><NIcon><FolderOpenOutline /></NIcon></template>选择 workspace 文件</NButton>
            </div>
          </div>
          <div class="file-hint">
            <span><NIcon><InformationCircleOutline /></NIcon> 工具页不重复上传文件，任务只保存文件 ID 引用。</span>
            <NButton text size="small" type="primary" @click="openDataManagement"><template #icon><NIcon><CloudUploadOutline /></NIcon></template>前往数据管理上传</NButton>
          </div>
        </div>

        <div class="input-card">
          <h3 class="section-title">清洗参数</h3>
          <div class="control-stack">
            <label class="range-control">
              <span><strong>最低质量阈值</strong><em>Q{{ qualityThreshold }}</em></span>
              <NSlider v-model:value="qualityThreshold" :min="5" :max="35" :step="1" />
              <small>默认 Q19，过滤低质量碱基。</small>
            </label>
            <label class="range-control">
              <span><strong>统一截断长度</strong><em>{{ trimDescription }}</em></span>
              <NSlider v-model:value="trimLength" :min="0" :max="300" :step="10" />
              <small>设置为 0 时保留原始 reads 长度。</small>
            </label>
            <div class="switch-control">
              <div><strong>接头序列去除</strong><small>自动检测并清除 adapter 序列。</small></div>
              <NSwitch v-model:value="adapterTrim" />
            </div>
          </div>
        </div>

        <NButton type="primary" block size="large" class="submit-button" @click="prepareTask">
          <template #icon><NIcon :size="18"><SparklesOutline /></NIcon></template>
          预检并创建质控任务
        </NButton>
      </section>

      <section class="results-section">
        <div class="results-header">
          <div>
            <h3 class="section-title">任务状态</h3>
            <span class="status-detail">{{ hasPreparedPreview ? '输入与参数预检完成，等待任务 API 接入。' : '选择样本并配置参数后即可预检。' }}</span>
          </div>
          <NTag :type="hasPreparedPreview ? 'success' : 'default'" size="small" round>{{ hasPreparedPreview ? '就绪' : '草稿' }}</NTag>
        </div>

        <div class="summary-grid">
          <article class="summary-card"><span>预期处理</span><strong>{{ hasInput ? '1 个样本' : '尚未添加样本' }}</strong><small>{{ libraryLabel }}</small></article>
          <article class="summary-card"><span>输出产物</span><strong>fastp + MultiQC</strong><small>HTML、JSON、clean FASTQ</small></article>
          <article class="summary-card"><span>当前规则</span><strong>Q{{ qualityThreshold }}</strong><small>{{ adapterTrim ? '接头去除已开启' : '接头去除未开启' }}</small></article>
        </div>

        <div class="report-card">
          <div class="report-heading">
            <div><h3 class="section-title">碱基质量分布</h3><span>任务完成后由 `fastp.json` 的真实数据重绘。</span></div>
            <NTag round size="small" type="info">预览</NTag>
          </div>
          <VChart :option="qualityChartOption" autoresize class="quality-chart" />
          <div class="report-footer"><span v-for="item in processingSummary" :key="item">{{ item }}</span></div>
        </div>

        <div class="deliverables-card">
          <h3 class="section-title">任务完成后可获得</h3>
          <ul>
            <li><NIcon><CheckmarkCircleOutline /></NIcon> 单样本 fastp HTML 与 JSON 报告</li>
            <li><NIcon><CheckmarkCircleOutline /></NIcon> 批次 MultiQC 汇总与可交互图表</li>
            <li><NIcon><CheckmarkCircleOutline /></NIcon> 清洗后 FASTQ 压缩包下载</li>
          </ul>
        </div>
      </section>
    </div>

    <FilePickerModal
      v-model:show="filePickerVisible"
      file-type="fastq"
      @select="selectWorkspaceFile"
    />
  </div>
</template>

<style scoped>
.fastq-page { min-height: 100%; padding: 16px; }
.page-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.page-title { margin: 0 auto 0 0; color: var(--neutral-text-1, var(--text-primary)); font-size: 20px; font-weight: 650; letter-spacing: -0.015em; font-optical-sizing: auto; }
.tool-alert { margin-bottom: 16px; border-radius: 10px; }
.fastq-layout { display: grid; grid-template-columns: minmax(340px, .78fr) minmax(0, 1.22fr); gap: 16px; align-items: start; }
.input-section, .results-section { display: flex; flex-direction: column; gap: 16px; }
.input-card, .report-card, .deliverables-card, .summary-card { border: 1px solid var(--neutral-border, #e5e6eb); border-radius: 12px; background: var(--neutral-card, var(--bg-card)); box-shadow: 0 1px 2px rgba(29, 33, 41, .03); }
.input-card { padding: 18px; }
.section-title { margin: 0 0 12px; color: var(--neutral-text-1, var(--text-primary)); font-size: 14px; font-weight: 650; letter-spacing: -0.01em; }
.control-hint, .file-hint { display: flex; align-items: center; gap: 5px; margin: 9px 0 0; color: var(--neutral-text-3, var(--text-tertiary)); font-size: 12px; line-height: 1.5; }.file-hint { justify-content: space-between; gap: 12px; }.file-hint > span { display: flex; align-items: center; gap: 5px; }
.input-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }.input-grid.paired { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.fastq-dropzone { min-height: 104px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; padding: 12px; box-sizing: border-box; border: 1.5px dashed #cfd6e6; border-radius: 10px; color: var(--neutral-text-3, var(--text-tertiary)); text-align: center; cursor: pointer; transition: background-color 180ms ease, border-color 180ms ease, transform 180ms ease; }
.fastq-dropzone:hover, .fastq-dropzone.selected, .fastq-dropzone:focus-visible { border-color: var(--brand-primary, #4c6fff); background: var(--brand-primary-light, #eef1ff); outline: none; }.fastq-dropzone:active { transform: scale(.985); transition-duration: 100ms; }.fastq-dropzone > .n-icon { color: var(--brand-primary, #4c6fff); }.fastq-dropzone strong { max-width: 100%; overflow: hidden; color: var(--neutral-text-1, var(--text-primary)); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.fastq-dropzone span, .range-control small, .switch-control small { color: var(--neutral-text-3, var(--text-tertiary)); font-size: 12px; }.remove-file, .choose-file { margin-top: 1px; color: var(--brand-primary, #4c6fff); }
.control-stack { display: grid; gap: 18px; }.range-control { display: block; }.range-control > span { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; color: var(--neutral-text-2, var(--text-secondary)); font-size: 13px; }.range-control strong, .switch-control strong { color: var(--neutral-text-1, var(--text-primary)); font-weight: 600; }.range-control em { color: var(--brand-primary, #4c6fff); font-size: 12px; font-style: normal; }.range-control small { display: block; margin-top: 4px; }.switch-control { display: flex; align-items: center; justify-content: space-between; gap: 16px; }.switch-control > div { display: grid; gap: 4px; }.submit-button { box-shadow: 0 8px 16px rgba(76, 111, 255, .16); transition: transform 180ms ease, box-shadow 180ms ease; }.submit-button:hover { box-shadow: 0 11px 24px rgba(76, 111, 255, .22); transform: translateY(-1px); }.submit-button:active { transform: scale(.98); transition-duration: 100ms; }
.results-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 2px 2px 0; }.results-header .section-title { margin-bottom: 4px; }.status-detail { color: var(--neutral-text-3, var(--text-tertiary)); font-size: 12px; }.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }.summary-card { min-height: 102px; padding: 15px; box-sizing: border-box; transition: transform 180ms ease, box-shadow 180ms ease; }.summary-card:hover { box-shadow: 0 8px 20px rgba(29, 33, 41, .07); transform: translateY(-2px); }.summary-card > span, .summary-card small { display: block; color: var(--neutral-text-3, var(--text-tertiary)); font-size: 12px; }.summary-card strong { display: block; margin: 8px 0 5px; color: var(--neutral-text-1, var(--text-primary)); font-size: 16px; line-height: 1.25; }
.report-card { padding: 18px 18px 12px; }.report-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }.report-heading .section-title { margin-bottom: 5px; }.report-heading span { color: var(--neutral-text-3, var(--text-tertiary)); font-size: 12px; }.quality-chart { height: 300px; margin-top: 8px; }.report-footer { display: flex; flex-wrap: wrap; gap: 7px; padding-top: 12px; border-top: 1px solid var(--neutral-border, #f2f3f5); }.report-footer span { padding: 4px 9px; border-radius: 999px; background: var(--neutral-fill, #f4f6fa); color: var(--neutral-text-2, var(--text-secondary)); font-size: 12px; }
.deliverables-card { padding: 18px; }.deliverables-card ul { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }.deliverables-card li { display: flex; align-items: center; gap: 7px; color: var(--neutral-text-2, var(--text-secondary)); font-size: 13px; }.deliverables-card .n-icon { color: #2aa876; }
@media (prefers-reduced-motion: reduce) { .fastq-dropzone, .submit-button, .summary-card { transition: opacity 150ms ease; }.fastq-dropzone:active, .submit-button:active, .submit-button:hover, .summary-card:hover { transform: none; } }
@media (prefers-reduced-transparency: reduce) { .input-card, .report-card, .deliverables-card, .summary-card { background: var(--neutral-card, #fff); } }
@media (prefers-contrast: more) { .input-card, .report-card, .deliverables-card, .summary-card { border-color: var(--neutral-text-2, #4e5969); } }
@media (max-width: 980px) { .fastq-layout { grid-template-columns: 1fr; }.input-section { order: 2; }.results-section { order: 1; } }
@media (max-width: 620px) { .fastq-page { padding: 12px; }.input-grid.paired, .summary-grid { grid-template-columns: 1fr; }.page-toolbar { flex-wrap: wrap; }.page-title { order: 3; width: 100%; }.results-header { align-items: flex-start; }.file-hint { align-items: flex-start; flex-direction: column; } }
</style>
