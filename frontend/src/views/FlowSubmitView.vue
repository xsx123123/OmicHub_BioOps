<script setup lang="ts">
import type { FlowConfig, FormValues, Parameter } from '@/types/schema'
import type { Task, CostEstimate, FilePickerItem } from '@/types'
import { apiClient } from '@/api'
import DynamicForm from '@/components/dynamic-form/DynamicForm.vue'
import FilePickerModal from '@/components/FilePickerModal.vue'
import PageHeader from '@/components/PageHeader.vue'
import ToolActionBar from '@/components/ToolActionBar.vue'
import {
  NAlert,
  NButton,
  NIcon,
  NInput,
  NModal,
  NSelect,
  NSpin,
  NTooltip,
  useMessage,
} from 'naive-ui'
import {
  AddOutline,
  CloseCircleOutline,
  DocumentTextOutline,
  FolderOpenOutline,
  HelpCircleOutline,
  LogoGithub,
  SendOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCookieStore } from '@/stores/cookie'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const cookieStore = useCookieStore()
const flowId = computed(() => route.params.flowId as string)

const flow = ref<FlowConfig | null>(null)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const taskName = ref('')

const pickerVisible = ref(false)
const pickerFileType = ref<string | undefined>(undefined)
const pickerTarget = ref<{ rowIndex: number; colName: string } | null>(null)
const pickerParamName = ref<string | null>(null)

const pasteModalVisible = ref(false)
const pasteText = ref('')

const parameters = computed(() => flow.value?.parameters || [])
const sampleSheetConfig = computed(() => flow.value?.sample_sheet)
const groupsDef = computed(() => flow.value?.groups || null)

const formValues = ref<FormValues>({})
const sampleSheet = ref<Record<string, string>[]>([
  { sample: '', sample_name: '', group: '' },
])
const comparisons = ref<{ Control: string; Treat: string }[]>([
  { Control: '', Treat: '' },
])

const costEstimate = ref<CostEstimate | null>(null)
const estimating = ref(false)
let estimateTimer: ReturnType<typeof setTimeout> | null = null

/* ── Synthetic required task-name parameter injected into basic group ── */
const TASK_NAME_PARAM: Parameter = {
  name: '_task_name',
  label: '任务名称',
  type: 'string',
  required: true,
  default: '',
  help_text: '请为该分析任务命名，便于在任务中心识别',
  ui: { group: 'basic', order: 5, span: 2, widget: 'input', placeholder: '如 T细胞活化分析_2024Q3' },
}

const displayParameters = computed<Parameter[]>(() => [TASK_NAME_PARAM, ...parameters.value])

const displayValues = computed<FormValues>({
  get: () => ({ ...formValues.value, _task_name: taskName.value }),
  set: (v) => {
    const { _task_name, ...rest } = v
    taskName.value = (_task_name as string) || ''
    formValues.value = rest
  },
})

/* ── Sample sheet helpers ── */
const sampleGroupColumn = computed(() => {
  return sampleSheetConfig.value?.ui?.group_column || 'group'
})

const groupValues = computed(() => {
  const col = sampleGroupColumn.value
  const vals = sampleSheet.value.map((r) => (r[col] || '').trim()).filter(Boolean)
  return [...new Set(vals)].sort()
})

const groupValueOptions = computed(() =>
  groupValues.value.map((v) => ({ label: v, value: v })),
)

const filledSampleCount = computed(
  () => sampleSheet.value.filter((row) => (row.sample || '').trim()).length,
)

const sampleStats = computed(() => {
  const rows = sampleSheet.value.filter((row) => (row.sample || '').trim())
  const groupColumn = sampleGroupColumn.value
  const groups = new Map<string, number>()
  for (const row of rows) {
    const group = (row[groupColumn] || '').trim() || '(未分组)'
    groups.set(group, (groups.get(group) || 0) + 1)
  }
  return { total: rows.length, groups }
})

const SHORT_COL_LABELS: Record<string, string> = {
  sample: '样本 ID',
  sample_name: '显示名称',
  group: '分组',
}

