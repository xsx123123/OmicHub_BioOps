<script setup lang="ts">
import { ref, shallowRef, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import {
  NButton, NIcon, NEmpty, NTag, NTabs, NTabPane, NPopconfirm,
  NSelect, NSpace, NTooltip, NSpin, useMessage,
} from 'naive-ui'
import {
  PlayOutline, StopCircleOutline, AddOutline, TrashOutline,
  RefreshOutline, CodeSlashOutline, TimeOutline, CheckmarkCircleOutline,
  CloseCircleOutline,
} from '@vicons/ionicons5'
import CodeEditor from '@/components/sandbox/CodeEditor.vue'
import { VChart } from '@/components/sandbox/echartsSetup'
import { useSandboxStore } from '@/stores/sandbox'
import { useSandboxWebSocket } from '@/composables/useSandboxWebSocket'
import type { SandboxEvent } from '@/types'

const message = useMessage()
const store = useSandboxStore()

const activeSessionId = ref('')
type WsInst = ReturnType<typeof useSandboxWebSocket>
const ws = shallowRef<WsInst | null>(null)
const wsSessionId = ref('')  // 追踪当前 ws 绑定的会话

const languageOptions = [{ label: 'Python 3.11 (scanpy)', value: 'python' }]
const language = ref('python')

async function handleCreate() {
  try {
    const s = await store.createSession(language.value)
    activeSessionId.value = s.id
    message.success('沙盒会话已就绪')
  } catch (e: unknown) {
    message.error((e as Error)?.message || '创建会话失败')
  }
}

async function handleDelete(id: string) {
  try {
    await store.deleteSession(id)
    if (activeSessionId.value === id) {
      activeSessionId.value = ''
      wsSessionId.value = ''
      ws.value?.disconnect()
      ws.value = null
    }
    message.success('已销毁会话')
  } catch (e: unknown) {
    message.error((e as Error)?.message || '销毁失败')
  }
}

function handleSelectSession(id: string) {
  activeSessionId.value = id
}

const DEFAULT_CODE = [
  '# OmicHub 交互式生信沙盒',
  '# 预装：scanpy(sc) / numpy(np) / pandas(pd) / seaborn(sns)',
  '# 回传图表：show_echarts(option)  回传图片：show_image(path)',
  '',
  'import numpy as np',
  '',
  "# 模拟 UMAP 散点（实际：sc.tl.umap(adata) 后取 adata.obsm['X_umap']）",
  'pts = np.random.randn(3000, 2).tolist()',
  'show_echarts({',
  "  title: { text: 'UMAP 散点 (scatterGL)' },",
  "  xAxis: { type: 'value' },",
  "  yAxis: { type: 'value' },",
  '  dataZoom: [{ type: "inside" }],',
  '  series: [{',
  "    type: 'scatterGL',",
  '    data: pts,',
  '    symbolSize: 3,',
  '    itemStyle: { opacity: 0.7 },',
  '  }],',
  '})',
  '',
].join('\n')
const code = ref(DEFAULT_CODE)

const running = ref(false)
const stdout = ref('')
const stderr = ref('')
const charts = ref<Record<string, unknown>[]>([])
const images = ref<string[]>([])
const lastResult = ref<{ exit_code: number; duration_ms: number } | null>(null)
const activeTab = ref<'output' | 'charts' | 'images'>('output')
const outputRef = ref<HTMLElement | null>(null)

function scrollToBottom() {
  nextTick(() => {
    const el = outputRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function resetOutput() {
  stdout.value = ''
  stderr.value = ''
  charts.value = []
  images.value = []
  lastResult.value = null
}

function ensureWs(): WsInst | null {
  if (!activeSessionId.value) return null
  // 复用已连接的同会话 ws，避免重复断开重连
  if (
    ws.value &&
    wsSessionId.value === activeSessionId.value &&
    ws.value.connected.value
  ) {
    return ws.value
  }
  ws.value?.disconnect()
  const inst = useSandboxWebSocket(activeSessionId.value)
  wsSessionId.value = activeSessionId.value
  inst.connect(handleEvent)
  ws.value = inst
  return inst
}

function handleEvent(e: SandboxEvent) {
  switch (e.type) {
    case 'stdout':
      stdout.value += e.data + '\n'
      activeTab.value = 'output'
      scrollToBottom()
      break
    case 'stderr':
      stderr.value += e.data + '\n'
      activeTab.value = 'output'
      scrollToBottom()
      break
    case 'echarts':
      charts.value.push(e.option)
      activeTab.value = 'charts'
      break
    case 'image':
      images.value.push(e.data)
      activeTab.value = 'images'
      break
    case 'done':
      lastResult.value = { exit_code: e.exit_code, duration_ms: e.duration_ms }
      running.value = false
      if (e.exit_code !== 0) activeTab.value = 'output'
      break
    case 'error':
      stderr.value += e.detail + '\n'
      running.value = false
      activeTab.value = 'output'
      break
  }
}

function handleRun() {
  if (!activeSessionId.value) {
    message.warning('请先创建沙盒会话')
    return
  }
  const inst = ensureWs()
  if (!inst) return
  if (!inst.connected.value) {
    message.info('正在连接沙盒…')
    setTimeout(() => {
      if (inst.connected.value) doExecute(inst)
      else message.error('沙盒连接失败，请稍后重试')
    }, 800)
    return
  }
  doExecute(inst)
}

function doExecute(inst: WsInst) {
  resetOutput()
  running.value = true
  inst.execute(code.value, 0)
}

function handleStop() {
  running.value = false
  wsSessionId.value = ''
  ws.value?.disconnect()
  ws.value = null
  message.info('已断开沙盒连接')
}

const hasOutput = computed(
  () => !!(stdout.value || stderr.value || charts.value.length || images.value.length),
)

const statusText = computed(() => {
  if (running.value) return '执行中'
  if (lastResult.value) {
    return lastResult.value.exit_code === 0
      ? '执行成功'
      : `执行失败 (exit ${lastResult.value.exit_code})`
  }
  return '空闲'
})

const statusType = computed<'success' | 'error' | 'default'>(() => {
  if (running.value || !lastResult.value) return 'default'
  return lastResult.value.exit_code === 0 ? 'success' : 'error'
})

function loadExample(name: 'umap' | 'heatmap' | 'image') {
  if (name === 'umap') {
    code.value = [
      '# UMAP 散点（scatterGL，支持十万级细胞）',
      'import numpy as np',
      'n = 20000',
      'pts = np.random.randn(n, 2).tolist()',
      'show_echarts({',
      "  title: { text: 'UMAP (scatterGL ' + str(n) + ' cells)' },",
      "  xAxis: { type: 'value', min: -4, max: 4 },",
      "  yAxis: { type: 'value', min: -4, max: 4 },",
      '  dataZoom: [{ type: "inside" }],',
      '  series: [{ type: "scatterGL", data: pts, symbolSize: 2, itemStyle: { opacity: 0.6 } }],',
      '})',
      '',
    ].join('\n')
  } else if (name === 'heatmap') {
    code.value = [
      '# 基因表达热图',
      'import numpy as np',
      "genes = ['CD3D', 'CD79A', 'MS4A1', 'CD8A', 'NKG7', 'LYZ', 'CD14']",
      "cells = ['C' + str(i) for i in range(12)]",
      'data = []',
      'for i in range(len(genes)):',
      '    for j in range(len(cells)):',
      '        data.append([j, i, round(float(np.random.rand()), 3)])',
      'show_echarts({',
      "  title: { text: 'Marker 基因表达热图' },",
      "  tooltip: { position: 'top' },",
      "  grid: { height: '60%', top: '10%' },",
      "  xAxis: { type: 'category', data: cells },",
      "  yAxis: { type: 'category', data: genes },",
      "  visualMap: { min: 0, max: 1, calculable: True, orient: 'horizontal', bottom: '2%' },",
      "  series: [{ type: 'heatmap', data: data, emphasis: { itemStyle: { shadowBlur: 10 } } }],",
      '})',
      '',
    ].join('\n')
  } else {
    code.value = [
      '# matplotlib 静态图回传',
      'import matplotlib.pyplot as plt',
      'import numpy as np',
      'fig, ax = plt.subplots(figsize=(6, 4))',
      'ax.scatter(*np.random.randn(2, 500), s=5, alpha=0.5)',
      "ax.set_title('scatter via matplotlib')",
      "out = '/workspace/output/demo.png'",
      'plt.savefig(out, dpi=120)',
      'show_image(out)',
      '',
    ].join('\n')
  }
}

onMounted(() => store.fetchSessions().catch(() => {}))

watch(activeSessionId, (id) => {
  if (id) ensureWs()
})

onBeforeUnmount(() => {
  ws.value?.disconnect()
  ws.value = null
})
</script>

<template>
  <main class="sandbox-page" aria-label="代码沙盒" :aria-busy="running">
    <div class="sandbox-toolbar">
      <NSpace align="center" :size="12">
        <NSelect
          v-model:value="language"
          :options="languageOptions"
          size="small"
          style="width: 200px"
          :disabled="!!activeSessionId"
        />
        <NButton type="primary" size="small" :disabled="!activeSessionId" @click="handleRun">
          <template #icon><NIcon><PlayOutline /></NIcon></template>
          运行
        </NButton>
        <NButton size="small" :disabled="!running" @click="handleStop">
          <template #icon><NIcon><StopCircleOutline /></NIcon></template>
          停止
        </NButton>
        <NTag :type="statusType" size="small" round role="status" aria-live="polite">
          <template #icon>
            <NIcon v-if="statusType === 'success'"><CheckmarkCircleOutline /></NIcon>
            <NIcon v-else-if="statusType === 'error'"><CloseCircleOutline /></NIcon>
            <NIcon v-else><TimeOutline /></NIcon>
          </template>
          {{ statusText }}
        </NTag>
        <NTooltip v-if="lastResult">
          <template #trigger>
            <span class="duration-text">{{ (lastResult.duration_ms / 1000).toFixed(2) }}s</span>
          </template>
          耗时
        </NTooltip>
      </NSpace>

      <NSpace align="center" :size="8">
        <NTooltip>
          <template #trigger>
            <NButton size="small" quaternary @click="loadExample('umap')">UMAP</NButton>
          </template>
          加载 scatterGL UMAP 示例
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton size="small" quaternary @click="loadExample('heatmap')">热图</NButton>
          </template>
          加载表达热图示例
        </NTooltip>
        <NTooltip>
          <template #trigger>
            <NButton size="small" quaternary @click="loadExample('image')">图片</NButton>
          </template>
          加载 matplotlib 图片示例
        </NTooltip>
        <NButton size="small" quaternary @click="resetOutput">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          清空
        </NButton>
      </NSpace>
    </div>

    <div class="sandbox-body">
      <aside class="session-panel">
        <div class="panel-header">
          <span class="panel-title">会话</span>
          <NButton size="tiny" quaternary circle @click="handleCreate">
            <NIcon><AddOutline /></NIcon>
          </NButton>
        </div>
        <div class="session-list">
          <NEmpty v-if="!store.sessions.length" size="small" description="无会话" style="margin-top: 40px" />
          <div
            v-for="s in store.sessions"
            :key="s.id"
            class="session-item"
            :class="{ active: s.id === activeSessionId }"
            @click="handleSelectSession(s.id)"
          >
            <div class="session-item-main">
              <span class="session-id">{{ s.id.slice(0, 8) }}</span>
              <NTag
                size="small"
                :type="
                  s.status === 'ready' || s.status === 'idle'
                    ? 'success'
                    : s.status === 'error'
                      ? 'error'
                      : 'default'
                "
              >
                {{ s.status }}
              </NTag>
            </div>
            <NPopconfirm @positive-click="handleDelete(s.id)">
              <template #trigger>
                <NButton size="tiny" quaternary circle @click.stop>
                  <NIcon><TrashOutline /></NIcon>
                </NButton>
              </template>
              销毁此会话？
            </NPopconfirm>
          </div>
        </div>
      </aside>

      <section class="editor-panel">
        <div class="panel-header">
          <span class="panel-title">analysis.py</span>
          <NTag v-if="!activeSessionId" size="small" type="warning">未创建会话</NTag>
          <NSpin v-else-if="running" size="small" />
        </div>
        <div class="editor-wrap">
          <CodeEditor v-model="code" :readonly="running" @run="handleRun" />
        </div>
      </section>

      <section class="result-panel">
        <div class="panel-header">
          <span class="panel-title">结果</span>
        </div>
        <NTabs v-model:value="activeTab" type="line" size="small" class="result-tabs">
          <NTabPane name="output" tab="输出">
            <div v-if="!hasOutput" class="result-empty">
              <NEmpty size="small" description="运行代码后在此查看输出">
                <template #icon>
                  <NIcon :size="40"><CodeSlashOutline /></NIcon>
                </template>
              </NEmpty>
            </div>
            <div v-else class="output-wrap" ref="outputRef">
              <pre v-if="stdout" class="output-stream stdout">{{ stdout }}</pre>
              <pre v-if="stderr" class="output-stream stderr">{{ stderr }}</pre>
            </div>
          </NTabPane>
          <NTabPane name="charts" :tab="`图表 (${charts.length})`">
            <div v-if="!charts.length" class="result-empty">
              <NEmpty size="small" description="代码调用 show_echarts() 后图表在此渲染" />
            </div>
            <div v-else class="charts-grid">
              <div v-for="(opt, i) in charts" :key="i" class="chart-card">
                <VChart :option="opt" autoresize style="height: 320px" />
              </div>
            </div>
          </NTabPane>
          <NTabPane name="images" :tab="`图片 (${images.length})`">
            <div v-if="!images.length" class="result-empty">
              <NEmpty size="small" description="代码调用 show_image() 后图片在此展示" />
            </div>
            <div v-else class="images-grid">
              <img v-for="(src, i) in images" :key="i" :src="src" class="result-image" />
            </div>
          </NTabPane>
        </NTabs>
      </section>
    </div>
  </main>
</template>

<style scoped>
.sandbox-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 16px;
  gap: 12px;
  background: var(--neutral-bg);
}
.sandbox-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  padding: 10px 14px;
  background: var(--card-bg, var(--neutral-popover, #fff));
  border: 1px solid var(--neutral-border);
  border-radius: 10px;
}
.duration-text {
  font-size: 12px;
  color: var(--neutral-text-2);
  font-family: 'JetBrains Mono', monospace;
}
.sandbox-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 200px 1fr 1fr;
  gap: 12px;
}
.session-panel,
.editor-panel,
.result-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--card-bg, var(--neutral-popover, #fff));
  border: 1px solid var(--neutral-border);
  border-radius: 10px;
  overflow: hidden;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--neutral-border);
  flex-shrink: 0;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  border-radius: 7px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background 0.15s;
}
.session-item:hover {
  background: var(--neutral-hover, #f2f3f8);
}
.session-item.active {
  background: var(--arco-primary-light, #e8f3ff);
}
.session-item-main {
  display: flex;
  align-items: center;
  gap: 8px;
}
.session-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--neutral-text-1);
}
.editor-wrap {
  flex: 1;
  min-height: 0;
}
.result-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.result-tabs :deep(.n-tab-pane) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
}
.result-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 200px;
}
.output-wrap {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12.5px;
  line-height: 1.55;
}
.output-stream {
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}
.output-stream.stdout {
  background: var(--neutral-hover, #f7f8fa);
  color: var(--neutral-text-1);
}
.output-stream.stderr {
  background: rgba(245, 63, 63, 0.08);
  color: #d03;
}
.charts-grid,
.images-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.chart-card {
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  padding: 8px;
  background: var(--neutral-popover, #fff);
}
.result-image {
  max-width: 100%;
  border-radius: 8px;
  border: 1px solid var(--neutral-border);
}
@media (max-width: 1024px) {
  .sandbox-body {
    grid-template-columns: 1fr;
    grid-template-rows: auto 320px 320px;
  }
}
</style>
