<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { festivalApi } from '@/api/festival'
import FestivalBackground from './FestivalBackground.vue'
import FestivalEffect from './FestivalEffect.vue'
import FestivalDecoration from './FestivalDecoration.vue'
import { resolveFestivalTheme } from '@/utils/festivalThemes'
import type { FestivalConfig } from '@/types/festival'

interface Props {
  festival: FestivalConfig
  /** 后端已领取状态：避免已领取用户仍看到领取按钮 */
  alreadyClaimed?: boolean
  /** 预览模式：不调用领取接口、不写 localStorage、不跳转 */
  preview?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  alreadyClaimed: false,
  preview: false,
})
const emit = defineEmits<{
  (e: 'claimed'): void
  (e: 'close'): void
}>()

const message = useMessage()
const visible = ref(true)
const claiming = ref(false)
const claimed = ref(props.alreadyClaimed)
const hasSeen = ref(false)

const storageSeenKey = computed(() => `festival_seen_${props.festival.id}`)
const theme = computed(() => resolveFestivalTheme(props.festival.name))
const popup = computed(() => props.festival.popup)
const quota = computed(() => props.festival.quotaBonus)
const animation = computed(() => popup.value.animation)
const animationEnabled = computed(() => animation.value?.enabled ?? true)
const animationType = computed(() => theme.value.id || theme.value.phenology || theme.value.animationType)
const animationDuration = computed(() => animation.value?.duration ?? 12)
const particleColors = computed(() => theme.value.particleColors)

const isProgrammersDay = computed(() => theme.value.id === 'programmers_day')

const popupWrapperClass = computed(() => ({
  [`festival-theme-${theme.value.id}`]: true,
  [`texture-${theme.value.texture || 'silk'}`]: true,
  [`form-${theme.value.form || 'tablet'}`]: true,
  [`layout-${theme.value.layout || 'classic'}`]: true,
  [`motion-${theme.value.motionProfile || 'gentle'}`]: true,
  [`phenology-${theme.value.phenology || theme.value.animationType}`]: true,
  'programmers-day-popup': isProgrammersDay.value,
}))

const showClaimButton = computed(
  () => quota.value.enabled && quota.value.amount > 0 && !claimed.value,
)

function formatFestivalText(source: string) {
  const amount = String(Math.floor(quota.value.amount || 0))
  return source
    .replace(/\{\{\s*bonusAmount\s*\}\}/g, amount)
    .replace(/\{amount\}/g, amount)
}

function stripDecorativeGlyphs(source: string) {
  return source
    .replace(/[\uFE0F\u200D]/g, '')
    .replace(/\p{Extended_Pictographic}/gu, '')
    .replace(/\s+/g, ' ')
    .trim()
}

const displayTitle = computed(() => stripDecorativeGlyphs(formatFestivalText(popup.value.title?.trim() || theme.value.title)))
const configuredPoem = computed(() => {
  const description = props.festival.description?.trim()
  if (!description) return { poem: theme.value.poem, author: theme.value.poemAuthor }

  const [poem, author = ''] = description.split(/——|--/, 2).map((part) => part.trim())
  return {
    poem: poem || theme.value.poem,
    author: author || theme.value.poemAuthor,
  }
})
const mainDescriptionSource = computed(() => (
  popup.value.description?.trim()
  || quota.value.description?.trim()
  || ''
))
const messageText = computed(() => {
  const configuredContent = popup.value.content?.trim()
  return formatFestivalText(mainDescriptionSource.value || configuredContent || theme.value.message)
})
const claimButtonText = computed(() => stripDecorativeGlyphs(popup.value.primaryButton?.text || theme.value.buttonText) || '领取')
const quotaUnitLabel = computed(() => {
  if (quota.value.unit === 'cookie') return '饼干'
  return quota.value.unit || '额度'
})
const quotaDescriptionText = computed(() => {
  const description = quota.value.description?.trim()
  if (description && description === mainDescriptionSource.value) {
    return quota.value.unit === 'cookie' ? '节日专属饼干' : '节日专属额度'
  }
  return description || '节日专属饼干'
})

watch(
  () => props.festival.id,
  () => {
    claimed.value = props.alreadyClaimed
    claiming.value = false
    if (props.preview) {
      visible.value = true
      return
    }
    hasSeen.value = localStorage.getItem(storageSeenKey.value) === '1'
    visible.value = !hasSeen.value
    if (hasSeen.value) emit('close')
  },
  { immediate: true },
)

watch(
  () => props.alreadyClaimed,
  (value) => {
    claimed.value = value
  },
)

async function handleClaim() {
  if (claiming.value) return
  if (props.preview) {
    claimed.value = true
    message.success('模拟领取成功（预览模式未实际发放额度）')
    emit('claimed')
    return
  }
  claiming.value = true
  try {
    const res = await festivalApi.claimFestival(props.festival.id)
    if (res.success) {
      claimed.value = true
      message.success(res.message)
      emit('claimed')
    } else {
      message.info(res.message)
    }
  } catch {
    message.error('领取失败，请稍后重试')
  } finally {
    claiming.value = false
  }
}