function shortColLabel(colName: string): string {
  return SHORT_COL_LABELS[colName] || colName.replace(/_/g, ' ')
}

/* ── Comparison group ── */
const comparisonParam = computed(() => {
  return parameters.value.find((p) => p.type === 'group' && p.name === 'comparisons')
})

const comparisonShowWhen = computed(() => {
  const ui = comparisonParam.value?.ui
  if (!ui?.show_when) return true
  const f = String(ui.show_when.field || '')
  return formValues.value[f] === ui.show_when.value
})

/* ── Required fields validation ── */
const requiredFields = computed(() => {
  const missing: string[] = []
  if (!taskName.value.trim()) missing.push(TASK_NAME_PARAM.label)
  for (const p of parameters.value) {
    if (!p.required) continue
    if (p.type === 'group' || p.type === 'section') continue
    if (p.condition && !evaluateCondition(p.condition, formValues.value)) continue
    const v = formValues.value[p.name]
    if (v === undefined || v === null || v === '') missing.push(p.label)
  }
  return missing
})

const submitBlocker = computed(() => {
  if (estimating.value) return '正在估算任务成本'
  if (requiredFields.value.length > 0) return `待填写${requiredFields.value[0]}`
  if (costEstimate.value && !costEstimate.value.affordable) return '饼干余额不足'
  return ''
})

const submitReady = computed(() => !submitBlocker.value)

function evaluateCondition(rule: any, vals: FormValues): boolean {
  if (!rule) return true
  if (rule.and_rules) return rule.and_rules.every((r: any) => evaluateCondition(r, vals))
  if (rule.or_rules) return rule.or_rules.some((r: any) => evaluateCondition(r, vals))
  if (rule.field && rule.operator) {
    const actual = vals[rule.field]
    if (rule.operator === 'eq') return actual === rule.value
    if (rule.operator === 'ne') return actual !== rule.value
    return true
  }
  return true
}

/* ── Sample row inline validation ── */
function isSampleRowValid(
  row: Record<string, string>,
): Record<string, 'error' | 'warning' | null> {
  const result: Record<string, 'error' | 'warning' | null> = {}
  const hasAnyValue = Object.values(row).some((v) => v?.trim())
  for (const col of sampleSheetConfig.value?.columns || []) {
    if (!hasAnyValue) {
      result[col.name] = null
      continue
    }
    const val = (row[col.name] || '').trim()
    if (col.required && !val) {
      result[col.name] = 'warning'
    } else {
      result[col.name] = null
    }
  }
  if (hasAnyValue) {
    const sampleVal = (row.sample || '').trim()
    if (sampleVal) {
      const dupes = sampleSheet.value.filter((r) => (r.sample || '').trim() === sampleVal)
      if (dupes.length > 1) result.sample = 'error'
    }
  }
  return result
}

/* ── Cookie / cost estimate ── */
async function fetchEstimate() {
  if (!flowId.value) return
  estimating.value = true
  try {
    const comps = buildComparisons() || []
    costEstimate.value = await cookieStore.estimateCost(
      flowId.value,
      filledSampleCount.value,
      comps.length,
    )
  } catch {
    costEstimate.value = null
  } finally {
    estimating.value = false
  }
}

function debouncedEstimate() {
  if (estimateTimer) clearTimeout(estimateTimer)
  estimateTimer = setTimeout(fetchEstimate, 500)
}

watch(flowId, fetchEstimate, { immediate: false })
watch(() => formValues.value, debouncedEstimate, { deep: true })
watch(() => sampleSheet.value, debouncedEstimate, { deep: true })

/* ── Fetch flow ── */
async function fetchFlow() {
  loading.value = true
  try {
    const res = await apiClient.get<FlowConfig>(`/flows/${flowId.value}`)
    flow.value = res.data
    const defaults: FormValues = {}
    for (const p of res.data.parameters) {
      if (p.default !== undefined) defaults[p.name] = p.default
    }
    formValues.value = defaults
    initSampleSheet()
    initComparisons()
  } catch (e: any) {
    error.value = e.response?.data?.detail || '获取流程详情失败'
  } finally {
    loading.value = false
  }
}

