<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NTabs, NTabPane, NForm, NFormItem, NInput, NButton,
  NSpace, NAvatar, NIcon, NTag, NSwitch, useMessage,
  NAlert, NDivider,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import {
  BulbOutline,
  ExtensionPuzzleOutline,
  GitNetworkOutline,
  GlobeOutline,
  LockClosedOutline,
  PersonOutline,
  SettingsOutline,
  ShieldCheckmarkOutline,
} from '@vicons/ionicons5'
import QRCode from 'qrcode'
import AdminTOTPConfirmModal from '@/components/AdminTOTPConfirmModal.vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { SiteSettings } from '@/types'
import { isFestivalEffectsEnabled, setFestivalEffectsEnabled } from '@/utils/interfacePreferences'
import PageHeader from '@/components/PageHeader.vue'
import { displayName as getDisplayName } from '@/utils/displayName'

const router = useRouter()
const authStore = useAuthStore()
const message = useMessage()

const isAdmin = computed(() => authStore.user?.role === 'admin')
const displayName = computed(() => getDisplayName(authStore.user))

// ===== 平台全局配置 =====
const platformConfig = ref<SiteSettings>({ registration_enabled: true, totp_policy: 'optional', subagent_fanout_enabled: false, agentteams_chat_entry_enabled: false, agent_memory_enabled: true })
const platformLoading = ref(false)
const platformPending = ref<Partial<SiteSettings> | null>(null)
const platformTotpModalVisible = ref(false)
const platformTotpLoading = ref(false)

const userId = computed(() => authStore.user?.id || '')
const profileFormRef = ref<FormInst | null>(null)
const passwordFormRef = ref<FormInst | null>(null)
const savingProfile = ref(false)
const savingPassword = ref(false)
const festivalEffectsEnabled = ref(false)

const profileForm = ref({
  username: '',
  email: '',
  nickname: '',
  avatar_url: '',
})

const passwordForm = ref({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

// ===== 二次验证（TOTP 2FA）状态 =====
const faEnabled = ref(false)
const faHasSecret = ref(false)
const faStep = ref<'idle' | 'setup' | 'disable'>('idle')
const faLoading = ref(false)
const otpauthUri = ref('')
const setupSecret = ref('')
const qrDataUrl = ref('')
const verifyCode = ref('')
const disableCode = ref('')

async function loadPlatformConfig() {
  try {
    const res = await apiClient.get<SiteSettings>('/platform/config')
    platformConfig.value = res.data
  } catch {
    /* 读取失败使用默认配置 */
  }
}

async function load2FAStatus() {
  try {
    const status = await authStore.fetch2FAStatus()
    faEnabled.value = status.enabled
    faHasSecret.value = status.has_secret
  } catch (e: any) {
    message.error(e.response?.data?.detail || '获取 2FA 状态失败')
  }
}

async function startSetup2FA() {
  faLoading.value = true
  try {
    const setup = await authStore.setup2FA()
    otpauthUri.value = setup.otpauth_uri
    setupSecret.value = setup.secret
    qrDataUrl.value = await QRCode.toDataURL(setup.otpauth_uri, { width: 200, margin: 2 })
    faStep.value = 'setup'
  } catch (e: any) {
    message.error(e.response?.data?.detail || '生成绑定二维码失败')
  } finally {
    faLoading.value = false
  }
}

async function confirmSetup2FA() {
  if (!/^\d{6}$/.test(verifyCode.value)) {
    message.error('请输入 6 位数字验证码')
    return
  }
  faLoading.value = true
  try {
    await authStore.confirmEnable2FA(verifyCode.value)
    message.success('二次验证已开启')
    faStep.value = 'idle'
    verifyCode.value = ''
    await load2FAStatus()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '验证码错误')
  } finally {
    faLoading.value = false
  }
}

function cancelSetup2FA() {
  faStep.value = 'idle'
  verifyCode.value = ''
  otpauthUri.value = ''
  setupSecret.value = ''
  qrDataUrl.value = ''
}

function startDisable2FA() {
  faStep.value = 'disable'
  disableCode.value = ''
}

async function confirmDisable2FA() {
  if (!/^\d{6}$/.test(disableCode.value)) {
    message.error('请输入 6 位数字验证码')
    return
  }
  faLoading.value = true
  try {
    await authStore.disable2FA(disableCode.value)
    message.success('二次验证已关闭')
    faStep.value = 'idle'
    disableCode.value = ''
    await load2FAStatus()
  } catch (e: any) {
    message.error(e.response?.data?.detail || '验证码错误')
  } finally {
    faLoading.value = false
  }
}

function cancelDisable2FA() {
  faStep.value = 'idle'
  disableCode.value = ''
}

function copySecret() {
  navigator.clipboard.writeText(setupSecret.value)
    .then(() => message.success('密钥已复制'))
    .catch(() => message.error('复制失败'))
}

const profileRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度 3-50 字符', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_]+$/, message: '只能包含字母、数字、下划线', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
}

