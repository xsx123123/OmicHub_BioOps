<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton,
  NSpin,
  NTag,
  NSpace,
  NIcon,
  NTooltip,
  useMessage,
  useDialog,
} from 'naive-ui'
import {
  TerminalOutline,
  ExpandOutline,
  ContractOutline,
  TrashOutline,
  TimeOutline,
  PlayOutline,
} from '@vicons/ionicons5'
import XTerminal from '@/components/terminal/XTerminal.vue'
import ImageSelector from '@/components/terminal/ImageSelector.vue'
import ResourceSettings from '@/components/terminal/ResourceSettings.vue'
import PageHeader from '@/components/PageHeader.vue'
import { useTerminalStore } from '@/stores/terminal'
import { formatMemoryMb } from '@/utils/terminal'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const store = useTerminalStore()

const fullScreen = ref(false)
const remainingMinutes = ref(0)
let countdownTimer: ReturnType<typeof setInterval> | null = null

const session = computed(() => store.currentSession)
const loading = computed(() => store.loading)
const images = computed(() => store.enabledImages)
const selectedImage = computed(() => store.selectedImage)
const memoryRange = computed(() => store.memoryRange)
const cpuRange = computed(() => store.cpuRange)
const terminalEnabled = computed(() => store.terminalEnabled)

const memoryMb = computed({
  get: () => store.effectiveMemoryMb,
  set: (val: number) => {
    store.customMemoryMb = val
  },
})

const cpuCores = computed({
  get: () => store.effectiveCpuCores,
  set: (val: number) => {
    store.customCpuCores = val
  },
})

const selectedImageLabel = computed(() => {
  if (!selectedImage.value) return '未选择'
  return `${selectedImage.value.icon} ${selectedImage.value.name}`
})

// 沙盒实际挂载的是用户工作台 workspace 目录，面向用户不暴露容器内路径（§5.4）
const mountDirectory = computed(() => '我的 workspace')
const mountDirectoryTip = '挂载工作台中的 workspace 目录，沙盒内修改实时同步、持久保存'

const statusType = computed(() => {
  switch (session.value?.status) {
    case 'running':
      return 'success'
    case 'idle':
      return 'warning'
    case 'creating':
      return 'info'
    case 'error':
      return 'error'
    default:
      return 'default'
  }
})

function startCountdown() {
  if (countdownTimer) clearInterval(countdownTimer)
  countdownTimer = setInterval(() => {
    if (!session.value?.expires_at) return
    const remaining = Math.max(
      0,
      Math.floor((new Date(session.value.expires_at).getTime() - Date.now()) / 60000),
    )
    remainingMinutes.value = remaining
  }, 60000)
}

async function handleCreate() {
  if (!terminalEnabled.value) {
    message.warning('云端沙盒终端已关闭')
    return
  }
  if (!selectedImage.value) {
    message.warning('请先选择一个镜像')
    return
  }
  try {
    await store.createSession()
    message.success('沙盒终端已启动')
    startCountdown()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '启动沙盒终端失败')
  }
}

function handleDestroy() {
  dialog.warning({
    title: '销毁终端会话',
    content: '确定要销毁当前终端会话吗？容器将被立即停止并删除。',
    positiveText: '销毁',
    negativeText: '取消',
    onPositiveClick: async () => {
      if (session.value) {
        try {
          await store.destroySession(session.value.session_id)
          message.success('终端会话已销毁')
        } catch {
          message.error('销毁失败')
        }
      }
      if (countdownTimer) clearInterval(countdownTimer)
      router.push('/tools')
    },
  })
}

onMounted(async () => {
  await store.fetchImages()
  if (session.value) {
    startCountdown()
  }
})

onBeforeUnmount(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})

watch(
  () => session.value?.expires_at,
  () => {
    if (session.value?.expires_at) {
      const remaining = Math.max(
        0,
        Math.floor((new Date(session.value.expires_at).getTime() - Date.now()) / 60000),
      )
      remainingMinutes.value = remaining
    }
  },
)
</script>

