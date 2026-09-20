<script setup lang="ts">
/**
 * AskUserCard — ask_user 澄清工具的可交互卡片
 *
 * 未回答：分页问题向导（选项点选 / "其他"自由输入 / 跳过 Esc / 下一步或提交）。
 * 已回答：折叠为工具卡片样式（"询问工具 | 已收集信息"），展开可回看问答。
 */
import { ref, computed, watch } from 'vue'
import { NButton, NIcon, NInput, NTag } from 'naive-ui'
import {
  ChatboxEllipsesOutline,
  CheckmarkOutline,
  ChevronForwardOutline,
  CreateOutline,
} from '@vicons/ionicons5'
import type { AskRequest, AskUserObjectReference } from './types'

const props = defineProps<{ ask: AskRequest }>()

const emit = defineEmits<{
  submit: [answers: string[], objectReference?: AskUserObjectReference]
}>()

const questions = computed(() => props.ask.questions || [])
const total = computed(() => questions.value.length)

// ---------- 未回答：分页收集 ----------
const currentIndex = ref(0)
/** 每题选中的选项（点选后写入；与自由输入互斥） */
const selections = ref<string[]>(questions.value.map(() => ''))
/** 每题"其他"自由输入文本（非空时优先于选项） */
const otherTexts = ref<string[]>(questions.value.map(() => ''))
/** 无选项的问题直接展开自由输入（含模型未给出有效问题的兜底形态） */
const showOther = ref<boolean[]>(questions.value.map((q) => !(q.options?.length)))
const objectPath = ref('')
const selectedObjectFile = ref<File | null>(null)
const objectFileInput = ref<HTMLInputElement | null>(null)

const current = computed(() => questions.value[currentIndex.value])
const isLast = computed(() => currentIndex.value >= total.value - 1)
/** 当前题有效答案：自由输入优先，其次点选选项 */
const currentAnswer = computed(
  () => otherTexts.value[currentIndex.value]?.trim() || selections.value[currentIndex.value] || '',
)
const objectRequired = computed(() => Boolean(props.ask.objectRequired))
const selectedWorkspaceCandidate = computed(() => props.ask.workspaceCandidates?.find(
  (item) => item.location === currentAnswer.value,
))
const hasExecutionObject = computed(() => Boolean(
  selectedObjectFile.value || objectPath.value.trim() || selectedWorkspaceCandidate.value,
))
const canSubmit = computed(() => objectRequired.value
  ? hasExecutionObject.value
  : Boolean(currentAnswer.value))
const isSubmitting = computed(() => Boolean(props.ask.submitting || submitting.value))

watch(() => props.ask.submitting, (value) => {
  if (!value) submitting.value = false
})

/** 选项展示顺序：含「推荐」标注的选项排在最前（稳定排序，其余保持模型给出的原顺序） */
function sortedOptions(opts?: string[]): string[] {
  if (!opts?.length) return []
  return [...opts].sort((a, b) => Number(b.includes('推荐')) - Number(a.includes('推荐')))
}

function isSelected(opt: string): boolean {
  return !otherTexts.value[currentIndex.value]?.trim() && selections.value[currentIndex.value] === opt
}

function selectOption(opt: string) {
  selections.value[currentIndex.value] = opt
  otherTexts.value[currentIndex.value] = ''
  showOther.value[currentIndex.value] = false
  if (objectRequired.value) {
    objectPath.value = ''
    selectedObjectFile.value = null
  }
}

function toggleOther() {
  showOther.value[currentIndex.value] = !showOther.value[currentIndex.value]
  if (showOther.value[currentIndex.value]) selections.value[currentIndex.value] = ''
}

function onOtherInput(value: string) {
  otherTexts.value[currentIndex.value] = value
}

function chooseObjectFile() {
  objectFileInput.value?.click()
}

function onObjectFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  selectedObjectFile.value = input.files?.[0] || null
  if (selectedObjectFile.value) {
    objectPath.value = ''
    selections.value[currentIndex.value] = ''
    otherTexts.value[currentIndex.value] = ''
  }
  input.value = ''
}

