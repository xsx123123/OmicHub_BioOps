<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NSpin, NTag } from 'naive-ui'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import ErrorPage from '@/components/ErrorPage.vue'
import { studioApi, type SharedStudioSession, type SharedToolInvocation } from '@/api/studio'
import PageHeader from '@/components/PageHeader.vue'

const route = useRoute()
const token = computed(() => String(route.params.token || ''))
const loading = ref(true)
const snapshot = ref<SharedStudioSession | null>(null)
const failed = ref(false)

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

/** R4：工具卡代码/路径摘要（arguments.code 优先，其次 path），截断防撑爆布局 */
function toolArgsSummary(invocation: SharedToolInvocation): string {
  const args = invocation.arguments
  if (!args || typeof args !== 'object') return ''
  const raw = typeof args.code === 'string' ? args.code : typeof args.path === 'string' ? args.path : ''
  return raw.length > 600 ? `${raw.slice(0, 600)}…` : raw
}

function toolIsTruncated(invocation: SharedToolInvocation): boolean {
  return Boolean(
    invocation.result_truncation?.payload_truncated ||
      invocation.ui_payload_truncation?.payload_truncated,
  )
}

function printPage() {
  window.print()
}

onMounted(async () => {
  try {
    snapshot.value = await studioApi.getSharedSession(token.value)
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main class="shared-studio">
    <div v-if="loading" class="center-state" role="status" aria-live="polite" aria-busy="true">
      <n-spin size="large" />
      <p>正在加载只读工作台…</p>
    </div>

    <ErrorPage
      v-else-if="failed || !snapshot"
      code="404"
      title="分享链接不存在或已失效"
      hint="链接可能已过期、被撤销或输入不完整。"
    />

    <template v-else>
      <PageHeader
        :title="snapshot.title"
        :subtitle="`OmicStudio · 只读分享 · 创建于 ${formatTime(snapshot.created_at)} · 链接有效至 ${formatTime(snapshot.expires_at)}`"
      >
        <template #leading>
          <n-tag size="small" :bordered="false">{{ snapshot.agent_id || '未标注 Agent' }}</n-tag>
        </template>
        <template #actions>
          <n-button class="no-print" @click="printPage">打印 / 保存为 PDF</n-button>
        </template>
      </PageHeader>

      <section class="section">
        <h2>对话记录</h2>
        <div v-if="snapshot.messages.length" class="messages">
          <article
            v-for="(item, index) in snapshot.messages"
            :key="`${item.created_at}-${index}`"
            class="message-card"
            :class="item.role"
          >
            <header>
              <strong>{{ item.role === 'user' ? '用户' : 'AI 助手' }}</strong>
              <time>{{ formatTime(item.created_at) }}</time>
            </header>
            <MarkdownRenderer :content="item.content" />
            <!-- R4：工具执行历史摘要（被分享方可见完整执行过程，只读） -->
            <div
              v-if="item.metadata_json?.tool_invocations?.length"
              class="tool-list"
            >
              <div
                v-for="(invocation, toolIndex) in item.metadata_json.tool_invocations"
                :key="toolIndex"
                class="tool-item"
              >
                <header>
                  <code>{{ invocation.tool_name || 'tool' }}</code>
                  <n-tag
                    size="tiny"
                    :bordered="false"
                    :type="invocation.success ? 'success' : 'error'"
                  >
                    {{ invocation.success ? '成功' : '失败' }}
                  </n-tag>
                  <n-tag
                    v-if="toolIsTruncated(invocation)"
                    size="tiny"
                    :bordered="false"
                    type="warning"
                  >
                    输出已截断
                  </n-tag>
                </header>
                <pre v-if="toolArgsSummary(invocation)">{{ toolArgsSummary(invocation) }}</pre>
              </div>
            </div>
          </article>
        </div>
        <p v-else class="empty">暂无可分享的对话内容</p>
      </section>

      <section class="section">
        <h2>工作区产物</h2>
        <div v-if="snapshot.artifacts.length" class="artifacts">
          <a
            v-for="artifact in snapshot.artifacts"
            :key="artifact.path"
            :href="studioApi.sharedArtifactUrl(token, artifact.path)"
            class="artifact"
            target="_blank"
            rel="noopener noreferrer"
          >
            <code>{{ artifact.path }}</code>
            <span>
              {{ artifact.size.toLocaleString() }} bytes
              <template v-if="artifact.sha256"> · sha256 {{ artifact.sha256.slice(0, 12) }}…</template>
            </span>
          </a>
        </div>
        <p v-else class="empty">暂无 output 产物</p>
      </section>

      <footer>该页面为只读快照，不提供代码执行、文件写入或能力加载入口。</footer>
    </template>
  </main>
</template>

<style scoped>
.shared-studio {
  min-height: 100vh;
  padding: 36px clamp(20px, 5vw, 72px) 64px;
  color: var(--neutral-text-1, #172033);
  background: var(--neutral-bg-1, #f7f8fa);
}
.center-state {
  min-height: 70vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--neutral-text-3, #667085);
}
.page-header,
.section,
footer {
  max-width: 980px;
  margin-inline: auto;
}
.section {
  margin-top: 26px;
}
.section h2 {
  margin-bottom: 12px;
  font-size: 18px;
}
.messages,
.artifacts {
  display: grid;
  gap: 12px;
}
.message-card,
.artifact {
  border: 1px solid var(--neutral-border, #e4e7ec);
  border-radius: 12px;
  background: var(--neutral-bg-2, #fff);
}
.message-card {
  padding: 14px 16px;
  break-inside: avoid;
}
.message-card.assistant {
  border-left: 3px solid var(--primary-color, #3b82f6);
}
.message-card > header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
}
/* R4：工具执行历史摘要 */
.tool-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
  border-top: 1px dashed var(--neutral-border, #e4e7ec);
  padding-top: 10px;
}
.tool-item {
  border: 1px solid var(--neutral-border, #eef1f4);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
}
.tool-item > header {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0;
}
.tool-item pre {
  margin: 6px 0 0;
  padding: 8px;
  border-radius: 6px;
  background: var(--neutral-bg-3, #f8fafc);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 180px;
  overflow: auto;
}
time,
.artifact span,
.empty,
footer {
  color: var(--neutral-text-3, #667085);
  font-size: 12px;
}
.artifact {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  color: inherit;
  text-decoration: none;
}
.artifact:hover {
  border-color: var(--primary-color, #3b82f6);
}
footer {
  margin-top: 36px;
  text-align: center;
}
@media print {
  .shared-studio {
    padding: 0;
    background: white;
  }
  .no-print,
  footer {
    display: none;
  }
  .message-card,
  .artifact {
    box-shadow: none;
  }
}
</style>
