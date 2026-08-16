<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NModal, NSpin } from 'naive-ui'

const props = defineProps<{ sourceUrl: string; caseId: string; title?: string }>()

const visible = ref(false)
const loading = ref(false)
const error = ref('')
const reportHtml = ref('')
const filename = computed(() => props.title || '动态分析报告')

function allowedReportUrl(): URL | null {
  try {
    const url = new URL(props.sourceUrl, window.location.origin)
    const sameOriginApi = url.origin === window.location.origin
      && url.pathname.startsWith(`/api/v1/agent-teams/cases/${encodeURIComponent(props.caseId)}/`)
    const caseArtifact = url.protocol === 'https:'
      && url.pathname.includes(`/agentteams-evidence/${props.caseId}/`)
    return sameOriginApi || caseArtifact ? url : null
  } catch {
    return null
  }
}

function injectContentSecurityPolicy(html: string): string {
  const policy = "default-src 'none'; img-src data: blob:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; media-src data: blob:; frame-src 'none'; form-action 'none'; base-uri 'none'"
  const meta = `<meta http-equiv="Content-Security-Policy" content="${policy}">`
  return /<head[\s>]/i.test(html) ? html.replace(/<head([^>]*)>/i, `<head$1>${meta}`) : `${meta}${html}`
}

async function openPreview() {
  const url = allowedReportUrl()
  visible.value = true
  if (!url) {
    error.value = '报告地址不属于当前 Case 的受控产物前缀。'
    return
  }
  loading.value = true
  error.value = ''
  reportHtml.value = ''
  try {
    const response = await fetch(url, {
      credentials: url.origin === window.location.origin ? 'same-origin' : 'omit',
      headers: { Accept: 'text/html' },
      referrerPolicy: 'no-referrer',
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    if (!(response.headers.get('content-type') || '').includes('text/html')) {
      throw new Error('产物不是 HTML 报告')
    }
    reportHtml.value = injectContentSecurityPolicy(await response.text())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '报告加载失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <NButton size="tiny" secondary @click.stop="openPreview">安全预览</NButton>
  <NModal v-model:show="visible" preset="card" :title="filename" :style="{ width: 'min(96vw, 1180px)' }">
    <NSpin :show="loading">
      <NAlert v-if="error" type="error" :show-icon="true">{{ error }}</NAlert>
      <iframe
        v-else-if="reportHtml"
        class="agentteams-report-frame"
        :srcdoc="reportHtml"
        sandbox="allow-scripts"
        referrerpolicy="no-referrer"
        title="AgentTeams 动态报告安全预览"
      />
    </NSpin>
  </NModal>
</template>

<style scoped>
.agentteams-report-frame {
  width: 100%;
  height: min(72vh, 820px);
  border: 1px solid var(--chat-border);
  border-radius: 8px;
  background: var(--neutral-card);
}
</style>
