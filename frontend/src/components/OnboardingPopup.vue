<script setup lang="ts">
import { computed } from 'vue'
// 彩蛋同款猫猫插画（猫猫踩地球）
import logoImg from '@/assets/ChatGPT_logo.png'

interface Props {
  visible: boolean
  // 管理员联系方式（来自 data/OmicHub.yaml registration.admin_contact）；为空则不展示该行
  adminContact?: string
}
const props = withDefaults(defineProps<Props>(), {
  adminContact: '',
})

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'go-knowledge'): void
  (e: 'skip'): void
}>()

const showContact = computed(() => props.adminContact.trim().length > 0)

function close() {
  emit('update:visible', false)
}

function handleGoKnowledge() {
  emit('go-knowledge')
  close()
}

function handleSkip() {
  emit('skip')
  close()
}
</script>

<template>
  <Transition
    enter-active-class="transition-opacity duration-300"
    leave-active-class="transition-opacity duration-200"
    enter-from-class="opacity-0"
    leave-to-class="opacity-0"
  >
    <div
      v-if="props.visible"
      class="fixed inset-0 z-[3000] flex items-center justify-center bg-black/50 p-4"
    >
      <!-- 弹窗主体 -->
      <div
        class="relative w-full max-w-lg overflow-hidden rounded-2xl bg-neutral-card shadow-2xl"
        style="animation: scaleIn 0.4s ease-out both"
      >
        <!-- 顶部主视觉图：上下浮动 -->
        <div class="flex justify-center pt-8 pb-2">
          <img
            :src="logoImg"
            alt="OmicHub 守护者"
            class="h-48 w-auto select-none drop-shadow-md animate-soft-float"
            draggable="false"
          />
        </div>

        <!-- 欢迎文案 -->
        <div class="px-8 pb-2 text-center">
          <h1 class="text-2xl font-bold text-text-primary">
            欢迎来到 OmicHub 🚀
          </h1>
          <p class="mt-2 mb-4 text-sm text-text-secondary">
            开启你的高效多组学探索之旅！先去看看实验室知识库吧～
          </p>
        </div>

        <!-- 核心快捷导航卡片：实验室知识库 -->
        <div class="px-8">
          <div
            role="button"
            tabindex="0"
            class="group flex cursor-pointer items-center gap-4 rounded-xl border border-neutral-border bg-neutral-card p-4 transition-all hover:border-primary hover:bg-primary-light"
            @click="handleGoKnowledge"
            @keyup.enter="handleGoKnowledge"
          >
            <span class="text-3xl">📚</span>
            <div class="flex-1 text-left">
              <div class="font-bold text-text-primary">实验室知识库</div>
              <div class="mt-0.5 text-xs text-text-tertiary">
                查阅组内标准操作规范与服务器使用指南
              </div>
            </div>
            <span class="text-text-disabled transition-colors group-hover:text-primary">→</span>
          </div>
        </div>

        <!-- 管理员联系方式提示 -->
        <div v-if="showContact" class="px-8 pt-3">
          <p class="text-center text-xs text-text-tertiary">
            遇到其他问题可联系管理员：<span class="font-medium text-text-secondary">{{ adminContact }}</span>
          </p>
        </div>

        <!-- 底部操作区 -->
        <div class="flex items-center justify-end gap-3 px-8 py-6">
          <button
            type="button"
            class="rounded-lg border border-primary px-4 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary-light"
            @click="handleSkip"
          >
            稍后再看
          </button>
          <button
            type="button"
            class="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover"
            @click="handleGoKnowledge"
          >
            前往知识库
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>