function initSampleSheet() {
  const cols = sampleSheetConfig.value?.columns || []
  if (cols.length === 0) return
  const empty: Record<string, string> = {}
  for (const col of cols) empty[col.name] = ''
  if (
    sampleSheet.value.length === 0 ||
    (sampleSheet.value.length === 1 && !sampleSheet.value[0].sample)
  ) {
    sampleSheet.value = [empty]
  }
}

function initComparisons() {
  if (!comparisonParam.value) return
  const existing = formValues.value.comparisons
  if (Array.isArray(existing) && existing.length > 0) {
    comparisons.value = existing.map((c: any) => ({
      Control: String(c.Control || ''),
      Treat: String(c.Treat || ''),
    }))
  } else {
    comparisons.value = [{ Control: '', Treat: '' }]
  }
}

/* ── Sample table operations ── */
function addSampleRow() {
  const empty: Record<string, string> = {}
  for (const col of sampleSheetConfig.value?.columns || []) empty[col.name] = ''
  sampleSheet.value.push(empty)
}

function removeSampleRow(index: number) {
  if (sampleSheet.value.length > 1) sampleSheet.value.splice(index, 1)
}

function isFileColumn(colName: string): boolean {
  const n = (colName || '').toLowerCase()
  return ['fastq', 'fastq_1', 'fastq_2', 'fq', 'bam', 'vcf', 'file', 'filepath', 'r1', 'r2'].some(
    (k) => n.includes(k),
  )
}

function openPicker(rowIndex: number, colName: string) {
  const n = colName.toLowerCase()
  let ft: string | undefined
  if (n.includes('fastq') || n.includes('fq') || n.includes('r1') || n.includes('r2')) ft = 'fastq'
  else if (n.includes('bam')) ft = 'bam'
  else if (n.includes('vcf')) ft = 'vcf'
  pickerFileType.value = ft
  pickerTarget.value = { rowIndex, colName }
  pickerVisible.value = true
}

function handleOpenPathPicker(paramName: string) {
  pickerParamName.value = paramName
  pickerFileType.value = undefined
  pickerTarget.value = null
  pickerVisible.value = true
}

function handlePickerSelect(items: FilePickerItem[]) {
  if (items.length === 0) return
  if (pickerParamName.value) {
    formValues.value = { ...formValues.value, [pickerParamName.value]: items[0].abs_path }
    pickerParamName.value = null
    return
  }
  if (pickerTarget.value) {
    sampleSheet.value[pickerTarget.value.rowIndex][pickerTarget.value.colName] = items[0].abs_path
    pickerTarget.value = null
  }
}

/* ── Paste / CSV import ── */
function importFromPaste() {
  pasteText.value = ''
  pasteModalVisible.value = true
}

function applyPasteImport() {
  const text = pasteText.value.trim()
  if (!text) return
  const lines = text.split(/\r?\n/).filter((l) => l.trim())
  if (lines.length === 0) return
  const cols = sampleSheetConfig.value?.columns || []
  const colNames = cols.map((c) => c.name)
  const rows: Record<string, string>[] = []
  for (const line of lines) {
    const cells = line.includes('\t') ? line.split('\t') : line.split(',')
    const row: Record<string, string> = {}
    for (let i = 0; i < colNames.length; i++) {
      row[colNames[i]] = (cells[i] || '').trim()
    }
    rows.push(row)
  }
  if (rows.length > 0) {
    sampleSheet.value = rows
    message.success(`已导入 ${rows.length} 行样本数据`)
  }
  pasteModalVisible.value = false
}

function handleCsvUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (e) => {
    const text = e.target?.result as string
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    if (lines.length < 2) {
      message.warning('CSV 文件至少需要表头 + 1 行数据')
      return
    }
    const cols = sampleSheetConfig.value?.columns || []
    const colNames = cols.map((c) => c.name)
    const headerCells = lines[0].split(',')
    const colMap: Record<string, number> = {}
    for (let i = 0; i < colNames.length; i++) {
      const idx = headerCells.findIndex(
        (h) => h.trim().toLowerCase() === colNames[i].toLowerCase(),
      )
      colMap[colNames[i]] = idx >= 0 ? idx : i
    }
    const rows: Record<string, string>[] = []
    for (let li = 1; li < lines.length; li++) {
      const cells = lines[li].split(',')
      const row: Record<string, string> = {}
      for (const cn of colNames) {
        const idx = colMap[cn]
        row[cn] = idx !== undefined && idx < cells.length ? cells[idx].trim() : ''
      }
      rows.push(row)
    }
    sampleSheet.value = rows
    message.success(`已从 CSV 导入 ${rows.length} 行样本数据`)
  }
  reader.readAsText(file)
  input.value = ''
}

/* ── Comparison operations ── */
function addComparison() {
  comparisons.value.push({ Control: '', Treat: '' })
}

function removeComparison(index: number) {
  if (comparisons.value.length > 1) comparisons.value.splice(index, 1)
}

function buildComparisons(): Record<string, string>[] | undefined {
  if (!comparisonShowWhen.value) return undefined
  const valid = comparisons.value.filter((c) => c.Control.trim() && c.Treat.trim())
  if (valid.length === 0) return undefined
  return valid.map((c) => ({ Control: c.Control.trim(), Treat: c.Treat.trim() }))
}

/* ── Submit ── */
function scrollToFirstError() {
  const firstMissing = requiredFields.value[0]
  if (firstMissing) {
    message.warning(`请先填写「${firstMissing}」`)
  }
}

async function submitTask() {
  if (requiredFields.value.length > 0) {
    scrollToFirstError()
    return
  }
  submitting.value = true
  error.value = ''
  try {
    if (cookieStore.isLoggedIn && costEstimate.value && !costEstimate.value.affordable) {
      error.value = `饼干余额不足: 需要 ${costEstimate.value.estimated_cost} 🥫, 当前可用 ${costEstimate.value.current_balance} 🥫`
      return
    }
    const comps = buildComparisons()
    const payload: Record<string, unknown> = {
      flow_id: flowId.value,
      name: taskName.value.trim(),
      parameters: formValues.value,
      sample_sheet: sampleSheet.value,
      execution_mode: 'local',
    }
    if (comps) payload.comparisons = comps
    const res = await apiClient.post<Task>('/tasks', payload)
    message.success('任务已提交')
    router.push({ name: 'task-detail', params: { taskId: res.data.id } })
  } catch (e: any) {
    error.value = e.response?.data?.detail || '提交任务失败'
  } finally {
    submitting.value = false
  }
}

watch(
  () => groupValues.value,
  () => {
    const valid = new Set(groupValues.value)
    for (const c of comparisons.value) {
      if (c.Control && !valid.has(c.Control)) c.Control = ''
      if (c.Treat && !valid.has(c.Treat)) c.Treat = ''
    }
  },
)

onMounted(fetchFlow)
onUnmounted(() => {
  if (estimateTimer) clearTimeout(estimateTimer)
})
</script>