const passwordRules: FormRules = {
  old_password: [
    { required: true, message: '请输入当前密码', trigger: 'blur' },
  ],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码长度 8-128 字符', trigger: 'blur' },
    { pattern: /^(?=.*[A-Za-z])(?=.*\d).+$/, message: '密码必须包含字母和数字', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    {
      validator: (_rule, value) => {
        if (value !== passwordForm.value.new_password) {
          return new Error('两次输入的密码不一致')
        }
        return true
      },
      trigger: 'blur',
    },
  ],
}

onMounted(async () => {
  festivalEffectsEnabled.value = isFestivalEffectsEnabled()
  if (!authStore.isLoggedIn) {
    router.push('/login')
    return
  }
  try {
    await authStore.fetchUser()
  } catch {
    router.push('/login')
    return
  }
  if (authStore.user) {
    profileForm.value.username = authStore.user.username
    profileForm.value.email = authStore.user.email
    profileForm.value.nickname = authStore.user.nickname || ''
    profileForm.value.avatar_url = authStore.user.avatar_url || ''
  }
  await loadPlatformConfig()
  await load2FAStatus()
})

function updateFestivalEffects(enabled: boolean) {
  festivalEffectsEnabled.value = enabled
  setFestivalEffectsEnabled(enabled)
  message.success(enabled ? '节日彩蛋已开启' : '节日彩蛋已关闭')
}

function requestPlatformChange(patch: Partial<SiteSettings>) {
  // 高敏感改动需 TOTP；账号未开 2FA 时给明确提示，而非弹一个填不上的验证码框
  if (!faEnabled.value) {
    message.warning('该操作为高敏感操作，请先在「账号安全」处开启二次验证（2FA）后再试')
    return
  }
  platformPending.value = patch
  platformTotpModalVisible.value = true
}

// 非敏感平台配置（功能灰度开关等）免 TOTP 直连保存
async function patchPlatformDirect(patch: Partial<SiteSettings>) {
  platformLoading.value = true
  try {
    const res = await apiClient.patch<SiteSettings>('/admin/platform-config', patch)
    platformConfig.value = res.data
    message.success('平台全局配置已保存')
  } catch (e: any) {
    console.error('平台配置保存失败:', e, 'payload:', patch)
    message.error(e.response?.data?.detail || '保存失败')
  } finally {
    platformLoading.value = false
  }
}

async function confirmPlatformChange(code: string) {
  if (!platformPending.value) return
  platformTotpLoading.value = true
  platformLoading.value = true
  try {
    const res = await apiClient.patch<SiteSettings>('/admin/platform-config', platformPending.value, {
      headers: { 'X-TOTP-Code': code },
    })
    platformConfig.value = res.data
    platformTotpModalVisible.value = false
    message.success('平台全局配置已保存')
  } catch (e: any) {
    console.error('平台配置保存失败:', e, 'payload:', platformPending.value)
    message.error(e.response?.data?.detail || '保存失败')
  } finally {
    platformLoading.value = false
    platformTotpLoading.value = false
    platformPending.value = null
  }
}

function cancelPlatformChange() {
  platformPending.value = null
}

function onRegistrationChange(value: boolean) {
  if (value === platformConfig.value.registration_enabled) return
  requestPlatformChange({ registration_enabled: value })
}

