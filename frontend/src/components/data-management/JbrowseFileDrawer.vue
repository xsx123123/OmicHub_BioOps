<script setup lang="ts">
/**
 * JbrowseFileDrawer.vue —— JBrowse「我的文件」抽屉
 *
 * 自包含：扫描用户目录 → 搜索过滤（防抖）→ 勾选 → 加载。
 * 选择状态由父级 selectedTracks 作为单一数据源，本组件通过 toggle 事件通知父级增删，
 * 自身不持有选中态，避免与父级（上传/URL 恢复/移除轨道）脱节。
 */
import { computed, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import {
  NDrawer, NDrawerContent, NCheckbox, NButton, NIcon, NSpin, NEmpty, NTag, useMessage,
} from 'naive-ui'
import { RefreshOutline, SearchOutline, FolderOpenOutline } from '@vicons/ionicons5'
import { jbrowseApi } from '@/api/jbrowse'
import type { ScannedFileDTO } from '@/types/jbrowse'

const props = defineProps<{
  /** 抽屉显隐（v-model:show） */
  show: boolean
  /** 父级已选轨道路径（selectedTracks.map(t => t.path)），用于回显勾选态与计数 */
  selectedPaths: string[]
  /**
   * NDrawer teleport 目标（透传 naive-ui `to`）。
   * 全屏模式下 fullscreen 元素之外的节点不可见，父级需传入页面根元素让抽屉渲染在其内部；
   * 不传则保持默认（teleport 到 body）。
   */
  to?: string | HTMLElement | null
}>()
const emit = defineEmits<{
  'update:show': [v: boolean]
  /** 切换某文件选中态；父级据此增删 selectedTracks */
  toggle: [file: ScannedFileDTO, selected: boolean]
  /** 加载已选文件；父级调用 loadBrowser */
  load: []
}>()
const message = useMessage()

// ==================== 扫描 ====================
const scannedFiles = ref<ScannedFileDTO[]>([])
const scanLoading = ref(false)

// ==================== 搜索（防抖 250ms）====================
const searchQuery = ref('')
const debouncedQuery = ref('')
const applyDebounced = useDebounceFn((v: string) => {
  debouncedQuery.value = v
}, 250)
watch(searchQuery, (v) => applyDebounced(v))

// ==================== 派生态 ====================
// 已选集合（由 props 派生，回显勾选 + 行高亮）
const selectedSet = computed(() => new Set(props.selectedPaths))

// 按防抖后的关键词过滤文件名
const filteredFiles = computed(() => {
  const q = debouncedQuery.value.trim().toLowerCase()
  if (!q) return scannedFiles.value
  return scannedFiles.value.filter((f) => f.name.toLowerCase().includes(q))
})

// ==================== 生命周期 ====================
// 抽屉打开时自动扫描并清空搜索
watch(
  () => props.show,
  (v) => {
    if (v) {
      searchQuery.value = ''
      debouncedQuery.value = ''
      refreshScan()
    }
  },
)

// ==================== 动作 ====================
async function refreshScan() {
  scanLoading.value = true
  try {
    const data = await jbrowseApi.scan()
    scannedFiles.value = data.files || []
  } catch {
    message.error('扫描文件失败')
  } finally {
    scanLoading.value = false
  }
}

function onToggle(file: ScannedFileDTO, selected: boolean) {
  emit('toggle', file, selected)
}

/** 选中所有已索引且尚未选中的文件 */
function selectAllIndexed() {
  for (const f of scannedFiles.value) {
    if (f.indexed && !selectedSet.value.has(f.path)) {
      emit('toggle', f, true)
    }
  }
}

async function createIndex(file: ScannedFileDTO) {
  try {
    const res = await jbrowseApi.createIndex(file.path)
    message.success(`索引任务已提交: ${res.task_id.slice(0, 8)}…`)
    // 索引由 Celery 异步执行；提交后刷新一次让状态尽早更新
    refreshScan()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '索引提交失败')
  }
}

function onLoad() {
  emit('load')
  emit('update:show', false)
}

/** 时间戳格式化：2026-07-03T12:21:04.240234 → 2026-07-03 12:21（截掉冗长微秒） */
function formatDate(iso: string): string {
  if (!iso) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso
}
</script>