<template>
  <div class="flow-submit-page">
    <PageHeader
      :title="flow?.meta.name || '提交任务'"
      :subtitle="flow?.meta.description || '配置分析参数与样本表后提交运行任务'"
    >
      <template v-if="flow?.meta.docs_url || flow?.meta.github_url" #actions>
        <a
          v-if="flow?.meta.github_url"
          :href="flow.meta.github_url"
          target="_blank"
          rel="noopener noreferrer"
          class="header-link"
        >
          <NIcon :size="16"><LogoGithub /></NIcon>
          Github 开源代码
        </a>
        <a
          v-if="flow?.meta.docs_url"
          :href="flow.meta.docs_url"
          target="_blank"
          rel="noopener noreferrer"
          class="header-link"
        >
          <NIcon :size="16"><DocumentTextOutline /></NIcon>
          开发者文档
        </a>
      </template>
    </PageHeader>

    <NAlert v-if="error" type="error" closable class="error-alert" @close="error = ''">
      {{ error }}
    </NAlert>

    <NSpin :show="loading">
      <div class="content-area">
        <div v-if="flow" class="form-content">
          <DynamicForm
            v-model="displayValues"
            :parameters="displayParameters"
            :groups="groupsDef"
            @open-path-picker="handleOpenPathPicker"
          />

          <!-- ── Sample Sheet ── -->
          <section v-if="sampleSheetConfig" class="form-section">
            <div class="section-header">
              <span class="group-bar" />
              <span class="section-title">样本表</span>
              <span class="section-desc">定义样本信息与分组</span>
              <div class="import-actions">
                <NButton
                  v-if="sampleSheetConfig.ui?.import?.includes('paste')"
                  size="small"
                  @click="importFromPaste"
                >
                  粘贴导入
                </NButton>
                <label
                  v-if="sampleSheetConfig.ui?.import?.includes('csv')"
                  class="csv-upload-btn"
                >
                  <NButton size="small">上传 CSV</NButton>
                  <input type="file" accept=".csv,.tsv,.txt" hidden @change="handleCsvUpload" />
                </label>
                <NButton
                  v-if="sampleSheetConfig.ui?.import?.includes('datacenter')"
                  size="small"
                  @click="openPicker(0, 'sample')"
                >
                  从数据管理选择
                </NButton>
              </div>
            </div>

            <div class="sample-table-wrap">
              <table class="sample-table">
                <thead>
                  <tr>
                    <th class="col-row-num">#</th>
                    <th v-for="col in sampleSheetConfig.columns" :key="col.name">
                      <span class="col-header-content">
                        {{ shortColLabel(col.name) }}
                        <span v-if="col.required" class="req-star">*</span>
                        <NTooltip v-if="col.description" trigger="hover" placement="top">
                          <template #trigger>
                            <NIcon :size="14" class="col-help-icon">
                              <HelpCircleOutline />
                            </NIcon>
                          </template>
                          {{ col.description }}
                        </NTooltip>
                      </span>
                    </th>
                    <th class="col-actions"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, index) in sampleSheet" :key="index">
                    <td class="col-row-num">{{ index + 1 }}</td>
                    <td
                      v-for="col in sampleSheetConfig.columns"
                      :key="col.name"
                      :class="{
                        'cell-warning': isSampleRowValid(row)[col.name] === 'warning',
                        'cell-error': isSampleRowValid(row)[col.name] === 'error',
                      }"
                    >
                      <div class="cell-inner">
                        <NInput
                          v-model:value="row[col.name]"
                          size="small"
                          :placeholder="col.example || ''"
                        />
                        <NButton
                          v-if="isFileColumn(col.name)"
                          size="tiny"
                          quaternary
                          class="cell-picker"
                          @click="openPicker(index, col.name)"
                        >
                          <template #icon
                            ><NIcon :size="14"><FolderOpenOutline /></NIcon
                          ></template>
                        </NButton>
                      </div>
                    </td>
                    <td class="col-actions">
                      <NTooltip v-if="sampleSheet.length > 1" trigger="hover">
                        <template #trigger>
                          <NButton
                            text
                            size="small"
                            class="delete-btn"
                            @click="removeSampleRow(index)"
                          >
                            <template #icon
                              ><NIcon :size="16"><TrashOutline /></NIcon
                            ></template>
                          </NButton>
                        </template>
                        删除该行
                      </NTooltip>
                    </td>
                  </tr>
                </tbody>
              </table>
              <button class="add-sample-row" type="button" @click="addSampleRow">
                <NIcon :size="16"><AddOutline /></NIcon>
                添加样本
              </button>
            </div>

            <div v-if="filledSampleCount > 0" class="sample-stats">
              共 <strong>{{ sampleStats.total }}</strong> 样本
              <template v-if="sampleStats.groups.size > 0">
                · {{ sampleStats.groups.size }} 个分组
                <span class="group-detail">
                  (<template v-for="[g, cnt] in sampleStats.groups" :key="g"
                    >{{ g }}: {{ cnt }}&ensp;</template
                  >)
                </span>
              </template>
            </div>
          </section>

          <!-- ── Comparison Groups (single location) ── -->
          <section v-if="comparisonParam && comparisonShowWhen" class="form-section">
            <div class="section-header">
              <span class="group-bar" />
              <span class="section-title">{{ comparisonParam.label }}</span>
              <span class="section-desc">{{ comparisonParam.help_text }}</span>
            </div>

            <div v-if="groupValues.length === 0" class="no-groups-hint">
              请先在样本表中填写 <code>{{ sampleGroupColumn }}</code> 列，比较组选项将自动联动。
            </div>

            <div v-else class="comparisons-list">
              <div v-for="(comp, idx) in comparisons" :key="idx" class="comparison-card">
                <div class="comparison-row">
                  <div class="comp-side comp-control">
                    <span class="comp-label">对照组</span>
                    <NSelect
                      v-model:value="comp.Control"
                      :options="groupValueOptions"
                      placeholder="选择对照组"
                      size="small"
                      clearable
                    />
                  </div>
                  <div class="comp-vs">
                    <span class="vs-line" />
                    <span class="vs-text">vs</span>
                    <span class="vs-arrow">&rarr;</span>
                  </div>
                  <div class="comp-side comp-treat">
                    <span class="comp-label">实验组</span>
                    <NSelect
                      v-model:value="comp.Treat"
                      :options="groupValueOptions"
                      placeholder="选择实验组"
                      size="small"
                      clearable
                    />
                  </div>
                  <NButton
                    v-if="comparisons.length > 1"
                    text
                    class="comp-delete"
                    @click="removeComparison(idx)"
                  >
                    <template #icon
                      ><NIcon :size="16"><CloseCircleOutline /></NIcon
                    ></template>
                  </NButton>
                </div>
              </div>
              <NButton dashed size="small" class="add-comp-btn" @click="addComparison">
                <template #icon><NIcon><AddOutline /></NIcon></template>
                {{ comparisonParam.group_config?.add_button_text || '+ 添加差异比较组' }}
              </NButton>
            </div>
          </section>
        </div>
      </div>
    </NSpin>

    <ToolActionBar
      v-if="flow && !loading"
      :ready="submitReady"
      :loading="submitting || estimating"
      ready-text="参数已就绪，可提交任务"
      :not-ready-text="submitBlocker || '待完善提交参数'"
      :not-ready-tip="submitBlocker"
      primary-label="提交任务"
      :primary-icon="SendOutline"
      @action="submitTask"
    />

    <FilePickerModal
      v-model:show="pickerVisible"
      :file-type="pickerFileType"
      @select="handlePickerSelect"
    />

    <NModal
      v-model:show="pasteModalVisible"
      preset="card"
      title="粘贴导入样本表"
      style="max-width: 560px"
    >
      <p class="paste-hint">从 Excel / TSV 复制数据后粘贴到下方（支持 Tab 或逗号分隔）：</p>
      <NInput
        v-model:value="pasteText"
        type="textarea"
        :rows="8"
        placeholder="sample&#9;sample_name&#9;group&#10;S001_Tumor&#9;S001&#9;Tumor&#10;..."
      />
      <NButton type="primary" block style="margin-top: 12px" @click="applyPasteImport"
        >确认导入</NButton
      >
    </NModal>
  </div>
