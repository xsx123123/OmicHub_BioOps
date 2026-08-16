<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NIcon } from 'naive-ui'
import { CloseOutline } from '@vicons/ionicons5'
import { announcementApi } from '@/api/announcements'
import { cookieApi } from '@/api/cookies'
import {
  DEFAULT_ICON_BY_TYPE,
  type Announcement,
} from '@/types/announcement'

const router = useRouter()

const props = withDefaults(defineProps<{
  title?: string
  description?: string
  actionText?: string
  to?: string
  dismissKey?: string
  closable?: boolean
}>(), {
  title: '',
  description: '',
  actionText: '',
  to: '',
  dismissKey: '',
  closable: true,
})

const banner = ref<Announcement | null>(null)
const visible = ref(false)

const STORAGE_PREFIX = 'omichub_banner_dismissed_'
const isStatic = computed(() => Boolean(props.title))
const staticStorageKey = computed(() => `${STORAGE_PREFIX}${props.dismissKey || props.title}`)
const displayTitle = computed(() => props.title || banner.value?.title || '')
const displayDescription = computed(() => props.description || banner.value?.description || '')
const displayActionText = computed(() => props.actionText || banner.value?.button_text || '')
const canDismiss = computed(() => isStatic.value ? props.closable : banner.value?.dismiss_behavior !== 'none')

/** 今日日期字符串 YYYY-MM-DD，用于 daily 关闭判断 */
function todayStr(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 该通知是否已被当前用户关闭 */
function isDismissed(b: Announcement): boolean {
  if (b.dismiss_behavior === 'none') return false
  const val = localStorage.getItem(STORAGE_PREFIX + b.id)
  if (!val) return false
  if (b.dismiss_behavior === 'forever') return true
  if (b.dismiss_behavior === 'daily') return val === todayStr()
  return false
}

function dismiss() {
  if (isStatic.value) {
    localStorage.setItem(staticStorageKey.value, 'forever')
    visible.value = false
    return
  }
  if (!banner.value) return
  const b = banner.value
  if (b.dismiss_behavior !== 'none') {
    const val = b.dismiss_behavior === 'daily' ? todayStr() : 'forever'
    localStorage.setItem(STORAGE_PREFIX + b.id, val)
  }
  // 触发 Transition leave（height + opacity 收起）
  visible.value = false
}

function handleNavigate() {
  if (isStatic.value) {
    if (props.to) router.push(props.to)
    return
  }
  if (!banner.value?.link) return
  const link = banner.value.link
  if (/^https?:\/\//.test(link)) {
    window.open(link, '_blank', 'noopener')
  } else {
    router.push(link)
  }
}

const iconDisplay = computed(() => {
  if (isStatic.value) return '✨'
  if (!banner.value) return '📢'
  return banner.value.icon || DEFAULT_ICON_BY_TYPE[banner.value.type] || '📢'
})

onMounted(async () => {
  if (isStatic.value) {
    visible.value = !props.closable || localStorage.getItem(staticStorageKey.value) !== 'forever'
    return
  }
  try {
    const [announcementResult, rateResult] = await Promise.allSettled([
      announcementApi.getActive(),
      cookieApi.getAiTokenRate(),
    ])
    const list = announcementResult.status === 'fulfilled' ? announcementResult.value : []
    if (rateResult.status === 'fulfilled' && rateResult.value.discount) {
      const discount = rateResult.value.discount
      list.unshift({
        id: `cookie-discount-${discount.id}`,
        title: discount.banner_title,
        description: discount.banner_description,
        type: 'success',
        icon: '🥫',
        link: '/cookies',
        button_text: '查看用量',
        start_time: `${discount.date_start}T00:00:00+08:00`,
        end_time: `${discount.date_end}T23:59:59+08:00`,
        dismiss_behavior: 'daily',
        priority: 10000,
        is_enabled: true,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })
    }
    // 后端已按优先级排序，取第一条未被当前用户关闭的
    const first = list.find((b) => !isDismissed(b)) || null
    banner.value = first
    if (first) visible.value = true
  } catch {
    // 拉取失败静默处理，不阻断首页渲染
  }
})
</script>

<template>
  <Transition name="banner-slide">
    <div
      v-if="(isStatic || banner) && visible"
      class="announcement-banner"
      @click="handleNavigate"
    >
      <div class="banner-icon">{{ iconDisplay }}</div>
      <div class="banner-content">
        <div class="banner-title">{{ displayTitle }}</div>
        <div class="banner-desc">{{ displayDescription }}</div>
      </div>
      <div class="banner-actions" @click.stop>
        <NButton
          v-if="displayActionText"
          size="small"
          class="banner-btn"
          @click="handleNavigate"
        >
          {{ displayActionText }}
        </NButton>
        <button
          v-if="canDismiss"
          class="banner-close"
          aria-label="关闭"
          @click.stop="dismiss"
        >
          <NIcon :size="14"><CloseOutline /></NIcon>
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.announcement-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 16px 0;
  padding: 16px 20px;
  border-radius: var(--radius-card);
  color: #fff;
  cursor: pointer;
  overflow: hidden;
  background: var(--brand-gradient);
  box-shadow: 0 4px 12px rgba(76, 111, 255, 0.18);
  transition: filter 0.2s ease;
}
.announcement-banner:hover {
  filter: brightness(1.05);
}