function handleClose() {
  if (!props.preview) {
    localStorage.setItem(storageSeenKey.value, '1')
  }
  visible.value = false
  emit('close')
}

function handleBackdropClick() {
  handleClose()
}

function handleSecondaryClick(btn: { action: string; link?: string | null }) {
  if (!props.preview && btn.action === 'navigate' && btn.link) {
    window.location.href = btn.link
  }
  handleClose()
}

const popupStyle = computed(() => {
  const ambient = theme.value.ambientColor || theme.value.borderColor
  const highlight = theme.value.highlightColor || theme.value.titleColor
  return {
    background: `
      radial-gradient(circle at 16% 0%, color-mix(in srgb, ${ambient} 22%, transparent) 0, transparent 34%),
      radial-gradient(circle at 88% 16%, color-mix(in srgb, ${highlight} 14%, transparent) 0, transparent 28%),
      radial-gradient(circle at 52% 118%, color-mix(in srgb, ${theme.value.titleColor} 10%, transparent) 0, transparent 42%),
      ${theme.value.gradient}
    `,
    borderColor: theme.value.borderColor,
    boxShadow: `0 34px 92px rgba(0, 0, 0, 0.54), 0 0 58px color-mix(in srgb, ${ambient} 18%, transparent), inset 0 1px 0 rgba(255,255,255,0.14)`,
    fontFamily: theme.value.fontFamily || "'Noto Serif SC', 'SF Pro Display', 'PingFang SC', serif",
  }
})

const titleStyle = computed(() => ({
  color: theme.value.titleColor,
  textShadow: `0 0 22px ${theme.value.borderColor}`,
  fontFamily: theme.value.fontFamily || 'inherit',
}))

const textStyle = computed(() => ({
  color: theme.value.textColor,
  fontFamily: theme.value.fontFamily || 'inherit',
}))

const taglineStyle = computed(() => ({
  color: theme.value.taglineColor,
}))

const amountStyle = computed(() => ({
  color: theme.value.amountColor,
  textShadow: theme.value.amountGlow,
}))

const buttonStyle = computed(() => ({
  background: theme.value.buttonGradient,
  color: theme.value.buttonTextColor,
  boxShadow: theme.value.buttonShadow,
  fontFamily: theme.value.fontFamily || 'inherit',
}))

const cssVars = computed(() => ({
  '--theme-color': theme.value.titleColor,
  '--theme-border': theme.value.borderColor,
  '--theme-amount': theme.value.amountColor,
  '--theme-glow': theme.value.amountGlow,
  '--theme-btn-shadow': theme.value.buttonShadow,
  '--theme-ambient': theme.value.ambientColor || theme.value.borderColor,
  '--theme-surface': theme.value.surfaceColor || 'rgba(14, 18, 26, 0.72)',
  '--theme-highlight': theme.value.highlightColor || theme.value.titleColor,
}))

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && visible.value) handleClose()
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Transition
    enter-active-class="transition-opacity duration-300"
    leave-active-class="festival-modal-leave transition-opacity duration-[240ms]"
    enter-from-class="opacity-0"
    leave-to-class="opacity-0"
  >
    <div
      v-if="visible"
      class="festival-modal fixed inset-0 z-[3500] flex items-center justify-center p-4"
      @click.self="handleBackdropClick"
    >
      <FestivalBackground
        :type="animationType"
        :colors="particleColors"
        :ambient-color="theme.ambientColor"
        :highlight-color="theme.highlightColor"
        :disabled="!animationEnabled"
      />

      <FestivalEffect
        v-if="animationEnabled"
        class="festival-effect-layer"
        :type="animationType"
        :duration="animationDuration"
        :colors="particleColors"
      />

      <div class="festival-backdrop" @click="handleBackdropClick" />

      <div
        class="festival-popup relative z-10 w-full max-w-lg overflow-hidden p-8 text-center"
        :class="popupWrapperClass"
        :style="[popupStyle, cssVars]"
        role="dialog"
        aria-modal="true"
        :aria-label="displayTitle"
        @click.stop
      >
        <div class="festival-surface" aria-hidden="true" />
        <FestivalDecoration :decoration="theme.decoration" :theme-color="theme.titleColor" :phenology="theme.phenology || theme.animationType" />
        <div class="festival-top-bar" />

        <button
          type="button"
          class="festival-close-btn"
          aria-label="关闭"
          @click="handleClose"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        <div class="festival-badge relative z-10 mx-auto mb-3 inline-flex items-center gap-1.5 rounded-full border px-4 py-1 text-xs">
          <span class="festival-badge-dot" aria-hidden="true" />
          <span class="font-medium">{{ festival.name }}</span>
        </div>

        <h2 class="festival-title" :style="titleStyle">
          {{ displayTitle }}
        </h2>

        <div class="festival-poem-card">
          <span class="quote-mark quote-left">“</span>
          <p class="festival-poem-title" :style="titleStyle">
            {{ configuredPoem.poem }}
          </p>
          <p class="festival-poem-author" :style="taglineStyle">—— {{ configuredPoem.author }}</p>
          <span class="quote-mark quote-right">”</span>
        </div>

        <div class="festival-divider" />

        <div class="festival-message" :style="textStyle">
          {{ messageText }}
        </div>

        <div v-if="quota.enabled" class="relative z-10 mt-6">
          <div class="festival-amount-card">
            <div class="festival-amount-halo" />
            <div class="festival-amount-label" :style="taglineStyle">节日专属额度</div>
            <div class="festival-amount-number" :style="amountStyle">
              +{{ Math.floor(quota.amount) }}
            </div>
            <div class="festival-amount-unit" :style="taglineStyle">{{ quotaUnitLabel }}</div>
          </div>
          <div class="festival-quota-desc" :style="taglineStyle">
            {{ quotaDescriptionText }}
          </div>
        </div>

        <div class="festival-actions">
          <button
            v-if="showClaimButton"
            type="button"
            class="festival-btn-primary"
            :disabled="claiming"
            :style="buttonStyle"
            @click="handleClaim"
          >
            {{ claiming ? '领取中...' : claimButtonText }}
          </button>
          <span
            v-else-if="claimed"
            class="festival-claimed-pill"
            :style="{ color: theme.taglineColor }"
          >
            已领取 ✓
          </span>

          <button
            v-if="popup.secondaryButton"
            type="button"
            class="festival-btn-secondary"
            @click="handleSecondaryClick(popup.secondaryButton)"
          >
            {{ popup.secondaryButton.text || '了解更多' }}
          </button>
        </div>


        <p class="festival-tagline" :style="taglineStyle">
          {{ isProgrammersDay ? '/* We are made of star-stuff */' : '"We are made of star-stuff"' }}
        </p>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.festival-backdrop {
  position: absolute;
  inset: 0;
  z-index: 1;
  background: rgba(0, 0, 0, 0.38);
  backdrop-filter: blur(14px) saturate(1.05);
  -webkit-backdrop-filter: blur(14px) saturate(1.05);
  pointer-events: auto;
}