</template>

<style scoped>
.flow-submit-page {
  min-height: 100%;
  background: var(--bg-page);
}

.error-alert {
  margin: 0 24px;
}

.header-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border-radius: 8px;
  background: var(--bg-card);
  border: 1px solid var(--stardust-border-soft, rgba(46, 91, 255, 0.08));
  color: var(--text-secondary);
  font-size: 13px;
  text-decoration: none;
  transition: all 0.2s;
}
.header-link:hover {
  color: var(--brand-primary);
  border-color: var(--brand-primary);
}

.content-area {
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px;
}

.form-content {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* Section headers (sample sheet, comparisons) */
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.group-bar {
  width: 4px;
  height: 18px;
  border-radius: 2px;
  background: var(--brand-primary);
  flex-shrink: 0;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

.section-desc {
  font-size: 12px;
  color: var(--text-tertiary);
}

.import-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.csv-upload-btn {
  cursor: pointer;
}

/* ── Sample table ── */
.sample-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--stardust-border-soft, rgba(46, 91, 255, 0.08));
  border-radius: 10px;
  background: var(--bg-card);
}

.sample-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.sample-table th,
.sample-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--stardust-border-soft, rgba(46, 91, 255, 0.06));
}

.sample-table thead th {
  font-weight: 600;
  color: var(--text-primary);
  background: var(--bg-page);
  font-size: 13px;
  position: sticky;
  top: 0;
}

