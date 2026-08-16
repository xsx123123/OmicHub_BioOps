<script setup lang="ts">
import { ref, nextTick, onMounted, watch } from 'vue'
import {
  NInput, NButton, NIcon, NScrollbar, NEmpty, NTag, NTooltip, NSpin,
} from 'naive-ui'
import {
  ChatbubblesOutline, AddOutline, TrashOutline, SendOutline, CubeOutline,
} from '@vicons/ionicons5'
import { useAIStore } from '@/stores/ai'
import { useAIWebSocket } from '@/composables/useAIWebSocket'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { AIEvent } from '@/types'

const store = useAIStore()
const { connected, lastError, connect, sendChat, disconnect } = useAIWebSocket()

const input = ref('')
const messagesEl = ref<InstanceType<typeof NScrollbar> | null>(null)
const toolEvents = ref<Array<{ tool: string; args: Record<string, unknown>; result?: Record<string, unknown> }>>([])

async function handleEvent(e: AIEvent) {
  switch (e.type) {
    case 'user_message':
      // 已由 send() 占位，此处替换为服务端正式消息
      replaceLastUser(e.message)
      break
    case 'token':
      store.appendAssistantToken(e.content)
      scrollToBottom()
      break
    case 'assistant_message':
      replaceLastAssistant(e.message)
      scrollToBottom()
      break
    case 'tool_call':
      toolEvents.value.push({ tool: e.tool, args: e.arguments })
      scrollToBottom()
      break
    case 'tool_result':
      if (toolEvents.value.length) toolEvents.value[toolEvents.value.length - 1].result = e.result
      scrollToBottom()
      break
    case 'done':
      store.finishStreaming()
      break
    case 'error':
      store.finishStreaming()
      toolEvents.value.push({ tool: 'error', args: {}, result: { error: e.detail } })
      break
  }
}

function replaceLastUser(msg: { id: string; role: string; content: string; timestamp: string }) {
  const msgs = store.currentConversation?.messages
  if (!msgs) return
  const last = msgs[msgs.length - 1]
  if (last && last.role === 'user') {
    last.id = msg.id
    last.content = msg.content
    last.timestamp = msg.timestamp
  }
}

function replaceLastAssistant(msg: { id: string; content: string; timestamp: string }) {
  const msgs = store.currentConversation?.messages
  if (!msgs) return
  const last = msgs[msgs.length - 1]
  if (last && last.role === 'assistant') {
    last.id = msg.id
    last.content = msg.content
    last.timestamp = msg.timestamp
  }
}

function scrollToBottom() {
  nextTick(() => messagesEl.value?.scrollTo({ top: 999999, behavior: 'smooth' }))
}

async function newConversation() {
  await store.createConversation('新对话')
  toolEvents.value = []
}

async function selectConv(id: string) {
  await store.selectConversation(id)
  toolEvents.value = []
}

async function deleteConv(id: string, e: Event) {
  e.stopPropagation()
  await store.deleteConversation(id)
}

