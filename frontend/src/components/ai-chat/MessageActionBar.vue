<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { NButton, NIcon, NPopover, NTooltip } from 'naive-ui'
import {
  CopyOutline,
  CheckmarkOutline,
  RefreshOutline,
  LanguageOutline,
  TrashOutline,
  PencilOutline,
  ReloadOutline,
} from '@vicons/ionicons5'
import type { CopyMode } from './types'

interface Props {
  visible: boolean
  isUser: boolean
  content: string
  modelName?: string
}

const props = withDefaults(defineProps<Props>(), {
  modelName: 'AI 助手',
})

const emit = defineEmits<{
  copy: [mode: CopyMode]
  regenerate: []
  retryWithModel: []
  translate: []
  delete: []
  edit: []
}>()

const copied = ref(false)
const confirmingDelete = ref(false)
let copyResetTimer: ReturnType<typeof setTimeout> | null = null

function buildCitation(content: string): string {
  const date = new Date().toISOString().slice(0, 10)
  const header = `> [AI 助手 · ${props.modelName} · ${date}]`
  const body = content
    .split('\n')
    .map((l) => `> ${l}`)
    .join('\n')
  return `${header}\n${body}`
}

async function doCopy(mode: CopyMode) {
  let text = props.content
  if (mode === 'citation') text = buildCitation(props.content)
  // markdown 模式原样复制（content 本身即 Markdown 源码）
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // HTTP / 嵌入式 WebView 等非安全上下文无法使用 Clipboard API 时，
    // 回退到浏览器仍支持的选区复制，避免按钮看似点击成功却没有内容。
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0'
    document.body.appendChild(textarea)
    textarea.select()
    const copiedByFallback = document.execCommand('copy')
    document.body.removeChild(textarea)
    if (!copiedByFallback) return
  }
  copied.value = true
  emit('copy', mode)
  if (copyResetTimer) clearTimeout(copyResetTimer)
  copyResetTimer = setTimeout(() => {
    copied.value = false
  }, 1500)
}

function handleRegenerate() {
  emit('regenerate')
}

function handleRetryWithModel() {
  emit('retryWithModel')
}

function handleTranslate() {
  emit('translate')
}

function handleEdit() {
  emit('edit')
}

function requestDelete() {
  confirmingDelete.value = true
}

function cancelDelete() {
  confirmingDelete.value = false
}

function confirmDelete() {
  confirmingDelete.value = false
  emit('delete')
}

onUnmounted(() => {
  if (copyResetTimer) clearTimeout(copyResetTimer)
})
</script>

<template>
  <template v-if="!confirmingDelete">
    <!-- 用户消息操作：重新发送、编辑、复制、删除 -->
    <div v-if="isUser" class="message-action-bar" :class="{ visible }">
      <n-tooltip placement="top" trigger="hover">
        <template #trigger>
          <n-button text class="action-btn" @click="handleRegenerate">
            <n-icon size="15"><ReloadOutline /></n-icon>
          </n-button>
        </template>
        <span>重新发送</span>
      </n-tooltip>

      <n-tooltip placement="top" trigger="hover">
        <template #trigger>
          <n-button text class="action-btn" @click="handleEdit">
            <n-icon size="15"><PencilOutline /></n-icon>
          </n-button>
        </template>
        <span>编辑</span>
      </n-tooltip>

      <n-tooltip placement="top" trigger="hover">
        <template #trigger>
          <n-button text class="action-btn" :class="{ copied }" @click="doCopy('plain')">
            <n-icon size="15">
              <CheckmarkOutline v-if="copied" />
              <CopyOutline v-else />
            </n-icon>
          </n-button>
        </template>
        <span>复制</span>
      </n-tooltip>

      <n-tooltip placement="top" trigger="hover">
        <template #trigger>
          <n-button text class="action-btn danger" @click="requestDelete">
            <n-icon size="15"><TrashOutline /></n-icon>
          </n-button>
        </template>
        <span>删除</span>
      </n-tooltip>
    </div>

    <!-- AI 消息操作 -->
    <div v-else class="message-action-bar" :class="{ visible }">
      <!-- 复制：弹层三模式 -->
      <n-popover trigger="click" placement="top" :width="170">
        <template #trigger>
          <n-button text class="action-btn" :class="{ copied }">
            <n-icon size="15">
              <CheckmarkOutline v-if="copied" />
              <CopyOutline v-else />
            </n-icon>
          </n-button>
        </template>
        <div style="display: flex; flex-direction: column; gap: 2px">
          <n-button text size="small" style="justify-content: flex-start" @click="doCopy('plain')">
            复制纯文本
          </n-button>
          <n-button text size="small" style="justify-content: flex-start" @click="doCopy('markdown')">
            复制 Markdown 源码
          </n-button>
          <n-button text size="small" style="justify-content: flex-start" @click="doCopy('citation')">
            复制为引用格式
          </n-button>
        </div>
      </n-popover>

      <!-- 重新生成：弹层 同模型 / 换模型 -->
      <n-popover trigger="click" placement="top" :width="150">
        <template #trigger>
          <n-button text class="action-btn">
            <n-icon size="15"><RefreshOutline /></n-icon>
          </n-button>
        </template>
        <div style="display: flex; flex-direction: column; gap: 2px">
          <n-button text size="small" style="justify-content: flex-start" @click="handleRegenerate">
            重新生成
          </n-button>
          <n-button text size="small" style="justify-content: flex-start" @click="handleRetryWithModel">
            换模型重试
          </n-button>
        </div>
      </n-popover>

      <!-- 翻译 -->
      <n-button text class="action-btn" @click="handleTranslate">
        <n-icon size="15"><LanguageOutline /></n-icon>
      </n-button>

      <!-- 删除 -->
      <n-button text class="action-btn danger" @click="requestDelete">
        <n-icon size="15"><TrashOutline /></n-icon>
      </n-button>
    </div>
  </template>

  <!-- 删除确认气泡 -->
  <div v-else class="message-action-bar visible">
    <div class="delete-confirm">
      <span>确认删除？</span>
      <button class="confirm-btn cancel" @click="cancelDelete">取消</button>
      <button class="confirm-btn delete" @click="confirmDelete">删除</button>
    </div>
  </div>
</template>