.col-header-content {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.col-help-icon {
  color: var(--text-tertiary);
  cursor: help;
  opacity: 0.6;
  transition: opacity 0.15s;
}
.col-help-icon:hover {
  opacity: 1;
}

.col-row-num {
  width: 40px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.col-actions {
  width: 36px;
  text-align: center;
}

.req-star {
  color: #e5484d;
  margin-left: 1px;
  font-weight: 400;
}

.cell-inner {
  display: flex;
  align-items: center;
  gap: 4px;
}

.cell-picker {
  flex-shrink: 0;
  opacity: 0.5;
  transition: opacity 0.15s;
}
.cell-picker:hover {
  opacity: 1;
}

.cell-warning :deep(.n-input) {
  --n-border: 1px solid #e5a618 !important;
}

.cell-error :deep(.n-input) {
  --n-border: 1px solid #e5484d !important;
}

.delete-btn {
  color: var(--text-tertiary);
  transition: color 0.15s;
}
.delete-btn:hover {
  color: #e5484d;
}

/* Add sample row: 48px height button */
.add-sample-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  height: 48px;
  border: 1px dashed var(--stardust-border-soft, rgba(46, 91, 255, 0.15));
  border-top: none;
  border-radius: 0 0 10px 10px;
  background: transparent;
  color: var(--text-tertiary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.add-sample-row:hover {
  color: var(--brand-primary);
  border-color: var(--brand-primary);
  background: rgba(76, 111, 255, 0.02);
}

.sample-stats {
  margin-top: 10px;
  font-size: 13px;
  color: var(--text-secondary);
}

.group-detail {
  font-size: 12px;
  color: var(--text-tertiary);
}

/* ── Comparisons ── */
.no-groups-hint {
  padding: 16px 20px;
  background: var(--brand-primary-light);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.no-groups-hint code {
  background: rgba(76, 111, 255, 0.12);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

.comparisons-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.comparison-card {
  padding: 14px 16px;
  border: 1px solid var(--stardust-border-soft, rgba(46, 91, 255, 0.08));
  border-radius: 10px;
  background: var(--bg-card);
  transition: box-shadow 0.2s;
}
.comparison-card:hover {
  box-shadow: 0 2px 8px rgba(76, 111, 255, 0.06);
}

.comparison-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.comp-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.comp-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-tertiary);
}

.comp-vs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding-bottom: 6px;
}

.vs-line {
  width: 20px;
  height: 1px;
  background: var(--text-tertiary);
}

.vs-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-primary);
  letter-spacing: 0.02em;
}

.vs-arrow {
  font-size: 14px;
  color: var(--brand-primary);
}

.comp-delete {
  flex-shrink: 0;
  color: var(--text-tertiary);
  margin-bottom: 4px;
  transition: color 0.15s;
}
.comp-delete:hover {
  color: #e5484d;
}

.add-comp-btn {
  align-self: flex-start;
}

.paste-hint {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

@media (max-width: 768px) {
  .content-area {
    padding: 16px;
  }
  .comparison-row {
    flex-wrap: wrap;
  }
  .comp-side {
    min-width: 120px;
  }
}
</style>