.festival-effect-layer {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}

.festival-modal {
  isolation: isolate;
}

.festival-popup {
  width: min(100%, 540px);
  min-height: 430px;
  border: 1px solid var(--theme-border);
  border-radius: 28px;
  color: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(30px) saturate(1.18);
  -webkit-backdrop-filter: blur(30px) saturate(1.18);
  transform-origin: center 56%;
  animation: modalSpringIn 680ms cubic-bezier(0.16, 1, 0.3, 1) both;
  transition: box-shadow 420ms cubic-bezier(0.16, 1, 0.3, 1), border-color 420ms cubic-bezier(0.16, 1, 0.3, 1);
  will-change: transform;
}

/* 退出沿同一空间路径返回（向下 + 缩小 + 失焦），缓动与入场互为镜像；
   animation: none 解除入场关键帧 forwards 填充对 transform 的锁定 */
.festival-modal-leave .festival-popup {
  animation: none;
  transform: translate3d(0, 14px, 0) scale(0.972);
  filter: blur(4px);
  transition:
    transform 240ms cubic-bezier(0.7, 0, 0.84, 0),
    filter 240ms cubic-bezier(0.7, 0, 0.84, 0);
}


.festival-popup.form-scroll {
  width: min(100%, 760px);
  min-height: 370px;
  padding: 34px 44px 30px;
  border-radius: 34px 18px 34px 18px;
}
.festival-popup.form-moon {
  width: min(100%, 530px);
  min-height: 486px;
  border-radius: 42px 42px 126px 126px / 34px 34px 78px 78px;
}
.festival-popup.form-ripple {
  width: min(100%, 570px);
  min-height: 430px;
  border-radius: 46px;
}
.festival-popup.form-jade {
  width: min(100%, 510px);
  border-radius: 44px 20px 44px 20px;
}
.festival-popup.form-mountain {
  width: min(100%, 590px);
  border-radius: 24px 42px 30px 42px;
}
.festival-popup.form-banner {
  width: min(100%, 760px);
  min-height: 390px;
  border-radius: 22px 48px 22px 48px;
}
.festival-popup.form-petal {
  width: min(100%, 540px);
  border-radius: 58px 26px 58px 26px;
}
.festival-popup.form-frost {
  width: min(100%, 520px);
  border-radius: 22px;
}
.festival-popup.form-terminal {
  width: min(100%, 620px);
  border-radius: 18px;
}
.festival-popup.form-orbital {
  width: min(100%, 600px);
  min-height: 455px;
  border-radius: 36px;
}

