<script setup lang="ts">
/**
 * YamlGenomeBrowser.vue —— 前端 YAML 驱动的 JBrowse 2 基因组浏览器
 *
 * 与 JBrowseViewer.vue（后端 /jbrowse/config 生成配置）不同，本组件在前端直接：
 *   ① onMounted 拉取 + 解析 /genomes.yaml（js-yaml），结果缓存进 ref，仅加载一次；
 *   ② 下拉框切换物种时，从缓存读取对应条目，走【适配器】把扁平 YAML 组装成
 *      JBrowse 2 所需的深层嵌套配置对象（即 createViewState 接受的那份 config）；
 *   ③ 将该配置 JSON 写成 blob URL 注入 iframe —— 这是 Vue + iframe 架构下
 *      「更新渲染状态」的等价实现（createViewState 本身是 React 专属 API，本项目未引入）。
 *
 * 数据流：fetch YAML → yaml.load → 缓存 genomesConfig → watch(selectedGenome)
 *         → buildJbrowseConfig（适配器）→ Blob → iframe src + :key 强刷。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NIcon, NSelect, NInput, NSpin, NEmpty, useMessage,
} from 'naive-ui'
import {
  LocationOutline, RefreshOutline, AlertCircleOutline,
} from '@vicons/ionicons5'
import { load as yamlLoad } from 'js-yaml'
import { absolutizeUris } from '@/utils/jbrowse'
import PageHeader from '@/components/PageHeader.vue'

const router = useRouter()
const message = useMessage()

// ==================== 类型定义 ====================

/** YAML 模板里每个物种条目（人类可读的扁平结构） */
interface GenomeEntry {
  /** 显示名称 */
  name: string
  /** FASTA 的可 fetch URI（本项目用 /tracks/...，由 nginx 流式输出） */
  fasta_uri: string
  /** FASTA .fai 索引 URI */
  fai_uri: string
  /** bgzip FASTA（.fa.gz）的 .gzi 索引 URI，可选 */
  gzi_uri?: string
  /** 默认定位，如 chr1:1000000-2000000 */
  default_location?: string
  /** 染色体别名 */
  aliases?: string[]
}

/** 解析后的 YAML 顶层结构：物种 ID → 条目 */
type GenomesYaml = Record<string, GenomeEntry>

/** JBrowse 2 UriLocation */
interface UriLocation {
  uri: string
  locationType: 'UriLocation'
}

/** JBrowse 2 配置对象（createViewState 接受的配置结构） */
interface JbrowseConfig {
  assemblies: Array<{
    name: string
    aliases: string[]
    sequence: {
      type: 'ReferenceSequenceTrack'
      trackId: string
      adapter: {
        type: 'IndexedFastaAdapter' | 'BgzipFastaAdapter'
        fastaLocation: UriLocation
        faiLocation: UriLocation
        gziLocation?: UriLocation
      }
    }
  }>
  tracks: unknown[]
  defaultSession: {
    name: string
    view: {
      id: string
      type: 'LinearGenomeView'
      tracks: unknown[]
      location?: { refName: string; start: number; end: number }
    }
  }
  configuration: {
    theme: { palette: { primary: { main: string } } }
  }
}

// ==================== 响应式状态 ====================

/** 缓存：解析后的整份 YAML（仅 onMounted 加载一次，下拉切换直接读内存） */
const genomesConfig = ref<GenomesYaml | null>(null)
/** 当前选中物种 ID */
const selectedGenome = ref<string>('')
/** 坐标输入框（跳转用） */
const locationInput = ref<string>('')
/** 配置加载中 */
const loading = ref(false)
/** 加载/解析错误文案（用于错误兜底 UI） */
const errorMsg = ref<string>('')
/** iframe src */
const jbrowseUrl = ref<string>('')
/** iframe 强制刷新 key：每次配置变更自增，丢弃 JBrowse localStorage 旧 session */
const iframeKey = ref(0)
/** 当前 blob URL（卸载/重建前回收，避免内存泄漏） */
let currentBlobUrl = ''

// ==================== 计算属性 ====================

/** 下拉框选项：由缓存的 YAML 派生，YAML 重新加载后自动更新 */
const genomeOptions = computed(() => {
  const cfg = genomesConfig.value
  if (!cfg) return []
  return Object.entries(cfg).map(([id, entry]) => ({
    label: entry.name || id,
    value: id,
  }))
})

