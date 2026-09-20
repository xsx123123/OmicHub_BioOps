<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github.css'

const props = defineProps<{
  content: string
  /** 在 sanitize 之前对渲染出的 HTML 做后处理（如把 [[citation:xxx]] 换成引用徽章） */
  transform?: (html: string) => string
}>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        const result = hljs.highlight(str, { language: lang })
        return `<pre class="hljs"><code>${result.value}</code></pre>`
      } catch {
        // fallthrough
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})

const html = computed(() => {
  const raw = md.render(props.content || '')
  const transformed = props.transform ? props.transform(raw) : raw
  return DOMPurify.sanitize(transformed, {
    ADD_ATTR: ['target', 'rel'],
  })
})

const copied = ref<string | null>(null)
let copyResetTimer: ReturnType<typeof setTimeout> | null = null

async function copyCode(e: MouseEvent) {
  const target = e.target as HTMLElement
  const btn = target.closest('.copy-btn') as HTMLElement | null
  if (!btn) return
  const pre = btn.parentElement?.querySelector('code')
  if (!pre) return
  const text = pre.textContent || ''
  try {
    await navigator.clipboard.writeText(text)
    copied.value = btn.dataset.id || '0'
    if (copyResetTimer) clearTimeout(copyResetTimer)
    copyResetTimer = setTimeout(() => (copied.value = null), 2000)
  } catch {
    // clipboard 不可用时静默失败
  }
}

onUnmounted(() => {
  if (copyResetTimer) clearTimeout(copyResetTimer)
})
</script>

<template>
  <div class="md-body" v-html="html" @click="copyCode"></div>
</template>

<style scoped>
.md-body {
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  margin: 0.6em 0 0.4em;
  font-weight: 600;
}
.md-body :deep(p) {
  margin: 0.4em 0;
}
.md-body :deep(ul),
.md-body :deep(ol) {
  padding-left: 1.4em;
  margin: 0.4em 0;
}
.md-body :deep(code) {
  background: var(--neutral-hover, #f2f3f8);
  padding: 0.1em 0.35em;
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.9em;
}
:root[data-theme="dark"] .md-body :deep(pre.hljs) {
  background: var(--neutral-card);
}
.md-body :deep(pre.hljs) {
  background: #f6f8fa;
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 8px;
  padding: 12px 14px;
  overflow-x: auto;
  margin: 0.5em 0;
  position: relative;
}
.md-body :deep(pre.hljs code) {
  background: transparent;
  padding: 0;
  font-size: 13px;
  line-height: 1.5;
}
.md-body :deep(blockquote) {
  border-left: 3px solid var(--arco-primary, #165dff);
  margin: 0.5em 0;
  padding: 0.2em 0.9em;
  color: var(--neutral-text-2, #4e5969);
}
.md-body :deep(table) {
  border-collapse: collapse;
  margin: 0.5em 0;
}
.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid var(--neutral-border, #e5e6eb);
  padding: 6px 10px;
}
.md-body :deep(a) {
  color: var(--arco-primary, #165dff);
  text-decoration: none;
}
.md-body :deep(a:hover) {
  text-decoration: underline;
}
</style>
