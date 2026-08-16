<script setup lang="ts">
/**
 * 傻妞 Agent 专属聊天背景 —— 全息投影水晶手机
 *
 * 设计来源：docs/26.7.7/傻妞Agent专属聊天背景提示词.md
 * - 位置：右下角偏中
 * - 占比：约画面 25%
 * - 透明度：10% - 15%，不干扰文字阅读
 * - 动画：4s 全息呼吸灯循环
 *
 * TODO：生成并替换 /assets/shaonu-hologram.png 后，可把 .shaonu-hologram-silhouette
 *       替换为 background-image: url('/assets/shaonu-hologram.png')，效果更精致。
 */
</script>

<template>
  <div class="shaonu-hologram-bg" aria-hidden="true">
    <!-- 外层蓝紫光晕脉动 -->
    <div class="shaonu-glow" />

    <!-- 数字粒子漂浮层 -->
    <div class="shaonu-particles">
      <span class="particle p1">0101</span>
      <span class="particle p2">1100</span>
      <span class="particle p3">ATGC</span>
      <span class="particle p4">1010</span>
      <span class="particle p5">✦</span>
      <span class="particle p6">01</span>
    </div>

    <div class="shaonu-hologram-silhouette">
      <div class="phone-frame">
        <div class="phone-screen">
          <div class="code-line" />
          <div class="code-line short" />
          <div class="code-line" />
        </div>
        <div class="phone-button" />
      </div>
      <div class="hologram-ring ring-1" />
      <div class="hologram-ring ring-2" />
      <div class="hologram-ring ring-3" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.shaonu-hologram-bg {
  position: absolute;
  right: 8%;
  bottom: 10%;
  width: 300px;
  height: 400px;
  pointer-events: none;
  z-index: 0;
  opacity: 0.12;
  animation: hologram-breathe 4s ease-in-out infinite;
}

/* ---- 外层光晕扩散 ---- */
.shaonu-glow {
  position: absolute;
  right: -10%;
  bottom: -8%;
  width: 140%;
  height: 140%;
  background: radial-gradient(
    ellipse at center,
    rgba(100, 180, 255, 0.14) 0%,
    rgba(140, 100, 255, 0.07) 35%,
    rgba(80, 200, 220, 0.03) 60%,
    transparent 75%
  );
  pointer-events: none;
  opacity: 0;
  animation:
    glow-enter 1.5s ease-out 0.3s forwards,
    glow-pulse 4s ease-in-out 1.8s infinite;
}

/* ---- 数字粒子层 ---- */
.shaonu-particles {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: hidden;
}

.particle {
  position: absolute;
  font-family: 'Courier New', monospace;
  font-size: 10px;
  color: rgba(100, 200, 255, 0.18);
  letter-spacing: 2px;
  white-space: nowrap;
  text-shadow: 0 0 6px rgba(100, 200, 255, 0.25);
}

.particle.p1 {
  right: 18%;
  bottom: 38%;
  animation: particle-float-1 8s linear infinite;
}

.particle.p2 {
  right: 26%;
  bottom: 52%;
  animation: particle-float-2 10s linear infinite;
}

.particle.p3 {
  right: 12%;
  bottom: 62%;
  font-size: 9px;
  color: rgba(138, 92, 246, 0.16);
  animation: particle-float-3 12s linear infinite;
}

.particle.p4 {
  right: 34%;
  bottom: 30%;
  animation: particle-float-1 9s linear infinite reverse;
}

.particle.p5 {
  right: 22%;
  bottom: 70%;
  font-size: 12px;
  color: rgba(150, 180, 255, 0.22);
  animation: particle-float-2 7s linear infinite;
}

.particle.p6 {
  right: 6%;
  bottom: 46%;
  animation: particle-float-3 11s linear infinite reverse;
}

