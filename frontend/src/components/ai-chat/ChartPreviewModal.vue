<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { NModal } from 'naive-ui'
import { VChart } from './setup'
import type { ChartData } from './types'

interface Props {
  show: boolean
  chart: ChartData | null
}

const props = defineProps<Props>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const plotlyContainer = ref<HTMLDivElement | null>(null)

function handleUpdateShow(value: boolean) {
  emit('update:show', value)
}

async function renderPlotly() {
  if (!plotlyContainer.value || !props.chart || props.chart.type !== 'plotly') return
  const Plotly = await import('plotly.js-dist-min')
  await nextTick()
  Plotly.newPlot(
    plotlyContainer.value,
    (props.chart.option.data || []) as Plotly.Data[],
    (props.chart.option.layout || {}) as Partial<Plotly.Layout>,
    {
      responsive: true,
      displayModeBar: true,
      displaylogo: false,
      // 默认 600 DPI 导出（scale = 600/96）
      toImageButtonOptions: {
        format: 'png',
        filename: 'omichub_plot_600dpi',
        scale: 6.25,
      } as Plotly.Config['toImageButtonOptions'],
    },
  )
}

watch(
  () => [props.show, props.chart],
  () => {
    if (props.show && props.chart?.type === 'plotly') {
      renderPlotly()
    }
  },
  { immediate: true },
)
</script>

<template>
  <NModal
    :show="props.show"
    preset="card"
    title="图表预览"
    style="width: min(90vw, 1200px)"
    :bordered="false"
    segmented
    @update:show="handleUpdateShow"
  >
    <div class="preview-body">
      <div
        v-if="chart?.type === 'plotly'"
        ref="plotlyContainer"
        class="plotly-preview"
      />
      <div v-else-if="chart?.type === 'echarts'" class="echarts-preview">
        <VChart
          :option="chart.option"
          autoresize
          style="width: 100%; height: 100%"
        />
      </div>
      <div v-else class="empty-preview">
        暂无图表
      </div>
    </div>
  </NModal>
</template>

<style scoped lang="scss">
.preview-body {
  width: 100%;
  height: 60vh;
  min-height: 400px;
}
.plotly-preview,
.echarts-preview {
  width: 100%;
  height: 100%;
}
.empty-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--chat-text-muted, #999);
}
</style>
