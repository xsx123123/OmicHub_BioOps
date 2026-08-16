<script setup lang="ts">
/**
 * LoginPageQuote —— 登录页顶部双语引言
 *
 * 位于页面最顶端，样式与底部 StardustQuote 保持一致：
 * 中文 14px 正常体、英文 16px 斜体，整体淡入入场。
 */
</script>

<template>
  <div class="login-page-top-quote">
    <p class="quote-cn">在某个地方，有某种不可思议的事物，正等待着被知晓。</p>
    <p class="quote-en gilded breathe">"Somewhere, something incredible is waiting to be known."</p>
    <p class="quote-tagline">Every genome tells a story.</p>
  </div>
</template>

<style scoped>
.login-page-top-quote {
  position: absolute;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 5;
  text-align: center;
  padding: 0 20px;
  width: 100%;
  max-width: 500px;
  pointer-events: none;
  opacity: 0;
  animation: topQuoteFadeIn 1.5s ease-out 0.2s forwards;
}

.quote-cn {
  font-size: 12px;
  font-weight: 400;
  color: rgba(255, 255, 255, 0.65);
  line-height: 1.5;
  letter-spacing: 0.02em;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  margin: 0 0 6px 0;
}

.quote-en {
  font-size: 13px;
  font-weight: 500;
  font-style: italic;
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.5;
  letter-spacing: 0.01em;
  margin: 0 0 4px 0;
}

.gilded {
  background: linear-gradient(
    90deg,
    rgba(238, 248, 255, 0.92) 0%,
    #ffffff 24%,
    #58a9ff 50%,
    #ffffff 76%,
    rgba(238, 248, 255, 0.92) 100%
  );
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  text-shadow: none;
}

.breathe {
  animation: shimmer 10s linear infinite, breathe-glow 6s ease-in-out infinite;
}

.quote-tagline {
  font-size: 11px;
  font-weight: 400;
  font-style: italic;
  font-family: Georgia, "Times New Roman", serif;
  color: rgba(255, 255, 255, 0.5);
  line-height: 1.5;
  letter-spacing: 0.04em;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  margin: 0;
}

@keyframes topQuoteFadeIn {
  0% {
    opacity: 0;
  }
  100% {
    opacity: 1;
  }
}

@keyframes shimmer {
  0% { background-position: 200% center; }
  100% { background-position: -200% center; }
}

@keyframes breathe-glow {
  0%, 100% {
    opacity: 0.88;
    filter: drop-shadow(0 0 9px rgba(112, 181, 255, 0.58));
  }
  50% {
    opacity: 1;
    filter: drop-shadow(0 0 18px rgba(112, 181, 255, 0.94));
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-page-top-quote,
  .breathe {
    animation: none;
  }

  .login-page-top-quote {
    opacity: 1;
  }
}

@media (max-width: 768px) {
  .login-page-top-quote {
    top: 20px;
  }

  .quote-cn {
    font-size: 11px;
  }

  .quote-en {
    font-size: 12px;
  }

  .quote-tagline {
    font-size: 10px;
  }
}

@media (max-width: 480px) {
  .login-page-top-quote {
    top: 18px;
    padding: 0 16px;
  }
}
</style>
