<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NIcon, NSelect, NInput, NTag, NSpace, NSpin, NEmpty,
  NModal, NUpload, NUploadDragger, NCheckbox, NProgress,
  NDivider, NForm, NFormItem, NTooltip, useMessage } from 'naive-ui'
import {
  LocationOutline, CloudUploadOutline,
  FolderOpenOutline, DesktopOutline,
  ExpandOutline, ContractOutline,
} from '@vicons/ionicons5'
import { jbrowseApi } from '@/api/jbrowse'
import { absolutizeUris } from '@/utils/jbrowse'
import JbrowseFileDrawer from '@/components/data-management/JbrowseFileDrawer.vue'
import PageHeader from '@/components/PageHeader.vue'
import type { AssemblyDTO, ScannedFileDTO, SelectedTrack } from '@/types/jbrowse'

const route = useRoute()
const router = useRouter()
const message = useMessage()

// ==================== 状态 ====================
const assemblies = ref<AssemblyDTO[]>([])
const assembliesLoading = ref(false)
const selectedAssembly = ref<string>('')
const regionInput = ref('')
const jbrowseUrl = ref('')
const selectedTracks = ref<SelectedTrack[]>([])
let currentBlobUrl = ''

// 初始化 loading + 超时兜底
const loading = ref(false)
const loadingText = ref('正在初始化基因组浏览器...')
let initTimer: ReturnType<typeof setTimeout> | null = null
// iframe 强制刷新 key：每次生成新配置时自增，确保 iframe 元素重建，
// 避免 JBrowse 2 复用 localStorage 旧 session 导致只显示 Logo
const iframeKey = ref(0)
let iframeLoadTimer: ReturnType<typeof setTimeout> | null = null
let uploadCloseTimer: ReturnType<typeof setTimeout> | null = null

// 上传
const showUploadModal = ref(false)
const uploadFileList = ref<any[]>([])
const uploadForm = ref({ assemblyId: '' as string, autoIndex: true })
interface UploadProgress { filename: string; status: 'uploading' | 'success' | 'error'; statusText: string; percent: number; message: string }
const uploadProgress = ref<UploadProgress[]>([])

// 我的文件抽屉
const showScanDrawer = ref(false)

// ==================== 全屏沉浸模式 ====================
// 优先 Fullscreen API（把页面根元素置入 top layer，平台页头 / 侧边导航自然被隔离在外），
// Esc 由浏览器原生退出；API 不可用（旧 Safari / 非手势触发被拒）时退回 fixed 定位兜底，
// 兜底态下自行监听 Esc。两条路径统一由 immersiveActive 驱动图标与提示文案。
const pageRootRef = ref<HTMLElement | null>(null)
const isFullscreen = ref(false)
const immersiveFallback = ref(false)
const immersiveActive = computed(() => isFullscreen.value || immersiveFallback.value)

function onFullscreenChange() {
  isFullscreen.value = document.fullscreenElement === pageRootRef.value
}

async function toggleFullscreen() {
  // 兜底态：再次点击即退出
  if (immersiveFallback.value) {
    immersiveFallback.value = false
    return
  }
  if (document.fullscreenElement) {
    try { await document.exitFullscreen() } catch { /* 已被浏览器退出，忽略 */ }
    return
  }
  const el = pageRootRef.value
  if (el?.requestFullscreen) {
    try {
      await el.requestFullscreen()
      return
    } catch { /* 请求被拒（如权限策略），落入 fixed 兜底 */ }
  }
  immersiveFallback.value = true
}

/** 兜底态监听 Esc 退出（Fullscreen API 路径由浏览器原生处理 Esc） */
function onImmersiveKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && immersiveFallback.value) immersiveFallback.value = false
}

// ==================== 计算属性 ====================
const assemblyOptions = computed(() =>
  assemblies.value.map((a) => ({
    label: a.name,
    value: a.id,
    species: a.species,
  })),
)

function renderAssemblyLabel(option: { label: string; species?: string }) {
  return h('div', { class: 'assembly-option' }, [
    h('span', { class: 'assembly-name' }, option.label),
    option.species ? h('span', { class: 'assembly-species' }, option.species) : null,
  ])
}

