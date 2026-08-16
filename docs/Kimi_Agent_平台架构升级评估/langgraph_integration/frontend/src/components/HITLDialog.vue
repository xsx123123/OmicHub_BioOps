<template>
  <!--
    HITLDialog.vue
    ==============
    HITL（人工在环）确认弹窗组件。

    支持的 HITL 类型:
      - param_confirm:  参数确认
      - task_submit:    任务提交确认
      - result_review:  结果审核
      - error_recovery: 错误恢复

    用法:
      <HITLDialog
        v-model:visible="showDialog"
        :request="hitlRequest"
        @confirm="onConfirm"
        @modify="onModify"
        @reject="onReject"
      />
  -->
  <Teleport to="body">
    <Transition name="hitl-fade">
      <div
        v-if="visible"
        class="hitl-overlay"
        @click.self="handleOverlayClick"
      >
        <div class="hitl-dialog" :class="[`type-${hitlType}`]">
          <!-- 头部 -->
          <div class="hitl-header">
            <div class="hitl-icon">
              <span v-if="hitlType === 'param_confirm'">⚙️</span>
              <span v-else-if="hitlType === 'task_submit'">🚀</span>
              <span v-else-if="hitlType === 'result_review'">📊</span>
              <span v-else-if="hitlType === 'error_recovery'">⚠️</span>
              <span v-else">❓</span>
            </div>
            <h3 class="hitl-title">{{ title }}</h3>
            <button class="hitl-close" @click="handleReject" aria-label="关闭">
              <svg width="20" height="20" viewBox="0 0 20 20">
                <path d="M15 5L5 15M5 5l10 10" stroke="currentColor" stroke-width="1.5" fill="none" />
              </svg>
            </button>
          </div>

          <!-- 描述 -->
          <div class="hitl-description" v-html="description" />

          <!-- 内容区域 -->
          <div class="hitl-content">
            <!-- 参数确认 -->
            <template v-if="hitlType === 'param_confirm'">
              <ParamConfirmView
                :payload="payload"
                v-model:modifications="modifications"
                :readonly="isSubmitting"
              />
            </template>

            <!-- 任务提交 -->
            <template v-else-if="hitlType === 'task_submit'">
              <TaskSubmitView :payload="payload" />
            </template>

            <!-- 结果审核 -->
            <template v-else-if="hitlType === 'result_review'">
              <ResultReviewView :payload="payload" />
            </template>

            <!-- 错误恢复 -->
            <template v-else-if="hitlType === 'error_recovery'">
              <ErrorRecoveryView :payload="payload" />
            </template>

            <!-- 备注输入 -->
            <div class="hitl-comment-section">
              <label class="hitl-comment-label">备注 (可选)</label>
              <textarea
                v-model="comment"
                class="hitl-comment-input"
                placeholder="添加备注说明..."
                :disabled="isSubmitting"
                rows="2"
              />
            </div>
          </div>

          <!-- 倒计时 -->
          <div v-if="remainingSeconds > 0" class="hitl-timer">
            <svg class="hitl-timer-icon" viewBox="0 0 24 24" width="16" height="16">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none" />
              <path d="M12 6v6l4 2" stroke="currentColor" stroke-width="2" fill="none" />
            </svg>
            <span>{{ formatTime(remainingSeconds) }}</span>
          </div>

          <!-- 操作按钮 -->
          <div class="hitl-actions">
            <button
              class="hitl-btn hitl-btn-secondary"
              @click="handleReject"
              :disabled="isSubmitting"
            >
              取消
            </button>
            <button
              v-if="hitlType === 'param_confirm'"
              class="hitl-btn hitl-btn-primary"
              @click="handleModify"
              :disabled="isSubmitting || !hasModifications"
            >
              修改并继续
            </button>
            <button
              class="hitl-btn hitl-btn-success"
              @click="handleConfirm"
              :disabled="isSubmitting"
            >
              <span v-if="isSubmitting" class="hitl-spinner" />
              <span v-else>确认</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import ParamConfirmView from './hitl/ParamConfirmView.vue'
import TaskSubmitView from './hitl/TaskSubmitView.vue'
import ResultReviewView from './hitl/ResultReviewView.vue'
import ErrorRecoveryView from './hitl/ErrorRecoveryView.vue'

// ── Props / Emits ──

interface Props {
  visible: boolean
  request: {
    id: string
    hitl_type: string
    title: string
    description: string
    payload: Record<string, any>
    thread_id: string
    remaining_seconds: number
  } | null
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:visible': [value: boolean]
  confirm: [payload: { requestId: string; comment?: string; modifications?: Record<string, any> }]
  modify: [payload: { requestId: string; modifications: Record<string, any>; comment?: string }]
  reject: [payload: { requestId: string; comment?: string }]
}>()