.festival-popup.form-scroll .festival-surface::before,
.festival-popup.form-banner .festival-surface::before,
.festival-popup.form-mountain .festival-surface::before,
.festival-popup.form-moon .festival-surface::before,
.festival-popup.form-ripple .festival-surface::before,
.festival-popup.form-frost .festival-surface::before,
.festival-popup.form-orbital .festival-surface::before {
  content: '';
  position: absolute;
  inset: 14px;
  border-radius: inherit;
  pointer-events: none;
  opacity: 0.24;
  mix-blend-mode: screen;
}
.festival-popup.form-scroll .festival-surface::before {
  border-top: 1px solid color-mix(in srgb, var(--theme-highlight) 50%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--theme-highlight) 38%, transparent);
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--theme-highlight) 8%, transparent), transparent);
}
.festival-popup.form-banner .festival-surface::before,
.festival-popup.form-mountain .festival-surface::before {
  inset: auto 20px 18px;
  height: 76px;
  border-radius: 0 0 28px 28px;
  background:
    linear-gradient(135deg, transparent 0 42%, color-mix(in srgb, var(--theme-highlight) 22%, transparent) 42% 44%, transparent 44%),
    linear-gradient(45deg, transparent 0 52%, color-mix(in srgb, var(--theme-color) 16%, transparent) 52% 54%, transparent 54%);
}
.festival-popup.form-moon .festival-surface::before {
  inset: 26px 48px auto;
  height: 132px;
  border-radius: 999px 999px 16px 16px;
  border-top: 1px solid color-mix(in srgb, var(--theme-highlight) 58%, transparent);
  background: radial-gradient(ellipse at 50% 0%, color-mix(in srgb, var(--theme-highlight) 18%, transparent), transparent 66%);
}
.festival-popup.form-ripple .festival-surface::before {
  inset: auto 24px 20px;
  height: 88px;
  border-radius: 999px;
  background: repeating-radial-gradient(ellipse at center, transparent 0 17px, color-mix(in srgb, var(--theme-highlight) 14%, transparent) 18px 19px, transparent 20px 35px);
}
.festival-popup.form-frost .festival-surface::before {
  background:
    linear-gradient(112deg, transparent 0 42%, color-mix(in srgb, var(--theme-highlight) 28%, transparent) 42% 43%, transparent 44%),
    linear-gradient(36deg, transparent 0 58%, color-mix(in srgb, var(--theme-color) 18%, transparent) 58% 59%, transparent 60%);
  filter: blur(0.2px);
}
.festival-popup.form-orbital .festival-surface::before {
  inset: 34px;
  border: 1px solid color-mix(in srgb, var(--theme-highlight) 28%, transparent);
  border-radius: 50%;
  transform: rotate(-18deg) scaleX(1.18);
}

.festival-popup.motion-water { animation-name: modalWaterIn; animation-duration: 820ms; }
.festival-popup.motion-botanical { animation-name: modalGrowIn; animation-duration: 760ms; }
.festival-popup.motion-crystal { animation-name: modalCondenseIn; animation-duration: 860ms; }
.festival-popup.motion-astral { animation-name: modalOrbitIn; animation-duration: 840ms; }
.festival-popup.motion-firm { animation-duration: 620ms; }