function onSubagentFanoutChange(value: boolean) {
  if (value === platformConfig.value.subagent_fanout_enabled) return
  void patchPlatformDirect({ subagent_fanout_enabled: value })
}

function onAgentTeamsChatEntryChange(value: boolean) {
  if (value === platformConfig.value.agentteams_chat_entry_enabled) return
  void patchPlatformDirect({ agentteams_chat_entry_enabled: value })
}

function onAgentMemoryChange(value: boolean) {
  if (value === (platformConfig.value.agent_memory_enabled ?? true)) return
  void patchPlatformDirect({ agent_memory_enabled: value })
}

function onTOTPPolicyChange(value: SiteSettings['totp_policy']) {
  if (value === platformConfig.value.totp_policy) return
  requestPlatformChange({ totp_policy: value })
}

async function saveProfile() {
  if (!userId.value) {
    message.error('用户信息未加载，请刷新页面后重试')
    return
  }
  try {
    await profileFormRef.value?.validate()
  } catch {
    return
  }
  savingProfile.value = true
  try {
    await apiClient.put(`/users/${userId.value}`, {
      username: profileForm.value.username,
      email: profileForm.value.email,
      nickname: profileForm.value.nickname || null,
      avatar_url: profileForm.value.avatar_url || null,
    })
    await authStore.fetchUser()
    message.success('个人信息保存成功')
  } catch (e: any) {
    console.error('保存个人信息失败:', e, 'userId:', userId.value)
    message.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingProfile.value = false
  }
}

async function savePassword() {
  if (!userId.value) {
    message.error('用户信息未加载，请刷新页面后重试')
    return
  }
  try {
    await passwordFormRef.value?.validate()
  } catch {
    return
  }
  savingPassword.value = true
  try {
    await apiClient.put(`/users/${userId.value}/password`, {
      old_password: passwordForm.value.old_password,
      new_password: passwordForm.value.new_password,
    })
    message.success('密码修改成功')
    passwordForm.value = { old_password: '', new_password: '', confirm_password: '' }
  } catch (e: any) {
    console.error('修改密码失败:', e, 'userId:', userId.value)
    message.error(e.response?.data?.detail || '密码修改失败')
  } finally {
    savingPassword.value = false
  }
}

const totpPolicyOptions: { key: SiteSettings['totp_policy']; label: string; desc: string }[] = [
  { key: 'off', label: '关闭', desc: '全平台禁用 TOTP' },
  { key: 'optional', label: '可选', desc: '用户自行决定是否开启' },
  { key: 'required', label: '强制', desc: '所有用户必须开启 TOTP' },
]
</script>