// ==================== 生命周期 ====================

onMounted(() => {
  // 仅在挂载时加载一次；后续下拉切换不再发请求
  loadGenomeConfig()
})

onUnmounted(() => {
  revokeBlobUrl()
})

// ==================== ① 请求 - 解析 - 缓存 ====================

/**
 * 异步加载并解析 YAML 配置，结果缓存进 genomesConfig。
 * 严谨错误处理：网络失败 / 非 2xx / 空文本 / YAML 语法错 / 顶层非对象
 * 均被捕获并以 UI 提示 + 控制台日志兜底，绝不抛 Uncaught TypeError。
 */
async function loadGenomeConfig(url = '/genomes.yaml'): Promise<void> {
  loading.value = true
  errorMsg.value = ''
  try {
    // 1) 网络请求
    let res: Response
    try {
      res = await fetch(url, { cache: 'no-cache' })
    } catch (networkErr) {
      throw new Error(`网络请求失败：${networkErr instanceof Error ? networkErr.message : '请检查网络'}`)
    }
    if (!res.ok) {
      throw new Error(`配置文件请求失败（HTTP ${res.status}）：${url}`)
    }

    // 2) 读取纯文本
    const text = await res.text()
    if (!text || !text.trim()) {
      throw new Error('配置文件为空')
    }

    // 3) js-yaml 解析（语法错会抛 YAMLException，带行列信息）
    let parsed: unknown
    try {
      parsed = yamlLoad(text)
    } catch (syntaxErr) {
      throw new Error(`YAML 语法错误：${syntaxErr instanceof Error ? syntaxErr.message : String(syntaxErr)}`)
    }

    // 4) 结构校验：顶层必须是非空对象
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('YAML 顶层必须是一个对象（物种 ID → 条目）')
    }
    const cfg = parsed as GenomesYaml
    if (Object.keys(cfg).length === 0) {
      throw new Error('配置为空：未定义任何物种')
    }

    // 5) 缓存到内存，后续下拉切换直接读取，不再 fetch
    genomesConfig.value = cfg

    // 默认选第一个物种，触发 watch → 自动构建配置并渲染
    const firstId = Object.keys(cfg)[0]
    selectedGenome.value = firstId
    message.success(`已加载 ${Object.keys(cfg).length} 个物种配置`)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    errorMsg.value = msg
    genomesConfig.value = null
    message.error(`加载基因组配置失败：${msg}`)
    // 控制台输出完整错误，便于排查
    console.error('[YamlGenomeBrowser] loadGenomeConfig failed:', e)
  } finally {
    loading.value = false
  }
}

// ==================== ④ 数据适配器（扁平 YAML → 深层 JBrowse 配置）====================

/**
 * 把 YAML 里人类可读的扁平条目，组装成 JBrowse 2 能识别的深层嵌套配置对象。
 * 这份对象正是 createViewState({ ... }) 期望的入参结构；本项目把它序列化进 blob
 * 交给 iframe，效果等价于「更新 viewState」。
 *
 * 适配要点：
 *   fasta_uri / fai_uri  →  sequence.adapter.{fastaLocation,faiLocation}.uri
 *   .fa.gz               →  BgzipFastaAdapter（额外需要 gziLocation）
 *   .fa / .fasta          →  IndexedFastaAdapter
 *   default_location     →  defaultSession.view.location { refName, start, end }
 */