.festival-popup::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: 0.32;
  mix-blend-mode: soft-light;
  background-image:
    radial-gradient(circle at 22% 18%, rgba(255,255,255,0.34) 0 1px, transparent 1.4px),
    radial-gradient(circle at 74% 62%, rgba(255,255,255,0.22) 0 1px, transparent 1.5px);
  background-size: 34px 34px, 46px 46px;
  mask-image: linear-gradient(black, transparent 92%);
  animation: texturePhase 22s cubic-bezier(0.22, 1, 0.36, 1) infinite alternate;
}
.texture-paper::before {
  background-image:
    linear-gradient(115deg, rgba(255,255,255,0.18) 0 1px, transparent 1px),
    radial-gradient(circle, rgba(255,255,255,0.26) 0 0.8px, transparent 1px);
  background-size: 26px 26px, 39px 39px;
}
.texture-mist::before,
.texture-frost::before {
  background-image:
    radial-gradient(circle at 18% 22%, rgba(255,255,255,0.32), transparent 28%),
    radial-gradient(circle at 78% 68%, rgba(255,255,255,0.22), transparent 32%),
    linear-gradient(100deg, rgba(255,255,255,0.12) 0 1px, transparent 1px);
  background-size: 100% 100%, 100% 100%, 38px 38px;
}
.texture-lattice::before,
.texture-code::before {
  background-image:
    linear-gradient(rgba(255,255,255,0.14) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.12) 1px, transparent 1px);
  background-size: 28px 28px, 28px 28px;
}
.texture-grain::before,
.texture-bamboo::before {
  background-image:
    linear-gradient(96deg, rgba(255,255,255,0.16) 0 1px, transparent 1px),
    linear-gradient(174deg, color-mix(in srgb, var(--theme-highlight) 12%, transparent) 0 1px, transparent 1px),
    radial-gradient(circle, rgba(255,255,255,0.18) 0 0.8px, transparent 1.2px);
  background-size: 18px 54px, 42px 96px, 33px 33px;
}
.texture-brocade::before {
  background-image:
    repeating-linear-gradient(45deg, color-mix(in srgb, var(--theme-highlight) 12%, transparent) 0 1px, transparent 1px 13px),
    repeating-linear-gradient(-45deg, color-mix(in srgb, var(--theme-color) 10%, transparent) 0 1px, transparent 1px 17px),
    radial-gradient(circle, rgba(255,255,255,0.16) 0 0.8px, transparent 1.2px);
  background-size: 48px 48px, 52px 52px, 36px 36px;
}
.texture-jade::before {
  background-image:
    radial-gradient(ellipse at 24% 28%, color-mix(in srgb, var(--theme-highlight) 22%, transparent), transparent 34%),
    radial-gradient(ellipse at 72% 68%, color-mix(in srgb, var(--theme-color) 14%, transparent), transparent 38%),
    linear-gradient(118deg, transparent 0 45%, rgba(255,255,255,0.12) 46% 47%, transparent 48%);
  background-size: 100% 100%, 100% 100%, 76px 76px;
}
.texture-porcelain::before {
  background-image:
    linear-gradient(28deg, transparent 0 38%, color-mix(in srgb, var(--theme-highlight) 16%, transparent) 39% 40%, transparent 41%),
    linear-gradient(112deg, transparent 0 56%, color-mix(in srgb, var(--theme-color) 12%, transparent) 57% 58%, transparent 59%),
    radial-gradient(circle, rgba(255,255,255,0.18) 0 0.8px, transparent 1.1px);
  background-size: 96px 96px, 132px 132px, 34px 34px;
}
.texture-book::before {
  background-image:
    radial-gradient(circle at 20% 22%, color-mix(in srgb, var(--theme-highlight) 12%, transparent) 0 1.2px, transparent 1.7px),
    radial-gradient(circle at 70% 62%, rgba(255,255,255,0.16) 0 0.8px, transparent 1.2px),
    linear-gradient(90deg, color-mix(in srgb, var(--theme-color) 10%, transparent) 0 1px, transparent 1px);
  background-size: 46px 46px, 31px 31px, 72px 100%;
}
.festival-surface {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    linear-gradient(145deg, rgba(255,255,255,0.11), transparent 34%),
    linear-gradient(180deg, rgba(255,255,255,0.055), transparent 72%),
    radial-gradient(circle at 50% -10%, color-mix(in srgb, var(--theme-highlight) 12%, transparent), transparent 38%);
  opacity: 0.9;
}
.festival-surface::before {
  content: none;
}
.festival-surface::after {
  content: '';
  position: absolute;
  inset: 1px;
  border-radius: 27px;
  pointer-events: none;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.18),
    inset 0 -1px 0 rgba(255,255,255,0.055),
    inset 1px 0 0 rgba(255,255,255,0.06),
    inset -1px 0 0 rgba(255,255,255,0.06);
}

@keyframes modalSpringIn {
  0% { opacity: 0; transform: translate3d(0, 24px, 0) scale(0.965); filter: blur(6px); }
  100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); filter: blur(0); }
}

@keyframes modalWaterIn {
  0% { opacity: 0; transform: translate3d(0, 28px, 0) scale(0.972, 0.985); filter: blur(10px); }
  100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); filter: blur(0); }
}
@keyframes modalGrowIn {
  0% { opacity: 0; transform: translate3d(0, 18px, 0) scale(0.94); filter: blur(7px); clip-path: inset(12% 8% 18% round 30px); }
  100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); filter: blur(0); clip-path: inset(0 round 30px); }
}
@keyframes modalCondenseIn {
  0% { opacity: 0; transform: translate3d(0, 14px, 0) scale(0.982); filter: blur(14px) saturate(0.86); }
  100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); filter: blur(0) saturate(1); }
}
@keyframes modalOrbitIn {
  0% { opacity: 0; transform: translate3d(0, 20px, 0) scale(0.966) rotateX(3deg); filter: blur(8px); }
  100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); filter: blur(0); }
}

@keyframes texturePhase {
  0% { background-position: 0 0, 0 0; opacity: 0.24; }
  100% { background-position: 18px -12px, -14px 16px; opacity: 0.38; }
}

.festival-top-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--theme-highlight) 68%, transparent), rgba(255,255,255,0.7), color-mix(in srgb, var(--theme-color) 54%, transparent), transparent);
  opacity: 0.86;
  border-radius: 28px 28px 0 0;
  z-index: 1;
  pointer-events: none;
}