.shaonu-hologram-silhouette {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.phone-frame {
  width: 120px;
  height: 220px;
  border-radius: 24px;
  background: linear-gradient(
    135deg,
    rgba(100, 200, 255, 0.45) 0%,
    rgba(138, 92, 246, 0.35) 50%,
    rgba(74, 59, 107, 0.4) 100%
  );
  box-shadow:
    inset 0 0 20px rgba(255, 255, 255, 0.25),
    0 0 40px rgba(100, 200, 255, 0.25),
    0 0 80px rgba(138, 92, 246, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.35);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 14px 10px 10px;
  gap: 10px;
}

.phone-screen {
  flex: 1;
  width: 100%;
  border-radius: 16px;
  background: linear-gradient(
    180deg,
    rgba(26, 26, 46, 0.55) 0%,
    rgba(74, 59, 107, 0.45) 100%
  );
  border: 1px solid rgba(255, 255, 255, 0.12);
  padding: 14px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
}

.code-line {
  height: 4px;
  border-radius: 2px;
  background: linear-gradient(90deg, rgba(100, 200, 255, 0.6), rgba(138, 92, 246, 0.4));
  width: 100%;
  opacity: 0.7;
}

.code-line.short {
  width: 60%;
}

.phone-button {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(100, 200, 255, 0.5), rgba(138, 92, 246, 0.3));
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 0 12px rgba(100, 200, 255, 0.3);
}

.hologram-ring {
  position: absolute;
  border-radius: 50%;
  border: 1px solid rgba(100, 200, 255, 0.25);
  pointer-events: none;
}

.ring-1 {
  width: 220px;
  height: 220px;
  box-shadow: 0 0 30px rgba(100, 200, 255, 0.12);
}

.ring-2 {
  width: 280px;
  height: 280px;
  border-color: rgba(138, 92, 246, 0.18);
  box-shadow: 0 0 40px rgba(138, 92, 246, 0.1);
}

.ring-3 {
  width: 340px;
  height: 340px;
  border-color: rgba(74, 59, 107, 0.12);
}

@keyframes hologram-breathe {
  0%,
  100% {
    opacity: 0.10;
    filter: brightness(1) drop-shadow(0 0 10px rgba(100, 200, 255, 0.1));
  }
  50% {
    opacity: 0.14;
    filter: brightness(1.3) drop-shadow(0 0 20px rgba(150, 100, 255, 0.2));
  }
}

@keyframes glow-enter {
  0% {
    opacity: 0;
    transform: scale(0.7);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes glow-pulse {
  0%, 100% {
    opacity: 0.7;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.08);
  }
}

@keyframes particle-float-1 {
  0% {
    transform: translateY(0) translateX(0);
    opacity: 0;
  }
  15% {
    opacity: 0.35;
  }
  85% {
    opacity: 0.2;
  }
  100% {
    transform: translateY(-120px) translateX(20px);
    opacity: 0;
  }
}

@keyframes particle-float-2 {
  0% {
    transform: translateY(0) translateX(0);
    opacity: 0;
  }
  20% {
    opacity: 0.3;
  }
  80% {
    opacity: 0.15;
  }
  100% {
    transform: translateY(-100px) translateX(-15px);
    opacity: 0;
  }
}

@keyframes particle-float-3 {
  0% {
    transform: translateY(0) translateX(0);
    opacity: 0;
  }
  10% {
    opacity: 0.25;
  }
  90% {
    opacity: 0.1;
  }
  100% {
    transform: translateY(-140px) translateX(10px);
    opacity: 0;
  }
}

@media (max-width: 768px) {
  .shaonu-hologram-bg {
    width: 180px;
    height: 240px;
    right: 4%;
    bottom: 8%;
  }

  .phone-frame {
    width: 80px;
    height: 150px;
    border-radius: 18px;
  }

  .ring-1 { width: 140px; height: 140px; }
  .ring-2 { width: 180px; height: 180px; }
  .ring-3 { width: 220px; height: 220px; }

  .particle {
    font-size: 8px;
  }
}
</style>
