<script setup lang="ts">
/**
 * 账户未激活弹窗 —— 复用 RegistrationDisabledModal 的视觉外壳，
 * 在其之上叠加“点击计数 + 文案切换 + 第 5 次猫爪彩蛋”交互。
 *
 * 计数规则（localStorage 键 cygnusX_activation_click_count）：
 *   - 第 1-2 次打开：正常版文案（title / message / button_text）
 *   - 第 3 次及以后：着急版文案（title_urgent / message_urgent / button_text_urgent）
 *   - 第 5 次点击“确认按钮”关闭后：派发全局事件 cygnusX:triggerCatPaws 触发猫爪彩蛋
 *
 * 计数仅由“确认按钮”点击驱动（confirm 事件）；蒙层关闭不计入。
 * 用户清除 localStorage → 计数自然重置。
 */
import { ref, computed, watch } from 'vue'
import RegistrationDisabledModal from '@/components/RegistrationDisabledModal.vue'
import { useSiteConfigStore } from '@/stores/site-config'

const props = defineProps<{
  /** 弹窗显隐 */
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const siteConfig = useSiteConfigStore()

const COUNT_KEY = 'cygnusX_activation_click_count'
/** 着急版阈值：累计点击数 >= 此值时切换文案 */
const URGENT_THRESHOLD = 2
/** 第 N 次点击触发猫爪彩蛋 */
const PAW_TRIGGER_AT = 5

// 当前用户累计点击次数（仅按钮点击累加）。弹窗打开时从 localStorage 读取。
const count = ref(0)

// 是否使用着急版文案：按“本次打开前的累计次数”判定
// （第 1 次打开 count=0、第 2 次 count=1 → 正常；第 3 次 count=2 → 着急）
const isUrgent = computed(() => count.value >= URGENT_THRESHOLD)

const currentTitle = computed(() =>
  isUrgent.value ? siteConfig.activationTitleUrgent : siteConfig.activationTitle,
)
const currentMessage = computed(() =>
  isUrgent.value ? siteConfig.activationMessageUrgent : siteConfig.activationMessage,
)
const currentButtonText = computed(() =>
  isUrgent.value ? siteConfig.activationButtonTextUrgent : siteConfig.activationButtonText,
)

// 每次打开弹窗时从 localStorage 重新读取计数（兼容用户清除存储后重置）
watch(
  () => props.show,
  (v) => {
    if (!v) return
    const raw = Number.parseInt(localStorage.getItem(COUNT_KEY) || '0', 10)
    count.value = Number.isFinite(raw) ? raw : 0
  },
)

function handleUpdateShow(v: boolean) {
  emit('update:show', v)
}

/**
 * 确认按钮点击：
 *   1. 累加计数并写回 localStorage；
 *   2. 若本次点击使计数到达 PAW_TRIGGER_AT，关闭后派发猫爪彩蛋事件；
 *   3. 关闭弹窗（由 RegistrationDisabledModal 内部完成，这里仅计数 + 派发事件）。
 */
function handleConfirm() {
  const next = count.value + 1
  count.value = next
  try {
    localStorage.setItem(COUNT_KEY, String(next))
  } catch {
    /* localStorage 不可用（隐私模式等）时静默降级，仅本次会话生效 */
  }
  // 第 5 次点击：关闭后触发全局猫爪彩蛋
  if (next === PAW_TRIGGER_AT) {
    window.dispatchEvent(new CustomEvent('cygnusX:triggerCatPaws'))
  }
}
</script>

<template>
  <RegistrationDisabledModal
    :show="props.show"
    :title="currentTitle"
    :message="currentMessage"
    :contact="siteConfig.activationContact"
    :button-text="currentButtonText"
    lottie-name="cat-fishing-on-moon.json"
    @update:show="handleUpdateShow"
    @confirm="handleConfirm"
  />
</template>
