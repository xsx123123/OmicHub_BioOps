<script setup lang="ts">
import { ref, watch } from 'vue'
import { NModal, NInput, NButton, NSpace, useMessage } from 'naive-ui'
import apiClient from '@/api/client'
import { displayName } from '@/utils/displayName'

interface TargetUser {
  id: string
  username: string
  nickname?: string | null
  admin_note?: string | null
}

const props = defineProps<{ show: boolean; user: TargetUser | null }>()
const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'success', note: string): void
}>()

const message = useMessage()
const submitting = ref(false)
const noteText = ref('')

// 弹窗打开时载入当前备注
watch(
  () => props.user,
  (u) => {
    noteText.value = u?.admin_note ?? ''
  },
)

function close() {
  emit('update:show', false)
}

async function handleSubmit() {
  if (!props.user) return
  const text = noteText.value.trim()
  if (text.length > 1000) {
    message.error('备注长度不能超过 1000 字符')
    return
  }
  submitting.value = true
  try {
    await apiClient.put(`/admin/users/${props.user.id}/note`, null, {
      params: { note: text },
    })
    message.success(text ? '备注已保存' : '备注已清除')
    emit('success', text)
    close()
  } catch (error: any) {
    message.error(error.response?.data?.detail || '保存失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <NModal
    :show="props.show"
    :auto-focus="false"
    :mask-closable="true"
    transform-origin="center"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div class="note-modal">
      <h3 class="note-title">编辑管理员备注</h3>
      <p v-if="props.user" class="note-desc">
        用户：{{ displayName(props.user) }}
        <span class="note-hint">（仅管理员可见）</span>
      </p>

      <NInput
        v-model:value="noteText"
        type="textarea"
        :autosize="{ minRows: 4, maxRows: 8 }"
        :maxlength="1000"
        show-count
        placeholder="记录辅助信息，如：客户要求延期、测试账号、合作项目代号等"
      />

      <NSpace justify="end" class="note-actions">
        <NButton @click="close">取消</NButton>
        <NButton type="primary" :loading="submitting" @click="handleSubmit">保存</NButton>
      </NSpace>
    </div>
  </NModal>
</template>

<style scoped>
.note-modal {
  width: 480px;
  max-width: calc(100vw - 32px);
  background: var(--neutral-card, #fff);
  border-radius: 12px;
  padding: 24px;
  box-sizing: border-box;
}
.note-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}
.note-desc {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
}
.note-hint {
  font-size: 12px;
  opacity: 0.8;
}
.note-actions {
  margin-top: 16px;
  width: 100%;
}
</style>
