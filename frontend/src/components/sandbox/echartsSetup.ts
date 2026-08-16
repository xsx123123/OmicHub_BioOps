import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { ScatterChart, HeatmapChart, BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
  VisualMapComponent,
  BrushComponent,
  ToolboxComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
// echarts-gl 提供 scatterGL（十万级细胞 UMAP 散点 WebGL 渲染）
import 'echarts-gl'

use([
  CanvasRenderer,
  ScatterChart,
  HeatmapChart,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
  VisualMapComponent,
  BrushComponent,
  ToolboxComponent,
])

export { VChart }
