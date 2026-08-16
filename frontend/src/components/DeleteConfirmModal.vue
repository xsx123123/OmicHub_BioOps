<script setup lang="ts">
import { computed, ref, watch } from 'vue'

/**
 * 高安全级别删除确认弹窗
 *
 * 设计：要求用户逐字输入一段包含目标用户名的确认文案，完全一致才放行删除按钮。
 * 用于「用户管理」页删除用户等不可逆操作，防止管理员误删。
 */

interface Props {
  /** 弹窗显隐（v-model:visible） */
  visible: boolean
  /** 待删除用户名（动态拼入确认文案，供用户照抄） */
  targetUsername: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'confirm'): void
}>()

// 输入框双向绑定的响应式文本
const confirmInputText = ref('')

// 用户必须逐字输入的确认文案（动态替换目标用户名）
const requiredText = computed(() =>
  `请确定删除${props.targetUsername}用户，该操作不能撤销，请二次确认`,
)

// 核心拦截：输入内容与确认文案完全一致才允许删除
const canConfirm = computed(() => confirmInputText.value === requiredText.value)

// 每次打开弹窗时清空输入，避免上次残留误触发
watch(
  () => props.visible,
  (v) => {
    if (v) confirmInputText.value = ''
  },
)

function close() {
  emit('update:visible', false)
}

function handleCancel() {
  confirmInputText.value = ''
  close()
}

function handleConfirm() {
  if (!canConfirm.value) return
  emit('confirm')
  confirmInputText.value = ''
  close()
}
</script>

<template>
  <Transition
    enter-active-class="transition-opacity duration-200"
    leave-active-class="transition-opacity duration-150"
    enter-from-class="opacity-0"
    leave-to-class="opacity-0"
  >
    <!-- 遮罩层：全屏固定 + 半透明黑底 + 轻微模糊 -->
    <div
      v-if="visible"
      class="fixed inset-0 z-[4000] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      @click.self="handleCancel"
    >
      <!-- 弹窗主体 -->
      <div
        class="w-full max-w-md rounded-lg bg-neutral-card p-6 shadow-xl"
        style="animation: scaleIn 0.2s ease-out both"
      >
        <!-- 顶部：红色警告图标 + 标题 -->
        <div class="flex items-center gap-3">
          <div
            class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-red-100"
          >
            <svg
              class="h-6 w-6 text-red-600"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <h3 class="text-lg font-bold text-gray-900 dark:text-gray-100">
            彻底删除用户
          </h3>
        </div>

        <!-- 不可逆提示 -->
        <p class="mt-4 text-sm text-gray-500 dark:text-gray-400">
          该操作将永久删除该用户及其关联数据，<span class="font-semibold text-red-600">不可恢复</span>。
          为防止误操作，请输入下方红字内容以二次确认：
        </p>

        <!-- 要求照抄的确认文案：加粗 + 红字 + 浅红背景块，方便用户照着打字 -->
        <div
          class="mt-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-bold text-red-600 break-all dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-400"
          role="note"
        >
          {{ requiredText }}
        </div>

        <!-- 输入框：聚焦时边框/光晕变红 -->
        <input
          v-model="confirmInputText"
          type="text"
          autocomplete="off"
          spellcheck="false"
          placeholder="请输入上方红字内容"
          class="mt-3 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition-colors placeholder:text-gray-400 focus:border-red-500 focus:ring-2 focus:ring-red-500/40 dark:border-gray-600 dark:bg-[#0f1320] dark:text-gray-100"
          @keyup.enter="handleConfirm"
        />

        <!-- 底部操作按钮 -->
        <div class="mt-6 flex justify-end gap-3">
          <!-- 取消：幽灵按钮 -->
          <button
            type="button"
            class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-transparent dark:text-gray-200 dark:hover:bg-gray-800"
            @click="handleCancel"
          >
            取消
          </button>

          <!-- 确认删除：输入完全一致才可点击，否则禁用 -->
          <button
            type="button"
            :disabled="!canConfirm"
            :class="[
              'rounded-md px-4 py-2 text-sm font-medium transition-colors',
              canConfirm
                ? 'bg-red-600 text-white hover:bg-red-700'
                : 'cursor-not-allowed bg-red-300 text-white dark:bg-red-900/40 dark:text-red-300/60',
            ]"
            @click="handleConfirm"
          >
            确认删除
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>