<template>
  <div class="terminal-page" :class="{ 'terminal-fullscreen': fullScreen, 'terminal-config-page': !session }" role="main" aria-label="云端沙盒终端">
    <div v-if="session" class="terminal-header session-header">
      <div class="header-left">
        <NIcon :size="20" color="var(--arco-primary)">
          <TerminalOutline />
        </NIcon>
        <span class="header-title">云端沙盒终端</span>
        <NTag :type="statusType" size="small" round role="status" aria-live="polite">
          {{ session.status }}
        </NTag>
        <span class="session-id">{{ session.session_id }}</span>
        <span v-if="session.image_name" class="image-name">{{ session.image_name }}</span>
      </div>
      <div class="header-right">
        <NSpace align="center" :size="8">
          <NIcon :size="14" color="var(--neutral-text-3)">
            <TimeOutline />
          </NIcon>
          <span class="remaining-time">{{ remainingMinutes }}分钟</span>
        </NSpace>
        <NButton quaternary size="small" @click="fullScreen = !fullScreen">
          <template #icon>
            <NIcon>
              <ContractOutline v-if="fullScreen" />
              <ExpandOutline v-else />
            </NIcon>
          </template>
        </NButton>
        <NButton type="error" size="small" quaternary @click="handleDestroy">
          <template #icon>
            <NIcon>
              <TrashOutline />
            </NIcon>
          </template>
        </NButton>
      </div>
    </div>

    <PageHeader
      v-else
      title="云端沙盒终端"
      subtitle="选择预装工具链的镜像，启动一个隔离、用完即毁的沙盒终端"
      back-to="/tools"
      back-label="返回工具箱"
    />

    <div class="terminal-body">
      <div v-if="loading" class="terminal-loading">
        <NSpin size="large" />
        <p class="loading-text">正在启动隔离容器...</p>
        <p v-if="selectedImage" class="loading-desc">镜像：{{ selectedImage.name }}</p>
      </div>

      <div v-else-if="session?.ws_url" class="terminal-content">
        <XTerminal :session-id="session.session_id" />
      </div>

      <div v-else class="terminal-selector">
        <div class="main-layout">
          <section class="environment-column">
            <div class="card-heading">
              <h2>选择分析环境</h2>
              <p>点击镜像卡片切换预装工具链</p>
            </div>
            <ImageSelector v-model="store.selectedImageId" :images="images" />
          </section>

          <aside class="configuration-column">
            <div class="card-heading">
              <h2>资源设置</h2>
              <p>切换环境后会恢复该镜像的推荐资源</p>
            </div>

            <section class="config-card resource-column">
              <ResourceSettings
                v-model:memory-mb="memoryMb"
                v-model:cpu-cores="cpuCores"
                :memory-min="memoryRange.min"
                :memory-max="memoryRange.max"
                :memory-step="memoryRange.step"
                :cpu-min="cpuRange.min"
                :cpu-max="cpuRange.max"
                :cpu-step="cpuRange.step"
                :recommended-memory-mb="selectedImage?.resources.memory_mb"
                :recommended-cpu-cores="selectedImage?.resources.cpu_cores"
                :disabled="loading"
              />
            </section>

            <section class="preview-panel">
              <div class="preview-title">
                <NIcon :size="18">
                  <TerminalOutline />
                </NIcon>
                启动配置预览
              </div>

              <div class="preview-row">
                <span class="preview-key">分析镜像</span>
                <span class="preview-val">{{ selectedImageLabel }}</span>
              </div>
              <div class="preview-row">
                <span class="preview-key">分配内存</span>
                <span class="preview-val">{{ formatMemoryMb(memoryMb) }}</span>
              </div>
              <div class="preview-row">
                <span class="preview-key">分配 CPU</span>
                <span class="preview-val">{{ cpuCores }} 核</span>
              </div>
              <div class="preview-row">
                <span class="preview-key">挂载目录</span>
                <NTooltip :show-arrow="false">
                  <template #trigger>
                    <span class="preview-val mount-directory">{{ mountDirectory }}</span>
                  </template>
                  {{ mountDirectoryTip }}
                </NTooltip>
              </div>
              <div class="preview-row">
                <span class="preview-key">生命周期</span>
                <span class="preview-val danger">用完即毁</span>
              </div>

              <NButton
                type="primary"
                size="large"
                block
                class="launch-button"
                :disabled="!selectedImage || !terminalEnabled"
                :loading="loading"
                @click="handleCreate"
              >
                <template #icon>
                  <NIcon>
                    <PlayOutline />
                  </NIcon>
                </template>
                启动 {{ selectedImage?.name || '终端' }}
              </NButton>
            </section>
          </aside>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.terminal-page {
  /* 消费全局语义令牌，明暗主题自动适配（fontend.md §3） */
  --terminal-bg: var(--neutral-bg);
  --terminal-card: var(--neutral-card);
  --terminal-primary: var(--arco-primary);
  --terminal-primary-light: color-mix(in srgb, var(--arco-primary) 12%, var(--neutral-card));
  --terminal-text: var(--neutral-text-1);
  --terminal-subtext: var(--neutral-text-3);
  --terminal-border: var(--neutral-border);
  --terminal-soft-border: var(--neutral-border);
  --terminal-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  min-height: 100%;
  box-sizing: border-box;
  background: var(--terminal-bg);
}

