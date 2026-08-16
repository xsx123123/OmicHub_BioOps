<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { masApi, type MasArtifact, type MasRunProgress } from '@/api/mas'

const props = defineProps<{ runId: string }>()
const progress = ref<MasRunProgress | null>(null)
const artifacts = ref<MasArtifact[]>([])
const error = ref('')
let timer: ReturnType<typeof setTimeout> | null = null
let streamController: AbortController | null = null

const terminal = computed(() => ['succeeded', 'failed', 'cancelled', 'rejected'].includes(progress.value?.status || ''))
const completedCount = computed(() => progress.value?.nodes.filter((node) => node.status === 'succeeded').length || 0)

async function refresh(): Promise<void> {
  try {
    progress.value = await masApi.getProgress(props.runId)
    artifacts.value = await masApi.listArtifacts(props.runId)
    error.value = ''
  } catch {
    error.value = 'MAS 运行状态获取失败，稍后自动重试'
  }
  if (!terminal.value) timer = setTimeout(refresh, 2000)
}

async function connectProgressStream(): Promise<void> {
  streamController = new AbortController()
  try {
    await masApi.streamProgress(props.runId, (nextProgress) => {
      progress.value = nextProgress
      error.value = ''
      if (nextProgress.nodes.some((node) => node.status === 'succeeded')) {
        void masApi.listArtifacts(props.runId).then((items) => { artifacts.value = items })
      }
    }, streamController.signal)
  } catch (streamError) {
    if ((streamError as DOMException).name === 'AbortError') return
    error.value = 'MAS 实时状态连接失败，已切换为轮询。'
    refresh()
  }
}

async function downloadArtifact(artifact: MasArtifact): Promise<void> {
  try {
    await masApi.downloadArtifact(props.runId, artifact)
  } catch {
    error.value = '产物下载失败，请稍后重试。'
  }
}

async function retryNode(nodeKey: string): Promise<void> {
  try {
    await masApi.retryNode(props.runId, nodeKey)
    await refresh()
  } catch {
    error.value = '节点重试失败，请检查重试次数或运行状态。'
  }
}

onMounted(connectProgressStream)
onUnmounted(() => {
  streamController?.abort()
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="mas-progress-card">
    <div class="header"><strong>多智能体分析</strong><span>{{ progress?.status || 'loading' }}</span></div>
    <div v-if="progress" class="summary">{{ completedCount }} / {{ progress.nodes.length }} 节点完成</div>
    <ul v-if="progress" class="nodes">
      <li v-for="node in progress.nodes" :key="node.key">
        <span>{{ node.key }}</span>
        <small>{{ node.status }} · {{ node.agent_id }}</small>
        <button v-if="node.status === 'failed'" type="button" @click="retryNode(node.key)">重试</button>
      </li>
    </ul>
    <div v-if="artifacts.length" class="artifacts">
      <strong>产物</strong>
      <button v-for="artifact in artifacts" :key="artifact.id" type="button" @click="downloadArtifact(artifact)">
        {{ artifact.logical_name }}
      </button>
    </div>
    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>

<style scoped>
.mas-progress-card { padding: 12px; border: 1px solid var(--chat-border, #e5e7eb); border-radius: 10px; background: var(--chat-ai-card, #fff); }
.header, .nodes li { display: flex; justify-content: space-between; gap: 8px; }
.header { color: var(--chat-text-primary, #1f2937); }
.summary, small { color: var(--chat-text-muted, #6b7280); font-size: 12px; }
.nodes { margin: 10px 0 0; padding: 0; list-style: none; }
.nodes li { padding: 4px 0; font-size: 13px; }
.nodes button { border: 0; padding: 0; color: #5b3cc4; background: transparent; cursor: pointer; text-decoration: underline; }
.error { margin-top: 8px; color: #d03050; font-size: 12px; }
.artifacts { display: grid; gap: 5px; margin-top: 10px; font-size: 12px; }
.artifacts button { width: fit-content; border: 0; padding: 0; color: #5b3cc4; background: transparent; cursor: pointer; text-decoration: underline; }
</style>