async function send() {
  const conv = store.currentConversation
  if (!conv || !input.value.trim() || store.streaming) return
  const content = input.value.trim()
  input.value = ''
  // 占位用户消息（立即渲染）
  store.appendMessage({
    id: crypto.randomUUID(),
    role: 'user',
    content,
    timestamp: new Date().toISOString(),
  })
  store.startStreamingAssistant()
  scrollToBottom()
  if (!connected.value) connect(handleEvent)
  sendChat(conv.id, content)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

onMounted(() => {
  store.fetchConversations()
  connect(handleEvent)
})

watch(
  () => store.currentConversation?.id,
  () => scrollToBottom()
)

defineExpose({ disconnect })
</script>

<template>
  <div class="ai-chat">
    <!-- 对话列表 -->
    <aside class="conv-list">
      <div class="conv-head">
        <span class="conv-title">对话</span>
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton quaternary circle size="small" @click="newConversation">
              <template #icon><NIcon><AddOutline /></NIcon></template>
            </NButton>
          </template>
          新建对话
        </NTooltip>
      </div>
      <NScroll class="conv-scroll">
        <div
          v-for="c in store.conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === store.currentConversation?.id }"
          @click="selectConv(c.id)"
        >
          <NIcon :size="16"><ChatbubblesOutline /></NIcon>
          <span class="conv-name">{{ c.title }}</span>
          <NIcon class="del" :size="14" @click="deleteConv(c.id, $event)"><TrashOutline /></NIcon>
        </div>
        <NEmpty v-if="!store.conversations.length" description="暂无对话" style="margin-top: 40px" />
      </NScroll>
    </aside>

    <!-- 对话区 -->
    <section class="chat-main">
      <header class="chat-header">
        <span>{{ store.currentConversation?.title || 'AI 助手' }}</span>
        <NTag :type="connected ? 'success' : 'default'" size="small" round>
          {{ connected ? '已连接' : '未连接' }}
        </NTag>
      </header>

      <NScrollbar ref="messagesEl" class="messages">
        <div v-if="!store.currentConversation" class="empty-state">
          <NIcon :size="56"><ChatbubblesOutline /></NIcon>
          <p>选择或新建一个对话开始</p>
        </div>
        <template v-else>
          <div v-if="lastError || !connected" class="connection-hint">
            <NTag v-if="lastError" type="error" size="small" round>
              {{ lastError }}
            </NTag>
            <NTag v-else-if="!connected" type="warning" size="small" round>
              连接断开，消息将在恢复后自动发送
            </NTag>
          </div>
          <div
            v-for="m in store.messages"
            :key="m.id"
            class="msg"
            :class="m.role"
          >
            <div v-if="m.role !== 'tool'" class="bubble" :class="m.role">
              <MarkdownRenderer v-if="m.role === 'assistant'" :content="m.content" />
              <span v-else class="plain">{{ m.content }}</span>
            </div>
          </div>
          <!-- 工具调用卡片 -->
          <div v-for="(t, i) in toolEvents" :key="`tool-${i}`" class="tool-card">
            <div class="tool-head"><NIcon :size="14"><CubeOutline /></NIcon> {{ t.tool }}</div>
            <pre v-if="Object.keys(t.args).length">{{ JSON.stringify(t.args, null, 2) }}</pre>
            <div v-if="t.result" class="tool-result">
              <pre>{{ JSON.stringify(t.result, null, 2) }}</pre>
            </div>
          </div>
          <div v-if="store.streaming" class="typing"><NSpin :size="14" /> 思考中…</div>
        </template>
      </NScrollbar>

      <footer class="composer">
        <NInput
          v-model:value="input"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          placeholder="输入消息（Enter 发送，Shift+Enter 换行）"
          @keydown="onKeydown"
          :disabled="!store.currentConversation"
        />
        <NButton type="primary" :loading="store.streaming" :disabled="!input.trim()" @click="send">
          <template #icon><NIcon><SendOutline /></NIcon></template>
        </NButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.ai-chat { display: flex; height: 100%; gap: 0; }
.conv-list { width: 240px; border-right: 1px solid var(--neutral-border); display: flex; flex-direction: column; background: var(--neutral-card); }
.conv-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid var(--neutral-border); }
.conv-title { font-weight: 600; font-size: 14px; }
.conv-scroll { flex: 1; }
.conv-item { display: flex; align-items: center; gap: 8px; padding: 9px 14px; cursor: pointer; font-size: 13px; color: var(--neutral-text-2); border-left: 2px solid transparent; }
.conv-item:hover { background: var(--neutral-hover); }
.conv-item.active { background: var(--arco-primary-light); color: var(--arco-primary); border-left-color: var(--arco-primary); }
.conv-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-item .del { opacity: 0; transition: opacity .15s; }
.conv-item:hover .del { opacity: .6; }
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.chat-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid var(--neutral-border); font-weight: 600; }
.messages { flex: 1; padding: 18px; }
.empty-state { display: flex; flex-direction: column; align-items: center; gap: 12px; color: var(--neutral-text-3); margin-top: 80px; }
.msg { display: flex; margin-bottom: 16px; }
.msg.user { justify-content: flex-end; }
.msg.assistant { justify-content: flex-start; }
.bubble { max-width: 78%; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.6; }
.bubble.user { background: var(--arco-primary); color: #fff; }
.bubble.assistant { background: var(--neutral-card); border: 1px solid var(--neutral-border); }
.plain { white-space: pre-wrap; }
.tool-card { margin: 8px 0; padding: 10px 12px; background: var(--neutral-hover); border: 1px dashed var(--neutral-border); border-radius: 8px; font-size: 12px; }
.tool-head { display: flex; align-items: center; gap: 6px; font-weight: 600; color: var(--neutral-text-2); margin-bottom: 6px; }
.tool-card pre, .tool-result pre { margin: 4px 0; font-size: 12px; overflow-x: auto; }
.typing { display: flex; align-items: center; gap: 8px; color: var(--neutral-text-3); font-size: 13px; padding: 4px 2px; }
.connection-hint { display: flex; justify-content: center; margin-bottom: 12px; }
.composer { display: flex; gap: 10px; padding: 12px 18px; border-top: 1px solid var(--neutral-border); align-items: flex-end; }
</style>
