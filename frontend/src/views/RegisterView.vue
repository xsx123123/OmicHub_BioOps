<template>
  <div class="register-page" role="main" aria-label="注册 CygnusX 账户">
    <StarField />
    <LoginPageQuote />

    <div class="register-content">
      <div class="register-card-wrapper">
        <div class="register-card animate-scale-in">
          <LogoAnimation size="small" />
          <div class="register-header">
            <h2 class="register-title gradient-text">注册账户</h2>
            <p class="register-subtitle">加入 CygnusX 多组学分析平台</p>
          </div>

          <n-alert v-if="registrationClosed" type="warning" :show-icon="true" class="error-alert">
            暂不接受新用户注册，如需账号请联系管理员。
          </n-alert>

          <div v-if="registrationClosed" class="register-actions register-actions--single">
            <n-button size="large" @click="$router.push('/login')">
              返回登录
            </n-button>
          </div>

          <n-form
            v-if="!registrationClosed"
            ref="formRef"
            :model="formData"
            :rules="rules"
            class="register-form"
          >
            <n-form-item label="用户名" path="username" class="form-item-half">
              <n-input
                v-model:value="formData.username"
                placeholder="字母/数字/下划线，3-50字符"
                size="large"
              >
                <template #prefix>
                  <n-icon :component="PersonOutline" />
                </template>
              </n-input>
            </n-form-item>

            <n-form-item label="邮箱" path="email" class="form-item-half">
              <n-input
                v-model:value="formData.email"
                placeholder="请输入邮箱地址"
                size="large"
              >
                <template #prefix>
                  <n-icon :component="MailOutline" />
                </template>
              </n-input>
            </n-form-item>

            <n-form-item label="密码" path="password" class="form-item-half">
              <n-input
                v-model:value="formData.password"
                type="password"
                show-password-on="click"
                placeholder="至少8位，包含字母和数字"
                size="large"
              >
                <template #prefix>
                  <n-icon :component="LockClosedOutline" />
                </template>
              </n-input>
            </n-form-item>

            <n-form-item label="确认密码" path="confirmPassword" class="form-item-half">
              <n-input
                v-model:value="formData.confirmPassword"
                type="password"
                show-password-on="click"
                placeholder="请再次输入密码"
                size="large"
                @keyup.enter="handleRegister"
              >
                <template #prefix>
                  <n-icon :component="LockClosedOutline" />
                </template>
              </n-input>
            </n-form-item>

            <n-alert v-if="errorMsg" type="error" :show-icon="true" class="error-alert form-item-full">
              {{ errorMsg }}
            </n-alert>

            <div class="agreement-row form-item-full">
              <n-checkbox v-model:checked="agreed" class="agreement-checkbox" />
              <span class="agreement-text">
                我已阅读并同意
                <a class="agreement-link" @click="showAgreementDrawer = true">《CygnusX 平台服务协议》</a>
              </span>
            </div>

            <div class="register-actions form-item-full">
              <n-button
                type="primary"
                size="large"
                :loading="loading"
                :disabled="!agreed || loading"
                @click="handleRegister"
              >
                注册账户
              </n-button>
              <span class="back-to-login">
                已有账号？<a @click="$router.push('/login')">返回登录</a>
              </span>
            </div>
          </n-form>
        </div>
      </div>
    </div>

    <AgreementDrawer
      v-model:show="showAgreementDrawer"
      @agree="agreed = true"
    />

    <StardustQuote placement="flow" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { PersonOutline, LockClosedOutline, MailOutline } from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import apiClient from '@/api/client'
import AgreementDrawer from '@/components/AgreementDrawer.vue'
import LoginPageQuote from '@/components/LoginPageQuote.vue'
import LogoAnimation from '@/components/LogoAnimation.vue'
import StarField from '@/components/StarField.vue'
import StardustQuote from '@/components/StardustQuote.vue'

const router = useRouter()
const authStore = useAuthStore()
const message = useMessage()
const formRef = ref()
const loading = ref(false)
const errorMsg = ref('')
const registrationClosed = ref(false)
const agreed = ref(false)
const showAgreementDrawer = ref(false)

onMounted(async () => {
  try {
    const res = await apiClient.get<{ registration_enabled: boolean }>('/site-settings')
    registrationClosed.value = !res.data.registration_enabled
  } catch {
    /* 接口异常默认允许注册 */
  }
})

const formData = ref({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度在 3 到 50 个字符', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_]+$/, message: '用户名只能包含字母、数字和下划线', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱地址', trigger: 'blur' },
    {
      pattern: /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/,
      message: '请输入正确的邮箱格式',
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码长度在 8 到 128 个字符', trigger: 'blur' },
    { pattern: /^(?=.*[A-Za-z])(?=.*\d).+$/, message: '密码必须包含字母和数字', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_rule: unknown, value: string) => {
        if (value !== formData.value.password) {
          return Promise.reject('两次输入的密码不一致')
        }
        return Promise.resolve()
      },
      trigger: 'blur',
    },
  ],
}

