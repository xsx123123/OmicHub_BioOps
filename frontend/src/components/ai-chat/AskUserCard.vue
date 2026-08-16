<script setup lang="ts">
/**
 * AskUserCard — ask_user 澄清工具的可交互卡片
 *
 * 未回答：分页问题向导（选项点选 / "其他"自由输入 / 跳过 Esc / 下一步或提交）。
 * 已回答：折叠为工具卡片样式（"询问工具 | 已收集信息"），展开可回看问答。
 */
import { ref, computed } from 'vue'
import { NButton, NIcon, NInput, NTag } from 'naive-ui'
import {
  ChatboxEllipsesOutline,
  CheckmarkOutline,
  ChevronForwardOutline,
  CreateOutline,
} from '@vicons/ionicons5'
import type { AskRequest } from './types'

const props = defineProps<{ ask: AskRequest }>()

const emit = defineEmits<{
  submit: [answers: string[]]
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

const current = computed(() => questions.value[currentIndex.value])
const isLast = computed(() => currentIndex.value >= total.value - 1)
/** 当前题有效答案：自由输入优先，其次点选选项 */
const currentAnswer = computed(
  () => otherTexts.value[currentIndex.value]?.trim() || selections.value[currentIndex.value] || '',
)

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
}

function toggleOther() {
  showOther.value[currentIndex.value] = !showOther.value[currentIndex.value]
  if (showOther.value[currentIndex.value]) selections.value[currentIndex.value] = ''
}

function onOtherInput(value: string) {
  otherTexts.value[currentIndex.value] = value
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
function submit() {
  if (submitting.value) return
  submitting.value = true
  emit(
    'submit',
    questions.value.map((_, i) => otherTexts.value[i]?.trim() || selections.value[i] || ''),
  )
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && !props.ask.answered) skip()
}

// ---------- 已回答：工具卡片样式，默认展开可回看问答 ----------
const collapsed = ref(false)
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
    v-if="!ask.answered"
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
        v-if="current?.options?.length"
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
        v-if="showOther[currentIndex]"
        :value="otherTexts[currentIndex]"
        size="small"
        placeholder="输入你的回答…"
        class="auc-other-input"
        @update:value="onOtherInput"
        @keydown.stop
      />
    </div>

    <div class="auc-footer">
      <n-button size="small" quaternary @click="skip">
        跳过
        <span class="auc-key-hint">Esc</span>
      </n-button>
      <n-button
        size="small"
        type="primary"
        :disabled="!currentAnswer"
        :loading="submitting"
        @click="next"
      >
        {{ isLast ? '提交' : '下一步' }} →
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
      <n-tag size="tiny" type="success" :bordered="false">已收集信息</n-tag>
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
  background: var(--chat-ai-card, #ffffff);
  border: 1px solid rgba(99, 102, 241, 0.35);
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  outline: none;
}

.ask-user-card.answered {
  padding: 8px 12px;
  border-color: var(--chat-border, #e5e7eb);
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
  color: var(--chat-text-primary, #1a1a1a);
  white-space: pre-wrap;
  word-break: break-word;
}

.auc-pager {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  color: var(--chat-text-muted, #999);
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
  border: 1px solid var(--chat-border, #e5e7eb);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;

  &:hover {
    border-color: var(--chat-accent, #4f8ef7);
  }

  &.selected {
    border-color: var(--chat-accent, #4f8ef7);
    background: rgba(79, 142, 247, 0.08);
  }
}

.auc-option-marker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  color: var(--chat-accent, #4f8ef7);
}

.auc-option-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  font-size: 11px;
  color: var(--chat-text-muted, #999);
  background: var(--chat-hover, #f3f4f6);
  border-radius: 4px;
}

.auc-option-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--chat-text-primary, #1a1a1a);
  word-break: break-word;
}

.auc-other .auc-option-marker {
  color: var(--chat-text-muted, #999);
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

.auc-key-hint {
  margin-left: 4px;
  padding: 0 4px;
  font-size: 11px;
  color: var(--chat-text-muted, #999);
  border: 1px solid var(--chat-border, #e5e7eb);
  border-radius: 4px;
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
  color: var(--chat-accent, #4f8ef7);
  flex-shrink: 0;
}

.auc-tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--chat-text-primary, #1a1a1a);
}

.auc-divider {
  font-size: 12px;
  color: var(--chat-text-muted, #ccc);
}

.auc-arrow {
  margin-left: auto;
  color: var(--chat-text-muted, #999);
  transition: transform 0.2s ease;

  &.rotated {
    transform: rotate(90deg);
  }
}

.auc-summary-body {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--chat-border, #e5e7eb);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.auc-qa-q {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--chat-text-primary, #1a1a1a);
  white-space: pre-wrap;
  word-break: break-word;
}

.auc-qa-a {
  margin-top: 2px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--chat-text-muted, #888);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
