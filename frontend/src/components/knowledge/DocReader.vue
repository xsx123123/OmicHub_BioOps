<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/preview.css'
import { NAlert } from 'naive-ui'
import { useThemeStore } from '@/stores/theme'
import DocEditors from '@/components/knowledge/DocEditors.vue'
import DocIssues from '@/components/knowledge/DocIssues.vue'
import KnowledgeStardustQuote from '@/components/knowledge/KnowledgeStardustQuote.vue'
import type { KnowledgeDoc } from '@/types/knowledge'

const themeStore = useThemeStore()
const mdTheme = computed<'light' | 'dark'>(() => (themeStore.isDark ? 'dark' : 'light'))

const props = defineProps<{
  doc: KnowledgeDoc
}>()

const emit = defineEmits<{
  refresh: []
}>()

const STATIC_IMAGE_BASE = '/docs-static/knowledge/'
const OPENING_STARDUST_QUOTE = /^>\s*"We are made of star-stuff\.[\s\S]*?\n>\s*——\s*卡尔·萨根（Carl Sagan）\s*\n*/

const hasStardustQuote = computed(
  () => props.doc.id === 'getting-started' && OPENING_STARDUST_QUOTE.test(props.doc.content || ''),
)

/** 把 Markdown/HTML 中的相对图片路径解析为后端静态资源 URL */
const resolvedContent = computed(() => {
  let text = props.doc.content || ''

  // 1) Markdown 图片语法: ![alt](figure/xxx.png "title") / ![alt](./figure/xxx.png)
  text = text.replace(
    /(!\[([^\]]*)\]\()(\.\/|)(figure\/[^)\s]+)(\s*"[^"]*")?(\))/g,
    (_match, prefix, _alt, _dot, relPath, title, suffix) =>
      `${prefix}${STATIC_IMAGE_BASE}${relPath}${title || ''}${suffix}`,
  )

  // 2) HTML <img> 标签: <img src="./figure/xxx.jpg" alt="...">
  text = text.replace(
    /<img\b([^\u003e]*)\bsrc=["'](\.\/|)(figure\/[^"']+)["']([^\u003e]*)\u003e/gi,
    (_match, before, _dot, relPath, after) => {
      const altMatch =
        (after as string).match(/alt=["']([^"']*)["']/) ||
        (before as string).match(/alt=["']([^"']*)["']/)
      const alt = altMatch ? altMatch[1] : ''
      return `![${alt}](${STATIC_IMAGE_BASE}${relPath})`
    },
  )

  if (hasStardustQuote.value) {
    text = text.replace(OPENING_STARDUST_QUOTE, '')
  }

  return text
})

const hasPendingRevision = computed(() => !!props.doc.pendingRevision)

// 预览容器的 id，用于在 DOM 中定位渲染出的标题
const previewId = 'knowledge-md-preview'

interface OutlineHeading {
  level: number
  text: string
}

