<script setup lang="ts">
import { ref, watch } from 'vue'
import { NModal, NForm, NFormItem, NInputNumber, NButton, NSpace, useMessage } from 'naive-ui'
import apiClient from '@/api/client'
import { displayName } from '@/utils/displayName'

interface TargetUser {
  id: string
  username: string
  nickname?: string | null
  storage_quota: number
  used_storage: number
}

const props = defineProps<{ show: boolean; user: TargetUser | null }>()
const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const submitting = ref(false)
const quotaGb = ref<number>(500)

function toGb(bytes: number) {
  return Number((bytes / 1024 / 1024 / 1024).toFixed(2))
}

watch(
  () => props.user,
  (u) => {
    if (u) quotaGb.value = toGb(u.storage_quota)
  },
)

function close() {
  emit('update:show', false)
}

async function handleSubmit() {
  if (!props.user) return
  if (quotaGb.value <= 0) {
    message.error('配额必须大于 0')
    return
  }
  if (quotaGb.value > 5120) {
    message.error('单用户配额上限 5 TiB')
    return
  }
  submitting.value = true
  try {
    await apiClient.put(`/admin/users/${props.user.id}/quota`, null, {
      params: { storage_quota_gb: quotaGb.value },
    })
    message.success(`已将 ${displayName(props.user)} 配额调整为 ${quotaGb.value} GiB`)
    close()
    emit('success')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '调整失败')
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
    <div class="quota-modal">
      <h3 class="quota-title">调整存储配额</h3>
      <p v-if="props.user" class="quota-desc">
        用户：{{ displayName(props.user) }}　当前已用：
        {{ toGb(props.user.used_storage) }} GiB
      </p>

      <NForm label-placement="top" size="medium">
        <NFormItem label="存储配额 (GiB)">
          <NInputNumber
            v-model:value="quotaGb"
            :min="0"
            :max="5120"
            :step="50"
            style="width: 100%"
            placeholder="单位 GiB，上限 5120（5 TiB）"
          />
        </NFormItem>
        <NSpace justify="end" class="quota-actions">
          <NButton @click="close">取消</NButton>
          <NButton type="primary" :loading="submitting" @click="handleSubmit">保存</NButton>
        </NSpace>
      </NForm>
    </div>
  </NModal>
</template>

<style scoped>
.quota-modal {
  width: 420px;
  max-width: calc(100vw - 32px);
  background: var(--neutral-card, #fff);
  border-radius: 12px;
  padding: 24px;
  box-sizing: border-box;
}
.quota-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}
.quota-desc {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
}
.quota-actions {
  margin-top: 8px;
  width: 100%;
}
</style>
