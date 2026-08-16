import type { Component } from 'vue'
import {
  AppsOutline,
  BarChartOutline,
  BookOutline,
  ChatbubblesOutline,
  CloudUploadOutline,
  ConstructOutline,
  DocumentTextOutline,
  DownloadOutline,
  FitnessOutline,
  GitNetworkOutline,
  FlaskOutline,
  GridOutline,
  HomeOutline,
  InformationCircleOutline,
  LayersOutline,
  LibraryOutline,
  ListOutline,
  MapOutline,
  SettingsOutline,
  SparklesOutline,
  StatsChartOutline,
  TerminalOutline,
} from '@vicons/ionicons5'
import type { HomeQuickEntry, QuickEntryColor } from '@/types'

export const quickEntryBgColors: Record<QuickEntryColor, string> = {
  blue: '#E8F3FF',
  purple: '#F0E8FF',
  violet: '#F3F0FF',
  cyan: '#E6FFFB',
  green: '#E8FFEA',
  orange: '#FFF2E8',
  teal: '#E8FFFA',
  gray: '#F2F3F5',
}

export const quickEntryIconColors: Record<QuickEntryColor, string> = {
  blue: '#165DFF',
  purple: '#722ED1',
  violet: '#8B5CF6',
  cyan: '#14C9C9',
  green: '#00B42A',
  orange: '#F77234',
  teal: '#0FC6C2',
  gray: '#4E5969',
}

export const quickEntryColorOptions: Array<{ label: string; value: QuickEntryColor }> = [
  { label: '蓝色', value: 'blue' },
  { label: '紫色', value: 'purple' },
  { label: '亮紫', value: 'violet' },
  { label: '青色', value: 'cyan' },
  { label: '绿色', value: 'green' },
  { label: '橙色', value: 'orange' },
  { label: '蓝绿', value: 'teal' },
  { label: '灰色', value: 'gray' },
]

export const homeQuickEntryIconMap: Record<string, Component> = {
  AppsOutline,
  BarChartOutline,
  BookOutline,
  ChatbubblesOutline,
  CloudUploadOutline,
  ConstructOutline,
  DocumentTextOutline,
  DownloadOutline,
  FitnessOutline,
  FlaskOutline,
  GridOutline,
  HomeOutline,
  InformationCircleOutline,
  LayersOutline,
  LibraryOutline,
  ListOutline,
  MapOutline,
  SettingsOutline,
  SparklesOutline,
  StatsChartOutline,
  TerminalOutline,
}

export const homeQuickEntryIconOptions = Object.keys(homeQuickEntryIconMap).map((key) => ({
  label: key.replace('Outline', ''),
  value: key,
}))