<template>
  <main class="admin-config-center settings-page">
    <PageHeader title="系统设置" subtitle="管理个人资料、登录安全与平台偏好" />
    <NTabs type="line" animated class="admin-config-tabs">
        <!-- 个人信息 -->
        <NTabPane name="profile" tab="个人信息">
          <NCard :bordered="false" class="arco-card settings-card">
            <div class="avatar-section">
              <NAvatar round :size="80" :src="profileForm.avatar_url || undefined">
                <NIcon :size="36"><PersonOutline /></NIcon>
              </NAvatar>
              <div class="avatar-info">
                <div class="avatar-name">{{ displayName }}</div>
                <NTag size="small" :type="authStore.user?.role === 'admin' ? 'warning' : 'default'">
                  {{ authStore.user?.role }}
                </NTag>
              </div>
            </div>

            <NForm ref="profileFormRef" :model="profileForm" :rules="profileRules" label-placement="top">
              <NFormItem label="用户名" path="username">
                <NInput v-model:value="profileForm.username" placeholder="用户名" />
              </NFormItem>
              <NFormItem label="昵称" path="nickname">
                <NInput v-model:value="profileForm.nickname" placeholder="留空则使用用户名" />
              </NFormItem>
              <NFormItem label="邮箱" path="email">
                <NInput v-model:value="profileForm.email" placeholder="邮箱" />
              </NFormItem>
              <NFormItem label="头像 URL" path="avatar_url">
                <NInput v-model:value="profileForm.avatar_url" placeholder="留空使用默认头像" />
              </NFormItem>
              <div class="form-actions">
                <NButton type="primary" :loading="savingProfile" @click="saveProfile">保存修改</NButton>
              </div>
            </NForm>
          </NCard>
        </NTabPane>

        <!-- 安全 / 修改密码 -->
        <NTabPane name="security" tab="安全设置">
          <div class="settings-section-grid">
            <NCard :bordered="false" class="arco-card settings-card">
              <template #header>
                <NSpace align="center">
                  <NIcon :size="18"><LockClosedOutline /></NIcon>
                  <span>修改密码</span>
                </NSpace>
              </template>
              <NForm ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-placement="top">
                <NFormItem label="当前密码" path="old_password">
                  <NInput v-model:value="passwordForm.old_password" type="password" show-password-on="click" placeholder="请输入当前密码" />
                </NFormItem>
                <NFormItem label="新密码" path="new_password">
                  <NInput v-model:value="passwordForm.new_password" type="password" show-password-on="click" placeholder="至少8位，包含字母和数字" />
                </NFormItem>
                <NFormItem label="确认新密码" path="confirm_password">
                  <NInput v-model:value="passwordForm.confirm_password" type="password" show-password-on="click" placeholder="请再次输入新密码" />
                </NFormItem>
                <div class="form-actions">
                  <NButton type="primary" :loading="savingPassword" @click="savePassword">修改密码</NButton>
                </div>
              </NForm>
            </NCard>

            <!-- 二次验证（TOTP 2FA） -->
            <NCard v-if="platformConfig.totp_policy === 'off'" :bordered="false" class="arco-card settings-card twofa-card twofa-disabled">
              <template #header>
                <NSpace align="center">
                  <NIcon :size="18" class="opacity-50"><ShieldCheckmarkOutline /></NIcon>
                  <span class="text-gray-400">二次验证（TOTP）</span>
                </NSpace>
              </template>
              <p class="text-sm text-gray-400">
                平台管理员已关闭二次验证功能，如有需要请联系管理员。
              </p>
            </NCard>

            <NCard v-else :bordered="false" class="arco-card settings-card twofa-card">
              <template #header>
                <NSpace align="center">
                  <NIcon :size="18"><ShieldCheckmarkOutline /></NIcon>
                  <span>二次验证（TOTP）</span>
                  <NTag v-if="faEnabled" size="small" type="success">已开启</NTag>
                  <NTag v-else size="small">未开启</NTag>
                </NSpace>
              </template>

              <!-- 强制开启提示 -->
              <NAlert
                v-if="platformConfig.totp_policy === 'required' && !faEnabled"
                type="warning"
                :show-icon="false"
                class="twofa-alert"
              >
                ⚠️ 平台要求所有用户必须开启二次验证，请尽快完成绑定。
              </NAlert>

              <!-- 未开启：引导绑定 -->
              <div v-if="!faEnabled && faStep !== 'setup'">
                <NAlert type="info" :show-icon="false" class="twofa-alert">
                  绑定 Google Authenticator、Microsoft Authenticator 等 TOTP 验证器后，
                  登录时将要求输入 6 位动态验证码，提升账号安全性。
                </NAlert>
                <div class="form-actions">
                  <NButton
                    :loading="faLoading"
                    :type="platformConfig.totp_policy === 'required' ? 'warning' : 'primary'"
                    @click="startSetup2FA"
                  >
                    开启二次验证
                  </NButton>
                </div>
              </div>

              <!-- 绑定中：展示二维码与确认 -->
              <div v-else-if="faStep === 'setup'">
                <NAlert type="warning" title="绑定步骤" class="twofa-alert">
                  1. 使用 Authenticator 应用扫描下方二维码；<br>
                  2. 输入应用显示的 6 位验证码完成绑定。
                </NAlert>
                <div class="twofa-qrcode">
                  <img v-if="qrDataUrl" :src="qrDataUrl" alt="2FA QR Code">
                </div>
                <div class="twofa-secret">
                  <span class="secret-label">手动输入密钥：</span>
                  <code>{{ setupSecret }}</code>
                  <NButton size="tiny" quaternary @click="copySecret">复制</NButton>
                </div>
                <NDivider />
                <NForm label-placement="top">
                  <NFormItem label="6 位验证码">
                    <NInput
                      v-model:value="verifyCode"
                      placeholder="请输入 Authenticator 中的 6 位验证码"
                      maxlength="6"
                      :input-props="{ inputmode: 'numeric', autocomplete: 'one-time-code' }"
                      @keyup.enter="confirmSetup2FA"
                    />
                  </NFormItem>
                  <div class="form-actions">
                    <NButton type="primary" :loading="faLoading" @click="confirmSetup2FA">
                      确认绑定
                    </NButton>
                    <NButton @click="cancelSetup2FA">取消</NButton>
                  </div>
                </NForm>
              </div>

              <!-- 已开启：关闭二次验证 -->
              <div v-else-if="faEnabled && faStep !== 'disable'">
                <NAlert type="success" :show-icon="false" class="twofa-alert">
                  当前账号已开启二次验证。登录或执行管理员敏感操作时，将要求输入 Authenticator 中的 6 位动态验证码。
                </NAlert>
                <div class="form-actions">
                  <NButton type="warning" ghost @click="startDisable2FA">关闭二次验证</NButton>
                </div>
              </div>

              <!-- 关闭中：输入当前验证码 -->
              <div v-else-if="faStep === 'disable'">
                <NAlert type="warning" :show-icon="false" class="twofa-alert">
                  为防止他人盗号后关闭二次验证，请先输入 Authenticator 中的 6 位当前验证码。
                </NAlert>
                <NForm label-placement="top">
                  <NFormItem label="6 位验证码">
                    <NInput
                      v-model:value="disableCode"
                      placeholder="请输入当前 6 位验证码"
                      maxlength="6"
                      :input-props="{ inputmode: 'numeric', autocomplete: 'one-time-code' }"
                      @keyup.enter="confirmDisable2FA"
                    />
                  </NFormItem>
                  <div class="form-actions">
                    <NButton type="error" :loading="faLoading" @click="confirmDisable2FA">
                      确认关闭
                    </NButton>
                    <NButton @click="cancelDisable2FA">取消</NButton>
                  </div>
                </NForm>
              </div>
            </NCard>
          </div>
        </NTabPane>

        <!-- 偏好设置 -->
        <NTabPane name="preferences" tab="偏好设置">
          <NCard :bordered="false" class="arco-card settings-card">
            <template #header>
              <NSpace align="center">
                <NIcon :size="18"><SettingsOutline /></NIcon>
                <span>界面偏好</span>
              </NSpace>
            </template>
            <div class="pref-list">
              <div class="pref-item">
                <div class="pref-info">
                  <div class="pref-label">主题模式</div>
                  <div class="pref-desc">跟随系统主题切换明暗模式</div>
                </div>
                <NTag size="small" type="info">即将支持</NTag>
              </div>
              <div class="pref-item">
                <div class="pref-info">
                  <div class="pref-label">节日彩蛋</div>
                  <div class="pref-desc">在节日或节气当天展示首页祝福与氛围效果</div>
                </div>
                <NSwitch :value="festivalEffectsEnabled" @update:value="updateFestivalEffects" />
              </div>
              <div class="pref-item">
                <div class="pref-info">
                  <div class="pref-label">通知提醒</div>
                  <div class="pref-desc">任务完成时发送通知</div>
                </div>
                <NTag size="small" type="info">即将支持</NTag>
              </div>
              <div class="pref-item">
                <div class="pref-info">
                  <div class="pref-label">默认分析流程</div>
                  <div class="pref-desc">设置常用的分析流程作为默认</div>
                </div>
                <NTag size="small" type="info">即将支持</NTag>
              </div>
            </div>
          </NCard>
        </NTabPane>

        <!-- 平台设置（仅管理员可见） -->
        <NTabPane v-if="isAdmin" name="platform" tab="平台设置">
          <section class="admin-config-section platform-settings-section" aria-label="平台设置">
            <div class="platform-settings-grid">
            <!-- 开放注册 -->
            <article class="platform-setting-card">
              <div class="platform-setting-card__header">
                <NIcon class="platform-setting-card__icon" aria-hidden="true"><GlobeOutline /></NIcon>
                <h2>开放用户注册</h2>
              </div>
              <p class="platform-setting-card__description">
                关闭后新用户将无法自助注册，需由管理员创建账号
              </p>
              <div class="platform-setting-card__control">
                <NSwitch
                  :value="platformConfig.registration_enabled"
                  :loading="platformLoading"
                  aria-label="开放用户注册"
                  @update:value="onRegistrationChange"
                />
              </div>
            </article>

            <!-- 并行子 Agent（灰度） -->
            <article class="platform-setting-card">
              <div class="platform-setting-card__header">
                <NIcon class="platform-setting-card__icon" aria-hidden="true"><GitNetworkOutline /></NIcon>
                <h2>对话内并行子 Agent</h2>
                <NTag size="small" type="warning" :bordered="false">灰度</NTag>
              </div>
              <p class="platform-setting-card__description">
                开启后，助手可用 parallel_subagents 工具把相互独立的子任务并行分派给多个专业
                Agent 执行并汇总，显著缩短复合请求耗时。环境变量
                SUBAGENT_FANOUT_ENABLED=true 也会强制启用（此时本开关关闭不生效）。
              </p>
              <div class="platform-setting-card__control">
                <NSwitch
                  :value="platformConfig.subagent_fanout_enabled"
                  :loading="platformLoading"
                  aria-label="启用对话内并行子 Agent"
                  @update:value="onSubagentFanoutChange"
                />
              </div>
            </article>

            <!-- 聊天协作 Case（灰度） -->
            <article class="platform-setting-card">
              <div class="platform-setting-card__header">
                <NIcon class="platform-setting-card__icon" aria-hidden="true"><ExtensionPuzzleOutline /></NIcon>
                <h2>聊天协作 Case</h2>
                <NTag size="small" type="warning" :bordered="false">灰度</NTag>
              </div>
              <p class="platform-setting-card__description">
                开启后，聊天可在用户确认后创建 AgentTeams 协作 Case；仍受 Bridge 配置与流程白名单限制。
              </p>
              <div class="platform-setting-card__control">
                <NSwitch
                  :value="platformConfig.agentteams_chat_entry_enabled"
                  :loading="platformLoading"
                  aria-label="启用聊天协作 Case"
                  @update:value="onAgentTeamsChatEntryChange"
                />
              </div>
            </article>

            <!-- Agent 长期记忆 -->
            <article class="platform-setting-card">
              <div class="platform-setting-card__header">
                <NIcon class="platform-setting-card__icon" aria-hidden="true"><BulbOutline /></NIcon>
                <h2>Agent 长期记忆</h2>
              </div>
              <p class="platform-setting-card__description">
                开启后，助手会跨会话记住用户的研究偏好与项目事实（mem0 引擎，加密落盘），
                并按对话自动沉淀。关闭后记忆召回、写入与自动沉淀全部停用，历史记忆保留。
                需部署侧 MEM0_ENGINE_ENABLED=true 才具备该能力。
              </p>
              <div class="platform-setting-card__control">
                <NSwitch
                  :value="platformConfig.agent_memory_enabled ?? true"
                  :loading="platformLoading"
                  aria-label="启用 Agent 长期记忆"
                  @update:value="onAgentMemoryChange"
                />
              </div>
            </article>

            <!-- TOTP 策略 -->
            <article class="platform-setting-card">
              <div class="platform-setting-card__header">
                <NIcon class="platform-setting-card__icon" aria-hidden="true"><LockClosedOutline /></NIcon>
                <h2>二次验证（TOTP）</h2>
              </div>
              <p class="platform-setting-card__description">
                {{ totpPolicyOptions.find(o => o.key === platformConfig.totp_policy)?.desc }}
              </p>
              <div class="platform-setting-card__control">
                <div class="omichub-segmented-toggle" role="group" aria-label="二次验证 TOTP 策略">
                  <button
                    v-for="opt in totpPolicyOptions"
                    :key="opt.key"
                    type="button"
                    :disabled="platformLoading"
                    :class="{ active: platformConfig.totp_policy === opt.key }"
                    :aria-pressed="platformConfig.totp_policy === opt.key"
                    @click="onTOTPPolicyChange(opt.key)"
                  >
                    {{ opt.label }}
                  </button>
                </div>
              </div>
            </article>
            </div>
          </section>
        </NTabPane>
    </NTabs>

    <!-- 平台配置修改：TOTP 二次确认 -->
    <AdminTOTPConfirmModal
      v-model:show="platformTotpModalVisible"
      title="修改平台全局配置"
      description="开放/关闭用户注册或调整 TOTP 策略属于高敏感操作，请输入当前 6 位 TOTP 验证码以继续。"
      confirm-text="确认修改"
      :loading="platformTotpLoading"
      @confirm="confirmPlatformChange"
      @cancel="cancelPlatformChange"
    />
  </main>