// 从 Markdown 源码解析大纲（跳过围栏代码块与引用块内的井号行），
// 不依赖 md-editor-v3 的 MdCatalog 内部事件总线，保证目录与正文一一对应。
const headings = computed<OutlineHeading[]>(() => {
  const lines = resolvedContent.value.split('\n')
  const result: OutlineHeading[] = []
  let inFence = false
  for (const raw of lines) {
    const line = raw.trimEnd()
    const fence = line.match(/^\s*(```|~~~)/)
    if (fence) {
      inFence = !inFence
      continue
    }
    if (inFence) continue
    if (/^\s*>/.test(line)) continue
    const m = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/)
    if (!m) continue
    const text = headingText(m[2])
    if (text) result.push({ level: m[1].length, text })
  }
  return result
})

// 去掉标题里的内联标记，使其与预览 DOM 的 textContent 对齐
function headingText(raw: string): string {
  return raw
    .replace(/!\[[^\]]*]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)]\([^)]*\)/g, '$1')
    .replace(/[*_~`]+/g, '')
    .replace(/<[^>]+>/g, '')
    .trim()
}

const activeHeadingIndex = ref(0)
let scrollEl: HTMLElement | null = null

function headingElements(): HTMLElement[] {
  const root = document.getElementById(previewId)
  return root ? Array.from(root.querySelectorAll('h1, h2, h3, h4, h5, h6')) : []
}

function scrollToHeading(idx: number) {
  const el = headingElements()[idx]
  if (el && scrollEl) {
    const top =
      el.getBoundingClientRect().top -
      scrollEl.getBoundingClientRect().top +
      scrollEl.scrollTop -
      16
    scrollEl.scrollTo({ top, behavior: 'smooth' })
  }
}

function updateActiveHeading() {
  if (!scrollEl) return
  const els = headingElements()
  if (!els.length) return
  const base = scrollEl.getBoundingClientRect().top + 24
  let active = 0
  for (let i = 0; i < els.length; i++) {
    if (els[i].getBoundingClientRect().top - base <= 0) active = i
    else break
  }
  activeHeadingIndex.value = active
}

function onOutlineScroll() {
  updateActiveHeading()
}

// 文档切换 / 内容变化后，预览重渲染完成再校准活动项
watch(
  () => props.doc.id,
  () => {
    activeHeadingIndex.value = 0
    nextTick(updateActiveHeading)
  },
)

onMounted(() => {
  const previewEl = document.getElementById(previewId)
  scrollEl = (previewEl?.closest('.content-body') as HTMLElement | null) || null
  if (scrollEl) scrollEl.addEventListener('scroll', onOutlineScroll, { passive: true })
  nextTick(updateActiveHeading)
})

onBeforeUnmount(() => {
  if (scrollEl) scrollEl.removeEventListener('scroll', onOutlineScroll)
})
</script>

<template>
  <div class="reader-layout">
    <div class="reader-preview" :id="previewId">
      <NAlert
        v-if="hasPendingRevision"
        type="warning"
        :show-icon="false"
        class="pending-alert"
      >
        当前版本正在审核中，您看到的是上一个已发布版本。
      </NAlert>

      <KnowledgeStardustQuote v-if="hasStardustQuote" />

      <MdPreview
        :model-value="resolvedContent"
        :theme="mdTheme"
        :preview-theme="'default'"
        :code-theme="'github'"
      />

      <DocEditors :editors="doc.editors" />
      <DocIssues :doc-id="doc.id" :issues="doc.issues" @refresh="$emit('refresh')" />
    </div>
    <aside class="reader-toc">
      <div class="toc-title">大纲</div>
      <nav v-if="headings.length" class="md-editor-catalog" aria-label="文档大纲">
        <div class="md-editor-catalog-container">
          <div
            v-for="(h, i) in headings"
            :key="`${i}-${h.text}`"
            class="md-editor-catalog-link"
            :class="{ 'md-editor-catalog-active': i === activeHeadingIndex }"
            :style="{ paddingLeft: (h.level - 1) * 12 + 10 + 'px' }"
            :title="h.text"
            role="link"
            tabindex="0"
            @click="scrollToHeading(i)"
            @keydown.enter.prevent="scrollToHeading(i)"
          >
            <span>{{ h.text }}</span>
          </div>
        </div>
      </nav>
      <div v-else class="toc-empty">暂无大纲</div>
    </aside>
  </div>
</template>

<style scoped>
.reader-layout {
  display: flex;
  gap: 24px;
  align-items: flex-start;
  min-width: 0; /* ← 防吹爆：允许整行窄于 min-content */
  background-color: var(--neutral-card);
  color: var(--neutral-text-1);
}

.reader-preview {
  flex: 0 0 80%;
  min-width: 0; /* 允许窄于 min-content，长字符串不再顶开本格 */
  overflow-wrap: anywhere; /* Markdown 长 URL / 长字符串自动折行，不撑爆预览区 */
  background-color: var(--neutral-card);
}

.pending-alert {
  margin-bottom: 16px;
}

.reader-toc {
  flex: 0 0 20%;
  min-width: 0; /* ← 防吹爆 */
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 180px);
  overflow-y: auto;
  border-left: 1px solid var(--neutral-border);
  padding-left: 16px;
  background-color: var(--neutral-card);
}

.toc-title {
  margin-bottom: var(--space-md);
  color: var(--neutral-text-3);
  font-size: var(--font-caption-size);
  font-weight: 600;
  line-height: var(--font-caption-height);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.reader-toc .md-editor-catalog {
  font-size: var(--font-small-size);
}

.reader-toc .md-editor-catalog-link {
  position: relative;
  display: block;
  padding: 5px 10px;
  border-radius: var(--radius-sm);
  color: var(--neutral-text-2);
  line-height: 1.5;
  cursor: pointer;
  transition: color var(--motion-quick) ease-out, background-color var(--motion-quick) ease-out;
}

.reader-toc .md-editor-catalog-link:hover {
  color: var(--neutral-text-1);
  background-color: var(--neutral-hover);
}

.reader-toc .md-editor-catalog-link:focus-visible {
  outline: 2px solid var(--arco-primary);
  outline-offset: -2px;
}

.reader-toc .md-editor-catalog-link.md-editor-catalog-active {
  color: var(--arco-primary);
  font-weight: 500;
  background-color: var(--arco-primary-light);
}

/* 活动大纲项左缘品牌状态线，呼应平台侧栏选中态 */
.reader-toc .md-editor-catalog-link.md-editor-catalog-active::before {
  position: absolute;
  top: 50%;
  left: 0;
  width: 3px;
  height: 14px;
  border-radius: 999px;
  background: var(--arco-primary);
  content: '';
  transform: translateY(-50%);
}

.toc-empty {
  color: var(--neutral-text-3);
  font-size: var(--font-small-size);
}

.reader-toc::-webkit-scrollbar {
  width: 6px;
}
.reader-toc::-webkit-scrollbar-track {
  background: transparent;
}
.reader-toc::-webkit-scrollbar-thumb {
  background: rgba(29, 33, 41, 0.15);
  border-radius: 999px;
}
.reader-toc::-webkit-scrollbar-thumb:hover {
  background: rgba(29, 33, 41, 0.32);
}
:root[data-theme="dark"] .reader-toc::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.16);
}
:root[data-theme="dark"] .reader-toc::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.28);
}