export const homeQuickRouteCatalog: HomeQuickEntry[] = [
  {
    key: 'dashboard',
    title: '仪表板',
    desc: '查看平台数据概览',
    to: '/dashboard',
    icon: 'GridOutline',
    icon_bg: 'blue',
  },
  {
    key: 'flows',
    title: '分析中心',
    desc: '选择并提交分析流程',
    to: '/flows',
    icon: 'FlaskOutline',
    icon_bg: 'blue',
  },
  {
    key: 'rna-seq',
    title: 'RNA-seq 分析',
    desc: '转录组差异表达分析',
    to: '/flows?type=rna-seq',
    icon: 'FlaskOutline',
    icon_bg: 'blue',
  },
  {
    key: 'atac-seq',
    title: 'ATAC-seq 分析',
    desc: '染色质开放性分析',
    to: '/flows?type=atac-seq',
    icon: 'FitnessOutline',
    icon_bg: 'purple',
  },
  {
    key: 'files',
    title: '数据管理',
    desc: '上传与管理样本数据',
    to: '/files',
    icon: 'CloudUploadOutline',
    icon_bg: 'cyan',
  },
  {
    key: 'database',
    title: '数据库',
    desc: '浏览基因组与功能注释库',
    to: '/database',
    icon: 'LayersOutline',
    icon_bg: 'teal',
  },
  {
    key: 'downloads',
    title: '数据下载',
    desc: '管理外部数据下载任务',
    to: '/downloads',
    icon: 'DownloadOutline',
    icon_bg: 'green',
  },
  {
    key: 'tasks',
    title: '任务中心',
    desc: '查看分析任务进度',
    to: '/tasks',
    icon: 'DocumentTextOutline',
    icon_bg: 'orange',
  },
  {
    key: 'reports',
    title: '结果报告中心',
    desc: '查看与交付分析报告',
    to: '/reports',
    icon: 'StatsChartOutline',
    icon_bg: 'purple',
  },
  {
    key: 'ai',
    title: '星尘AI',
    desc: '对话式生信分析与结果解读',
    to: '/ai',
    icon: 'SparklesOutline',
    icon_bg: 'violet',
  },
  {
    key: 'tools',
    title: '生信工具箱',
    desc: '进入常用生信工具集合',
    to: '/tools',
    icon: 'ConstructOutline',
    icon_bg: 'teal',
  },
  {
    key: 'tools-fastq-qc',
    title: 'FASTQ 质控',
    desc: '检查测序数据质量',
    to: '/tools/fastq-qc',
    icon: 'StatsChartOutline',
    icon_bg: 'blue',
  },
  {
    key: 'tools-jbrowse',
    title: '基因组浏览器',
    desc: '打开 JBrowse 可视化查看',
    to: '/tools/jbrowse',
    icon: 'MapOutline',
    icon_bg: 'teal',
  },
  {
    key: 'tools-blast',
    title: '序列检索',
    desc: '进行 BLAST 序列比对',
    to: '/tools/blast',
    icon: 'LibraryOutline',
    icon_bg: 'cyan',
  },
  {
    key: 'tools-plot',
    title: '绘图工坊',
    desc: '制作常用科研图表',
    to: '/tools/plot',
    icon: 'BarChartOutline',
    icon_bg: 'purple',
  },
  {
    key: 'tools-volcano',
    title: '火山图绘制',
    desc: '绘制差异分析火山图',
    to: '/tools/volcano',
    icon: 'StatsChartOutline',
    icon_bg: 'orange',
  },
  {
    key: 'tools-kegg-enrichment',
    title: 'KEGG 富集分析',
    desc: '进行通路富集分析',
    to: '/tools/kegg-enrichment',
    icon: 'AppsOutline',
    icon_bg: 'green',
  },
  {
    key: 'tools-seq-manipulator',
    title: '序列魔术师',
    desc: '处理常见序列操作',
    to: '/tools/seq-manipulator',
    icon: 'ListOutline',
    icon_bg: 'blue',
  },
  {
    key: 'tools-format-converter',
    title: '格式转换器',
    desc: '轻量转换数据格式',
    to: '/tools/format-converter',
    icon: 'DocumentTextOutline',
    icon_bg: 'gray',
  },
  {
    key: 'tools-terminal',
    title: '云端沙盒终端',
    desc: '进入在线分析终端',
    to: '/tools/terminal',
    icon: 'TerminalOutline',
    icon_bg: 'orange',
  },
  {
    key: 'knowledge',
    title: '实验室知识库',
    desc: '查阅实验室文档资料',
    to: '/knowledge',
    icon: 'BookOutline',
    icon_bg: 'purple',
  },
  {
    key: 'cookies',
    title: '用量统计',
    desc: '查看账户用量与余额',
    to: '/cookies',
    icon: 'BarChartOutline',
    icon_bg: 'green',
  },
  {
    key: 'about',
    title: '关于 OmicHub',
    desc: '了解平台与项目信息',
    to: '/about',
    icon: 'InformationCircleOutline',
    icon_bg: 'gray',
  },
]

export const defaultHomeQuickEntries: HomeQuickEntry[] = [
  createHomeQuickEntry('/flows?type=rna-seq'),
  createHomeQuickEntry('/flows?type=atac-seq'),
  createHomeQuickEntry('/files'),
  createHomeQuickEntry('/ai'),
  createHomeQuickEntry('/tasks'),
]

export function resolveHomeQuickEntryIcon(icon?: string): Component {
  return homeQuickEntryIconMap[icon || ''] || DocumentTextOutline
}

export function createHomeQuickEntry(to: string): HomeQuickEntry {
  const entry = homeQuickRouteCatalog.find((item) => item.to === to) || homeQuickRouteCatalog[0]
  return { ...entry }
}

export function normalizeHomeQuickEntries(entries?: Array<Partial<HomeQuickEntry>> | null): HomeQuickEntry[] {
  const source = Array.isArray(entries) && entries.length ? entries : defaultHomeQuickEntries
  const normalized = source
    .map((entry, index) => {
      const matched = homeQuickRouteCatalog.find((item) => item.to === entry.to || item.key === entry.key)
      const base = matched || defaultHomeQuickEntries[index] || homeQuickRouteCatalog[0]
      const color = quickEntryColorOptions.some((item) => item.value === entry.icon_bg)
        ? entry.icon_bg as QuickEntryColor
        : base.icon_bg
      const icon = entry.icon && homeQuickEntryIconMap[entry.icon] ? entry.icon : base.icon
      return {
        key: String(entry.key || base.key || `quick-entry-${index}`),
        title: String(entry.title || base.title),
        desc: String(entry.desc || base.desc || ''),
        to: String(entry.to || base.to),
        icon,
        icon_bg: color,
      }
    })
    .filter((entry) => entry.to.startsWith('/') && !entry.to.startsWith('//'))
    .slice(0, 8)
  return normalized.length ? normalized : defaultHomeQuickEntries.map((entry) => ({ ...entry }))
}
