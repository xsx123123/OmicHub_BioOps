<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NForm, NFormItem, NInput, NIcon, useMessage } from 'naive-ui'
import type { FormRules } from 'naive-ui'
import { Planet, PersonOutline, MailOutline, LockClosedOutline } from '@vicons/ionicons5'
import { markSetupComplete } from '@/router'
import { useAuthStore } from '@/stores/auth'
import type { RegisterRequest } from '@/types'

const router = useRouter()
const authStore = useAuthStore()
const message = useMessage()

const loading = ref(false)
const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度为 3-50 个字符', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_]+$/, message: '用户名只能包含字母、数字和下划线', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码长度为 8-128 个字符', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string) => {
        if (!/[A-Za-z]/.test(value)) return new Error('密码必须包含至少一个字母')
        if (!/\d/.test(value)) return new Error('密码必须包含至少一个数字')
        return true
      },
      trigger: 'blur',
    },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string) => {
        if (value !== form.password) return new Error('两次输入的密码不一致')
        return true
      },
      trigger: 'blur',
    },
  ],
}

const formRef = ref<InstanceType<typeof NForm> | null>(null)

async function handleSetup(e: Event) {
  e.preventDefault()
  if (loading.value) return

  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  loading.value = true
  try {
    const req: RegisterRequest = {
      username: form.username,
      email: form.email,
      password: form.password,
    }
    await authStore.setupFirstAdmin(req)
    markSetupComplete()
    message.success('root 管理员账号创建成功，欢迎进入 CygnusX')
    router.push('/')
  } catch (error: any) {
    const detail = error.response?.data?.detail || '初始化失败，请稍后重试'
    message.error(detail)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="setup-page" aria-label="初始化 CygnusX" :aria-busy="loading">
    <div class="setup-overlay" />
    <div class="setup-content">
      <NCard class="setup-card" :bordered="false">
        <div class="setup-header">
          <NIcon :size="56" class="setup-icon">
            <Planet />
          </NIcon>
          <h1 class="setup-title">
            欢迎来到 CygnusX
          </h1>
          <p class="setup-subtitle">
            首次使用，请创建 root 管理员账号
          </p>
        </div>

        <NForm ref="formRef" :model="form" :rules="rules" label-placement="top" size="large">
          <NFormItem label="用户名" path="username">
            <NInput v-model:value="form.username" placeholder="root / admin" clearable>
              <template #prefix>
                <NIcon :component="PersonOutline" />
              </template>
            </NInput>
          </NFormItem>

          <NFormItem label="邮箱" path="email">
            <NInput v-model:value="form.email" placeholder="admin@example.com" clearable>
              <template #prefix>
                <NIcon :component="MailOutline" />
              </template>
            </NInput>
          </NFormItem>

          <NFormItem label="密码" path="password">
            <NInput v-model:value="form.password" type="password" show-password-on="mousedown" placeholder="至少 8 位，包含字母和数字">
              <template #prefix>
                <NIcon :component="LockClosedOutline" />
              </template>
            </NInput>
          </NFormItem>

          <NFormItem label="确认密码" path="confirmPassword">
            <NInput v-model:value="form.confirmPassword" type="password" show-password-on="mousedown" placeholder="再次输入密码">
              <template #prefix>
                <NIcon :component="LockClosedOutline" />
              </template>
            </NInput>
          </NFormItem>

          <NButton type="primary" size="large" block :loading="loading" @click="handleSetup">
            创建管理员账号
          </NButton>
        </NForm>

        <p class="setup-hint">
          该账号将拥有系统最高权限，请妥善保管密码。
        </p>
      </NCard>
    </div>
  </main>
</template>

<style scoped>
.setup-page {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background-image: url('/backgrounds/milky-way.png');
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
}

.setup-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    135deg,
    rgba(8, 12, 26, 0.78) 0%,
    rgba(16, 20, 38, 0.62) 50%,
    rgba(8, 12, 26, 0.78) 100%
  );
}

.setup-content {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 440px;
  padding: 24px;
}

.setup-card {
  background: rgba(20, 24, 40, 0.8);
  backdrop-filter: blur(14px);
  border-radius: 18px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
  color: #f0f2f8;
}

.setup-card :deep(.n-card__content) {
  padding: 36px;
}

.setup-header {
  text-align: center;
  margin-bottom: 28px;
}

.setup-icon {
  color: #a5b4fc;
  margin-bottom: 14px;
}

.setup-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0 0 8px;
  background: linear-gradient(90deg, #a5b4fc, #67e8f9);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.setup-subtitle {
  font-size: 15px;
  color: #94a3b8;
  margin: 0;
}

.setup-card :deep(.n-form-item-label) {
  color: #cbd5e1;
  font-weight: 500;
}

.setup-card :deep(.n-input) {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 8px;
}

.setup-card :deep(.n-input__input-el),
.setup-card :deep(.n-input__placeholder) {
  color: #e2e8f0;
}

.setup-card :deep(.n-input__prefix) {
  color: #94a3b8;
}

.setup-hint {
  margin: 20px 0 0;
  text-align: center;
  font-size: 12px;
  color: #64748b;
}

@media (max-width: 480px) {
  .setup-card :deep(.n-card__content) {
    padding: 24px;
  }
}
</style>