.reader-preview :deep(.md-editor),
.reader-preview :deep(.md-editor-dark) {
  --md-bk-color: var(--neutral-card);
  --md-bk-color-outstand: var(--neutral-hover);
  --md-bk-hover-color: var(--neutral-hover);
  --md-color: var(--neutral-text-1);
  --md-hover-color: var(--neutral-text-1);
  --md-border-color: var(--neutral-border);
  --md-border-hover-color: var(--neutral-border);
  background-color: var(--neutral-card);
  border-color: transparent; /* 预览模式去外框，与外层卡片无缝融合 */
}

.reader-preview :deep(.md-editor-content),
.reader-preview :deep(.md-editor-preview-wrapper),
.reader-preview :deep(.md-editor-preview) {
  background-color: var(--neutral-card);
  color: var(--neutral-text-1);
}

.reader-preview :deep(.md-editor-preview pre),
.reader-preview :deep(.md-editor-preview blockquote),
.reader-preview :deep(.md-editor-preview table thead th) {
  background-color: var(--neutral-hover);
}
.reader-preview :deep(.md-editor-preview :not(pre) > code) {
  background-color: var(--neutral-hover);
}
.reader-preview :deep(.md-editor-preview blockquote) {
  border-left-color: var(--neutral-border);
}
.reader-preview :deep(.md-editor-preview table td),
.reader-preview :deep(.md-editor-preview table th) {
  border-color: var(--neutral-border);
}
.reader-toc .md-editor-catalog {
  background-color: var(--neutral-card);
}

@media (max-width: 1024px) {
  .reader-layout {
    flex-direction: column;
  }
  .reader-preview {
    flex: 1 1 auto;
  }
  .reader-toc {
    position: static;
    max-height: 240px;
    border-left: none;
    border-top: 1px solid var(--neutral-border);
    padding-left: 0;
    padding-top: 12px;
  }
}
</style>