// 已选轨道路径（传给抽屉回显勾选态）
const selectedPaths = computed(() => selectedTracks.value.map((t) => t.path))

// ==================== 生命周期 ====================
onMounted(async () => {
  document.addEventListener('fullscreenchange', onFullscreenChange)
  window.addEventListener('keydown', onImmersiveKeydown)
  await loadAssemblies()

  // 从 URL 参数恢复状态（方便从「数据管理」模块深链跳转）
  const { assembly, tracks, region, autoLoad } = route.query
  if (typeof assembly === 'string' && assembly) selectedAssembly.value = assembly
  if (typeof region === 'string') regionInput.value = region
  if (typeof autoLoad === 'string' && autoLoad) {
    selectedTracks.value.push({
      path: autoLoad,
      name: autoLoad.split('/').pop() || autoLoad,
      indexed: true,
    })
  } else if (tracks) {
    const arr = Array.isArray(tracks) ? tracks : [tracks]
    const trackPaths = arr.filter((p): p is string => typeof p === 'string')
    selectedTracks.value = trackPaths.map((p) => ({
      path: p,
      name: p.split('/').pop() || p,
      indexed: true,
    }))
  }

  // 自动初始化：无需用户点击「加载浏览器」
  if (selectedAssembly.value) {
    await loadBrowser()
  } else {
    message.warning('未找到可用的参考基因组，请先在管理端配置')
  }
})

onUnmounted(() => {
  revokeBlobUrl()
  if (initTimer) clearTimeout(initTimer)
  if (iframeLoadTimer) clearTimeout(iframeLoadTimer)
  if (uploadCloseTimer) clearTimeout(uploadCloseTimer)
  if (centeringTimer) clearTimeout(centeringTimer)
  welcomeObserver?.disconnect()
  welcomeObserver = null
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  window.removeEventListener('keydown', onImmersiveKeydown)
  // 离开页面时若仍处于原生全屏，主动退出，避免残留黑屏
  if (document.fullscreenElement === pageRootRef.value) {
    document.exitFullscreen().catch(() => {})
  }
})

function revokeBlobUrl() {
  if (currentBlobUrl) {
    URL.revokeObjectURL(currentBlobUrl)
    currentBlobUrl = ''
  }
}

// ==================== API 调用 ====================
async function loadAssemblies() {
  assembliesLoading.value = true
  try {
    const data = await jbrowseApi.listAssemblies()
    assemblies.value = data.assemblies || []
    // 默认选第一个有 .fai 索引的
    if (!selectedAssembly.value) {
      const available = assemblies.value.find((a) => a.fai_exists) || assemblies.value[0]
      if (available) selectedAssembly.value = available.id
    }
  } catch {
    message.error('加载参考基因组失败')
  } finally {
    assembliesLoading.value = false
  }
}

/**
 * 生成 JBrowse 2 配置并以 iframe 加载。
 * - 坐标格式校验 → 配置生成（写 blob URL 绕过 JWT）→ iframe 重建（key 自增）
 * - loading 覆盖层：iframe @load 后隐藏；10s 超时兜底提示
 */