.festival-close-btn {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 20;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.82);
  cursor: pointer;
  transition: transform 260ms cubic-bezier(0.16, 1, 0.3, 1), background 260ms cubic-bezier(0.16, 1, 0.3, 1), border-color 260ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 260ms cubic-bezier(0.16, 1, 0.3, 1);
}
.festival-close-btn svg {
  width: 16px;
  height: 16px;
}
.festival-close-btn:hover {
  transform: translateY(-1px) scale(1.04);
  background: rgba(255, 255, 255, 0.13);
  border-color: var(--theme-border);
  color: var(--theme-color);
  box-shadow: 0 10px 24px rgba(0,0,0,0.16), 0 0 18px color-mix(in srgb, var(--theme-border) 72%, transparent);
}
.festival-close-btn:active {
  transform: translateY(0) scale(0.96);
  box-shadow: inset 0 2px 8px rgba(0,0,0,0.2);
  transition-duration: 100ms;
}
.festival-close-btn:focus-visible,
.festival-btn-primary:focus-visible,
.festival-btn-secondary:focus-visible {
  outline: 2px solid var(--theme-color);
  outline-offset: 2px;
}

.festival-badge {
  border-color: color-mix(in srgb, var(--theme-color) 30%, rgba(255,255,255,0.18));
  background: color-mix(in srgb, var(--theme-surface) 78%, rgba(255,255,255,0.08));
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.12), 0 10px 24px rgba(0,0,0,0.08);
  color: rgba(255, 255, 255, 0.84);
}
.festival-badge-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--theme-color);
  box-shadow: 0 0 18px color-mix(in srgb, var(--theme-color) 72%, transparent);
}

.festival-title {
  position: relative;
  z-index: 10;
  margin: 0 44px 14px;
  font-size: 1.52rem;
  font-weight: 800;
  line-height: 1.28;
  /* 大字标题收紧字距（字号越大字距越显宽），并启用光学尺寸 */
  letter-spacing: -0.01em;
  font-optical-sizing: auto;
  word-break: keep-all;
}

.festival-poem-card {
  position: relative;
  z-index: 10;
  margin: 0 auto 16px;
  max-width: 92%;
  padding: 18px 24px 14px;
  background: color-mix(in srgb, var(--theme-surface) 78%, rgba(255,255,255,0.06));
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid color-mix(in srgb, var(--theme-color) 34%, transparent);
  border-radius: 18px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.1), inset 0 0 24px rgba(255,255,255,0.035), 0 16px 34px rgba(0,0,0,0.16);
}

.layout-couplet .festival-poem-card {
  max-width: min(94%, 520px);
  border-radius: 12px;
  border-left-color: color-mix(in srgb, var(--theme-highlight) 56%, transparent);
  border-right-color: color-mix(in srgb, var(--theme-highlight) 56%, transparent);
  box-shadow: inset 10px 0 18px color-mix(in srgb, var(--theme-color) 7%, transparent), inset -10px 0 18px color-mix(in srgb, var(--theme-highlight) 6%, transparent), 0 16px 34px rgba(0,0,0,0.16);
}
.layout-moon-arc .festival-poem-card {
  max-width: min(94%, 430px);
  padding-top: 24px;
  border-radius: 999px 999px 26px 26px;
  background: radial-gradient(ellipse at 50% 0%, color-mix(in srgb, var(--theme-highlight) 13%, transparent), transparent 68%), color-mix(in srgb, var(--theme-surface) 78%, rgba(255,255,255,0.06));
}
.layout-river .festival-poem-card {
  border-radius: 26px 42px 26px 42px;
}
.layout-river .festival-divider {
  width: min(82%, 420px);
  height: 10px;
  border-radius: 999px;
  background:
    radial-gradient(ellipse at 20% 50%, color-mix(in srgb, var(--theme-highlight) 32%, transparent), transparent 48%),
    radial-gradient(ellipse at 74% 54%, color-mix(in srgb, var(--theme-color) 28%, transparent), transparent 52%);
  box-shadow: 0 0 18px color-mix(in srgb, var(--theme-border) 74%, transparent);
}
.layout-vertical-rain .festival-poem-card {
  display: inline-flex;
  max-width: min(100%, 340px);
  min-height: 176px;
  justify-content: center;
  align-items: center;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  border-radius: 30px 14px 30px 14px;
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--theme-highlight) 10%, transparent), transparent 32%),
    color-mix(in srgb, var(--theme-surface) 80%, rgba(255,255,255,0.06));
}
.layout-vertical-rain .festival-poem-title {
  max-height: 9.4em;
  font-size: 1.18rem;
  letter-spacing: 0.06em;
}
.layout-vertical-rain .festival-poem-author {
  margin: 0 8px 0 0;
  font-size: 0.72rem;
}
.layout-vertical-rain .quote-mark { display: none; }
.layout-mountain .festival-poem-card {
  border-radius: 18px 34px 18px 34px;
  background:
    linear-gradient(160deg, transparent 0 58%, color-mix(in srgb, var(--theme-highlight) 10%, transparent) 59% 60%, transparent 62%),
    color-mix(in srgb, var(--theme-surface) 78%, rgba(255,255,255,0.06));
}
.layout-mountain .festival-divider {
  height: 14px;
  background:
    linear-gradient(135deg, transparent 0 44%, var(--theme-color) 45% 46%, transparent 47%),
    linear-gradient(45deg, transparent 0 52%, color-mix(in srgb, var(--theme-highlight) 70%, transparent) 53% 54%, transparent 55%);
  box-shadow: none;
}
.layout-bridge .festival-poem-card {
  border-radius: 999px 999px 24px 24px;
  border-top-color: color-mix(in srgb, var(--theme-highlight) 54%, transparent);
}
.layout-field .festival-amount-card {
  border-radius: 12px 18px 12px 18px;
  background:
    linear-gradient(rgba(255,255,255,0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px),
    linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.035));
  background-size: 18px 18px, 18px 18px, 100% 100%;
}
.layout-code {
  text-align: left;
}
.layout-code .festival-badge,
.layout-code .festival-actions,
.layout-code .festival-tagline {
  margin-left: 0;
  margin-right: auto;
}
.layout-code .festival-poem-card,
.layout-code .festival-message {
  margin-left: 0;
  margin-right: 0;
  max-width: 100%;
}
.layout-code .festival-poem-card {
  border-radius: 14px;
}
.layout-star-map .festival-poem-card {
  border-radius: 32px;
  background:
    radial-gradient(circle at 18% 28%, color-mix(in srgb, var(--theme-highlight) 22%, transparent) 0 1px, transparent 2px),
    radial-gradient(circle at 76% 66%, color-mix(in srgb, var(--theme-color) 18%, transparent) 0 1px, transparent 2px),
    color-mix(in srgb, var(--theme-surface) 78%, rgba(255,255,255,0.06));
}
.festival-poem-title {
  margin: 0;
  font-family: 'Noto Serif SC', 'STKaiti', 'KaiTi', serif;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1.45;
}
.festival-poem-author {
  margin: 7px 0 0;
  font-size: 0.82rem;
  font-style: italic;
  opacity: 0.82;
}
.quote-mark {
  position: absolute;
  font-family: 'Noto Serif SC', serif;
  font-size: 50px;
  line-height: 1;
  color: var(--theme-color);
  opacity: 0.16;
  pointer-events: none;
}
.quote-left { top: 5px; left: 8px; }
.quote-right { bottom: -10px; right: 10px; }