<template>
  <NDrawer :show="show" :width="480" :to="to || undefined" @update:show="emit('update:show', $event)">
    <NDrawerContent title="我的文件" closable :body-content-style="{ padding: '20px' }">
      <NSpin :show="scanLoading">
        <!-- 顶部操作栏：刷新 + 选中所有已索引 -->
        <div class="flex items-center justify-between mb-3">
          <NButton size="small" type="primary" tertiary @click="refreshScan">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
            刷新
          </NButton>
          <NButton
            size="small"
            quaternary
            :disabled="scannedFiles.length === 0"
            @click="selectAllIndexed"
          >
            选中所有已索引
          </NButton>
        </div>

        <!-- 搜索框：放大镜前缀 + 防抖过滤，整行宽度 -->
        <div class="relative mb-4">
          <NIcon
            :size="16"
            class="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary pointer-events-none"
          >
            <SearchOutline />
          </NIcon>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索文件名..."
            class="w-full pl-9 pr-3 py-2 text-sm bg-neutral-bg border border-neutral-border rounded-lg text-text-primary placeholder-text-tertiary focus:outline-none focus:ring-2 focus:ring-primary-light focus:border-primary transition"
          />
        </div>

        <!-- 空状态：无可加载文件（区分于「搜索无结果」）-->
        <div v-if="scannedFiles.length === 0 && !scanLoading" class="py-10">
          <NEmpty>
            <template #icon>
              <NIcon :size="48" class="text-text-disabled"><FolderOpenOutline /></NIcon>
            </template>
            <div class="text-center max-w-xs mx-auto px-2">
              <p class="text-sm font-medium text-text-primary mb-2">未找到可加载的轨道文件</p>
              <p class="text-xs text-text-secondary leading-relaxed">
                JBrowse 仅支持已比对 / 注释的格式：<strong>BAM · CRAM · BigWig · VCF.gz · bed.gz · gff3.gz</strong>。
                若你目录下只有 FASTQ / SRA 原始测序数据，需先运行分析流程生成 BAM，或直接上传轨道文件。
              </p>
            </div>
          </NEmpty>
        </div>

        <!-- 搜索无结果 -->
        <div v-else-if="filteredFiles.length === 0" class="py-10">
          <NEmpty description="未找到匹配的文件" />
        </div>

        <!-- 文件列表：每项独立卡片，hover 高亮，选中行蓝色高亮 -->
        <div v-else class="flex flex-col gap-2.5">
          <div
            v-for="file in filteredFiles"
            :key="file.path"
            class="flex items-center gap-3 p-3 rounded-xl border transition-colors"
            :class="
              selectedSet.has(file.path)
                ? 'bg-primary-light/60 border-primary-light cursor-pointer'
                : file.can_load
                  ? 'border-neutral-border hover:bg-neutral-hover hover:border-neutral-border cursor-pointer'
                  : 'border-neutral-border cursor-not-allowed'
            "
            @click="file.can_load && onToggle(file, !selectedSet.has(file.path))"
          >
            <!-- 勾选框：包一层 @click.stop，避免与行点击重复触发 -->
            <span @click.stop>
              <NCheckbox
                :checked="selectedSet.has(file.path)"
                :disabled="!file.can_load"
                @update:checked="(v: boolean) => onToggle(file, v)"
              />
            </span>

            <!-- 文件信息：主标题加深加粗，次级信息小字灰色 -->
            <div class="flex-1 min-w-0">
              <p
                class="text-sm font-medium truncate"
                :class="file.can_load ? 'text-text-primary' : 'text-text-tertiary'"
              >
                {{ file.name }}
              </p>
              <div class="flex items-center gap-2 mt-1">
                <span class="text-xs px-1.5 py-0.5 rounded-md bg-neutral-hover text-text-secondary font-medium">
                  {{ file.type }}
                </span>
                <span class="text-xs text-text-secondary">{{ file.size_human }}</span>
                <span class="text-xs text-text-disabled">·</span>
                <span class="text-xs text-text-secondary">{{ formatDate(file.modified) }}</span>
              </div>
            </div>

            <!-- 索引状态 / 创建索引（次级主色按钮，small）-->
            <div class="flex-shrink-0">
              <NTag v-if="file.indexed" size="small" type="success" :bordered="false" round>已索引</NTag>
              <NButton
                v-else
                size="small"
                type="primary"
                tertiary
                @click.stop="createIndex(file)"
              >
                创建索引
              </NButton>
            </div>
          </div>
        </div>
      </NSpin>

      <template #footer>
        <div class="flex items-center justify-between w-full">
          <span class="text-xs text-text-secondary">已选 {{ selectedPaths.length }} 个文件</span>
          <NButton type="primary" :disabled="selectedPaths.length === 0" @click="onLoad">
            加载选中文件
          </NButton>
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>
