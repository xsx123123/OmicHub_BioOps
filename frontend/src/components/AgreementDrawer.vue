<script setup lang="ts">
import { computed, watch } from 'vue'
import { NButton, NDrawer, NDrawerContent, NSpin } from 'naive-ui'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { useAgreementText } from '@/composables/useAgreementText'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  agree: []
}>()

const { text, loading, error, fetchText } = useAgreementText()

const drawerWidth = computed(() => {
  if (typeof window === 'undefined') return 640
  return window.innerWidth <= 768 ? '100%' : 640
})

const htmlContent = computed(() => {
  if (!text.value) return ''
  const md = new MarkdownIt({ breaks: true, linkify: true })
  const raw = md.render(text.value)
  return DOMPurify.sanitize(raw)
})

watch(
  () => props.show,
  (visible) => {
    if (visible) fetchText()
  },
)

function close() {
  emit('update:show', false)
}

function agreeAndClose() {
  emit('agree')
  close()
}
</script>

<template>
  <NDrawer
    :show="show"
    :width="drawerWidth"
    placement="right"
    :mask-closable="true"
    @update:show="$emit('update:show', $event)"
  >
    <NDrawerContent title="OmicHub 平台服务协议" :native-scrollbar="false" closable>
      <div class="agreement-body">
        <NSpin v-if="loading" size="large" />
        <div v-else-if="error" class="agreement-error">{{ error }}</div>
        <div
          v-else
          class="agreement-markdown"
          v-html="htmlContent"
        />
      </div>

      <template #footer>
        <div class="agreement-footer">
          <NButton size="large" @click="close">不同意</NButton>
          <NButton type="primary" size="large" @click="agreeAndClose">同意并继续</NButton>
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.agreement-body {
  min-height: 200px;
  padding: 24px;
}
.agreement-markdown {
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-text-2, #4e5969);
}
.agreement-markdown :deep(h1) {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text-1, #1d2129);
  margin-bottom: 16px;
}
.agreement-markdown :deep(h2) {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text-1, #1d2129);
  margin-top: 24px;
  margin-bottom: 16px;
}
.agreement-markdown :deep(p) {
  margin-bottom: 16px;
}
.agreement-markdown :deep(ul) {
  padding-left: 20px;
  margin-bottom: 16px;
}
.agreement-markdown :deep(li) {
  margin-bottom: 8px;
}
.agreement-markdown :deep(strong) {
  color: var(--color-text-1, #1d2129);
}
.agreement-error {
  color: #f53f3f;
  text-align: center;
  padding: 48px 0;
}
.agreement-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
</style>