</template>

<style scoped>
.settings-page {
  padding: 32px 24px 48px;
}

.settings-section-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 24px;
}

@media (min-width: 1024px) {
  .settings-section-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.settings-card {
  padding: 32px;
}

@media (max-width: 640px) {
  .settings-card {
    padding: 24px;
  }
}

.avatar-section {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 32px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--neutral-border);
}

.avatar-name {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--neutral-text-1);
}

.form-actions {
  margin-top: 24px;
  display: flex;
  gap: 12px;
}

.pref-list {
  display: flex;
  flex-direction: column;
}

.pref-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0;
  border-bottom: 1px solid var(--neutral-border);
}

.pref-item:last-child {
  border-bottom: none;
}

.pref-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--neutral-text-1);
}

.pref-desc {
  font-size: 13px;
  color: var(--neutral-text-3);
  margin-top: 4px;
}

.twofa-card {
  margin-top: 0;
}

:root[data-theme="dark"] .twofa-disabled {
  background: var(--neutral-hover);
  border-color: var(--neutral-border);
}

.twofa-disabled {
  background: var(--neutral-fill-2);
  border-color: var(--neutral-border);
}

.twofa-alert {
  margin-bottom: 20px;
}

.twofa-qrcode {
  display: flex;
  justify-content: center;
  margin: 20px 0;
}

