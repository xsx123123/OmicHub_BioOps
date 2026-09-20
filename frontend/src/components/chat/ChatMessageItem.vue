<script setup lang="ts">
import { computed } from 'vue'
import { NAvatar, NButton, NIcon, NTooltip, useMessage } from 'naive-ui'
import { CopyOutline, RefreshOutline, ThumbsUpOutline, ThumbsDownOutline } from '@vicons/ionicons5'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { DisplayMessage } from '@/types/chat'

const props = defineProps<{
  message: DisplayMessage
  assistantIcon?: string
  assistantColor?: string
}>()

const emit = defineEmits<{
  regenerate: []
}>()

const naiveMessage = useMessage()

const isUser = computed(() => props.message.role === 'user')
const isError = computed(() => props.message.status === 'error')
const isStreaming = computed(() => props.message.status === 'streaming')

const formattedTime = computed(() => {
  try {
    return new Date(props.message.created_at).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
})

async function copyMessage() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    naiveMessage.success('已复制')
  } catch {
    naiveMessage.error('复制失败')
  }
}
</script>

<template>
  <div class="message-item" :class="{ 'message-user': isUser, 'message-ai': !isUser }">
    <div class="avatar-wrapper">
      <NAvatar
        v-if="isUser"
        round
        :size="36"
        color="var(--arco-primary-light)"
        style="color: var(--arco-primary); font-weight: 600"
      >
        我
      </NAvatar>
      <NAvatar
        v-else
        round
        :size="36"
        :color="assistantColor || '#4f8ef7'"
        style="color: #fff; font-size: 18px"
      >
        {{ assistantIcon || '🤖' }}
      </NAvatar>
    </div>

    <div class="message-body">
      <div class="message-header">
        <span class="role-name">{{ isUser ? '我' : 'AI 助手' }}</span>
        <span class="message-time">{{ formattedTime }}</span>
      </div>

      <details v-if="message.reasoning" class="reasoning-block">
        <summary>思考过程</summary>
        <div class="reasoning-content">{{ message.reasoning }}</div>
      </details>

      <div class="message-content" :class="{ 'error-content': isError }">
        <template v-if="isStreaming && !message.content">
          <span class="typing-indicator">
            <span></span><span></span><span></span>
          </span>
        </template>
        <template v-else>
          <MarkdownRenderer :content="message.content || ''" />
          <span v-if="isStreaming" class="cursor-blink">▊</span>
        </template>
        <div v-if="isError && message.error" class="error-reason">{{ message.error }}</div>
      </div>

      <div v-if="!isStreaming && !isUser && message.content" class="message-actions">
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton quaternary size="tiny" @click="copyMessage">
              <template #icon><NIcon :component="CopyOutline" /></template>
            </NButton>
          </template>
          复制
        </NTooltip>
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton quaternary size="tiny" @click="emit('regenerate')">
              <template #icon><NIcon :component="RefreshOutline" /></template>
            </NButton>
          </template>
          重新生成
        </NTooltip>
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton quaternary size="tiny">
              <template #icon><NIcon :component="ThumbsUpOutline" /></template>
            </NButton>
          </template>
          赞
        </NTooltip>
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton quaternary size="tiny">
              <template #icon><NIcon :component="ThumbsDownOutline" /></template>
            </NButton>
          </template>
          踩
        </NTooltip>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-item {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  transition: background 0.15s;
}
.message-item:hover {
  background: var(--neutral-hover, rgba(0, 0, 0, 0.02));
}
.message-user {
  flex-direction: row-reverse;
}
.message-user .message-body {
  align-items: flex-end;
}
.message-body {
  display: flex;
  flex-direction: column;
  max-width: 80%;
  min-width: 0;
}
.message-header {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 4px;
}
.role-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}
.message-time {
  font-size: 11px;
  color: var(--neutral-text-3, #86909c);
}
.message-content {
  padding: 10px 14px;
  border-radius: 12px;
  background: var(--neutral-hover, #f7f8fa);
  word-break: break-word;
}
.message-user .message-content {
  background: var(--arco-primary-light);
  color: var(--neutral-text-1);
}
.error-content {
  background: var(--arco-danger-light) !important;
  color: var(--arco-danger);
}
.error-reason {
  margin-top: 6px;
  font-size: 13px;
  color: var(--arco-danger);
}
.reasoning-block {
  margin-bottom: 6px;
  font-size: 13px;
  background: var(--neutral-hover, #f7f8fa);
  border-radius: 8px;
  padding: 6px 10px;
  color: var(--neutral-text-3, #86909c);
}
.reasoning-block summary {
  cursor: pointer;
  font-style: italic;
}
.reasoning-content {
  margin-top: 4px;
  padding: 4px 0;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
}
.message-actions {
  display: flex;
  gap: 2px;
  margin-top: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}
.message-item:hover .message-actions {
  opacity: 1;
}
.typing-indicator {
  display: inline-flex;
  gap: 4px;
  padding: 4px 0;
}
.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--neutral-text-3, #86909c);
  animation: typing 1.4s infinite ease-in-out;
}
.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes typing {
  0%, 60%, 100% {
    transform: scale(0.7);
    opacity: 0.4;
  }
  30% {
    transform: scale(1);
    opacity: 1;
  }
}
.cursor-blink {
  animation: blink 1s infinite;
  font-weight: 100;
  margin-left: 2px;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
</style>
