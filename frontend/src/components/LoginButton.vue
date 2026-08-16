<script setup lang="ts">
import { CheckmarkCircleOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'

/**
 * LoginButton —— 登录页主操作按钮
 *
 * 设计目标：现代 AI SaaS 级质感（Linear / Notion / Vercel 风格）
 * - 品牌蓝色 + 柔和投影，营造轻盈发光感
 * - 完整的 idle / loading / success / disabled 状态
 * - 所有过渡使用 cubic-bezier(.4,0,.2,1)，180~250ms
 */

withDefaults(
  defineProps<{
    disabled?: boolean
    loading?: boolean
    success?: boolean
  }>(),
  {
    disabled: false,
    loading: false,
    success: false,
  },
)

const emit = defineEmits<{
  click: []
}>()

function handleClick() {
  emit('click')
}
</script>

<template>
  <button
    type="button"
    class="login-button"
    :class="{
      'login-button--loading': loading,
      'login-button--success': success,
      'login-button--disabled': disabled && !loading && !success,
    }"
    :disabled="disabled || loading || success"
    @click="handleClick"
  >
    <span class="login-button__bg" aria-hidden="true" />
    <span class="login-button__glow" aria-hidden="true" />

    <span class="login-button__content">
      <span v-if="loading" class="login-button__spinner" aria-hidden="true" />
      <NIcon v-else-if="success" class="login-button__success-icon" :size="20" aria-hidden="true">
        <CheckmarkCircleOutline />
      </NIcon>
      <span class="login-button__text">
        <template v-if="loading">登录中...</template>
        <template v-else-if="success">登录成功</template>
        <template v-else>登录</template>
      </span>
    </span>
  </button>
</template>

<style scoped>
.login-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 150px;
  height: 48px;
  padding: 0 28px;
  border: none;
  border-radius: var(--radius-button);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.3px;
  color: #ffffff;
  cursor: pointer;
  outline: none;
  overflow: hidden;
  background: transparent;
  box-shadow: 0 8px 24px rgba(76, 111, 255, 0.24);
  transform: scale(1);
  transition:
    transform 200ms cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 200ms cubic-bezier(0.4, 0, 0.2, 1);
}

.login-button__bg {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: var(--brand-primary);
  opacity: 1;
  transition:
    opacity 250ms cubic-bezier(0.4, 0, 0.2, 1),
    background 250ms cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 0;
}

.login-button:hover:not(:disabled):not(.login-button--disabled) {
  transform: scale(1.02);
  box-shadow: 0 12px 30px rgba(76, 111, 255, 0.34);
}

.login-button:hover:not(:disabled):not(.login-button--disabled) .login-button__bg {
  background: var(--brand-primary-hover);
}

.login-button:active:not(:disabled):not(.login-button--disabled) {
  transform: scale(0.98);
  box-shadow: 0 4px 14px rgba(76, 111, 255, 0.2);
}

.login-button:focus-visible {
  box-shadow:
    0 0 0 4px rgba(76, 111, 255, 0.18),
    0 8px 24px rgba(76, 111, 255, 0.24);
}

.login-button__content {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  pointer-events: none;
}

.login-button__text {
  white-space: nowrap;
}

.login-button__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.login-button__success-icon {
  display: inline-flex;
  color: rgba(255, 255, 255, 0.96);
  filter: drop-shadow(0 1px 2px rgba(5, 90, 62, 0.2));
}

/* Disabled state */
:root[data-theme="dark"] .login-button--disabled .login-button__bg {
  background: var(--neutral-hover);
}
.login-button--disabled .login-button__bg {
  background: #e8ecf4;
}

:root[data-theme="dark"] .login-button--disabled {
  color: var(--neutral-text-4);
}
.login-button--disabled {
  color: #aeb7c7;
  cursor: not-allowed;
  box-shadow: none;
  transform: scale(1);
}

.login-button--disabled:hover,
.login-button--disabled:active {
  transform: scale(1);
  box-shadow: none;
}

/* Success state: emerald green gradient */
.login-button--success .login-button__bg {
  background: linear-gradient(135deg, #34d399 0%, #10b981 100%);
}

.login-button--success {
  cursor: default;
  box-shadow: 0 8px 24px rgba(16, 185, 129, 0.3);
  transform: scale(1);
}

.login-button__glow {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  opacity: 0;
  pointer-events: none;
  z-index: 0;
}

.login-button--success .login-button__glow {
  animation: successGlow 900ms cubic-bezier(0.4, 0, 0.2, 1) forwards;
}

@keyframes successGlow {
  0% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.45);
    opacity: 0.8;
  }
  70% {
    box-shadow: 0 0 0 18px rgba(16, 185, 129, 0);
    opacity: 0.4;
  }
  100% {
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
    opacity: 0;
  }
}
</style>