async function loadBrowser() {
  if (!selectedAssembly.value) {
    message.warning('请先选择参考基因组')
    return
  }
  // 坐标格式校验（用户已输入时）
  if (regionInput.value && !validateRegion(regionInput.value)) {
    message.error('坐标格式错误，请使用 chr:start-end 格式')
    return
  }

  loading.value = true
  loadingText.value = '正在初始化基因组浏览器...'
  if (initTimer) clearTimeout(initTimer)
  // 超时兜底：iframe 10s 未完成加载则判定初始化失败
  initTimer = setTimeout(() => {
    if (loading.value) {
      loading.value = false
      message.error('初始化失败：参考基因组文件可能缺失或格式错误')
      console.error(
        '[JBrowse] 初始化超时(10s)。可能原因：参考基因组 FASTA/.fai 缺失、' +
          '/tracks/ 不可达、或 /jbrowse2/ 静态资源未正确挂载',
      )
    }
  }, 10000)

  try {
    const config = await jbrowseApi.generateConfig({
      assembly: selectedAssembly.value,
      tracks: selectedTracks.value.map((t) => t.path),
      region: regionInput.value || undefined,
    })
    // ⚠️ 关键：后端返回的 uri 是相对路径（/tracks/...），而 blob URL 是 opaque base，
    // JBrowse 用 new URL(uri, blobBase) 解析会抛 Invalid URL → 参考序列加载失败、只显示 Logo。
    // 写入 blob 前把所有 uri 补成绝对 URL（带 origin），绕开 opaque base 限制。
    absolutizeUris(config)
    // 写入 blob URL 交给 iframe：JBrowse 2 fetch blob 不需要 JWT，
    // 轨道数据经 nginx /tracks/ 流式读取
    revokeBlobUrl()
    const blob = new Blob([JSON.stringify(config)], { type: 'application/json' })
    currentBlobUrl = URL.createObjectURL(blob)
    // 追加 &loc= 让 JBrowse 2 web 在引导时直接定位到目标区域，
    // 配合 defaultSession 双保险，避免只渲染 Logo
    const loc = regionInput.value || ''
    jbrowseUrl.value =
      `/jbrowse2/?config=${encodeURIComponent(currentBlobUrl)}` +
      (loc ? `&loc=${encodeURIComponent(loc)}` : '')
    // 强制 iframe 重建，丢弃 JBrowse localStorage 中的旧 session
    iframeKey.value++

    // 更新 URL，方便分享 / 刷新恢复
    router.replace({
      query: {
        ...route.query,
        assembly: selectedAssembly.value,
        tracks: selectedTracks.value.map((t) => t.path),
        region: regionInput.value || undefined,
      },
    })
  } catch (e: any) {
    loading.value = false
    if (initTimer) {
      clearTimeout(initTimer)
      initTimer = null
    }
    message.error(e?.response?.data?.detail || '生成浏览器配置失败')
    console.error('[JBrowse] 配置生成失败:', e)
  }
}

/** iframe HTML 加载完成（JBrowse app 开始引导）→ 隐藏 loading + 适配欢迎屏 */
function onIframeLoad(event: Event) {
  setupWelcomeCentering(event.target as HTMLIFrameElement)
  // 留一帧让 JBindView 完成首屏渲染，避免 loading 闪烁与 Logo 残影叠加
  if (iframeLoadTimer) clearTimeout(iframeLoadTimer)
  iframeLoadTimer = setTimeout(() => {
    loading.value = false
    if (initTimer) {
      clearTimeout(initTimer)
      initTimer = null
    }
  }, 300)
}

// ==================== 欢迎屏垂直居中（同源 iframe 纯展示层注入） ====================
// JBrowse 2 无会话时的欢迎界面（Start a new session / Recent sessions）是一个顶部对齐的
// MUI Container，查看区撑满后会出现"上半截内容、下半截大段空白"的割裂感。
// iframe 与主站同源（nginx 同域挂载 /jbrowse2/），这里仅注入展示层样式：
// 祖先链补全高度 + flex 居中该 Container。不触碰配置生成 / blob URL / 轨道数据等集成逻辑。
let welcomeObserver: MutationObserver | null = null
let centeringTimer: ReturnType<typeof setTimeout> | null = null

function applyWelcomeCentering(doc: Document) {
  // 按文案识别欢迎屏 Container，避免误伤会话视图；id 标记做幂等快路径
  const marked = doc.getElementById('cygnusx-welcome-center')
  if (marked) return
  const container = Array.from(doc.querySelectorAll<HTMLElement>('.MuiContainer-root'))
    .find((el) => el.textContent?.includes('Start a new session'))
  if (!container) return
  const parent = container.parentElement
  if (!parent) return
  container.id = 'cygnusx-welcome-center'
  // 祖先链逐层补 100% 高度（已有内联高度的节点不动），让 flex 居中生效
  let node: HTMLElement | null = parent
  while (node) {
    if (!node.style.height) node.style.height = '100%'
    node = node.parentElement
  }
  parent.style.display = 'flex'
  parent.style.flexDirection = 'column'
  // 设置按钮原为 float:right；flex 上下文 float 失效，固定到右上角保持原视觉位置
  const settings = parent.querySelector<HTMLElement>(':scope > button')
  if (settings) {
    parent.style.position = 'relative'
    settings.style.position = 'absolute'
    settings.style.top = '4px'
    settings.style.right = '4px'
  }
  // flex 纵列中 margin auto 吸收剩余空间 → 垂直居中；内容超高时退化为顶部对齐
  container.style.marginTop = 'auto'
  container.style.marginBottom = 'auto'
}