const handleRegister = async () => {
  if (!formRef.value) return

  errorMsg.value = ''

  try {
    await formRef.value.validate()
  } catch {
    errorMsg.value = '请检查表单填写是否正确'
    return
  }

  loading.value = true

  try {
    await authStore.register({
      username: formData.value.username,
      email: formData.value.email,
      password: formData.value.password,
    })
    message.success('注册成功，请登录')
    router.push('/login')
  } catch (error: any) {
    errorMsg.value = error.response?.data?.detail || '注册失败，请检查输入信息'
    message.error(errorMsg.value)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-page {
  position: relative;
  width: 100vw;
  min-height: 100dvh;
  box-sizing: border-box;
  overflow-x: hidden;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 24px 24px 20px;
  /* 与登录页 Hero 同款淡紫渐变 */
  background: linear-gradient(135deg, #6b7fd4 0%, #8b7fd4 35%, #a080d4 65%, #b080c8 100%);
}

:root[data-theme='dark'] .register-page {
  background: linear-gradient(135deg, #2a3a6e 0%, #3a2a6e 35%, #4a2a6e 65%, #3a2a5e 100%);
}

.register-content {
  position: relative;
  z-index: 10;
  width: 100%;
  flex: 1 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 72px 0 0;
}

.register-card-wrapper {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 704px;
  padding: 3px;
  border-radius: 19px;
}

:root[data-theme='dark'] .register-card-wrapper {
  padding: 3px;
  border-radius: 19px;
}

:root[data-theme='dark'] .register-card-wrapper::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border-radius: 19px;
  background: conic-gradient(
    from 45deg,
    rgba(255, 200, 100, 0.12) 0deg,
    rgba(255, 225, 160, 0.22) 90deg,
    rgba(255, 200, 100, 0.12) 180deg,
    rgba(255, 180, 90, 0.08) 270deg,
    rgba(255, 200, 100, 0.12) 360deg
  );
  -webkit-mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  padding: 2.5px;
  box-sizing: border-box;
  z-index: 0;
  pointer-events: none;
}

:root[data-theme='dark'] .register-card-wrapper::after {
  content: '';
  position: absolute;
  top: -3px;
  left: -3px;
  right: -3px;
  bottom: -3px;
  border-radius: 21px;
  background: transparent;
  box-shadow:
    0 0 18px rgba(255, 200, 100, 0.08),
    0 0 36px rgba(255, 180, 80, 0.04);
  animation: golden-breathe 6s ease-in-out infinite;
  z-index: -1;
  pointer-events: none;
}

@keyframes golden-breathe {
  0%, 100% {
    box-shadow:
      0 0 18px rgba(255, 200, 100, 0.07),
      0 0 36px rgba(255, 180, 80, 0.035);
  }
  50% {
    box-shadow:
      0 0 24px rgba(255, 215, 130, 0.12),
      0 0 48px rgba(255, 195, 100, 0.06);
  }
}

.register-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 698px;
  padding: 28px 40px 32px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 16px;
  box-shadow: 0 25px 60px rgba(40, 30, 80, 0.15), inset 0 1px rgba(255, 255, 255, 0.45);
  transition: transform 220ms ease-out, box-shadow 220ms ease-out, background-color 220ms ease-out;
}

.register-card:focus-within {
  transform: translateY(-2px);
  box-shadow: 0 32px 76px rgba(40, 30, 80, 0.2), inset 0 1px rgba(255, 255, 255, 0.55);
}

:root[data-theme='dark'] .register-card {
  background: rgba(30, 30, 60, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
}

.register-header {
  text-align: center;
  margin-bottom: 24px;
  position: relative;
  z-index: 2;
}

.register-title {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 8px;
  filter: drop-shadow(0 4px 18px rgba(64, 120, 255, 0.25));
}

.register-subtitle {
  font-size: 14px;
  color: var(--neutral-text-2);
}

.register-form {
  margin-top: 16px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 20px;
}

.register-form .form-item-half {
  grid-column: span 1;
}

.register-form .form-item-full {
  grid-column: 1 / -1;
}

.register-form :deep(.n-form-item) {
  margin-bottom: 0;
}

.register-form :deep(.n-form-item-feedback) {
  min-height: 18px;
  padding-top: 4px;
}

.register-form :deep(.n-form-item-feedback__line) {
  font-size: 12px;
  line-height: 1.4;
}

/* 表单元素可见性修复 */
.register-form :deep(.n-input) {
  --n-border-color: rgba(60, 60, 100, 0.16);
  --n-border-hover: rgba(60, 60, 100, 0.28);
  --n-border-focus: var(--arco-primary);
  --n-color: rgba(255, 255, 255, 0.55);
  --n-color-focus: rgba(255, 255, 255, 0.72);
  --n-placeholder-color: var(--neutral-text-3);
  --n-box-shadow-focus: 0 0 0 4px rgba(77, 124, 255, 0.15);
  --n-icon-color: var(--neutral-text-3);
}

.register-form :deep(.n-input--focus) {
  border-color: var(--arco-primary);
}

.register-form :deep(.n-input .n-input__input-el),
.register-form :deep(.n-input .n-input__textarea-el) {
  color: var(--neutral-text-1);
}

.register-form :deep(.n-form-item .n-form-item-label) {
  color: var(--neutral-text-2);
}

:root[data-theme='dark'] .register-form :deep(.n-input) {
  --n-border-color: rgba(255, 255, 255, 0.18) !important;
  --n-border-hover: rgba(255, 255, 255, 0.28) !important;
  --n-border-focus: var(--arco-primary) !important;
  --n-color: rgba(255, 255, 255, 0.07) !important;
  --n-color-focus: rgba(255, 255, 255, 0.1) !important;
  --n-text-color: var(--neutral-text-1) !important;
  --n-placeholder-color: var(--neutral-text-3) !important;
  --n-box-shadow-focus: 0 0 0 3px rgba(155, 124, 247, 0.2) !important;
  --n-icon-color: var(--neutral-text-3) !important;
}

:root[data-theme='dark'] .register-form :deep(.n-form-item .n-form-item-label) {
  color: var(--neutral-text-1) !important;
}

.register-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 8px;
  gap: 12px;
}

.register-actions :deep(.n-button--primary-type) {
  width: 100%;
  --n-color: linear-gradient(135deg, #7c3aed, #6d28d9) !important;
  --n-color-hover: linear-gradient(135deg, #8b5cf6, #7c3aed) !important;
  --n-color-pressed: linear-gradient(135deg, #6d28d9, #5b21b6) !important;
  --n-color-focus: linear-gradient(135deg, #7c3aed, #6d28d9) !important;
  --n-text-color: #ffffff !important;
  --n-text-color-hover: #ffffff !important;
  --n-text-color-pressed: #f3e8ff !important;
  --n-box-shadow: 0 6px 16px rgba(124, 58, 237, 0.35) !important;
  --n-box-shadow-hover: 0 8px 20px rgba(124, 58, 237, 0.5) !important;
  --n-box-shadow-pressed: 0 3px 10px rgba(124, 58, 237, 0.3) !important;
  transition: transform 0.15s ease, box-shadow 0.2s ease;
}

.register-actions :deep(.n-button--primary-type:hover) {
  transform: translateY(-1px);
}

.register-actions :deep(.n-button--primary-type:active) {
  transform: scale(0.98);
}

.register-actions :deep(.n-button--primary-type.n-button--disabled) {
  opacity: 0.5;
  filter: grayscale(1);
  cursor: not-allowed;
  transform: none !important;
  box-shadow: none !important;
}

.agreement-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
}

.agreement-checkbox {
  --n-color-checked: var(--arco-primary);
  --n-color-checked-hover: var(--arco-primary);
  --n-border-checked: var(--arco-primary);
  --n-border-focus: var(--arco-primary);
  --n-box-shadow-focus: 0 0 0 2px rgba(22, 93, 255, 0.2);
}

.agreement-text {
  font-size: 13px;
  color: var(--neutral-text-2);
  line-height: 1.5;
}

.agreement-link {
  color: var(--arco-primary);
  text-decoration: none;
  cursor: pointer;
  transition: color 0.2s ease, text-decoration 0.2s ease;
}

.agreement-link:hover {
  color: var(--arco-primary-hover);
  text-decoration: underline;
}

.back-to-login {
  font-size: 13px;
  color: var(--neutral-text-3);
  cursor: default;
}

.back-to-login a {
  color: var(--arco-primary);
  text-decoration: none;
  margin-left: 4px;
  cursor: pointer;
  transition: color 0.2s ease, text-decoration 0.2s ease;
}

.back-to-login a:hover {
  color: var(--arco-primary-active);
  text-decoration: underline;
}

.register-actions--single {
  flex-direction: row;
  justify-content: center;
}

.error-alert {
  margin-bottom: 16px;
}

@media (max-width: 480px) {
  .register-page {
    gap: 12px;
    padding: 16px;
  }

  .register-content {
    padding-top: 56px;
  }

  .register-card {
    padding: 24px 20px 28px;
  }

  .register-title {
    font-size: 24px;
  }

  .register-form {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .register-form .form-item-half {
    grid-column: 1 / -1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .register-card,
  .register-actions :deep(.n-button--primary-type) {
    transition-duration: 1ms;
  }

  :root[data-theme='dark'] .register-card-wrapper::after {
    animation: none;
  }
}
</style>