function buildJbrowseConfig(id: string, entry: GenomeEntry, locationStr: string): JbrowseConfig {
  // 根据 FASTA 扩展名推断 adapter 类型：bgzip 压缩走 BgzipFastaAdapter
  const isBgzip = /\.fa(sta)?\.gz$/i.test(entry.fasta_uri)

  const fastaLocation: UriLocation = { uri: entry.fasta_uri, locationType: 'UriLocation' }
  const faiLocation: UriLocation = { uri: entry.fai_uri, locationType: 'UriLocation' }

  const adapter: JbrowseConfig['assemblies'][number]['sequence']['adapter'] = isBgzip
    ? {
        type: 'BgzipFastaAdapter',
        fastaLocation,
        faiLocation,
        // bgzip 需要 .gzi 索引；缺失时不写该字段（JBrowse 会尝试自动找，找不到则报错）
        ...(entry.gzi_uri
          ? { gziLocation: { uri: entry.gzi_uri, locationType: 'UriLocation' } as UriLocation }
          : {}),
      }
    : {
        type: 'IndexedFastaAdapter',
        fastaLocation,
        faiLocation,
      }

  // 解析默认定位字符串 → { refName, start, end }
  const location = parseLocation(locationStr)

  return {
    assemblies: [
      {
        name: id,
        aliases: entry.aliases ?? [],
        sequence: {
          type: 'ReferenceSequenceTrack',
          trackId: `${id}-reference`,
          adapter,
        },
      },
    ],
    // 初始轨道为空，后续可动态添加
    tracks: [],
    defaultSession: {
      name: `OmicHub-${id}`,
      view: {
        id: 'linearGenomeView',
        type: 'LinearGenomeView',
        tracks: [],
        // 仅在解析成功时写入 location，避免 JBrowse 拿到非法定位
        ...(location ? { location } : {}),
      },
    },
    // JBrowse 内部主题色对齐平台主色
    configuration: {
      theme: { palette: { primary: { main: '#165DFF' } } },
    },
  }
}

/**
 * 解析坐标字符串为 JBrowse 2 location 对象。
 * 兼容三种写法：chr1:1000000-2000000 / LG1:1..10000 / Chr1:1,000,000-2,000,000
 * 解析失败返回 null（调用方决定是否写入配置）。
 */
function parseLocation(raw: string): { refName: string; start: number; end: number } | null {
  if (!raw) return null
  // 归一化：.. → -，去逗号、空白
  const norm = raw.replace(/\s/g, '').replace(/,/g, '').replace(/\.\./g, '-')
  const m = /^([A-Za-z0-9_.]+):(\d+)-(\d+)$/.exec(norm)
  if (!m) return null
  return { refName: m[1], start: Number(m[2]), end: Number(m[3]) }
}

/** 坐标格式校验（跳转前用） */
function validateLocation(raw: string): boolean {
  return parseLocation(raw) !== null
}

// ==================== ③ 渲染：配置 → blob → iframe（createViewState 的 Vue 等价实现）====================

function revokeBlobUrl() {
  if (currentBlobUrl) {
    URL.revokeObjectURL(currentBlobUrl)
    currentBlobUrl = ''
  }
}

/**
 * 用选中的物种（可选坐标覆盖）构建配置并刷新 iframe。
 * 每次 config 变化都重建 iframe 元素（:key 自增），确保 JBrowse 丢弃旧 session。
 */
async function applyGenome(id: string, locationOverride?: string): Promise<void> {
  const cfg = genomesConfig.value
  if (!cfg || !id) return

  const entry = cfg[id]
  if (!entry) {
    message.warning('未找到该物种的配置，请重新选择')
    return
  }

  // 坐标优先用用户输入，其次用物种默认定位
  const loc = locationOverride ?? entry.default_location ?? ''
  if (loc && !validateLocation(loc)) {
    message.error('坐标格式错误，请使用 chr:start-end 格式')
    return
  }

  // 适配器：扁平 → 深层 JBrowse 配置
  const config = buildJbrowseConfig(id, entry, loc)

  // ⚠️ 关键：blob URL 是 opaque base，JBrowse 用 new URL(uri, blobBase) 解析相对 uri 会抛
  // Invalid URL。写入 blob 前把所有 uri 补成绝对 URL（带 origin），绕开 opaque base 限制。
  absolutizeUris(config)

  // 序列化为 blob，注入 iframe（绕过 JWT；详见 pipelines/jbrowse2/README.md）
  revokeBlobUrl()
  const blob = new Blob([JSON.stringify(config)], { type: 'application/json' })
  currentBlobUrl = URL.createObjectURL(blob)
  jbrowseUrl.value =
    `/jbrowse2/?config=${encodeURIComponent(currentBlobUrl)}` +
    (loc ? `&loc=${encodeURIComponent(loc)}` : '')
  iframeKey.value++
}

// ==================== ② 状态联动 ====================

// 下拉框变化：从缓存读取对应物种 → 重置坐标输入 → 重建配置并渲染
watch(selectedGenome, (id) => {
  if (!id) return
  const entry = genomesConfig.value?.[id]
  // 切换物种时坐标输入框回到该物种的默认定位
  locationInput.value = entry?.default_location ?? ''
  applyGenome(id)
})