.twofa-qrcode img {
  width: 200px;
  height: 200px;
  border-radius: 8px;
  border: 1px solid var(--neutral-border);
}

.twofa-secret {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  font-size: 13px;
  color: var(--neutral-text-2);
}

:root[data-theme="dark"] .twofa-secret code {
  background: var(--neutral-hover);
}
.twofa-secret code {
  background: var(--neutral-fill-2);
  padding: 4px 8px;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.secret-label {
  color: var(--neutral-text-3);
}

@media (max-width: 480px) {
  .twofa-secret {
    flex-direction: column;
    align-items: flex-start;
  }
  .form-actions {
    flex-wrap: wrap;
  }
}

.platform-settings-section {
  padding-bottom: 4px;
}

.platform-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

.platform-setting-card {
  display: flex;
  min-width: 0;
  min-height: 224px;
  flex-direction: column;
  padding: 24px;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
}

.platform-setting-card__header {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.platform-setting-card__icon {
  display: inline-flex;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  line-height: 1;
}

.platform-setting-card__header h2 {
  min-width: 0;
  margin: 0;
  color: var(--neutral-text-1);
  font-size: 16px;
  font-weight: 500;
  line-height: 24px;
}

.platform-setting-card__description {
  margin: 16px 0 20px;
  color: var(--neutral-text-2);
  font-size: 13px;
  line-height: 20px;
}

.platform-setting-card__control {
  display: flex;
  align-items: center;
  min-height: 34px;
  margin-top: auto;
}

.platform-setting-card :deep(.n-switch) {
  flex: 0 0 auto;
}

.platform-setting-card :deep(.omichub-segmented-toggle button:disabled) {
  cursor: not-allowed;
  opacity: 0.55;
}

@media (max-width: 767px) {
  .settings-page {
    padding: 24px 16px 40px;
  }

  .platform-settings-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .platform-setting-card {
    min-height: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .platform-setting-card {
    transition: none;
  }
}
</style>