/** 建立观察：欢迎屏可能在用户关闭会话后重新挂载（React 新建节点，标记丢失），故节流重跑 */
function setupWelcomeCentering(iframe: HTMLIFrameElement) {
  try {
    const doc = iframe.contentDocument
    if (!doc?.body) return
    applyWelcomeCentering(doc)
    welcomeObserver?.disconnect()
    welcomeObserver = new MutationObserver(() => {
      if (centeringTimer) return
      centeringTimer = setTimeout(() => {
        centeringTimer = null
        try { applyWelcomeCentering(doc) } catch { /* iframe 文档已销毁 */ }
      }, 200)
    })
    welcomeObserver.observe(doc.body, { childList: true, subtree: true })
  } catch { /* 跨域或文档未就绪，静默忽略 */ }
}

function onAssemblyChange() {
  // 切换参考基因组：清空已选轨道与坐标，自动重新加载
  selectedTracks.value = []
  regionInput.value = ''
  loadBrowser()
}

function jumpToRegion() {
  regionInput.value = formatRegion(regionInput.value)
  loadBrowser()
}

function formatRegion(value: string): string {
  const match = value.trim().match(/^([A-Za-z0-9_.]+)\s*:\s*([\d,]+)\s*-\s*([\d,]+)$/)
  if (!match) return value
  const formatNumber = (part: string) => Number(part.replace(/,/g, '')).toLocaleString('en-US')
  return `${match[1]}:${formatNumber(match[2])}-${formatNumber(match[3])}`
}

/** 校验 chr:start-end（支持逗号千分位与空白） */
function validateRegion(s: string): boolean {
  const norm = s.replace(/\s/g, '').replace(/,/g, '')
  return /^[A-Za-z0-9_.]+:\d+-\d+$/.test(norm)
}

// ==================== 轨道管理 ====================
function removeTrack(track: SelectedTrack) {
  const idx = selectedTracks.value.findIndex((t) => t.path === track.path)
  if (idx > -1) {
    selectedTracks.value.splice(idx, 1)
    if (jbrowseUrl.value) loadBrowser()
  }
}

// ==================== 上传 ====================
async function handleUpload() {
  if (uploadFileList.value.length === 0) {
    message.warning('请选择要上传的文件')
    return
  }
  uploadProgress.value = uploadFileList.value.map((f) => ({
    filename: f.name,
    status: 'uploading',
    statusText: '上传中',
    percent: 0,
    message: '',
  }))

  for (let i = 0; i < uploadFileList.value.length; i++) {
    const item = uploadFileList.value[i]
    const prog = uploadProgress.value[i]
    const rawFile = item.file as File
    if (!rawFile) {
      prog.status = 'error'
      prog.statusText = '失败'
      prog.message = '无法读取文件'
      continue
    }
    try {
      const res = await jbrowseApi.upload(
        rawFile,
        { assemblyId: uploadForm.value.assemblyId, autoIndex: uploadForm.value.autoIndex },
        (p) => { prog.percent = p },
      )
      prog.status = 'success'
      prog.statusText = '上传成功'
      prog.percent = 100
      prog.message = res.index_task_id ? '索引任务已排队' : ''
      // 自动加入已选轨道
      if (!selectedTracks.value.some((t) => t.path === res.saved_path)) {
        selectedTracks.value.push({ path: res.saved_path, name: res.filename, indexed: true })
      }
    } catch (e: any) {
      prog.status = 'error'
      prog.statusText = '上传失败'
      prog.message = e?.response?.data?.detail || e.message || '未知错误'
    }
  }

  if (uploadCloseTimer) clearTimeout(uploadCloseTimer)
  uploadCloseTimer = setTimeout(() => {
    showUploadModal.value = false
    resetUpload()
  }, 1500)
}

function resetUpload() {
  uploadFileList.value = []
  uploadForm.value = { assemblyId: '', autoIndex: true }
  uploadProgress.value = []
}

