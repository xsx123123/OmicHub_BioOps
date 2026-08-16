<template>
  <div class="login-page" role="main" aria-label="登录 OmicHub">
    <StarField />
    <LoginPageQuote />
    <div class="login-content">
      <div class="login-card-wrapper">
        <div class="login-card animate-scale-in">
          <div class="login-header">
            <LogoAnimation />
            <h2 class="login-title">OmicHub</h2>
            <p class="login-subtitle">欢迎登录多组学分析平台</p>
          </div>
          <n-form ref="formRef" :model="formData" :rules="rules" class="login-form">
            <!-- 第一步：账号密码 -->
            <template v-if="step === 'credentials'">
              <n-form-item label="用户名" path="username">
                <n-input
                  v-model:value="formData.username"
                  placeholder="请输入用户名"
                  size="large"
                  @keyup.enter="handleLogin"
                >
                  <template #prefix>
                    <n-icon :component="PersonOutline" />
                  </template>
                </n-input>
              </n-form-item>

              <n-form-item label="密码" path="password">
                <n-input
                  v-model:value="formData.password"
                  type="password"
                  show-password-on="click"
                  placeholder="请输入密码"
                  size="large"
                  @keyup.enter="handleLogin"
                >
                  <template #prefix>
                    <n-icon :component="LockClosedOutline" />
                  </template>
                </n-input>
              </n-form-item>
            </template>

            <!-- 第二步：TOTP 6 位验证码 -->
            <template v-else>
              <n-form-item label="6 位动态验证码" path="totpCode">
                <n-input
                  v-model:value="formData.totpCode"
                  placeholder="请输入 Authenticator 验证码"
                  size="large"
                  maxlength="6"
                  :input-props="{ inputmode: 'numeric', autocomplete: 'one-time-code' }"
                  @keyup.enter="handleVerify2FA"
                />
              </n-form-item>
              <p class="totp-hint">已开启二次验证，请打开 Authenticator 应用查看当前验证码。</p>
            </template>

            <div v-if="errorMessage" class="login-error-message">
              {{ errorMessage }}
            </div>

            <div class="login-actions">
              <LoginButton
                v-if="step === 'credentials'"
                :disabled="isLoginButtonDisabled"
                :loading="loading"
                :success="loginSuccess"
                @click="handleLogin"
              />
              <template v-else>
                <n-button type="primary" size="large" :loading="loading" @click="handleVerify2FA">
                  验证并登录
                </n-button>
                <n-button size="large" @click="resetToCredentials">
                  返回
                </n-button>
              </template>
              <n-button v-if="step === 'credentials'" size="large" @click="handleRegister">
                还没有账号？立即注册
              </n-button>
            </div>
          </n-form>
        </div>
      </div>
    </div>
    <StardustQuote />
    <RegistrationDisabledModal
      v-model:show="showRegModal"
      :message="siteConfig.registrationDisabledMessage"
      :contact="siteConfig.adminContact"
    />
    <!-- 账户未激活弹窗：专用 ActivationModal（点击计数 + 文案切换 + 第 5 次猫爪彩蛋），
         文案/联系方式由 YAML activation 段驱动 -->
    <ActivationModal v-model:show="showInactiveModal" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { PersonOutline, LockClosedOutline } from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import { useSiteConfigStore } from '@/stores/site-config'
import RegistrationDisabledModal from '@/components/RegistrationDisabledModal.vue'
import ActivationModal from '@/components/ActivationModal.vue'
import LoginButton from '@/components/LoginButton.vue'
import LogoAnimation from '@/components/LogoAnimation.vue'
import LoginPageQuote from '@/components/LoginPageQuote.vue'
import StarField from '@/components/StarField.vue'
import StardustQuote from '@/components/StardustQuote.vue'

const router = useRouter()
const authStore = useAuthStore()
const message = useMessage()
const siteConfig = useSiteConfigStore()
const formRef = ref()
const loading = ref(false)
const errorMessage = ref('')
const showRegModal = ref(false)
// 账户未激活时弹模态框（带管理员联系方式），比纯 toast 更友好
const showInactiveModal = ref(false)

