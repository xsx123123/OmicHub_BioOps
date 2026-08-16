<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NDrawer,
  NDrawerContent,
  NCard,
  NSpace,
  NButton,
  NPopconfirm,
  NInput,
  NModal,
  useMessage,
} from 'naive-ui'
import apiClient from '@/api/client'
import type { PendingDoc, DocAuditRequest } from '@/types/knowledge'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  audited: []
}>()

const message = useMessage()

const pendingDocs = ref<PendingDoc[]>([])
const loading = ref(false)
const rejectModal = ref({
  show: false,
  docId: '',
  reason: '',
})

const hasPending = computed(() => pendingDocs.value.length > 0)

async function fetchPending() {
  loading.value = true
  try {
    const res = await apiClient.get<PendingDoc[]>('/docs/knowledge/audit/pending')
    pendingDocs.value = res.data
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '获取待审核列表失败')
  } finally {
    loading.value = false
  }
}

function openReject(docId: string) {
  rejectModal.value = { show: true, docId, reason: '' }
}

async function handleAudit(docId: string, action: 'approve' | 'reject', reason?: string) {
  if (action === 'reject' && !reason?.trim()) {
    message.error('请填写拒绝原因')
    return
  }
  try {
    const payload: DocAuditRequest = { action, reason: reason?.trim() }
    await apiClient.post(`/docs/knowledge/${docId}/audit`, payload)
    message.success(action === 'approve' ? '已通过' : '已拒绝')
    await fetchPending()
    emit('audited')
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '审核操作失败')
  }
}

async function confirmReject() {
  await handleAudit(rejectModal.value.docId, 'reject', rejectModal.value.reason)
  rejectModal.value.show = false
}

// 抽屉打开时自动刷新
function handleOpen() {
  void fetchPending()
}
</script>

<template>
  <NDrawer
    :show="props.show"
    :width="420"
    placement="right"
    @update:show="(v) => emit('update:show', v)"
    @after-enter="handleOpen"
  >
    <NDrawerContent title="待审核文档" closable>
      <div v-if="!hasPending && !loading" class="empty-text">暂无待审核文档</div>
      <NSpace v-else vertical size="medium">
        <NCard
          v-for="doc in pendingDocs"
          :key="doc.id"
          size="small"
          :title="doc.title"
          :segmented="{ content: true }"
        >
          <template #header-extra>
            <span class="category-tag">{{ doc.category }}</span>
          </template>
          <div class="pending-meta">
            <p><strong>提交者：</strong>{{ doc.submitter || '未知' }}</p>
            <p><strong>变更：</strong>{{ doc.editSummary || '无摘要' }}</p>
            <p v-if="doc.createdAt"><strong>时间：</strong>{{ new Date(doc.createdAt).toLocaleString() }}</p>
          </div>
          <template #footer>
            <NSpace justify="end" size="small">
              <NButton size="small" type="success" @click="handleAudit(doc.id, 'approve')">
                通过
              </NButton>
              <NButton size="small" type="error" @click="openReject(doc.id)">
                拒绝
              </NButton>
            </NSpace>
          </template>
        </NCard>
      </NSpace>
    </NDrawerContent>
  </NDrawer>

  <NModal
    v-model:show="rejectModal.show"
    preset="dialog"
    title="填写拒绝原因"
    positive-text="确认拒绝"
    negative-text="取消"
    @positive-click="confirmReject"
  >
    <NInput
      v-model:value="rejectModal.reason"
      type="textarea"
      placeholder="请说明拒绝原因，便于提交者修改"
      :rows="4"
    />
  </NModal>
</template>

<style scoped>
.empty-text {
  text-align: center;
  color: var(--neutral-text-3);
  padding: 32px 0;
}

.category-tag {
  font-size: 12px;
  color: var(--neutral-text-3);
  background: var(--neutral-hover);
  padding: 2px 8px;
  border-radius: 4px;
}

.pending-meta {
  font-size: 13px;
  color: var(--neutral-text-2);
  line-height: 1.8;
}

.pending-meta p {
  margin: 0;
}
</style>
