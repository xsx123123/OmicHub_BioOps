<script setup lang="ts">
/**
 * JBrowseLinkGenerator.vue —— JBrowse 2 直链生成器弹窗
 *
 * 嵌入「数据管理」模块：用户从工作空间选一个文件 → 生成可供【外部】JBrowse 2
 * 直接读取的 URL（经平台 /tracks/ 网关，原生支持 HTTP Range + CORS）。
 *
 * 两态切换：
 *   状态 A（文件选择期）：展示文件列表，类型色块 + 图标区分，hover 高亮
 *   状态 B（链接生成期）：只读 URL 文本框 + 复制按钮（复制成功变绿 2s）+ 索引防呆提示
 *
 * URL 策略：origin + /tracks/ + file.path
 *   - file.path 是相对 /data/cygnusx 的路径（file_service._resolve_abs = storage_root / path）
 *   - nginx /tracks/ alias 到 /data/cygnusx/，配好 Accept-Ranges + CORS（见 pipelines/jbrowse2/README.md）
 *   - 故该 URL 即 JBrowse 2 可流式读取的直链，外部 JBrowse 无需 JWT
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import type { Component } from 'vue'
import { NModal, NIcon, NEmpty, useMessage } from 'naive-ui'
import {
  ArrowBackOutline, CloseOutline, CopyOutline, CheckmarkCircleOutline,
  ChevronForwardOutline, WarningOutline, LayersOutline, DocumentTextOutline,
  StatsChartOutline, DocumentOutline,
} from '@vicons/ionicons5'
import type { DataFile } from '@/types'

const props = defineProps<{
  /** 弹窗显隐（v-model:show） */
  show: boolean
  /** 工作空间文件列表（由父页面传入） */
  files: DataFile[]
}>()
const emit = defineEmits<{ 'update:show': [v: boolean] }>()
const message = useMessage()

// 当前选中文件（null = 状态 A；非 null = 状态 B）
const selectedFile = ref<DataFile | null>(null)
// 复制成功态：true 时按钮变绿显示「已复制！」，2s 后恢复
const copied = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | null = null

// 弹窗打开时重置到状态 A，避免残留上次选择
watch(
  () => props.show,
  (v) => {
    if (v) {
      selectedFile.value = null
      copied.value = false
    }
  },
)

function close() {
  emit('update:show', false)
}
function back() {
  selectedFile.value = null
  copied.value = false
}

// ==================== 文件类型识别（按扩展名，比 file_type 枚举更精确）====================
type BioType = 'bam' | 'cram' | 'vcf' | 'gff3' | 'bigwig' | 'fasta' | 'fastq' | 'other'
function bioType(name: string): BioType {
  const n = name.toLowerCase()
  if (n.endsWith('.bam')) return 'bam'
  if (n.endsWith('.cram')) return 'cram'
  if (n.endsWith('.vcf.gz') || n.endsWith('.vcf')) return 'vcf'
  if (n.endsWith('.gff3.gz') || n.endsWith('.gff3')) return 'gff3'
  if (n.endsWith('.bw') || n.endsWith('.bigwig')) return 'bigwig'
  if (n.endsWith('.fa.gz') || n.endsWith('.fasta.gz') || n.endsWith('.fa') || n.endsWith('.fasta')) return 'fasta'
  if (n.endsWith('.fq.gz') || n.endsWith('.fastq.gz') || n.endsWith('.fastq')) return 'fastq'
  return 'other'
}

/** 类型 → 展示元数据：色块徽标 + 图标，用于区分 BAM / VCF / GFF3 等 */
const TYPE_META: Record<BioType, { label: string; badge: string; icon: Component }> = {
  bam:    { label: 'BAM',    badge: 'bg-green-100 text-green-700',    icon: LayersOutline },
  cram:   { label: 'CRAM',   badge: 'bg-emerald-100 text-emerald-700', icon: LayersOutline },
  vcf:    { label: 'VCF',    badge: 'bg-orange-100 text-orange-700',  icon: DocumentTextOutline },
  gff3:   { label: 'GFF3',   badge: 'bg-purple-100 text-purple-700',  icon: DocumentTextOutline },
  bigwig: { label: 'BigWig', badge: 'bg-blue-100 text-blue-700',      icon: StatsChartOutline },
  fasta:  { label: 'FASTA',  badge: 'bg-gray-100 text-gray-700',      icon: DocumentOutline },
  fastq:  { label: 'FASTQ',  badge: 'bg-cyan-100 text-cyan-700',      icon: DocumentOutline },
  other:  { label: 'FILE',   badge: 'bg-gray-100 text-gray-700',      icon: DocumentOutline },
}
function metaOf(f: DataFile) {
  return TYPE_META[bioType(f.original_name)]
}

// ==================== 直链生成（核心）====================
const trackUrl = computed(() => {
  if (!selectedFile.value) return ''
  // file.path 相对 /data/cygnusx；nginx /tracks/ alias 到 /data/cygnusx/ → 直接拼
  return `${window.location.origin}/tracks/${selectedFile.value.path}`
})

// ==================== 智能防呆：大容量/压缩格式需配套索引 ====================
const needsIndex = computed(() => {
  const f = selectedFile.value
  if (!f) return false
  const n = f.original_name.toLowerCase()
  // .bam 需 .bai；.vcf.gz / .gff3.gz 需 .tbi
  return n.endsWith('.bam') || n.endsWith('.vcf.gz') || n.endsWith('.gff3.gz')
})

