<template>
  <n-modal
    :show="show"
    preset="dialog"
    :title="title"
    :positive-text="confirmText"
    :negative-text="cancelText"
    :loading="loading"
    :closable="!loading"
    :mask-closable="!loading"
    @positive-click="handleConfirm"
    @negative-click="handleCancel"
    @update:show="handleUpdateShow"
  >
    <template #icon>
      <n-icon size="22" color="#F0A020">
        <ShieldCheckmarkOutline />
      </n-icon>
    </template>
    <div class="totp-confirm-body">
      <p class="totp-confirm-desc">{{ description }}</p>
      <n-input
        ref="inputRef"
        v-model:value="code"
        placeholder="请输入 6 位动态验证码"
        maxlength="6"
        size="large"
        :input-props="{ inputmode: 'numeric', autocomplete: 'one-time-code' }"
        @keyup.enter="handleConfirm"
      />
      <p class="totp-confirm-hint">
        请打开 Authenticator 应用，查看当前 6 位验证码。管理员敏感操作需二次校验。
      </p>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { NModal, NInput, NIcon } from 'naive-ui'
import { ShieldCheckmarkOutline } from '@vicons/ionicons5'

const props = withDefaults(defineProps<{
  show: boolean
  title?: string
  description?: string
  confirmText?: string
  cancelText?: string
  loading?: boolean
}>(), {
  title: '管理员二次验证',
  description: '该操作属于高敏感操作，请输入当前 TOTP 验证码以继续。',
  confirmText: '确认',
  cancelText: '取消',
  loading: false,
})

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'confirm', code: string): void
  (e: 'cancel'): void
}>()

const code = ref('')
const inputRef = ref<InstanceType<typeof NInput> | null>(null)

watch(() => props.show, (visible) => {
  if (visible) {
    code.value = ''
    nextTick(() => {
      inputRef.value?.focus()
    })
  }
})

function handleConfirm() {
  if (!/^\d{6}$/.test(code.value)) {
    return false // 阻止关闭，等待合法输入
  }
  emit('confirm', code.value)
  // 由父组件控制 show/loading；如果未加载则关闭
  if (!props.loading) {
    emit('update:show', false)
  }
  return false
}

function handleCancel() {
  emit('cancel')
  emit('update:show', false)
}

function handleUpdateShow(value: boolean) {
  if (!value && !props.loading) {
    emit('cancel')
  }
  emit('update:show', value)
}
</script>

<style scoped>
.totp-confirm-body {
  padding-top: 8px;
}
.totp-confirm-desc {
  margin: 0 0 16px;
  font-size: 14px;
  color: var(--neutral-text-2);
  line-height: 1.6;
}
.totp-confirm-hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--neutral-text-3);
  line-height: 1.5;
}
</style>
