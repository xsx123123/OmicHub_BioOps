<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { NModal, NButton, NIcon, useMessage } from 'naive-ui'
import { Vue3Lottie } from 'vue3-lottie'
import { MailOutline, CopyOutline, CheckmarkOutline } from '@vicons/ionicons5'

// ⚠️ 注意：这里的局部变量曾命名为 message，与下方 prop `message` 同名，
// 导致模板里 {{ message }} 被遮蔽成 useMessage() 返回的 MessageApi 对象（页面渲染出 {}）。
// 故重命名为 messageApi，避免与 prop 冲突。
const messageApi = useMessage()

const props = withDefaults(
  defineProps<{
    /** 弹窗显隐 */
    show: boolean
    /** 弹窗主标题（小字说明，置于文案上方）；空则不渲染标题行 */
    title?: string
    /** 关闭注册时的提示文案（来自 YAML registration.disabled_message）；未传时用默认兜底 */
    message?: string
    /** 管理员联系方式（邮箱）；空则不显示邮箱胶囊 */
    contact?: string
    /** Lottie 动画文件名（位于 public/lottie/ 下）；默认 cat.json */
    lottieName?: string
    /** 底部确认按钮文案；默认“我知道了” */
    buttonText?: string
  }>(),
  {
    title: '',
    message: '叮咚！自助注册通道暂时休息啦～(≧▽≦) 想要加入平台的话，请呼叫管理员为你创建专属账号呀！',
    contact: '',
    lottieName: 'cat.json',
    buttonText: '我知道了',
  },
)

const emit = defineEmits<{
  'update:show': [value: boolean]
  /** 点击底部确认按钮时触发（区别于蒙层关闭：仅按钮点击才会计数/触发彩蛋） */
  confirm: []
}>()

// cat.json 静态路径：public/lottie/{lottieName} → 访问 URL /lottie/{lottieName}
// 用 BASE_URL 拼接，兼容部署到子路径；改 json 后刷新即生效，无需重新 build
const lottieUrl = computed(
  () => `${import.meta.env.BASE_URL}lottie/${props.lottieName}`,
)

// 动画尺寸：放大到 140px，居中显示
const lottieSize = 140

// 动画加载失败兜底：cat.json 尚未放置 / 损坏时显示猫 emoji，弹窗仍可用
const lottieFailed = ref(false)
function handleLottieError() {
  lottieFailed.value = true
}
// 每次打开弹窗重置失败标记，让用户后来补放 cat.json 时能重新加载动画
watch(
  () => props.show,
  (v) => {
    if (v) lottieFailed.value = false
  },
)

// 复制邮箱到剪贴板（navigator.clipboard 失败时降级 execCommand）
const copied = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | null = null
async function copyContact() {
  const email = props.contact?.trim()
  if (!email) return
  try {
    await navigator.clipboard.writeText(email)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = email
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
    } catch {
      /* ignore */
    }
    document.body.removeChild(ta)
  }
  copied.value = true
  messageApi.success('邮箱已复制')
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    copied.value = false
  }, 2000)
}

function handleUpdateShow(v: boolean) {
  emit('update:show', v)
}
function close() {
  emit('update:show', false)
}
/** 点击确认按钮：先发 confirm（供父组件计数/触发彩蛋），再关闭。
 *  蒙层关闭只走 handleUpdateShow，不会触发 confirm。 */
function handleConfirm() {
  emit('confirm')
  close()
}