// ==================== 剪贴板复制（成功变绿 2s）====================
async function copyUrl() {
  if (!trackUrl.value) return
  try {
    await navigator.clipboard.writeText(trackUrl.value)
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (e) {
    console.error('[JBrowseLinkGenerator] 复制失败:', e)
    message.error('复制失败，请手动选中文本框内容复制')
  }
}

onUnmounted(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <NModal
    :show="show"
    :mask-closable="true"
    :auto-focus="false"
    @update:show="emit('update:show', $event)"
  >
    <div class="w-full max-w-2xl mx-4 bg-neutral-card rounded-xl shadow-xl overflow-hidden">
      <!-- 头部 -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-neutral-border">
        <div class="flex items-center gap-2">
          <button
            v-if="selectedFile"
            class="text-text-tertiary hover:text-text-secondary transition-colors"
            title="返回文件选择"
            @click="back"
          >
            <NIcon :size="18"><ArrowBackOutline /></NIcon>
          </button>
          <h3 class="text-base font-semibold text-text-primary">JBrowse 直链生成器</h3>
        </div>
        <button
          class="text-text-tertiary hover:text-text-secondary transition-colors"
          @click="close"
        >
          <NIcon :size="20"><CloseOutline /></NIcon>
        </button>
      </div>

      <!-- 状态 A：文件选择期 -->
      <div v-if="!selectedFile" class="p-6">
        <p class="text-sm text-text-secondary mb-4">选择一个文件，生成可供 JBrowse 2 直接读取的直链</p>
        <div v-if="files.length === 0" class="py-12">
          <NEmpty description="当前目录暂无文件" />
        </div>
        <ul v-else class="max-h-96 overflow-y-auto divide-y divide-neutral-border">
          <li
            v-for="f in files"
            :key="f.id"
            class="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer hover:bg-primary-light transition-colors group"
            @click="selectedFile = f"
          >
            <span
              class="inline-flex items-center justify-center w-9 h-9 rounded-lg flex-shrink-0"
              :class="metaOf(f).badge"
            >
              <NIcon :size="18"><component :is="metaOf(f).icon" /></NIcon>
            </span>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-text-primary truncate">{{ f.original_name }}</p>
              <p class="text-xs text-text-tertiary truncate">{{ f.path }}</p>
            </div>
            <span
              class="text-xs px-2 py-0.5 rounded-md font-medium flex-shrink-0"
              :class="metaOf(f).badge"
            >{{ metaOf(f).label }}</span>
            <NIcon :size="16" class="text-text-disabled group-hover:text-primary flex-shrink-0">
              <ChevronForwardOutline />
            </NIcon>
          </li>
        </ul>
      </div>

      <!-- 状态 B：链接生成期 -->
      <div v-else class="p-6">
        <!-- 选中文件摘要 -->
        <div class="flex items-center gap-3 p-3 bg-neutral-bg rounded-lg mb-4">
          <span
            class="inline-flex items-center justify-center w-9 h-9 rounded-lg flex-shrink-0"
            :class="metaOf(selectedFile).badge"
          >
            <NIcon :size="18"><component :is="metaOf(selectedFile).icon" /></NIcon>
          </span>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-text-primary truncate">{{ selectedFile.original_name }}</p>
            <p class="text-xs text-text-tertiary truncate">{{ selectedFile.path }}</p>
          </div>
          <span
            class="text-xs px-2 py-0.5 rounded-md font-medium flex-shrink-0"
            :class="metaOf(selectedFile).badge"
          >{{ metaOf(selectedFile).label }}</span>
        </div>

        <!-- 只读直链文本框 + 复制按钮 -->
        <label class="block text-xs font-medium text-text-secondary mb-1.5">JBrowse 2 直链（URL）</label>
        <div class="flex gap-2">
          <input
            :value="trackUrl"
            readonly
            class="flex-1 min-w-0 px-3 py-2 bg-neutral-bg border border-neutral-border rounded-lg text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-primary-light"
            @focus="($event.target as HTMLInputElement).select()"
          />
          <button
            class="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-sm font-medium transition-colors whitespace-nowrap"
            :class="copied ? 'bg-green-500' : 'bg-blue-600 hover:bg-blue-700'"
            @click="copyUrl"
          >
            <NIcon :size="16"><component :is="copied ? CheckmarkCircleOutline : CopyOutline" /></NIcon>
            {{ copied ? '已复制！' : '复制链接' }}
          </button>
        </div>

        <!-- 智能防呆：索引文件提示 -->
        <div
          v-if="needsIndex"
          class="mt-4 flex gap-2 items-start p-3 bg-yellow-50 text-yellow-700 rounded-lg border border-yellow-200"
        >
          <NIcon :size="18" class="flex-shrink-0 mt-0.5"><WarningOutline /></NIcon>
          <p class="text-sm leading-relaxed">
            ⚠️ 提示：您选择的是大容量或压缩格式文件。在 JBrowse 2 中添加该主文件链接后，系统会要求您提供对应的索引文件（如 .bai 或 .tbi）链接。请确保云端同目录下已生成对应的索引。
          </p>
        </div>

        <!-- 使用说明 -->
        <div class="mt-4 p-3 bg-primary-light rounded-lg">
          <p class="text-xs text-primary leading-relaxed">
            <strong>用法：</strong>复制此链接 → 打开 JBrowse 2 → Add track → URL → 粘贴。该直链经平台 /tracks/ 网关输出，原生支持 HTTP Range（分段读取）与跨域，JBrowse 2 可流式读取大文件，无需整包下载。
          </p>
        </div>
      </div>
    </div>
  </NModal>
</template>
