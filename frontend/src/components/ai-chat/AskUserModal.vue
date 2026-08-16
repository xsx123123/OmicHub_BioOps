<script setup lang="ts">
import { NModal } from 'naive-ui'
import AskUserCard from './AskUserCard.vue'
import type { AskRequest } from './types'

const props = defineProps<{
  show: boolean
  ask: AskRequest | null
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [answers: string[]]
}>()

function close(): void {
  emit('update:show', false)
}

function submit(answers: string[]): void {
  emit('submit', answers)
}
</script>

<template>
  <NModal
    :show="props.show && !!props.ask"
    preset="card"
    title="确认分析方案"
    :mask-closable="false"
    :close-on-esc="true"
    :bordered="false"
    :style="{ width: 'min(560px, calc(100vw - 32px))' }"
    aria-label="确认分析方案"
    @update:show="(value) => value ? undefined : close()"
  >
    <div class="ask-modal-intro">
      <span class="ask-modal-eyebrow">AI 执行前确认</span>
      <p>分析尚未开始。请确认是否按当前方案继续，或返回调整分析参数。</p>
    </div>
    <AskUserCard v-if="props.ask" :ask="props.ask" @submit="submit" />
  </NModal>
</template>

<style scoped>
.ask-modal-intro {
  margin-bottom: 4px;
}

.ask-modal-eyebrow {
  color: var(--brand-primary, #4f8ef7);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ask-modal-intro p {
  margin: 6px 0 0;
  color: var(--neutral-text-2, #667085);
  font-size: 13px;
  line-height: 1.6;
}

:deep(.ask-user-card) {
  margin-top: 16px;
  padding: 0;
  border: 0;
  box-shadow: none;
}
</style>