// ── 状态 ──

const comment = ref('')
const modifications = ref<Record<string, any>>({})
const isSubmitting = ref(false)
const remainingSeconds = ref(0)
let timerInterval: ReturnType<typeof setInterval> | null = null

// ── 计算属性 ──

const hitlType = computed(() => props.request?.hitl_type || '')
const title = computed(() => props.request?.title || '请确认')
const description = computed(() => props.request?.description || '')
const payload = computed(() => props.request?.payload || {})
const hasModifications = computed(() => Object.keys(modifications.value).length > 0)

// ── 倒计时逻辑 ──

watch(
  () => props.visible,
  (visible) => {
    if (visible && props.request) {
      remainingSeconds.value = props.request.remaining_seconds
      startTimer()
    } else {
      stopTimer()
    }
  },
)

function startTimer() {
  stopTimer()
  timerInterval = setInterval(() => {
    remainingSeconds.value--
    if (remainingSeconds.value <= 0) {
      stopTimer()
      handleReject()
    }
  }, 1000)
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

onUnmounted(stopTimer)

// ── 事件处理 ──

function closeDialog() {
  emit('update:visible', false)
}

function handleOverlayClick() {
  // 点击遮罩不关闭，防止误操作
}

async function handleConfirm() {
  if (!props.request || isSubmitting.value) return
  isSubmitting.value = true
  emit('confirm', {
    requestId: props.request.id,
    comment: comment.value || undefined,
    modifications: hasModifications.value ? modifications.value : undefined,
  })
  closeDialog()
}

async function handleModify() {
  if (!props.request || isSubmitting.value) return
  isSubmitting.value = true
  emit('modify', {
    requestId: props.request.id,
    modifications: modifications.value,
    comment: comment.value || undefined,
  })
  closeDialog()
}

async function handleReject() {
  if (!props.request || isSubmitting.value) return
  isSubmitting.value = true
  emit('reject', {
    requestId: props.request.id,
    comment: comment.value || undefined,
  })
  closeDialog()
}
</script>

<style scoped>
.hitl-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.hitl-dialog {
  background: var(--n-modal-color, #fff);
  border-radius: 16px;
  width: 100%;
  max-width: 560px;
  max-height: 85vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.15);
}

.hitl-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 24px 0;
}

.hitl-icon {
  font-size: 28px;
  flex-shrink: 0;
}

.hitl-title {
  flex: 1;
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--n-text-color, #333);
}

.hitl-close {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--n-text-color-3, #999);
  transition: all 0.2s;
}

.hitl-close:hover {
  background: var(--n-close-color-hover, #f0f0f0);
  color: var(--n-text-color, #333);
}

.hitl-description {
  padding: 8px 24px 0;
  font-size: 14px;
  color: var(--n-text-color-2, #666);
  line-height: 1.6;
}

.hitl-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}

.hitl-comment-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--n-divider-color, #e8e8e8);
}

.hitl-comment-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--n-text-color-2, #666);
  margin-bottom: 8px;
}

.hitl-comment-input {
  width: 100%;
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid var(--n-border-color, #d9d9d9);
  background: var(--n-input-color, #fafafa);
  color: var(--n-text-color, #333);
  font-size: 14px;
  resize: vertical;
  transition: border-color 0.2s;
}

.hitl-comment-input:focus {
  outline: none;
  border-color: var(--n-primary-color, #18a058);
}

.hitl-timer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 24px;
  font-size: 13px;
  color: var(--n-warning-color, #f0a020);
}

.hitl-timer-icon {
  animation: spin 2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.hitl-actions {
  display: flex;
  gap: 12px;
  padding: 16px 24px 20px;
  justify-content: flex-end;
}

.hitl-btn {
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.hitl-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.hitl-btn-secondary {
  background: var(--n-button-color-tertiary, #f0f0f0);
  color: var(--n-text-color, #333);
}

.hitl-btn-secondary:hover:not(:disabled) {
  background: var(--n-button-color-tertiary-hover, #e0e0e0);
}

.hitl-btn-primary {
  background: var(--n-primary-color, #18a058);
  color: white;
}

.hitl-btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.hitl-btn-success {
  background: var(--n-success-color, #18a058);
  color: white;
}

.hitl-btn-success:hover:not(:disabled) {
  opacity: 0.9;
}

.hitl-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* 过渡动画 */
.hitl-fade-enter-active,
.hitl-fade-leave-active {
  transition: opacity 0.3s ease;
}

.hitl-fade-enter-from,
.hitl-fade-leave-to {
  opacity: 0;
}
</style>