.festival-divider {
  position: relative;
  z-index: 10;
  width: min(76%, 360px);
  height: 1px;
  margin: 0 auto 16px;
  background: linear-gradient(90deg, transparent, var(--theme-color), rgba(255,255,255,0.72), var(--theme-color), transparent);
  box-shadow: 0 0 14px var(--theme-border);
  animation: dividerExpand 0.64s cubic-bezier(0.16, 1, 0.3, 1) both 0.12s;
}
@keyframes dividerExpand {
  from { transform: scaleX(0); opacity: 0; }
  to { transform: scaleX(1); opacity: 1; }
}

.festival-message {
  position: relative;
  z-index: 10;
  max-width: 29rem;
  margin: 0 auto;
  white-space: pre-line;
  font-size: 0.95rem;
  line-height: 1.75;
  text-wrap: pretty;
}

.festival-amount-card {
  position: relative;
  display: inline-grid;
  min-width: 184px;
  padding: 16px 38px 14px;
  background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.035));
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid color-mix(in srgb, var(--theme-color) 34%, rgba(255,255,255,0.12));
  border-radius: 18px;
  overflow: visible;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.12), 0 18px 34px rgba(0,0,0,0.18);
}
.festival-amount-label,
.festival-amount-unit,
.festival-quota-desc {
  font-size: 0.75rem;
}
.festival-amount-halo {
  position: absolute;
  inset: -4px;
  border-radius: 22px;
  border: 1px solid var(--theme-border);
  animation: haloPulse 2.8s cubic-bezier(0.37, 0, 0.63, 1) infinite;
  pointer-events: none;
}
@keyframes haloPulse {
  0%, 100% { transform: scale(1); opacity: 0.36; box-shadow: 0 0 0 0 var(--theme-border); }
  50% { transform: scale(1.04); opacity: 0.72; box-shadow: 0 0 26px 4px var(--theme-border); }
}
.festival-amount-number {
  font-size: clamp(2.6rem, 9vw, 3.55rem);
  font-weight: 900;
  line-height: 1;
  /* 超大数字负字距，避免视觉上散开 */
  letter-spacing: -0.02em;
  font-optical-sizing: auto;
  animation: amountGlow 2.8s cubic-bezier(0.37, 0, 0.63, 1) infinite;
}
@keyframes amountGlow {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.18); }
}
.festival-quota-desc {
  margin-top: 6px;
}

