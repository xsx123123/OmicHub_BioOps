<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'

const props = defineProps<{
  content: string
  title?: string
}>()

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function inlineMarkdown(text: string): string {
  return (
    escapeHtml(text)
      // 代码
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // 粗体
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      // 斜体
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      // 链接
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
  )
}

function parseMarkdown(md: string): string {
  const lines = md.split('\n')
  let html = ''
  let i = 0
  let inCodeBlock = false
  let codeBuffer: string[] = []
  let codeLang = ''
  let inList = false
  let listType: 'ul' | 'ol' | null = null
  let inTable = false
  let tableBuffer: string[] = []

  function closeList() {
    if (inList && listType) {
      html += `</${listType}>`
      inList = false
      listType = null
    }
  }

  function closeTable() {
    if (inTable && tableBuffer.length > 0) {
      html += '<table class="md-table"><thead><tr>'
      const headers = tableBuffer[0].split('|').map((c) => c.trim()).filter(Boolean)
      headers.forEach((h) => {
        html += `<th>${inlineMarkdown(h)}</th>`
      })
      html += '</tr></thead><tbody>'
      for (let t = 2; t < tableBuffer.length; t++) {
        const cells = tableBuffer[t].split('|').map((c) => c.trim()).filter(Boolean)
        if (cells.length === 0) continue
        html += '<tr>'
        cells.forEach((c) => {
          html += `<td>${inlineMarkdown(c)}</td>`
        })
        html += '</tr>'
      }
      html += '</tbody></table>'
      tableBuffer = []
      inTable = false
    }
  }

  while (i < lines.length) {
    const line = lines[i]

    // 代码块
    if (line.startsWith('```')) {
      if (inCodeBlock) {
        html += `<pre class="md-code-block"><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`
        codeBuffer = []
        inCodeBlock = false
      } else {
        closeList()
        closeTable()
        codeLang = line.slice(3).trim()
        inCodeBlock = true
      }
      i++
      continue
    }

    if (inCodeBlock) {
      codeBuffer.push(line)
      i++
      continue
    }

    // 空行
    if (line.trim() === '') {
      closeList()
      closeTable()
      i++
      continue
    }

    // 表格
    if (line.includes('|')) {
      closeList()
      if (!inTable) {
        inTable = true
        tableBuffer = []
      }
      tableBuffer.push(line)
      i++
      continue
    } else {
      closeTable()
    }

    // 标题
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/)
    if (headingMatch) {
      closeList()
      const level = headingMatch[1].length
      const text = headingMatch[2].trim()
      html += `<h${level} class="md-h${level}">${inlineMarkdown(text)}</h${level}>`
      i++
      continue
    }

    // 无序列表
    const ulMatch = line.match(/^[-*]\s+(.*)$/)
    if (ulMatch) {
      closeTable()
      if (!inList || listType !== 'ul') {
        closeList()
        html += '<ul class="md-list md-list-ul">'
        inList = true
        listType = 'ul'
      }
      html += `<li>${inlineMarkdown(ulMatch[1])}</li>`
      i++
      continue
    }

    // 有序列表
    const olMatch = line.match(/^\d+\.\s+(.*)$/)
    if (olMatch) {
      closeTable()
      if (!inList || listType !== 'ol') {
        closeList()
        html += '<ol class="md-list md-list-ol">'
        inList = true
        listType = 'ol'
      }
      html += `<li>${inlineMarkdown(olMatch[1])}</li>`
      i++
      continue
    }

    // 普通段落
    closeList()
    html += `<p class="md-paragraph">${inlineMarkdown(line)}</p>`
    i++
  }

  if (inCodeBlock) {
    html += `<pre class="md-code-block"><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`
  }
  closeList()
  closeTable()

  return html
}

const renderedHtml = computed(() => DOMPurify.sanitize(parseMarkdown(props.content)))
</script>

<template>
  <article class="markdown-reader">
    <h1 v-if="title" class="md-title">{{ title }}</h1>
    <div class="md-body" v-html="renderedHtml" />
  </article>
</template>

<style scoped>
.markdown-reader {
  color: var(--neutral-text-1);
  line-height: 1.8;
}

.md-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0 0 20px;
  color: var(--neutral-text-1);
}

:deep(.md-body .md-h1) {
  font-size: 24px;
  font-weight: 600;
  margin: 32px 0 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--neutral-border);
}

:deep(.md-body .md-h2) {
  font-size: 20px;
  font-weight: 600;
  margin: 28px 0 14px;
}

:deep(.md-body .md-h3) {
  font-size: 18px;
  font-weight: 600;
  margin: 24px 0 12px;
}

:deep(.md-body .md-h4),
:deep(.md-body .md-h5),
:deep(.md-body .md-h6) {
  font-size: 16px;
  font-weight: 600;
  margin: 20px 0 10px;
}

:deep(.md-body .md-paragraph) {
  margin: 0 0 16px;
  color: var(--neutral-text-2);
}

:deep(.md-body .md-list) {
  margin: 0 0 16px;
  padding-left: 20px;
  color: var(--neutral-text-2);
}

:deep(.md-body .md-list li) {
  margin-bottom: 8px;
}

:deep(.md-body code) {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  background: var(--neutral-hover);
  color: var(--arco-primary);
  padding: 2px 6px;
  border-radius: 4px;
}

:deep(.md-body .md-code-block) {
  background: #1e1e1e;
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
  margin: 0 0 20px;
}

:deep(.md-body .md-code-block code) {
  background: transparent;
  color: #d4d4d4;
  padding: 0;
  font-size: 13px;
  line-height: 1.6;
}

:deep(.md-body .md-table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 20px;
  font-size: 14px;
}

:deep(.md-body .md-table th),
:deep(.md-body .md-table td) {
  border: 1px solid var(--neutral-border);
  padding: 10px 12px;
  text-align: left;
}

:deep(.md-body .md-table th) {
  background: var(--neutral-hover);
  font-weight: 600;
  color: var(--neutral-text-1);
}

:deep(.md-body .md-table td) {
  color: var(--neutral-text-2);
}

:deep(.md-body a) {
  color: var(--arco-primary);
  text-decoration: none;
}

:deep(.md-body a:hover) {
  text-decoration: underline;
}

:deep(.md-body strong) {
  color: var(--neutral-text-1);
  font-weight: 600;
}
</style>
