<script setup lang="ts">
import { ref, reactive } from 'vue'
import {
  NModal, NForm, NFormItem, NInput, NButton, NSpace, useMessage,
} from 'naive-ui'
import apiClient from '@/api/client'

/**
 * 管理员添加用户弹窗
 * - 字段校验复用注册页风格：用户名/邮箱/密码 + 确认密码
 * - 创建即为 active，无需审批
 */
const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const formRef = ref()
const submitting = ref(false)

const formData = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  lab_group: '',
})

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度 3-50 字符', trigger: 'blur' },
    {
      pattern: /^[a-zA-Z0-9_]+$/,
      message: '仅支持字母/数字/下划线',
      trigger: 'blur',
    },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    {
      pattern: /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/,
      message: '邮箱格式不正确',
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码长度 8-128 字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string) =>
        value === formData.password || new Error('两次输入的密码不一致'),
      trigger: 'blur',
    },
  ],
}

function resetForm() {
  formData.username = ''
  formData.email = ''
  formData.password = ''
  formData.confirmPassword = ''
  formData.lab_group = ''
  formRef.value?.restoreValidation?.()
}

function close() {
  emit('update:show', false)
}

async function handleSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    await apiClient.post('/admin/users', {
      username: formData.username,
      email: formData.email,
      password: formData.password,
      lab_group: formData.lab_group || null,
    })
    message.success(`用户 ${formData.username} 创建成功`)
    resetForm()
    close()
    emit('success')
  } catch (error: any) {
    const detail = error.response?.data?.detail || '创建失败'
    message.error(detail)
  } finally {
    submitting.value = false
  }
}

function handleUpdateShow(v: boolean) {
  if (!v) resetForm()
  emit('update:show', v)
}
</script>

<template>
  <NModal
    :show="props.show"
    :auto-focus="false"
    :mask-closable="true"
    transform-origin="center"
    @update:show="handleUpdateShow"
  >
    <div class="add-user-modal">
      <h3 class="add-user-title">添加用户</h3>
      <p class="add-user-desc">创建后账号即为启用状态，可直接登录。</p>

      <NForm ref="formRef" :model="formData" :rules="rules" label-placement="top" size="medium">
        <NFormItem label="用户名" path="username">
          <NInput v-model:value="formData.username" placeholder="字母/数字/下划线，3-50 字符" />
        </NFormItem>
        <NFormItem label="邮箱" path="email">
          <NInput v-model:value="formData.email" placeholder="请输入邮箱" />
        </NFormItem>
        <NFormItem label="所属课题组" path="lab_group">
          <NInput v-model:value="formData.lab_group" placeholder="可选，如：王鑫课题组" maxlength="120" />
        </NFormItem>
        <NFormItem label="密码" path="password">
          <NInput
            v-model:value="formData.password"
            type="password"
            show-password-on="click"
            placeholder="至少 8 位，含字母和数字"
          />
        </NFormItem>
        <NFormItem label="确认密码" path="confirmPassword">
          <NInput
            v-model:value="formData.confirmPassword"
            type="password"
            show-password-on="click"
            placeholder="请再次输入密码"
          />
        </NFormItem>

        <NSpace justify="end" class="add-user-actions">
          <NButton @click="close">取消</NButton>
          <NButton type="primary" :loading="submitting" @click="handleSubmit">创建</NButton>
        </NSpace>
      </NForm>
    </div>
  </NModal>
</template>

<style scoped>
.add-user-modal {
  width: 420px;
  max-width: calc(100vw - 32px);
  background: var(--neutral-card, #fff);
  border-radius: 12px;
  padding: 24px;
  box-sizing: border-box;
}
.add-user-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}
.add-user-desc {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
}
.add-user-actions {
  margin-top: 8px;
  width: 100%;
}
</style>