onUnmounted(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <NModal
    :show="show"
    :auto-focus="false"
    :mask-closable="true"
    transform-origin="center"
    @update:show="handleUpdateShow"
  >
    <div class="reg-modal">
      <!-- 顶部 Lottie 猫动画（放大 + 居中） -->
      <div class="reg-lottie">
        <Vue3Lottie
          v-if="!lottieFailed"
          :animation-link="lottieUrl"
          :loop="true"
          :auto-play="true"
          :height="lottieSize"
          :width="lottieSize"
          @on-error="handleLottieError"
        />
        <div v-else class="reg-lottie-fallback" aria-hidden="true">🐱</div>
      </div>

      <!-- 标题（可选，账户未激活等场景使用） -->
      <p v-if="title" class="reg-title">{{ title }}</p>

      <!-- 提示文案（居中 / 行高 1.6 / 深灰） -->
      <p class="reg-message">{{ message }}</p>

      <!-- 邮箱胶囊 + 复制按钮 -->
      <div v-if="contact" class="reg-contact-row">
        <a
          :href="`mailto:${contact}`"
          class="reg-contact-pill"
          :title="`发送邮件到 ${contact}`"
        >
          <NIcon :size="14" class="reg-pill-icon">
            <MailOutline />
          </NIcon>
          <span class="reg-pill-text">{{ contact }}</span>
        </a>
        <button
          class="reg-copy-btn"
          type="button"
          :title="copied ? '已复制' : '复制邮箱'"
          @click="copyContact"
        >
          <NIcon :size="14">
            <CheckmarkOutline v-if="copied" />
            <CopyOutline v-else />
          </NIcon>
        </button>
      </div>

      <!-- 底部按钮（居中） -->
      <NButton type="primary" class="reg-confirm-btn" @click="handleConfirm">
        {{ buttonText }}
      </NButton>
    </div>
  </NModal>
</template>

<style scoped>
.reg-modal {
  width: 400px;
  max-width: calc(100vw - 48px);
  /* Glassmorphism：半透明白底，透出背后登录卡片与渐变 */
  background-color: rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  /* 玻璃边缘：极细半透明白边 */
  border: 1px solid rgba(255, 255, 255, 0.4);
  border-radius: 16px;
  padding: 28px 28px 24px;
  /* 弥散柔和阴影 */
  box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.1);
  display: flex;
  flex-direction: column;
  align-items: center;
  box-sizing: border-box;
}

:root[data-theme="dark"] .reg-modal {
  background-color: rgba(21, 26, 37, 0.85);
  border-color: rgba(255, 255, 255, 0.1);
}

/* ===== Lottie 动画区（放大到 140px，居中） ===== */
.reg-lottie {
  height: 140px;
  width: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
  flex-shrink: 0;
}

.reg-lottie-fallback {
  font-size: 80px;
  line-height: 140px;
  text-align: center;
  animation: reg-bounce 1.6s ease-in-out infinite;
}

@keyframes reg-bounce {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-6px);
  }
}

/* ===== 标题（居中 / 加粗 / 深色，账户未激活等场景） ===== */
.reg-title {
  text-align: center;
  font-size: 17px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0 0 8px;
  word-break: break-word;
}

/* ===== 文案（居中 / 行高 1.6 / 深灰 #4B5563） ===== */
.reg-message {
  text-align: center;
  font-size: 15px;
  line-height: 1.6;
  color: var(--neutral-text-2);
  margin: 4px 0 18px;
  word-break: break-word;
}

/* ===== 邮箱胶囊 + 复制按钮 ===== */
.reg-contact-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 20px;
  max-width: 100%;
}

.reg-contact-pill {
  /* 不设 max-width 上限，让胶囊按内容自适应；仅受弹窗宽度约束 */
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  min-width: 0;
  padding: 8px 16px;
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: background 0.2s ease;
}

.reg-contact-pill:hover {
  filter: brightness(0.92);
}

.reg-pill-icon {
  flex-shrink: 0;
  color: var(--arco-primary);
}

/* 邮箱文本：不截断、不换行、完整展示 */
.reg-pill-text {
  flex-shrink: 0;
  white-space: nowrap;
}

.reg-copy-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--neutral-border);
  background: var(--neutral-card);
  border-radius: 999px;
  color: var(--neutral-text-2);
  cursor: pointer;
  transition: all 0.2s ease;
}

.reg-copy-btn:hover {
  background: var(--neutral-hover);
  color: var(--arco-primary);
  border-color: var(--arco-primary);
}

/* ===== 底部按钮（居中） ===== */
.reg-confirm-btn {
  width: 100%;
  border-radius: 8px;
  font-weight: 500;
}

/* ===== 移动端窄屏：缩小胶囊字号与内边距，保证完整邮箱可见 ===== */
@media (max-width: 400px) {
  .reg-contact-pill {
    font-size: 11px;
    padding: 6px 12px;
    gap: 4px;
  }
}
</style>