// ==================== 我的文件抽屉事件 ====================
/** 抽屉切换文件选中态：增删 selectedTracks（单一数据源在父级） */
function onDrawerToggle(file: ScannedFileDTO, selected: boolean) {
  if (selected) {
    if (!selectedTracks.value.some((t) => t.path === file.path)) {
      selectedTracks.value.push({ path: file.path, name: file.name, indexed: file.indexed })
    }
  } else {
    const idx = selectedTracks.value.findIndex((t) => t.path === file.path)
    if (idx > -1) selectedTracks.value.splice(idx, 1)
  }
}

/** 抽屉「加载选中文件」：触发浏览器重新渲染（抽屉自行关闭） */
function onDrawerLoad() {
  loadBrowser()
}
</script>

<template>
  <div
    ref="pageRootRef"
    class="jbrowse-page"
    :class="{ 'jbrowse-page--immersive': immersiveFallback }"
    role="main"
    aria-label="Web 基因组浏览器"
  >
    <PageHeader
      compact
      title="Web 基因组浏览器"
      subtitle="基于 JBrowse 2 · 支持 BAM / BigWig / VCF / GFF3 流式浏览"
      back-to="/tools"
      back-label="返回工具箱"
    />

    <section class="browser-toolbar" aria-label="基因组浏览器工具栏">
      <div class="toolbar-primary">
        <span class="ctrl-label">参考基因组</span>
        <NSelect
          v-model:value="selectedAssembly"
          :options="assemblyOptions"
          :loading="assembliesLoading"
          placeholder="选择参考基因组"
          size="small"
          :render-label="renderAssemblyLabel"
          class="assembly-select"
          @update:value="onAssemblyChange"
        />
        <NInput
          v-model:value="regionInput"
          placeholder="chr1:1,000,000-2,000,000"
          size="small"
          class="region-input"
          @blur="regionInput = formatRegion(regionInput)"
          @keyup.enter="jumpToRegion"
        />
        <NButton class="jump-button" size="small" type="primary" @click="jumpToRegion">
          <template #icon><NIcon><LocationOutline /></NIcon></template>
          跳转
        </NButton>
      </div>
      <div class="toolbar-actions">
        <NButton class="outline-button" size="small" @click="showUploadModal = true">
          <template #icon><NIcon><CloudUploadOutline /></NIcon></template>
          上传文件
        </NButton>
        <NButton class="outline-button" size="small" @click="showScanDrawer = true">
          <template #icon><NIcon><FolderOpenOutline /></NIcon></template>
          我的文件
        </NButton>
        <NTooltip placement="bottom" :delay="300">
          <template #trigger>
            <NButton
              class="outline-button fullscreen-toggle"
              size="small"
              :aria-label="immersiveActive ? '退出全屏' : '全屏沉浸模式'"
              @click="toggleFullscreen"
            >
              <template #icon>
                <NIcon><ContractOutline v-if="immersiveActive" /><ExpandOutline v-else /></NIcon>
              </template>
            </NButton>
          </template>
          {{ immersiveActive ? '退出全屏（Esc）' : '全屏沉浸模式' }}
        </NTooltip>
      </div>
    </section>

    <!-- 已选轨道 -->
    <div v-if="selectedTracks.length > 0" class="track-bar">
      <span class="track-label">已选轨道：</span>
      <NSpace :size="6" wrap>
        <NTag
          v-for="track in selectedTracks"
          :key="track.path"
          closable
          type="info"
          size="small"
          @close="removeTrack(track)"
        >
          {{ track.name }}
          <template v-if="!track.indexed" #avatar>
            <span style="color: #d03050">待索引</span>
          </template>
        </NTag>
      </NSpace>
    </div>

    <!-- JBrowse 2 渲染区（flex:1 铺满剩余高度，iframe 100% 继承） -->
    <div class="browser-view">
      <div v-if="loading" class="loading-mask">
        <NSpin size="large" />
        <p class="loading-text">{{ loadingText }}</p>
      </div>
      <iframe
        v-if="jbrowseUrl"
        :key="iframeKey"
        :src="jbrowseUrl"
        frameborder="0"
        class="jbrowse-iframe"
        @load="onIframeLoad($event)"
      />
      <div v-else-if="!loading" class="empty-state">
        <NEmpty>
          <template #icon><NIcon :size="64"><DesktopOutline /></NIcon></template>
          <div class="empty-desc">
            <p class="empty-title">基因组浏览器未加载</p>
            <p class="empty-hint">请选择参考基因组；若持续未加载，请检查 FASTA/.fai 是否完整、/tracks/ 是否可达</p>
          </div>
        </NEmpty>
      </div>
    </div>

    <!-- 上传弹窗 -->
    <!-- to 指向页面根元素：全屏模式下 fullscreen 元素之外的节点不可见，
         弹窗必须渲染在页面子树内才能在沉浸态正常使用 -->
    <NModal
      v-model:show="showUploadModal"
      preset="card"
      title="上传轨道文件"
      style="width: 600px; max-width: 92vw"
      :mask-closable="false"
      :to="pageRootRef || undefined"
    >
      <NForm label-placement="top">
        <NFormItem label="选择文件" required>
          <NUpload
            v-model:file-list="uploadFileList"
            :default-upload="false"
            multiple
            :max="5"
            accept=".bam,.cram,.bw,.bigwig,.vcf,.vcf.gz,.bed,.bed.gz,.gff3,.gff3.gz,.fasta,.fa"
          >
            <NUploadDragger>
              <div class="upload-drag">
                <NIcon :size="36" class="upload-icon"><CloudUploadOutline /></NIcon>
                <p class="upload-title">点击或拖拽文件到此处上传</p>
                <p class="upload-hint">支持 BAM / BigWig / VCF / BED / GFF3 / FASTA，单个文件最大 10GB</p>
              </div>
            </NUploadDragger>
          </NUpload>
        </NFormItem>
        <NFormItem label="关联参考基因组">
          <NSelect
            v-model:value="uploadForm.assemblyId"
            :options="assemblyOptions"
            placeholder="可选：关联参考基因组"
            clearable
          />
        </NFormItem>
        <NFormItem>
          <NCheckbox v-model:checked="uploadForm.autoIndex">上传后自动创建索引（推荐）</NCheckbox>
        </NFormItem>
      </NForm>

      <NDivider v-if="uploadProgress.length > 0" style="margin: 8px 0" />
      <div v-if="uploadProgress.length > 0" class="upload-progress">
        <div v-for="item in uploadProgress" :key="item.filename" class="progress-item">
          <div class="progress-header">
            <span class="progress-name">{{ item.filename }}</span>
            <NTag
              size="small"
              :type="item.status === 'success' ? 'success' : item.status === 'error' ? 'error' : 'info'"
            >
              {{ item.statusText }}
            </NTag>
          </div>
          <NProgress
            v-if="item.status === 'uploading'"
            :percentage="item.percent"
            size="small"
            :show-indicator="false"
          />
          <p v-if="item.message" class="progress-msg">{{ item.message }}</p>
        </div>
      </div>

      <template #footer>
        <NSpace justify="end">
          <NButton @click="showUploadModal = false">取消</NButton>
          <NButton type="primary" :loading="uploadProgress.some((p) => p.status === 'uploading')" @click="handleUpload">
            开始上传
          </NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- 我的文件抽屉（独立组件：扫描 / 搜索 / 勾选 / 加载）-->
    <JbrowseFileDrawer
      v-model:show="showScanDrawer"
      :selected-paths="selectedPaths"
      :to="pageRootRef"
      @toggle="onDrawerToggle"
      @load="onDrawerLoad"
    />
  </div>
