<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'
import { useRouter } from 'vue-router'
import { NButton } from 'naive-ui'
import ErrorPage from '@/components/ErrorPage.vue'

const router = useRouter()
const hasError = ref(false)
const errorMessage = ref('')
const errorInfo = ref('')

onErrorCaptured((err, instance, info) => {
  hasError.value = true
  errorMessage.value = err instanceof Error ? err.message : String(err)
  errorInfo.value = info
  console.error('[AppErrorBoundary]', err, info, instance)
  return false
})

function reload() {
  window.location.reload()
}
</script>

<template>
  <ErrorPage
    v-if="hasError"
    code="500"
    title="页面出了点小问题"
    :hint="errorMessage || '渲染异常，请刷新重试'"
  >
    <template #actions>
      <NButton type="primary" size="large" @click="reload">刷新页面</NButton>
      <NButton size="large" ghost color="white" text-color="white" @click="router.push('/')">
        返回首页
      </NButton>
    </template>
    <details v-if="errorInfo" class="error-detail">
      <summary>技术详情</summary>
      <p class="error-detail-info">{{ errorInfo }}</p>
    </details>
  </ErrorPage>
  <slot v-else />
</template>

<style scoped>
.error-detail {
  margin-top: 24px;
  font-size: 12px;
  opacity: 0.7;
  color: white;
}

.error-detail summary {
  cursor: pointer;
}

.error-detail-info {
  margin-top: 8px;
  word-break: break-all;
}
</style>