.festival-actions {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 28px;
  flex-wrap: wrap;
}
.festival-btn-primary {
  min-height: 46px;
  border-radius: 999px;
  border: none;
  padding: 12px 34px;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0;
  transition: transform 260ms cubic-bezier(0.16, 1, 0.3, 1), filter 260ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 260ms cubic-bezier(0.16, 1, 0.3, 1);
  cursor: pointer;
  box-shadow: var(--theme-btn-shadow), 0 0 0 1px rgba(255, 255, 255, 0.12);
}
.festival-btn-primary:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.018);
  filter: brightness(1.06);
  box-shadow: var(--theme-btn-shadow), 0 0 0 1px rgba(255, 255, 255, 0.18), 0 0 28px color-mix(in srgb, var(--theme-border) 72%, transparent);
}
.festival-btn-primary:active:not(:disabled) {
  transform: translateY(1px) scale(0.982);
  filter: brightness(0.98);
  box-shadow: 0 8px 22px rgba(0,0,0,0.22), inset 0 2px 10px rgba(0,0,0,0.18);
  /* 按压反馈必须即时：缩短过渡时间，避免“慢半拍”的迟滞感 */
  transition-duration: 100ms;
}
.festival-btn-primary:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.festival-btn-secondary,
.festival-claimed-pill {
  min-height: 42px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  padding: 10px 22px;
  font-size: 14px;
  font-weight: 650;
}
.festival-btn-secondary {
  color: rgba(255, 255, 255, 0.9);
  transition: background 260ms cubic-bezier(0.16, 1, 0.3, 1), border-color 260ms cubic-bezier(0.16, 1, 0.3, 1), color 260ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 260ms cubic-bezier(0.16, 1, 0.3, 1), transform 260ms cubic-bezier(0.16, 1, 0.3, 1);
}
.festival-btn-secondary:hover {
  transform: translateY(-1px);
  background: rgba(255, 255, 255, 0.13);
  border-color: var(--theme-border);
  color: var(--theme-color);
  box-shadow: 0 10px 24px rgba(0,0,0,0.14), 0 0 18px color-mix(in srgb, var(--theme-border) 64%, transparent);
}
.festival-btn-secondary:active {
  transform: translateY(1px) scale(0.985);
}
.festival-claimed-pill {
  display: inline-flex;
  align-items: center;
}

.festival-tagline {
  position: relative;
  z-index: 10;
  margin: 20px 0 0;
  font-size: 0.75rem;
  font-style: italic;
  /* 小号文字加正字距提升可读性 */
  letter-spacing: 0.04em;
}


@media (max-width: 640px) {
  .festival-popup,
  .festival-popup.form-scroll,
  .festival-popup.form-banner,
  .festival-popup.form-moon,
  .festival-popup.form-ripple,
  .festival-popup.form-jade,
  .festival-popup.form-mountain,
  .festival-popup.form-petal,
  .festival-popup.form-frost,
  .festival-popup.form-terminal,
  .festival-popup.form-orbital {
    width: min(100%, 420px);
    max-height: min(92vh, 760px);
    min-height: auto;
    overflow-y: auto;
    padding: 26px 18px 22px;
    border-radius: 22px;
  }
  .festival-close-btn {
    top: 12px;
    right: 12px;
  }
  .festival-title {
    margin: 0 38px 12px;
    font-size: 1.28rem;
  }
  .festival-poem-card {
    max-width: 100%;
    padding: 16px 18px 12px;
    border-radius: 14px;
  }
  .festival-poem-title {
    font-size: 1.1rem;
  }
  .festival-message {
    font-size: 0.9rem;
    line-height: 1.68;
  }
  .festival-amount-card {
    min-width: 164px;
    padding-inline: 28px;
  }
  .festival-btn-primary,
  .festival-btn-secondary,
  .festival-claimed-pill {
    width: min(100%, 260px);
    justify-content: center;
  }
}

@media (prefers-reduced-motion: reduce) {
  /* 减少动态效果 ≠ 无反馈：保留容器的不透明度交叉淡入淡出，去掉位移/缩放/模糊 */
  .festival-popup,
  .festival-popup::before,
  .festival-divider,
  .festival-amount-halo,
  .festival-amount-number {
    animation: none !important;
  }
  .festival-popup,
  .festival-btn-primary,
  .festival-btn-secondary,
  .festival-close-btn {
    transition: none;
  }
  .festival-modal-leave .festival-popup {
    transform: none;
    filter: none;
  }
}

@media (prefers-reduced-transparency: reduce) {
  /* 减少透明度：去掉毛玻璃，表面改为近实色（内联渐变背景用 !important 覆盖） */
  .festival-backdrop {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    background: rgba(0, 0, 0, 0.72);
  }
  .festival-popup {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    background-color: rgba(16, 19, 26, 0.97) !important;
  }
  .festival-poem-card,
  .festival-amount-card,
  .festival-badge,
  .festival-close-btn,
  .festival-btn-secondary,
  .festival-claimed-pill {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-contrast: more) {
  /* 高对比：边框更实、层次边界更清晰 */
  .festival-popup {
    border-color: var(--theme-color);
  }
  .festival-poem-card,
  .festival-amount-card {
    border-color: color-mix(in srgb, var(--theme-color) 70%, #fff);
  }
  .festival-close-btn,
  .festival-btn-secondary,
  .festival-claimed-pill {
    border-color: rgba(255, 255, 255, 0.6);
  }
}
</style>