</template>

<style scoped>
/* ===== 全高 flex 布局：依赖路由 meta.fullscreen 提供有界高度的 flex 链 =====
   空间分配：查看区 = 100vh - 平台页头(56) - 标题区 - 工具条 - 页面 padding，
   左右仅保留 16px 页面 padding（全宽，不做居中限宽） */
.jbrowse-page {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--neutral-bg);
  box-sizing: border-box;
  padding: 0 16px 12px;
}

/* Fullscreen API 路径：页面根元素进入 top layer，平台页头 / 侧边导航自然不可见。
   UA 会把 fullscreen 元素底色置黑，这里显式声明背景保持平台观感 */
.jbrowse-page:fullscreen {
  background: var(--neutral-bg);
}

/* fixed 兜底路径：Fullscreen API 不可用时以 fixed 覆盖整个视口，
   z-index 高于平台 chrome、低于 naive 弹层（modal/drawer 起始 2000+） */
.jbrowse-page--immersive {
  position: fixed;
  inset: 0;
  z-index: 1500;
  background: var(--neutral-bg);
}

/* ===== 工具条：与页头同层级的紧凑横条（约 48px），去卡片化 ===== */
.browser-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
  box-sizing: border-box;
  min-height: 48px;
  padding: 10px 0;
  border-bottom: 1px solid var(--neutral-border, #e5e6eb);
  background: transparent;
}
.toolbar-primary,
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.toolbar-actions { margin-left: auto; }
.browser-toolbar :deep(.n-button),
.browser-toolbar :deep(.n-base-selection),
.browser-toolbar :deep(.n-input) { height: 28px; border-radius: 8px; }
.assembly-select { width: 240px; min-width: 240px; }
.region-input { width: 220px; min-width: 220px; }
.outline-button { border-color: #d1d5db; color: #374151; background: #fff; }
.outline-button:hover { border-color: #9ca3af; color: #1f2937; }
.assembly-option { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
.assembly-name { color: #111827; font-size: 14px; white-space: nowrap; }
.assembly-species { color: #6b7280; font-size: 12px; font-style: italic; white-space: nowrap; }
.ctrl-label {
  font-size: 13px;
  color: var(--neutral-text-2, #4e5969);
  white-space: nowrap;
}

/* ===== 已选轨道条：与工具条同层级，仅在选中轨道时出现 ===== */
.track-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  background: transparent;
  border-bottom: 1px solid var(--neutral-border, #e5e6eb);
  flex-wrap: wrap;
}
.track-label {
  font-size: 13px;
  color: var(--neutral-text-2, #4e5969);
  white-space: nowrap;
}

/* ===== JBrowse 渲染区：flex:1 铺满剩余高度，iframe 100% 继承 =====
   min-height 480px 兜底：极端矮视口下查看区不被压缩到不可用；
   overflow hidden，滚动完全交给 JBrowse 内部 */
.browser-view {
  flex: 1 1 auto;
  min-height: 480px;
  position: relative;
  overflow: hidden;
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 8px;
}
.jbrowse-iframe {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}
.loading-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.75);
  z-index: 10;
}
.loading-text {
  font-size: 13px;
  color: var(--neutral-text-2, #4e5969);
  margin: 0;
}
:root[data-theme="dark"] .loading-mask {
  background: rgba(21, 26, 37, 0.75);
}
.empty-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  margin: 8px 0 4px;
}
.empty-hint {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  max-width: 360px;
}

/* ===== 上传 ===== */
.upload-drag {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 28px 20px;
}
.upload-icon {
  color: var(--neutral-text-3, #86909c);
  margin-bottom: 8px;
}
.upload-title {
  font-size: 14px;
  color: var(--neutral-text-2, #4e5969);
  margin: 0 0 4px;
}
.upload-hint {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  margin: 0;
}
.upload-progress {
  margin-top: 4px;
}
.progress-item {
  margin-bottom: 12px;
}
.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.progress-name {
  font-size: 13px;
  color: var(--neutral-text-1, #1d2129);
}
.progress-msg {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  margin: 4px 0 0;
}

@media (max-width: 768px) {
  .jbrowse-page { padding: 0 12px 12px; }
  .browser-toolbar { align-items: stretch; flex-direction: column; min-height: 0; }
  .toolbar-primary, .toolbar-actions { width: 100%; flex-wrap: wrap; margin-left: 0; }
  .toolbar-primary { align-items: stretch; }
  .toolbar-primary .ctrl-label { width: 100%; }
  .assembly-select, .region-input { flex: 1 1 100%; width: 100%; min-width: 0; }
  .toolbar-actions :deep(.n-button) { flex: 1 1 0; }
  .browser-view { min-height: 360px; }
  .ctrl-label {
    display: none;
  }
}
</style>
