<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { NIcon, NSpin, NButton } from 'naive-ui'
import {
  DocumentTextOutline,
  FolderOutline,
  FolderOpenOutline,
} from '@vicons/ionicons5'
import type { MentionItem } from './types'

interface Props {
  items: MentionItem[]
  activeIndex: number
  loading?: boolean
  state?: 'idle' | 'loading' | 'error' | 'empty' | 'forbidden'
  /** 当前 @ 查询词（区分"没有匹配的文件"与"目录下暂无文件"） */
  query?: string
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  state: 'idle',
  query: '',
})

const emit = defineEmits<{
  select: [item: MentionItem]
  referenceDirectory: [item: MentionItem]
  hover: [index: number]
  retry: []
  close: []
}>()

const listRef = ref<HTMLDivElement>()

watch(
  () => props.activeIndex,
  () => {
    nextTick(() => {
      const el = listRef.value?.querySelector('.mention-item.active')
      el?.scrollIntoView({ block: 'nearest' })
    })
  },
)

/** 路径超长中间截断：保留头尾，便于识别目录归属 */
function middleTrunc(text: string, max = 52): string {
  if (!text || text.length <= max) return text
  const head = Math.ceil((max - 1) * 0.6)
  const tail = max - 1 - head
  return `${text.slice(0, head)}…${text.slice(-tail)}`
}

/** 悬浮提示：完整路径 + UUID（UUID 仅在此处出现，主行不裸显） */
function itemTitle(item: MentionItem): string {
  const parts: string[] = []
  if (item.description) parts.push(item.description)
  if (item.uuid) parts.push(`ID: ${item.uuid}`)
  return parts.join('\n')
}
</script>

<template>
  <div class="mention-menu" @mousedown.prevent>
    <div class="menu-header">
      <span class="header-title">@ 引用</span>
      <span class="header-sub">输入文件名筛选上下文 · 找智能体请用 /</span>
    </div>

    <div ref="listRef" v-animate-list.200 class="mention-list" role="listbox" aria-label="@ 引用列表">
      <div v-if="loading" class="menu-state">
        <n-spin size="small" />
        <span>正在搜索工作区文件…</span>
      </div>

      <div v-else-if="state === 'forbidden'" class="menu-state error">
        <span>无权限访问该目录</span>
        <n-button size="tiny" quaternary type="primary" @click="emit('retry')">重试</n-button>
      </div>

      <div v-else-if="state === 'error'" class="menu-state error">
        <span>文件搜索服务异常，请稍后重试</span>
        <n-button size="tiny" quaternary type="primary" @click="emit('retry')">重试</n-button>
      </div>

      <div v-else-if="items.length === 0" class="menu-state">
        <n-icon size="20" class="empty-icon"><FolderOpenOutline /></n-icon>
        <span>{{ query.trim() ? '没有匹配的文件' : '该目录下暂无可引用文件' }}</span>
      </div>

      <template v-else>
        <div
          v-for="(item, index) in items"
          :key="item.key"
          class="mention-item"
          :class="{ active: index === activeIndex }"
          role="option"
          :aria-selected="index === activeIndex"
          :title="itemTitle(item)"
          @click="emit('select', item)"
          @mouseenter="emit('hover', index)"
        >
          <div class="item-icon" :class="`kind-${item.kind}`">
            <n-icon size="16">
              <component :is="item.kind === 'directory' ? FolderOutline : DocumentTextOutline" />
            </n-icon>
          </div>
          <div class="item-info">
            <div class="item-name" :class="{ 'file-name': item.kind === 'file' }">{{ item.name }}</div>
            <div class="item-desc">{{ middleTrunc(item.description) }}</div>
          </div>
          <template v-if="item.kind === 'directory'">
            <n-button
              size="tiny"
              secondary
              type="primary"
              class="reference-directory"
              :aria-label="`引用整个目录 ${item.name}`"
              @click.stop="emit('referenceDirectory', item)"
            >
              引用目录
            </n-button>
            <span class="item-tag">进入</span>
          </template>
          <span v-else class="item-tag">File</span>
        </div>
      </template>
    </div>

    <div class="menu-footer">
      <span class="footer-agent-hint">想找智能体？输入 <kbd>/</kbd> 试试</span>
      <span><kbd>↑↓</kbd> 导航</span>
      <span><kbd>Enter</kbd> 选择</span>
      <span><kbd>Esc</kbd> 关闭</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.mention-menu {
  position: absolute;
  left: -1px;
  right: -1px;
  bottom: calc(100% - 1px);
  z-index: 0;
  width: auto;
  max-width: none;
  max-height: 320px;
  background: var(--chat-input-bg);
  border: 1px solid var(--chat-input-border);
  border-bottom: none;
  border-radius: var(--chat-radius-xl, 20px) var(--chat-radius-xl, 20px) 0 0;
  box-shadow: none;
  overflow: hidden;
  transform-origin: bottom;

  .menu-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--chat-input-border);

    .header-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--chat-text-primary);
    }

    .header-sub {
      font-size: 12px;
      color: var(--chat-text-secondary);
    }
  }

  .mention-list {
    max-height: 220px;
    overflow-y: auto;
    padding: 4px;
  }

  .menu-state {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 28px 16px;
    font-size: 13px;
    color: var(--chat-text-secondary);

    .empty-icon { opacity: 0.6; }
    &.error { color: var(--chat-error); }
  }

  .mention-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 8px;
    cursor: pointer;
    color: var(--chat-text-primary);
    transition: background 140ms ease-out;

    &:hover,
    &.active { background: var(--chat-surface-hover); }

    .item-icon {
      width: 30px;
      height: 30px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      flex-shrink: 0;

      &.kind-directory { background: var(--icon-cyan-bg); color: #0891b2; }
      &.kind-file { background: var(--icon-blue-bg); color: var(--brand-primary); }
    }

    .item-info { flex: 1; min-width: 0; }

    .item-name {
      font-size: 14px;
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .file-name {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }

    .item-desc {
      margin-top: 1px;
      font-size: 12px;
      color: var(--chat-text-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .item-tag {
      flex-shrink: 0;
      padding: 1px 6px;
      border: 1px solid var(--chat-input-border);
      border-radius: 9999px;
      color: var(--chat-text-secondary);
      font-size: 12px;
    }

    .reference-directory { flex-shrink: 0; }
  }

  .menu-footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 16px;
    padding: 8px 12px;
    border-top: 1px solid var(--chat-input-border);
    color: var(--chat-text-secondary);
    font-size: 12px;

    .footer-agent-hint {
      margin-right: auto;
      color: var(--chat-text-secondary);
      opacity: 0.85;
    }

    kbd {
      display: inline-block;
      margin: 0 1px;
      padding: 1px 5px;
      background: var(--chat-surface-hover);
      border: 1px solid var(--chat-input-border);
      border-radius: 4px;
      font: inherit;
      font-size: 11px;
    }
  }
}

@media (prefers-reduced-motion: reduce) {
  .mention-menu { transition: none; }
}
</style>