function clearObjectFile() {
  selectedObjectFile.value = null
}

function onObjectPathInput(value: string) {
  objectPath.value = value
  if (value.trim()) {
    selectedObjectFile.value = null
    selections.value[currentIndex.value] = ''
    otherTexts.value[currentIndex.value] = ''
  }
}

/** 跳过当前题（答案留空，由 AI 自行决定）；最后一题时直接提交 */
function skip() {
  selections.value[currentIndex.value] = ''
  otherTexts.value[currentIndex.value] = ''
  advance()
}

function next() {
  selections.value[currentIndex.value] = currentAnswer.value
  advance()
}

function advance() {
  if (isLast.value) submit()
  else currentIndex.value += 1
}

const submitting = ref(false)
function submit(allowMissingExecutionObject = false) {
  if (isSubmitting.value || (objectRequired.value && !hasExecutionObject.value && !allowMissingExecutionObject)) return
  submitting.value = true
  emit(
    'submit',
    questions.value.map((_, i) => otherTexts.value[i]?.trim() || selections.value[i] || ''),
    objectRequired.value && hasExecutionObject.value
      ? {
          path: objectPath.value.trim() || undefined,
          file: selectedObjectFile.value || undefined,
          contextRef: selectedWorkspaceCandidate.value,
        }
      : undefined,
  )
}

function discussInstead() {
  selections.value[currentIndex.value] = '先讨论方案（暂不执行）'
  otherTexts.value[currentIndex.value] = ''
  submit(true)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape' || props.ask.answered) return
  if (objectRequired.value) discussInstead()
  else skip()
}

// ---------- 已回答：折叠为工具卡片样式（§18.4.2 默认折叠单行，点击展开回看问答） ----------
const collapsed = ref(true)
function toggle() {
  collapsed.value = !collapsed.value
}

function displayAnswer(index: number): string {
  const answer = props.ask.answers?.[index]?.trim()
  return answer || '无偏好，由你决定'
}
</script>