/** 跳转按钮：用当前坐标输入框的值覆盖默认定位并重渲染 */
function jumpToRegion() {
  if (!selectedGenome.value) {
    message.warning('请先选择参考基因组')
    return
  }
  applyGenome(selectedGenome.value, locationInput.value)
}

/** 手动重新拉取 YAML（绕过缓存，开发/运维用） */
function reloadConfig() {
  loadGenomeConfig()
}
</script>

<template>
  <div class="yaml-browser-page" role="main" aria-label="YAML 驱动基因组浏览器">
    <!-- 工具栏 -->
    <PageHeader
      title="🧬 YAML 驱动基因组浏览器"
      subtitle="前端解析 genomes.yaml · 适配器构建 JBrowse 2 配置"
      back-to="/tools"
      back-label="返回工具箱"
    >
      <template #actions>
        <span class="ctrl-label">参考基因组</span>
        <NSelect
          v-model:value="selectedGenome"
          :options="genomeOptions"
          :loading="loading"
          :disabled="!genomesConfig"
          placeholder="选择物种"
          size="small"
          style="width: 220px"
        />
        <NInput
          v-model:value="locationInput"
          placeholder="chr1:1000000-2000000"
          size="small"
          style="width: 220px"
          @keyup.enter="jumpToRegion"
        >
          <template #prefix><span class="loc-prefix">🧭</span></template>
        </NInput>
        <NButton size="small" type="primary" @click="jumpToRegion">
          <template #icon><NIcon><LocationOutline /></NIcon></template>
          跳转
        </NButton>
        <NButton size="small" @click="reloadConfig">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          重载配置
        </NButton>
      </template>
    </PageHeader>

    <!-- 渲染区 -->
    <div class="browser-view">
      <!-- 初始化 / 重载 loading -->
      <div v-if="loading" class="loading-mask">
        <NSpin size="large" />
        <p class="loading-text">正在加载基因组配置...</p>
      </div>

      <!-- 加载失败兜底：避免空白或 Uncaught TypeError -->
      <div v-else-if="errorMsg" class="error-state">
        <NEmpty>
          <template #icon><NIcon :size="64" color="#F53F3F"><AlertCircleOutline /></NIcon></template>
          <div class="empty-desc">
            <p class="empty-title">配置加载失败</p>
            <p class="empty-hint">{{ errorMsg }}</p>
            <NButton size="small" type="primary" style="margin-top: 12px" @click="reloadConfig">重试</NButton>
          </div>
        </NEmpty>
      </div>

      <!-- JBrowse 2 iframe（:key 变化即重建，等价于 viewState 更新）-->
      <iframe
        v-else-if="jbrowseUrl"
        :key="iframeKey"
        :src="jbrowseUrl"
        frameborder="0"
        class="jbrowse-iframe"
      />

      <!-- 无数据空状态 -->
      <div v-else class="empty-state">
        <NEmpty description="暂无可用基因组，请检查 genomes.yaml" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 全高 flex 布局：依赖路由 meta.fullscreen 提供有界高度的 flex 链 */
.yaml-browser-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--neutral-bg);
}

/* 工具栏 */
.ctrl-label { font-size: 13px; color: var(--neutral-text-2, #4e5969); white-space: nowrap; }
.loc-prefix { font-size: 13px; line-height: 1; }

/* 渲染区 */
.browser-view {
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
  background: var(--neutral-card, #fff);
}
.jbrowse-iframe { width: 100%; height: 100%; border: none; display: block; }

.loading-mask {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  background: rgba(255, 255, 255, 0.75); z-index: 10;
}
.loading-text { font-size: 13px; color: var(--neutral-text-2, #4e5969); margin: 0; }
:root[data-theme="dark"] .loading-mask { background: rgba(21, 26, 37, 0.75); }

.error-state, .empty-state {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
}
.empty-title { font-size: 15px; font-weight: 600; color: var(--neutral-text-1, #1d2129); margin: 8px 0 4px; }
.empty-hint { font-size: 12px; color: var(--neutral-text-3, #86909c); max-width: 420px; word-break: break-all; }

@media (max-width: 768px) {
  .ctrl-label {
    display: none;
  }
}
</style>
