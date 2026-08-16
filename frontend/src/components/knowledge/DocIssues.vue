<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NButton,
  NInput,
  NSpace,
  NTag,
  NPopconfirm,
  useMessage,
} from 'naive-ui'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { IssueItem, IssueCreateRequest } from '@/types/knowledge'
import { displayName } from '@/utils/displayName'

const props = defineProps<{
  docId: string
  issues: IssueItem[]
}>()

const emit = defineEmits<{
  refresh: []
}>()

const message = useMessage()
const authStore = useAuthStore()

const isAdmin = computed(() => authStore.isAdmin)
const currentUserName = computed(() => displayName(authStore.user))

const newContent = ref('')
const replyTarget = ref<{ id: string; userName: string } | null>(null)
const sending = ref(false)

const topIssues = computed(() => props.issues)

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString()
}

function startReply(issue: IssueItem) {
  replyTarget.value = { id: issue.id, userName: issue.userName }
}

function cancelReply() {
  replyTarget.value = null
}

async function sendIssue() {
  const content = newContent.value.trim()
  if (!content) {
    message.error('请输入留言内容')
    return
  }
  sending.value = true
  try {
    const payload: IssueCreateRequest = {
      content,
      replyTo: replyTarget.value?.id || null,
    }
    await apiClient.post(`/docs/knowledge/${props.docId}/issues`, payload)
    message.success(replyTarget.value ? '回复成功' : '留言成功')
    newContent.value = ''
    replyTarget.value = null
    emit('refresh')
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '发送失败')
  } finally {
    sending.value = false
  }
}

async function deleteIssue(issueId: string) {
  try {
    await apiClient.delete(`/docs/knowledge/issues/${issueId}`)
    message.success('已删除')
    emit('refresh')
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '删除失败')
  }
}

async function resolveIssue(issueId: string) {
  try {
    await apiClient.post(`/docs/knowledge/issues/${issueId}/resolve`)
    message.success('已标记为已解决')
    emit('refresh')
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '操作失败')
  }
}

function canDelete(issue: IssueItem | IssueItem['replies'][number]): boolean {
  return isAdmin.value || issue.userName === currentUserName.value
}
</script>

<template>
  <div class="doc-issues">
    <div class="section-title">💬 讨论 ({{ topIssues.length }})</div>

    <div v-if="!topIssues.length" class="empty-text">暂无讨论，来说两句吧～</div>

    <div v-for="issue in topIssues" :key="issue.id" class="issue-card">
      <div class="issue-header">
        <span class="issue-author">{{ issue.userName }}</span>
        <span class="issue-time">{{ formatTime(issue.createdAt) }}</span>
        <NTag v-if="issue.status === 1" size="small" type="success">已解决</NTag>
        <NTag v-else-if="issue.status === 2" size="small" type="default">已关闭</NTag>
      </div>
      <div class="issue-content">{{ issue.content }}</div>
      <NSpace size="small" class="issue-actions">
        <NButton size="tiny" text @click="startReply(issue)">回复</NButton>
        <NButton
          v-if="isAdmin && issue.status === 0"
          size="tiny"
          text
          type="success"
          @click="resolveIssue(issue.id)"
        >
          标记已解决
        </NButton>
        <NPopconfirm v-if="canDelete(issue)" @positive-click="deleteIssue(issue.id)">
          <template #trigger>
            <NButton size="tiny" text type="error">删除</NButton>
          </template>
          确定删除这条留言？
        </NPopconfirm>
      </NSpace>

      <!-- 回复列表 -->
      <div v-if="issue.replies?.length" class="replies">
        <div v-for="reply in issue.replies" :key="reply.id" class="reply-item">
          <div class="issue-header">
            <span class="issue-author">{{ reply.userName }}</span>
            <span class="issue-time">{{ formatTime(reply.createdAt) }}</span>
          </div>
          <div class="issue-content">{{ reply.content }}</div>
          <NSpace v-if="canDelete(reply)" size="small" class="issue-actions">
            <NPopconfirm @positive-click="deleteIssue(reply.id)">
              <template #trigger>
                <NButton size="tiny" text type="error">删除</NButton>
              </template>
              确定删除这条回复？
            </NPopconfirm>
          </NSpace>
        </div>
      </div>
    </div>

    <!-- 新建留言/回复输入区 -->
    <div class="issue-input-area">
      <div v-if="replyTarget" class="reply-tip">
        回复 <strong>{{ replyTarget.userName }}</strong>
        <NButton size="tiny" text @click="cancelReply">取消</NButton>
      </div>
      <div class="issue-input-wrapper">
        <NInput
          v-model:value="newContent"
          type="textarea"
          class="issue-textarea"
          :placeholder="replyTarget ? '写下你的回复…' : '写下你的评论…'"
          :autosize="{ minRows: 3, maxRows: 8 }"
        />
        <NButton
          type="primary"
          size="small"
          class="issue-send-btn"
          :loading="sending"
          @click="sendIssue"
        >
          发送
        </NButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.doc-issues {
  margin-top: 48px;
  padding-top: 32px;
  border-top: 1px solid var(--neutral-border);
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin-bottom: 16px;
}

.empty-text {
  color: var(--neutral-text-3);
  font-size: 13px;
  padding: 12px 0;
}

.issue-card {
  background: var(--neutral-hover);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}

.issue-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.issue-author {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.issue-time {
  font-size: 12px;
  color: var(--neutral-text-3);
}

.issue-content {
  font-size: 14px;
  color: var(--neutral-text-2);
  line-height: 1.6;
  white-space: pre-wrap;
}

.issue-actions {
  margin-top: 8px;
}

.replies {
  margin-top: 12px;
  padding-left: 16px;
  border-left: 2px solid var(--neutral-border);
}

.reply-item {
  margin-top: 10px;
}

.issue-input-area {
  margin-top: 24px;
}

.reply-tip {
  font-size: 13px;
  color: var(--neutral-text-2);
  margin-bottom: 10px;
}

.issue-input-wrapper {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-end;
}

.issue-textarea {
  width: 100%;
}

.issue-textarea :deep(.n-input__textarea-el) {
  min-height: 80px;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid var(--neutral-border);
  background-color: var(--neutral-card);
  color: var(--neutral-text-1);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  resize: vertical;
}

.issue-textarea :deep(.n-input__textarea-el:focus) {
  border-color: var(--arco-primary);
  box-shadow: 0 0 0 2px var(--arco-primary-light);
}

.issue-textarea :deep(.n-input__placeholder) {
  color: var(--neutral-text-3);
}

.issue-send-btn {
  flex-shrink: 0;
  border-radius: 6px;
  padding: 0 18px;
}
</style>