<template>
  <!-- 未回答：交互式分页问题卡片 -->
  <div
    v-if="!ask.answered && !ask.submitted"
    class="ask-user-card"
    tabindex="0"
    @keydown="handleKeydown"
  >
    <div class="auc-header">
      <span class="auc-question">{{ current?.question || '请补充你的需求细节' }}</span>
      <span v-if="total > 1" class="auc-pager">
        <n-button text size="tiny" :disabled="currentIndex === 0" @click="currentIndex -= 1">
          ‹
        </n-button>
        <span class="auc-pager-text">{{ currentIndex + 1 }}/{{ total }}</span>
        <n-button text size="tiny" :disabled="currentIndex >= total - 1" @click="currentIndex += 1">
          ›
        </n-button>
      </span>
    </div>

    <div class="auc-options">
      <div
        v-for="(opt, i) in sortedOptions(current?.options)"
        :key="opt"
        class="auc-option"
        :class="{ selected: isSelected(opt) }"
        role="button"
        tabindex="-1"
        @click="selectOption(opt)"
      >
        <span class="auc-option-marker">
          <n-icon v-if="isSelected(opt)" size="13"><CheckmarkOutline /></n-icon>
          <span v-else class="auc-option-num">{{ i + 1 }}</span>
        </span>
        <span class="auc-option-text">{{ opt }}</span>
      </div>

      <div
        v-if="current?.options?.length && !objectRequired"
        class="auc-option auc-other"
        :class="{ selected: !!otherTexts[currentIndex]?.trim() }"
        role="button"
        tabindex="-1"
        @click="toggleOther"
      >
        <span class="auc-option-marker">
          <n-icon size="13"><CreateOutline /></n-icon>
        </span>
        <span class="auc-option-text">其他</span>
      </div>

      <n-input
        v-if="showOther[currentIndex] && !objectRequired"
        :value="otherTexts[currentIndex]"
        size="small"
        placeholder="输入你的回答…"
        class="auc-other-input"
        @update:value="onOtherInput"
        @keydown.stop
      />

      <div v-if="objectRequired" class="auc-object-ref">
        <span class="auc-object-ref__label">数据来源（任选其一）</span>
        <div class="auc-object-ref__actions">
          <n-button size="small" secondary :disabled="isSubmitting" @click="chooseObjectFile">选择并上传文件</n-button>
          <input ref="objectFileInput" class="auc-object-ref__input" type="file" @change="onObjectFileChange" />
          <span v-if="selectedObjectFile" class="auc-object-ref__file">
            {{ selectedObjectFile.name }}
            <button type="button" aria-label="移除所选文件" @click="clearObjectFile">×</button>
          </span>
        </div>
        <n-input
          v-if="!selectedObjectFile"
          :value="objectPath"
          size="small"
          placeholder="填写工作区文件名/路径，例如 raw/genes.xlsx"
          @update:value="onObjectPathInput"
          @keydown.stop
        />
        <span class="auc-object-ref__hint">选择候选文件、上传文件或填写路径，任选一种即可；暂不执行可先讨论方案。</span>
      </div>
    </div>

    <div class="auc-footer">
      <n-button v-if="!objectRequired" size="small" quaternary @click="skip">
        跳过
        <span class="auc-key-hint">Esc</span>
      </n-button>
      <n-button v-else size="small" quaternary :disabled="isSubmitting" @click="discussInstead">
        先讨论方案
      </n-button>
      <n-button
        size="small"
        type="primary"
        :disabled="!canSubmit"
        :loading="isSubmitting"
        @click="next"
      >
        {{ objectRequired && isLast ? '使用此数据继续' : (isLast ? '提交' : '下一步') }} →
        <span class="auc-key-hint auc-key-hint--primary">↵</span>
      </n-button>
    </div>
  </div>

  <!-- 已回答：折叠为工具卡片样式，展开可回看问答 -->
  <div v-else class="ask-user-card answered">
    <div
      class="auc-summary-header"
      role="button"
      :aria-expanded="!collapsed"
      tabindex="0"
      @click="toggle"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
    >
      <n-icon size="14" class="auc-icon"><ChatboxEllipsesOutline /></n-icon>
      <span class="auc-tool-name">询问工具</span>
      <span class="auc-divider">|</span>
      <n-tag size="tiny" :type="ask.answered ? 'success' : 'info'" :bordered="false">
        {{ ask.answered ? '已收集信息' : ask.answerStatus === 'waiting_upload' ? '等待上传' : '已提交' }}
      </n-tag>
      <n-icon size="13" class="auc-arrow" :class="{ rotated: !collapsed }">
        <ChevronForwardOutline />
      </n-icon>
    </div>
    <div v-show="!collapsed" class="auc-summary-body">
      <div v-for="(q, i) in questions" :key="i" class="auc-qa">
        <div class="auc-qa-q">{{ q.question || '请补充你的需求细节' }}</div>
        <div class="auc-qa-a">{{ displayAnswer(i) }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ask-user-card {
  width: 100%;
  margin-top: 10px;
  padding: 14px 16px;
  background: var(--chat-ai-card, var(--neutral-card));
  border: 1px solid var(--chat-accent-border, color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 35%, transparent));
  border-radius: 12px;
  box-shadow: var(--chat-shadow-sm, var(--shadow-card));
  outline: none;
}
.auc-object-ref { display: grid; gap: var(--space-xs); margin-top: var(--space-sm); padding: var(--space-sm); border: 1px solid var(--chat-accent-border, var(--neutral-border)); border-radius: var(--radius-sm); background: var(--neutral-fill-1); }
.auc-object-ref__label { color: var(--neutral-text-1); font-size: var(--font-small-size); font-weight: 600; }
.auc-object-ref__actions { display: flex; align-items: center; gap: var(--space-xs); min-width: 0; }
.auc-object-ref__input { display: none; }
.auc-object-ref__file { display: inline-flex; min-width: 0; align-items: center; gap: 4px; color: var(--neutral-text-2); font-size: var(--font-small-size); overflow-wrap: anywhere; }
.auc-object-ref__file button { border: 0; padding: 0; color: var(--neutral-text-3); background: transparent; cursor: pointer; font-size: 16px; line-height: 1; }
.auc-object-ref__hint { color: var(--neutral-text-3); font-size: var(--font-small-size); line-height: 1.5; }