.banner-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

.banner-content {
  flex: 1;
  min-width: 0;
}
.banner-title {
  font-size: 15px;
  font-weight: 600;
  line-height: 20px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.banner-desc {
  font-size: 13px;
  line-height: 18px;
  color: rgba(255, 255, 255, 0.85);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}

.banner-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
/* Banner 渐变背景上的按钮：白底实心 + 品牌紫文字，与 Hero 按钮同一规范。
   同 Hero：--n-* 变量被 Naive 内联覆盖无效，直接用 CSS 属性覆盖。 */
.n-button.banner-btn {
  background-color: rgba(255, 255, 255, 0.95);
  color: #6366f1;
  height: auto;
  padding: 6px 16px;
  font-size: 13px;
  border: none;
  border-radius: 10px;
  font-weight: 700;
  letter-spacing: 0.3px;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.4), 0 2px 12px rgba(0, 0, 0, 0.15);
  transition: all 0.2s ease;
}
.n-button.banner-btn:hover,
.n-button.banner-btn:focus {
  background-color: #ffffff;
  color: #6366f1;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.5), 0 4px 16px rgba(0, 0, 0, 0.18);
  transform: translateY(-1px);
}
.n-button.banner-btn :deep(.n-button__border),
.n-button.banner-btn :deep(.n-button__state-border) {
  display: none;
}

.banner-close {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.18);
  border: none;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 0.2s ease, background 0.2s ease;
}
.banner-close:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: rotate(90deg);
}

/* 入场：从上方滑入 */
.banner-slide-enter-active {
  transition: transform 0.4s ease-out, opacity 0.4s ease-out;
}
.banner-slide-enter-from {
  transform: translateY(-20px);
  opacity: 0;
}

/* 离场：高度 + 透明度收起 */
.banner-slide-leave-active {
  transition: transform 0.3s ease-out, opacity 0.3s ease-out,
    max-height 0.3s ease-out, margin 0.3s ease-out, padding 0.3s ease-out;
  max-height: 80px;
}
.banner-slide-leave-to {
  transform: translateY(-10px);
  opacity: 0;
  max-height: 0;
  margin: 0;
  padding: 0;
}

/* 移动端：文字换行，避免按钮/关闭溢出 */
@media (max-width: 768px) {
  .announcement-banner {
    flex-wrap: wrap;
    gap: 8px;
  }
  .banner-content {
    order: 3;
    flex-basis: 100%;
    min-width: 100%;
  }
  .banner-title,
  .banner-desc {
    white-space: normal;
  }
}
</style>