// 拉取注册开关（site-settings，DB）+ 提示文案（site-content，YAML）
onMounted(() => {
  siteConfig.fetchSiteConfig()
})

// 点击“注册”：开关关闭时拦截并弹自定义模态框提示，不跳转；开启时正常跳转注册页
// 首次点击前若配置尚未就绪，先等一次拉取（已就绪则立即放行，不额外发请求）
async function handleRegister() {
  if (!siteConfig.loaded) await siteConfig.fetchSiteConfig()
  if (siteConfig.allowRegistration) {
    router.push('/register')
    return
  }
  showRegModal.value = true
}

const formData = ref({
  username: '',
  password: '',
  totpCode: '',
})

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度在 3 到 50 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码长度在 8 到 128 个字符', trigger: 'blur' },
  ],
  totpCode: [
    { required: true, message: '请输入 6 位验证码', trigger: 'blur' },
    { pattern: /^\d{6}$/, message: '验证码必须为 6 位数字', trigger: 'blur' },
  ],
}

const step = ref<'credentials' | 'totp'>('credentials')
const challengeToken = ref('')
const loginSuccess = ref(false)
let redirectTimer: ReturnType<typeof setTimeout> | null = null
let loginSuccessTimer: ReturnType<typeof setTimeout> | null = null

const isLoginButtonDisabled = computed(() => {
  return !formData.value.username || !formData.value.password
})

function resetToCredentials() {
  step.value = 'credentials'
  challengeToken.value = ''
  formData.value.totpCode = ''
  errorMessage.value = ''
}

function redirectHome() {
  try {
    router.push('/')
  } catch {
    window.location.href = '/'
  }
  if (redirectTimer) clearTimeout(redirectTimer)
  redirectTimer = setTimeout(() => {
    if (window.location.pathname === '/login') {
      window.location.href = '/'
    }
  }, 100)
}

function handleLoginError(error: any) {
  const status = error.response?.status
  const detail: string = error.response?.data?.detail || ''

  if (status >= 500) {
    const sysMsg = '系统内部错误，请联系管理员'
    errorMessage.value = sysMsg
    message.error(sysMsg)
  } else if (detail.includes('未激活')) {
    errorMessage.value = detail
    if (!siteConfig.loaded) siteConfig.fetchSiteConfig().catch(() => {})
    showInactiveModal.value = true
  } else {
    const authMsg = detail || '用户名或密码错误'
    errorMessage.value = authMsg
    message.error(authMsg)
  }
}

const handleLogin = async () => {
  if (!formRef.value) return

  errorMessage.value = ''

  try {
    await formRef.value.validate()
  } catch {
    return
  }

  loading.value = true

  try {
    const result = await authStore.login(formData.value.username, formData.value.password)

    if (result.requires_2fa) {
      challengeToken.value = result.challenge_token || ''
      step.value = 'totp'
      message.info('请打开 Authenticator 应用，输入 6 位动态验证码')
      return
    }

    loginSuccess.value = true
    message.success('登录成功')
    if (loginSuccessTimer) clearTimeout(loginSuccessTimer)
    loginSuccessTimer = setTimeout(() => {
      redirectHome()
    }, 1200)
  } catch (error: any) {
    handleLoginError(error)
  } finally {
    loading.value = false
  }
}

const handleVerify2FA = async () => {
  if (!formRef.value) return
  errorMessage.value = ''

  try {
    await formRef.value.validate()
  } catch {
    return
  }

  if (!challengeToken.value) {
    errorMessage.value = '2FA 凭证丢失，请重新登录'
    return
  }

  loading.value = true
  try {
    await authStore.complete2FALogin(challengeToken.value, formData.value.totpCode)
    message.success('登录成功')
    redirectHome()
  } catch (error: any) {
    handleLoginError(error)
  } finally {
    loading.value = false
  }
}

onUnmounted(() => {
  if (redirectTimer) clearTimeout(redirectTimer)
  if (loginSuccessTimer) clearTimeout(loginSuccessTimer)
})
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  /* 与 Hero 同色系，但饱和度降低，更柔和 */
  background: linear-gradient(135deg, #6b7fd4 0%, #8b7fd4 35%, #a080d4 65%, #b080c8 100%);
  background-size: 400% 400%;
  animation: gradientShift 12s ease infinite;
  position: relative;
  overflow: hidden;
}