/* 未回答：静态高亮 + 入场动画 + 恰好 2 次呼吸脉冲。
   多条动画必须在同一 animation 简写中逗号分隔声明——分散到基类与
   :not(.answered) 两个选择器会因简写覆盖导致入场动画失效。 */
.ask-user-card:not(.answered) {
  border-color: var(--chat-accent, var(--arco-primary));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 25%, transparent);
  animation:
    auc-card-enter 0.3s ease-out,
    auc-card-pulse 2.4s ease-in-out 0.3s 2;
}

@keyframes auc-card-enter {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes auc-card-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 25%, transparent);
  }
  50% {
    box-shadow: 0 0 0 5px color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 40%, transparent);
  }
}

.ask-user-card.answered {
  padding: 8px 12px;
  border-color: var(--chat-border, var(--neutral-border));
}

/* ===== 未回答：问题向导 ===== */
.auc-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.auc-question {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--chat-text-primary, var(--neutral-text-1));
  white-space: pre-wrap;
  word-break: break-word;
}

.auc-pager {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.auc-pager-text {
  font-size: 12px;
  min-width: 32px;
  text-align: center;
}

.auc-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
}

.auc-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;

  &:hover {
    border-color: var(--chat-accent, var(--arco-primary));
  }

  &.selected {
    border-color: var(--chat-accent, var(--arco-primary));
    background: color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 12%, transparent);
  }
}

.auc-option-marker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  color: var(--chat-accent, var(--arco-primary));
}

.auc-option-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 12px;
  color: var(--chat-text-muted, var(--neutral-text-3));
  background: var(--chat-hover, var(--neutral-hover));
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 6px;
}

.auc-option-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--chat-text-primary, var(--neutral-text-1));
  word-break: break-word;
}

.auc-other .auc-option-marker {
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.auc-other-input {
  margin-top: 2px;
}

.auc-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}

/* 快捷键徽标（kbd 风格：11px、圆角 4px、半透明底） */
.auc-key-hint {
  margin-left: 4px;
  padding: 0 4px;
  font-size: 11px;
  line-height: 16px;
  color: var(--chat-text-muted, var(--neutral-text-3));
  background: color-mix(in srgb, var(--chat-text-muted, var(--neutral-text-3)) 10%, transparent);
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 4px;
}

/* 主按钮内的徽标反色，保证在 accent 底色上的对比度 */
.auc-key-hint--primary {
  color: var(--text-on-primary, #fff);
  background: color-mix(in srgb, var(--text-on-primary, #fff) 16%, transparent);
  border-color: color-mix(in srgb, var(--text-on-primary, #fff) 45%, transparent);
}

/* ===== 已回答：折叠摘要 ===== */
.auc-summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.auc-icon {
  color: var(--chat-accent, var(--arco-primary));
  flex-shrink: 0;
}

.auc-tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--chat-text-primary, var(--neutral-text-1));
}

.auc-divider {
  font-size: 12px;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.auc-arrow {
  margin-left: auto;
  color: var(--chat-text-muted, var(--neutral-text-3));
  transition: transform 0.2s ease;

  &.rotated {
    transform: rotate(90deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  /* 减少动态效果：取消入场与脉冲动画，仅保留静态高亮边框 */
  .ask-user-card:not(.answered) {
    animation: none;
  }

  .auc-arrow {
    transition: none;
  }
}

/* 展开态限高 220px，内部纵向滚动（§18.4.1） */
.auc-summary-body {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--chat-border, var(--neutral-border));
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 220px;
  overflow-y: auto;
}

/* 问题 / 回答分行：问题次级文本色、回答主文本色（§18.4.2） */
.auc-qa-q {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--chat-text-secondary, var(--neutral-text-2));
  white-space: pre-wrap;
  word-break: break-word;
}

.auc-qa-a {
  margin-top: 2px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--chat-text-primary, var(--neutral-text-1));
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