.terminal-config-page {
  padding: 32px 24px 24px;
}

.terminal-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: #1e1e1e;
}

.terminal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--terminal-border);
  background: var(--terminal-card);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.header-title {
  color: var(--terminal-text);
  font-size: 15px;
  font-weight: 600;
}

.session-id {
  color: var(--terminal-subtext);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.image-name {
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--terminal-primary-light);
  color: var(--terminal-primary);
  font-size: 12px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.remaining-time {
  color: var(--terminal-subtext);
  font-size: 12px;
}

.terminal-body {
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: auto;
}

.terminal-content {
  width: 100%;
  height: 100%;
}

.terminal-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
}

.loading-text {
  margin: 0;
  color: var(--terminal-subtext);
  font-size: 14px;
}

.loading-desc {
  margin: 0;
  color: var(--terminal-subtext);
  font-size: 12px;
}

.terminal-selector {
  width: 100%;
  max-width: 1600px;
  margin: 0 auto;
  padding: 24px;
  box-sizing: border-box;
}

.main-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);
  gap: 20px;
  /* stretch：右列与左列同高，配合 .preview-panel flex:1 使预览底边与最后一张镜像卡片对齐 */
  align-items: stretch;
}

.environment-column,
.configuration-column {
  min-width: 0;
}

.configuration-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.configuration-column > .card-heading {
  margin-bottom: 0;
}

.config-card,
.preview-panel {
  background: var(--terminal-card);
  border: 1px solid var(--terminal-border);
  border-radius: 12px;
  box-shadow: var(--terminal-shadow);
}

.config-card {
  padding: 24px;
}

.card-heading {
  margin-bottom: 16px;
}

.card-heading h2 {
  margin: 0;
  color: var(--terminal-text);
  font-size: 16px;
  font-weight: 600;
}

.card-heading p {
  margin: 5px 0 0;
  color: var(--terminal-subtext);
  font-size: 12px;
  line-height: 1.45;
}

.empty-state {
  margin-top: 16px;
}

.preview-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  padding: 20px 24px 24px;
}

/* 启动按钮沉底，预览面板拉伸后与左列卡片底边对齐 */
.preview-panel .launch-button {
  margin-top: auto;
}

.preview-panel .preview-row:last-of-type {
  margin-bottom: 16px;
}

.preview-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--terminal-text);
  font-size: 15px;
  font-weight: 700;
}

.preview-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 30px;
}

.preview-key {
  flex: 0 0 auto;
  color: var(--terminal-subtext);
  font-size: 13px;
}

.preview-val {
  min-width: 0;
  color: var(--terminal-text);
  font-size: 13px;
  font-weight: 700;
  text-align: right;
  word-break: break-word;
}

.mount-directory {
  display: block;
  max-width: 174px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-val.danger {
  color: var(--arco-danger);
}

.launch-button {
  height: 40px;
  margin-top: 16px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--arco-primary) 25%, transparent);
}

:deep(.launch-button.n-button--disabled) {
  box-shadow: none;
}

@media (max-width: 1199px) {
  .terminal-config-page {
    padding: 24px 12px 16px;
  }
  .terminal-selector {
    padding: 16px;
  }

  .main-layout {
    grid-template-columns: 1fr;
  }

  .configuration-column {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
    align-items: stretch;
  }

  .configuration-column > .card-heading {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .terminal-config-page {
    padding: 20px 12px 16px;
  }

  .terminal-selector {
    padding: 12px;
  }

  .config-card,
  .preview-panel {
    padding: 18px;
  }

  .configuration-column {
    grid-template-columns: 1fr;
  }
}
</style>