.login-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.35;
  pointer-events: none;
  z-index: 1;
}
.login-orb--1 {
  width: 400px;
  height: 400px;
  background: #c5d0ff;
  top: -100px;
  right: -100px;
  animation: drift 14s ease-in-out infinite;
}
.login-orb--2 {
  width: 300px;
  height: 300px;
  background: #e0c8ff;
  bottom: -50px;
  left: -50px;
  animation: drift 16s ease-in-out infinite reverse;
}

.login-card-wrapper {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 426px;
  padding: 3px;
  border-radius: 19px;
}

.login-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 420px;
  padding: 28px 32px 32px;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(24px) saturate(150%);
  -webkit-backdrop-filter: blur(24px) saturate(150%);
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: 16px;
  box-shadow: 0 25px 60px rgba(7, 34, 82, 0.2), inset 0 1px rgba(255, 255, 255, 0.45);
  transition: transform 220ms ease-out, box-shadow 220ms ease-out, background-color 220ms ease-out;
}

:root[data-theme='dark'] .login-card-wrapper {
  /* 暗色：使用与平台主色一致的蓝靛边缘 */
  padding: 3px;
  border-radius: 19px;
}

/* 蓝靛边框层：静态锥形渐变，mask 镂空内部 */
:root[data-theme='dark'] .login-card-wrapper::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border-radius: 19px;
  background: conic-gradient(
    from 45deg,
    rgba(91, 139, 255, 0.14) 0deg,
    rgba(155, 184, 255, 0.28) 90deg,
    rgba(91, 139, 255, 0.14) 180deg,
    rgba(112, 102, 236, 0.12) 270deg,
    rgba(91, 139, 255, 0.14) 360deg
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

/* 静态环境光晕层 */
:root[data-theme='dark'] .login-card-wrapper::after {
  content: '';
  position: absolute;
  top: -3px;
  left: -3px;
  right: -3px;
  bottom: -3px;
  border-radius: 21px;
  background: transparent;
  box-shadow:
    0 0 22px rgba(91, 139, 255, 0.12),
    0 0 44px rgba(91, 139, 255, 0.05);
  z-index: -1;
  pointer-events: none;
}

:root[data-theme='dark'] .login-card {
  background: rgba(8, 23, 53, 0.78);
  border: 1px solid rgba(165, 192, 255, 0.14);
  box-shadow: 0 24px 80px rgba(0, 9, 30, 0.4), inset 0 1px rgba(196, 216, 255, 0.08);
}

.login-page {
  position: relative;
  width: 100vw;
  min-height: 100dvh;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-content {
  position: relative;
  z-index: 10;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0 16px;
}

.login-card:focus-within {
  transform: translateY(-1px);
  box-shadow: 0 30px 72px rgba(7, 34, 82, 0.28), inset 0 1px rgba(255, 255, 255, 0.58);
}

.login-header {
  text-align: center;
  margin-bottom: 16px;
  position: relative;
  z-index: 2;
}
.login-title {
  color: var(--brand-primary);
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 6px;
  filter: drop-shadow(0 4px 18px rgba(64, 120, 255, 0.25));
}
.login-subtitle {
  font-size: 14px;
  color: var(--neutral-text-2);
}
.login-form {
  margin-top: 0;
}
.login-form :deep(.n-form-item) {
  margin-bottom: 16px;
}
.login-form :deep(.n-form-item:last-of-type) {
  margin-bottom: 20px;
}
.login-error-message {
  margin-bottom: 16px;
  color: var(--arco-danger);
  font-size: 13px;
  text-align: center;
}
.login-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 0;
  gap: 16px;
}

.login-actions :deep(.n-button:not(.n-button--primary-type)) {
  --n-text-color: var(--neutral-text-2) !important;
  --n-text-color-hover: var(--arco-primary) !important;
  --n-text-color-pressed: var(--arco-primary-active) !important;
  --n-border: none !important;
  --n-border-hover: none !important;
  --n-border-pressed: none !important;
  --n-color: transparent !important;
  --n-color-hover: transparent !important;
  --n-color-pressed: transparent !important;
  font-weight: 500;
  text-decoration: underline;
  text-decoration-color: transparent;
  transition: color 180ms ease-out, text-decoration-color 180ms ease-out, transform 120ms ease-out;
}

.login-actions :deep(.n-button:not(.n-button--primary-type):hover) {
  text-decoration-color: rgba(77, 124, 255, 0.4);
}

.login-actions :deep(.n-button:active) {
  transform: scale(0.98);
}

.totp-hint {
  margin: -8px 0 16px;
  font-size: 13px;
  color: var(--neutral-text-2);
  text-align: center;
}

/* 暗色模式：提升表单标签、输入框、按钮对比度 */
:root[data-theme='dark'] .login-form :deep(.n-form-item .n-form-item-label) {
  color: var(--neutral-text-1) !important;
}

:root[data-theme='dark'] .login-form :deep(.n-input) {
  --n-border-color: rgba(255, 255, 255, 0.18) !important;
  --n-border-hover: rgba(255, 255, 255, 0.28) !important;
  --n-border-focus: var(--arco-primary) !important;
  --n-color: rgba(255, 255, 255, 0.07) !important;
  --n-color-focus: rgba(255, 255, 255, 0.1) !important;
  --n-text-color: var(--neutral-text-1) !important;
  --n-placeholder-color: var(--neutral-text-3) !important;
  --n-box-shadow-focus: 0 0 0 3px rgba(118, 145, 255, 0.24) !important;
  --n-icon-color: var(--neutral-text-3) !important;
}

:root[data-theme='dark'] .login-actions :deep(.n-button:not(.n-button--primary-type)) {
  --n-text-color: var(--neutral-text-2) !important;
  --n-text-color-hover: var(--arco-primary-hover) !important;
  --n-text-color-pressed: var(--arco-primary-active) !important;
  --n-border: 1px solid rgba(192, 200, 255, 0.45) !important;
  --n-border-hover: 1px solid rgba(192, 200, 255, 0.6) !important;
  --n-border-pressed: 1px solid rgba(192, 200, 255, 0.5) !important;
}

/* 登录主按钮在暗色下使用更亮的渐变 */
:root[data-theme='dark'] .login-actions :deep(.n-button--primary-type) {
  --n-text-color: #ffffff !important;
  --n-text-color-hover: #ffffff !important;
  --n-text-color-pressed: #f0f0f8 !important;
}

/* 亮色模式：优化输入框边框与 placeholder 可读性 */
.login-form :deep(.n-input) {
  --n-border-color: rgba(60, 60, 100, 0.16);
  --n-border-hover: rgba(60, 60, 100, 0.28);
  --n-border-focus: var(--arco-primary);
  --n-color: rgba(255, 255, 255, 0.55);
  --n-color-focus: rgba(255, 255, 255, 0.72);
  --n-placeholder-color: var(--neutral-text-3);
  --n-box-shadow-focus: 0 0 0 4px rgba(77, 124, 255, 0.15);
  --n-icon-color: var(--neutral-text-3);
}

.login-form :deep(.n-input--focus) {
  border-color: var(--arco-primary);
}

.login-form :deep(.n-input .n-input__input-el),
.login-form :deep(.n-input .n-input__textarea-el) {
  color: var(--neutral-text-1);
}
.login-form :deep(.n-input .n-input__placeholder) {
  color: var(--n-placeholder-color);
}
.login-form :deep(.n-form-item .n-form-item-label) {
  color: var(--neutral-text-2);
}

/* 表单校验提示精致化 */
:deep(.n-form-item) .n-form-item-feedback {
  min-height: 18px;
  padding-top: 4px;
}
:deep(.n-form-item) .n-form-item-feedback__line {
  font-size: 12px;
  line-height: 1.4;
}

@media (prefers-reduced-motion: reduce) {
  .login-card,
  .login-actions :deep(.n-button) {
    transition-duration: 1ms;
  }
}
</style>
