<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  /** 节日/物候类型标识，决定背景意象 */
  type?: string
  /** 主题色板，用于星火粒子与光晕 */
  colors?: string[]
  /** 环境光/氛围色 */
  ambientColor?: string
  /** 高光色 */
  highlightColor?: string
  /** 是否禁用动画 */
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  type: 'spring_festival',
  colors: () => ['#E7C27E', '#A8675D', '#F4E7D2'],
  ambientColor: '#D8B46A',
  highlightColor: '#F8E6BF',
  disabled: false,
})

const reducedMotion = typeof window !== 'undefined'
  ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
  : false

const isAnimationDisabled = computed(() => props.disabled || reducedMotion)

const motifType = computed(() => {
  const t = String(props.type)
  if (['spring_festival', 'national_day'].includes(t)) return 'lanterns'
  if (['lantern_festival'].includes(t)) return 'lantern_ripples'
  if (['dragon_boat', 'li_chun'].includes(t)) return 'bamboo'
  if (['qixi'].includes(t)) return 'bridge'
  if (['mid_autumn', 'dong_zhi'].includes(t)) return 'moon'
  if (['christmas', 'new_year'].includes(t)) return 'snow'
  if (['double_ninth', 'qiu_fen', 'xia_zhi'].includes(t)) return 'leaves'
  if (['valentine'].includes(t)) return 'hearts'
  if (['programmers_day'].includes(t)) return 'code'
  if (['anniversary'].includes(t)) return 'orbit'
  return 'embers'
})

function seededRandom(seed: number) {
  const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453
  return x - Math.floor(x)
}

const embers = computed(() => {
  const count = 26
  const list = []
  for (let i = 0; i < count; i++) {
    const pseudo = seededRandom(i)
    const left = 4 + (pseudo * 92) % 92
    const sizeBase = 4 + (pseudo * 8) % 8
    const delay = (i % 7) * -2.4 + (pseudo * 1.2)
    const duration = 18 + (i % 5) * 3.6 + pseudo * 4
    const drift = -18 + (i % 3) * 18 + pseudo * 12
    const blur = 4 + (i % 4) * 3 + pseudo * 3
    const colorIndex = i % props.colors.length
    list.push({
      id: i,
      left: `${left.toFixed(2)}%`,
      size: `${sizeBase.toFixed(2)}px`,
      delay: `${delay.toFixed(2)}s`,
      duration: `${duration.toFixed(2)}s`,
      drift: `${drift.toFixed(2)}px`,
      blur: `${blur.toFixed(2)}px`,
      color: props.colors[colorIndex] || props.colors[0],
    })
  }
  return list
})

const snowflakes = computed(() => {
  return Array.from({ length: 20 }, (_, i) => {
    const pseudo = seededRandom(i + 200)
    return {
      id: i,
      left: `${(5 + pseudo * 90).toFixed(2)}%`,
      size: `${(3 + pseudo * 6).toFixed(2)}px`,
      delay: `${(-pseudo * 12).toFixed(2)}s`,
      duration: `${(10 + pseudo * 10).toFixed(2)}s`,
      drift: `${(-20 + pseudo * 40).toFixed(2)}px`,
    }
  })
})

const codeLines = computed(() => {
  const chars = '01{}[];<>/=+*-'
  return Array.from({ length: 16 }, (_, i) => {
    const pseudo = seededRandom(i + 400)
    return {
      id: i,
      left: `${(4 + pseudo * 92).toFixed(2)}%`,
      delay: `${(-pseudo * 4).toFixed(2)}s`,
      duration: `${(3 + pseudo * 5).toFixed(2)}s`,
      length: `${(20 + pseudo * 80).toFixed(2)}px`,
      char: chars[i % chars.length],
    }
  })
})

const leaves = computed(() => {
  return Array.from({ length: 10 }, (_, i) => {
    const pseudo = seededRandom(i + 600)
    return {
      id: i,
      left: `${(5 + pseudo * 90).toFixed(2)}%`,
      delay: `${(-pseudo * 10).toFixed(2)}s`,
      duration: `${(12 + pseudo * 8).toFixed(2)}s`,
      drift: `${(-40 + pseudo * 80).toFixed(2)}px`,
      size: `${(8 + pseudo * 14).toFixed(2)}px`,
      rotation: `${pseudo * 360}deg`,
    }
  })
})

const hearts = computed(() => {
  return Array.from({ length: 8 }, (_, i) => {
    const pseudo = seededRandom(i + 800)
    return {
      id: i,
      left: `${(10 + pseudo * 80).toFixed(2)}%`,
      delay: `${(-pseudo * 8).toFixed(2)}s`,
      duration: `${(9 + pseudo * 6).toFixed(2)}s`,
      drift: `${(-15 + pseudo * 30).toFixed(2)}px`,
      size: `${(6 + pseudo * 10).toFixed(2)}px`,
    }
  })
})

const lanterns = computed(() => {
  return Array.from({ length: 5 }, (_, i) => {
    const pseudo = seededRandom(i + 1000)
    return {
      id: i,
      left: `${(12 + i * 18 + pseudo * 6).toFixed(2)}%`,
      delay: `${(-pseudo * 6).toFixed(2)}s`,
      duration: `${(10 + pseudo * 6).toFixed(2)}s`,
      size: `${(28 + pseudo * 34).toFixed(2)}px`,
    }
  })
})

const bambooLeaves = computed(() => {
  return Array.from({ length: 8 }, (_, i) => {
    const pseudo = seededRandom(i + 1200)
    return {
      id: i,
      left: `${(5 + pseudo * 90).toFixed(2)}%`,
      delay: `${(-pseudo * 10).toFixed(2)}s`,
      duration: `${(10 + pseudo * 8).toFixed(2)}s`,
      drift: `${(-30 + pseudo * 60).toFixed(2)}px`,
      size: `${(12 + pseudo * 20).toFixed(2)}px`,
    }
  })
})

const ripples = computed(() => {
  return Array.from({ length: 5 }, (_, i) => ({
    id: i,
    delay: `${(i * 1.6).toFixed(2)}s`,
    duration: '5s',
  }))
})

const rootClass = computed(() => ({
  'festival-background': true,
  [`theme-${props.type}`]: true,
  [`motif-${motifType.value}`]: true,
  'animation-disabled': isAnimationDisabled.value,
}))

const cssVars = computed(() => ({
  '--bg-ambient': props.ambientColor,
  '--bg-highlight': props.highlightColor,
  '--bg-spark-0': props.colors[0] || '#E7C27E',
  '--bg-spark-1': props.colors[1] || '#A8675D',
  '--bg-spark-2': props.colors[2] || '#F4E7D2',
}))
</script>

<template>
  <div :class="rootClass" :style="cssVars" aria-hidden="true">
    <!-- 暗流涌动的背景基色：径向渐变 + 缓慢呼吸缩放 -->
    <div class="bg-base" />

    <!-- 多层柔光晕，制造灯笼/微光感 -->
    <div class="bg-glow bg-glow-primary" />
    <div class="bg-glow bg-glow-secondary" />
    <div class="bg-glow bg-glow-tertiary" />

    <!-- 卡片正后方的专属暗金色光晕，跟随卡片呼吸 -->
    <div class="card-halo" />

    <!-- 节日专属意象层 -->
    <div class="motif-layer">
      <!-- 春节/国庆：红灯笼上下浮动 -->
      <div v-if="motifType === 'lanterns'" class="motif motif-lanterns">
        <span
          v-for="lantern in lanterns"
          :key="lantern.id"
          class="lantern"
          :style="{
            left: lantern.left,
            width: lantern.size,
            height: `calc(${lantern.size} * 1.25)`,
            animationDelay: lantern.delay,
            animationDuration: lantern.duration,
          }"
        />
      </div>

      <!-- 元宵节：水面灯影涟漪 -->
      <div v-if="motifType === 'lantern_ripples'" class="motif motif-ripples">
        <span
          v-for="ripple in ripples"
          :key="ripple.id"
          class="water-ripple"
          :style="{
            left: `${18 + ripple.id * 16}%`,
            top: `${62 + (ripple.id % 3) * 8}%`,
            animationDelay: ripple.delay,
            animationDuration: ripple.duration,
          }"
        />
      </div>

      <!-- 端午/立春：竹叶飘落 -->
      <div v-if="motifType === 'bamboo'" class="motif motif-bamboo">
        <span
          v-for="leaf in bambooLeaves"
          :key="leaf.id"
          class="bamboo-leaf"
          :style="{
            left: leaf.left,
            width: leaf.size,
            height: `calc(${leaf.size} * 0.35)`,
            animationDelay: leaf.delay,
            animationDuration: leaf.duration,
            '--leaf-drift': leaf.drift,
          }"
        />
      </div>

      <!-- 七夕：鹊桥弧线 -->
      <div v-if="motifType === 'bridge'" class="motif motif-bridge">
        <div class="magpie-bridge" />
        <span
          v-for="i in 3"
          :key="`star-${i}`"
          class="shooting-star"
          :style="{
            top: `${12 + i * 14}%`,
            animationDelay: `${i * 2.4}s`,
            animationDuration: `${3 + i * 0.6}s`,
          }"
        />
      </div>

      <!-- 中秋/冬至：月晕与水波 -->
      <div v-if="motifType === 'moon'" class="motif motif-moon">
        <div class="moon-glow" />
        <span
          v-for="ripple in ripples"
          :key="`moon-ripple-${ripple.id}`"
          class="water-ripple"
          :style="{
            left: `${30 + ripple.id * 10}%`,
            top: '78%',
            animationDelay: ripple.delay,
            animationDuration: ripple.duration,
          }"
        />
      </div>

      <!-- 冬至/圣诞/元旦：雪花飘落 -->
      <div v-if="motifType === 'snow'" class="motif motif-snow">
        <span
          v-for="flake in snowflakes"
          :key="flake.id"
          class="snowflake"
          :style="{
            left: flake.left,
            width: flake.size,
            height: flake.size,
            animationDelay: flake.delay,
            animationDuration: flake.duration,
            '--snow-drift': flake.drift,
          }"
        />
      </div>

      <!-- 重阳/秋分/夏至：落叶/枫叶飘落 -->
      <div v-if="motifType === 'leaves'" class="motif motif-leaves">
        <span
          v-for="leaf in leaves"
          :key="leaf.id"
          class="maple-leaf"
          :style="{
            left: leaf.left,
            width: leaf.size,
            height: leaf.size,
            animationDelay: leaf.delay,
            animationDuration: leaf.duration,
            '--leaf-drift': leaf.drift,
            '--leaf-rotation': leaf.rotation,
          }"
        />
      </div>

      <!-- 情人节：爱心上升 -->
      <div v-if="motifType === 'hearts'" class="motif motif-hearts">
        <span
          v-for="heart in hearts"
          :key="heart.id"
          class="floating-heart"
          :style="{
            left: heart.left,
            width: heart.size,
            height: heart.size,
            animationDelay: heart.delay,
            animationDuration: heart.duration,
            '--heart-drift': heart.drift,
          }"
        />
      </div>

      <!-- 程序员节：代码雨 -->
      <div v-if="motifType === 'code'" class="motif motif-code">
        <span
          v-for="line in codeLines"
          :key="line.id"
          class="code-line"
          :style="{
            left: line.left,
            height: line.length,
            animationDelay: line.delay,
            animationDuration: line.duration,
          }"
        >{{ line.char }}</span>
      </div>

      <!-- 周年庆：星图轨道 -->
      <div v-if="motifType === 'orbit'" class="motif motif-orbit">
        <span class="orbit orbit-1" />
        <span class="orbit orbit-2" />
        <span class="orbit orbit-3" />
        <span class="orbit-dot dot-1" />
        <span class="orbit-dot dot-2" />
        <span class="orbit-dot dot-3" />
      </div>
    </div>

    <!-- 高级失焦星火：20-30 个模糊粒子，自下而上漂浮 -->
    <div class="ember-field">
      <span
        v-for="ember in embers"
        :key="ember.id"
        class="ember"
        :style="{
          left: ember.left,
          width: ember.size,
          height: ember.size,
          animationDelay: ember.delay,
          animationDuration: ember.duration,
          '--ember-drift': ember.drift,
          '--ember-blur': ember.blur,
          '--ember-color': ember.color,
        }"
      />
    </div>

    <!-- 极淡的 vignette，让中心更聚焦 -->
    <div class="bg-vignette" />
  </div>
</template>

<style scoped>
.festival-background {
  position: absolute;
  inset: 0;
  /* 必须高于 festival-backdrop（z-index:1），否则会被毛玻璃模糊/压暗到看不见 */
  z-index: 2;
  pointer-events: none;
  overflow: hidden;
  isolation: isolate;
  background: #000;
}

/* ═══════════════════════════════════════════════════════════════════
 *  暗流涌动的背景基色
 *  中心：极暗酒红 #2A0A0A，四周过渡到纯黑
 * ═══════════════════════════════════════════════════════════════════ */
.bg-base {
  position: absolute;
  inset: -10%;
  z-index: 0;
  background:
    radial-gradient(
      ellipse at 50% 45%,
      #2A0A0A 0%,
      rgba(26, 5, 5, 0.92) 24%,
      rgba(10, 3, 3, 0.72) 48%,
      rgba(0, 0, 0, 0.96) 74%,
      #000 100%
    );
  transform-origin: center;
  animation: baseBreathe 14s cubic-bezier(0.37, 0, 0.63, 1) infinite;
  will-change: transform;
}

@keyframes baseBreathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.06); }
}

/* ═══════════════════════════════════════════════════════════════════
 *  多层柔光晕
 * ═══════════════════════════════════════════════════════════════════ */
.bg-glow {
  position: absolute;
  z-index: 1;
  border-radius: 50%;
  filter: blur(80px);
  pointer-events: none;
  mix-blend-mode: screen;
  transform-origin: center;
}

.bg-glow-primary {
  top: 20%;
  left: 25%;
  width: 55vw;
  height: 55vw;
  max-width: 680px;
  max-height: 680px;
  background: radial-gradient(
    circle at center,
    color-mix(in srgb, var(--bg-ambient, #D8B46A) 22%, transparent) 0%,
    transparent 62%
  );
  animation: glowDriftA 18s cubic-bezier(0.22, 1, 0.36, 1) infinite alternate,
             glowBreathe 8s cubic-bezier(0.37, 0, 0.63, 1) infinite;
}

.bg-glow-secondary {
  bottom: 18%;
  right: 18%;
  width: 42vw;
  height: 42vw;
  max-width: 520px;
  max-height: 520px;
  background: radial-gradient(
    circle at center,
    color-mix(in srgb, var(--bg-highlight, #F8E6BF) 14%, transparent) 0%,
    transparent 58%
  );
  animation: glowDriftB 22s cubic-bezier(0.22, 1, 0.36, 1) infinite alternate,
             glowBreathe 10s cubic-bezier(0.37, 0, 0.63, 1) infinite 1.4s;
}

.bg-glow-tertiary {
  top: 50%;
  left: 50%;
  width: 80vw;
  height: 80vw;
  max-width: 960px;
  max-height: 960px;
  transform: translate(-50%, -50%);
  background: radial-gradient(
    circle at center,
    color-mix(in srgb, var(--bg-ambient, #D8B46A) 8%, transparent) 0%,
    transparent 55%
  );
  animation: glowBreathe 12s cubic-bezier(0.37, 0, 0.63, 1) infinite 2.1s;
}

@keyframes glowDriftA {
  0% { transform: translate3d(0, 0, 0); }
  100% { transform: translate3d(4vw, -3vh, 0); }
}

@keyframes glowDriftB {
  0% { transform: translate3d(0, 0, 0); }
  100% { transform: translate3d(-3vw, 4vh, 0); }
}

@keyframes glowBreathe {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  50% { opacity: 0.85; transform: scale(1.08); }
}

/* ═══════════════════════════════════════════════════════════════════
 *  卡片正后方的专属暗金色光晕
 *  6 秒一周期缓动呼吸
 * ═══════════════════════════════════════════════════════════════════ */
.card-halo {
  position: absolute;
  top: 50%;
  left: 50%;
  z-index: 2;
  width: min(560px, 96vw);
  height: min(520px, 84vh);
  border-radius: 34px;
  transform: translate(-50%, -50%);
  pointer-events: none;
  background: radial-gradient(
    ellipse at 50% 42%,
    color-mix(in srgb, var(--bg-ambient, #D8B46A) 18%, transparent) 0%,
    color-mix(in srgb, var(--bg-ambient, #D8B46A) 6%, transparent) 36%,
    transparent 66%
  );
  filter: blur(80px);
  opacity: 0.72;
  mix-blend-mode: screen;
  animation: cardHaloBreathe 6s cubic-bezier(0.37, 0, 0.63, 1) infinite;
  will-change: opacity, transform;
}

@keyframes cardHaloBreathe {
  0%, 100% {
    opacity: 0.55;
    transform: translate(-50%, -50%) scale(0.96);
  }
  50% {
    opacity: 0.86;
    transform: translate(-50%, -50%) scale(1.06);
  }
}

/* ═══════════════════════════════════════════════════════════════════
 *  高级失焦星火
 * ═══════════════════════════════════════════════════════════════════ */
.ember-field {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
  overflow: hidden;
}

.ember {
  position: absolute;
  bottom: -18px;
  display: block;
  border-radius: 50%;
  background: radial-gradient(
    circle at 30% 30%,
    color-mix(in srgb, var(--ember-color, #E7C27E) 92%, #fff),
    var(--ember-color, #E7C27E) 52%,
    transparent 76%
  );
  filter: blur(var(--ember-blur, 6px));
  opacity: 0;
  mix-blend-mode: screen;
  box-shadow:
    0 0 calc(var(--ember-blur, 6px) * 1.5) color-mix(in srgb, var(--ember-color, #E7C27E) 60%, transparent),
    0 0 calc(var(--ember-blur, 6px) * 3) color-mix(in srgb, var(--ember-color, #E7C27E) 24%, transparent);
  animation-name: emberRise, emberTwinkle;
  animation-timing-function: linear, ease-in-out;
  animation-iteration-count: infinite, infinite;
  will-change: transform, opacity;
}

@keyframes emberRise {
  0% {
    transform: translate3d(0, 0, 0);
    opacity: 0;
  }
  8% {
    opacity: var(--ember-enter-opacity, 0.55);
  }
  92% {
    opacity: var(--ember-exit-opacity, 0.35);
  }
  100% {
    transform: translate3d(var(--ember-drift, 0), calc(-100vh - 60px), 0);
    opacity: 0;
  }
}

@keyframes emberTwinkle {
  0%, 100% { filter: blur(var(--ember-blur, 6px)) brightness(0.82); }
  25% { filter: blur(calc(var(--ember-blur, 6px) + 1px)) brightness(1.18); }
  50% { filter: blur(var(--ember-blur, 6px)) brightness(0.7); }
  75% { filter: blur(calc(var(--ember-blur, 6px) + 2px)) brightness(1.08); }
}

.ember:nth-child(4n+1) { --ember-enter-opacity: 0.62; --ember-exit-opacity: 0.28; }
.ember:nth-child(4n+2) { --ember-enter-opacity: 0.48; --ember-exit-opacity: 0.22; }
.ember:nth-child(4n+3) { --ember-enter-opacity: 0.55; --ember-exit-opacity: 0.35; }
.ember:nth-child(4n+4) { --ember-enter-opacity: 0.42; --ember-exit-opacity: 0.18; }

/* ═══════════════════════════════════════════════════════════════════
 *  节日专属意象层
 * ═══════════════════════════════════════════════════════════════════ */
.motif-layer {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  overflow: hidden;
}

.motif {
  position: absolute;
  inset: 0;
  opacity: 0;
  pointer-events: none;
}

/* ── 灯笼（春节/国庆） ── */
.motif-lanterns { opacity: 1; }
.lantern {
  position: absolute;
  bottom: -80px;
  border-radius: 40% 40% 46% 46%;
  background:
    radial-gradient(
      ellipse at 50% 35%,
      color-mix(in srgb, var(--bg-highlight, #F8E6BF) 55%, transparent),
      color-mix(in srgb, var(--bg-ambient, #D8B46A) 28%, transparent) 52%,
      transparent 76%
    );
  box-shadow:
    0 0 28px color-mix(in srgb, var(--bg-ambient, #D8B46A) 35%, transparent),
    inset 0 -6px 14px color-mix(in srgb, #8B0000 22%, transparent);
  filter: blur(0.5px);
  opacity: 0;
  animation: lanternFloat linear infinite;
}
.lantern::before {
  content: '';
  position: absolute;
  top: -8px;
  left: 50%;
  transform: translateX(-50%);
  width: 30%;
  height: 8px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--bg-ambient, #D8B46A) 60%, transparent);
}
.lantern::after {
  content: '';
  position: absolute;
  bottom: -14px;
  left: 50%;
  transform: translateX(-50%);
  width: 2px;
  height: 14px;
  background: color-mix(in srgb, var(--bg-ambient, #D8B46A) 50%, transparent);
}

@keyframes lanternFloat {
  0% { transform: translate3d(0, 0, 0); opacity: 0; }
  10% { opacity: 0.7; }
  90% { opacity: 0.5; }
  100% { transform: translate3d(0, calc(-100vh - 120px), 0); opacity: 0; }
}

/* ── 水面涟漪（元宵/中秋） ── */
.motif-ripples,
.motif-moon .water-ripple { opacity: 1; }
.water-ripple {
  position: absolute;
  width: 90px;
  height: 22px;
  border: 1px solid color-mix(in srgb, var(--bg-ambient, #D8B46A) 28%, transparent);
  border-radius: 50%;
  filter: blur(0.5px);
  opacity: 0;
  animation: rippleExpand linear infinite;
}

@keyframes rippleExpand {
  0% { transform: scale(0.6); opacity: 0; }
  20% { opacity: 0.45; }
  80% { opacity: 0.1; }
  100% { transform: scale(2.2); opacity: 0; }
}

/* ── 竹叶（端午/立春） ── */
.motif-bamboo { opacity: 1; }
.bamboo-leaf {
  position: absolute;
  top: -30px;
  border-radius: 0 80% 0 80%;
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--bg-ambient, #84A78B) 45%, transparent),
    transparent 72%
  );
  filter: blur(0px);
  opacity: 0;
  animation: leafFall linear infinite;
}

@keyframes leafFall {
  0% { transform: translate3d(0, 0, 0) rotate(0deg); opacity: 0; }
  10% { opacity: 0.55; }
  90% { opacity: 0.25; }
  100% { transform: translate3d(var(--leaf-drift, 40px), calc(100vh + 60px), 0) rotate(720deg); opacity: 0; }
}

/* ── 鹊桥（七夕） ── */
.motif-bridge { opacity: 1; }
.magpie-bridge {
  position: absolute;
  top: 36%;
  left: 50%;
  width: 70vw;
  max-width: 720px;
  height: 180px;
  transform: translateX(-50%);
  border-top: 2px solid color-mix(in srgb, var(--bg-ambient, #B894B5) 28%, transparent);
  border-radius: 50% 50% 0 0 / 100% 100% 0 0;
  filter: blur(1px);
  opacity: 0.55;
  animation: bridgePulse 6s cubic-bezier(0.37, 0, 0.63, 1) infinite;
}
.magpie-bridge::after {
  content: '';
  position: absolute;
  top: 8px;
  left: 50%;
  width: 90%;
  height: 100%;
  transform: translateX(-50%);
  border-top: 1px solid color-mix(in srgb, var(--bg-highlight, #E9D9E8) 18%, transparent);
  border-radius: 50% 50% 0 0 / 100% 100% 0 0;
}

@keyframes bridgePulse {
  0%, 100% { opacity: 0.42; filter: blur(1px); }
  50% { opacity: 0.72; filter: blur(1.5px); }
}

.shooting-star {
  position: absolute;
  right: -40px;
  width: 80px;
  height: 1px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--bg-highlight, #E9D9E8) 60%, transparent), transparent);
  filter: blur(0.5px);
  opacity: 0;
  transform: rotate(-25deg);
  animation: shooting linear infinite;
}

@keyframes shooting {
  0% { transform: translate3d(0, 0, 0) rotate(-25deg); opacity: 0; }
  15% { opacity: 1; }
  40% { opacity: 0; }
  100% { transform: translate3d(-60vw, 18vh, 0) rotate(-25deg); opacity: 0; }
}

/* ── 月晕（中秋/冬至） ── */
.motif-moon { opacity: 1; }
.moon-glow {
  position: absolute;
  top: 14%;
  right: 18%;
  width: 22vw;
  height: 22vw;
  max-width: 260px;
  max-height: 260px;
  border-radius: 50%;
  background: radial-gradient(
    circle at center,
    color-mix(in srgb, var(--bg-highlight, #E9E0CF) 22%, transparent) 0%,
    color-mix(in srgb, var(--bg-ambient, #DAD0BA) 10%, transparent) 42%,
    transparent 68%
  );
  filter: blur(24px);
  opacity: 0.72;
  animation: moonBreathe 8s cubic-bezier(0.37, 0, 0.63, 1) infinite;
}

@keyframes moonBreathe {
  0%, 100% { opacity: 0.58; transform: scale(1); }
  50% { opacity: 0.86; transform: scale(1.08); }
}

/* ── 雪花（冬至/圣诞/元旦） ── */
.motif-snow { opacity: 1; }
.snowflake {
  position: absolute;
  top: -20px;
  border-radius: 50%;
  background: radial-gradient(
    circle at 30% 30%,
    color-mix(in srgb, var(--bg-highlight, #ffffff) 85%, transparent),
    color-mix(in srgb, var(--bg-ambient, #B0C4DE) 45%, transparent) 55%,
    transparent 78%
  );
  filter: blur(0.5px);
  opacity: 0;
  animation: snowFall linear infinite;
}
.snowflake::before,
.snowflake::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 140%;
  height: 1px;
  background: color-mix(in srgb, var(--bg-highlight, #ffffff) 35%, transparent);
  transform: translate(-50%, -50%);
}
.snowflake::after { transform: translate(-50%, -50%) rotate(60deg); }
.snowflake:nth-child(3n)::before { transform: translate(-50%, -50%) rotate(30deg); }

@keyframes snowFall {
  0% { transform: translate3d(0, 0, 0) rotate(0deg); opacity: 0; }
  10% { opacity: 0.7; }
  90% { opacity: 0.3; }
  100% { transform: translate3d(var(--snow-drift, 20px), calc(100vh + 40px), 0) rotate(360deg); opacity: 0; }
}

/* ── 落叶/枫叶（重阳/秋分/夏至） ── */
.motif-leaves { opacity: 1; }
.maple-leaf {
  position: absolute;
  top: -40px;
  opacity: 0;
  filter: blur(0px);
  animation: leafFall linear infinite;
}
.maple-leaf::before {
  content: '';
  display: block;
  width: 100%;
  height: 100%;
  background:
    radial-gradient(ellipse at 50% 90%, color-mix(in srgb, var(--bg-ambient, #D2691E) 50%, transparent) 0%, transparent 60%),
    radial-gradient(ellipse at 20% 50%, color-mix(in srgb, var(--bg-highlight, #DAA520) 30%, transparent) 0%, transparent 55%),
    radial-gradient(ellipse at 80% 50%, color-mix(in srgb, var(--bg-ambient, #CD853F) 30%, transparent) 0%, transparent 55%);
  clip-path: polygon(50% 0%, 62% 28%, 98% 35%, 70% 55%, 80% 91%, 50% 70%, 20% 91%, 30% 55%, 2% 35%, 38% 28%);
  transform: rotate(var(--leaf-rotation, 0deg));
}

/* ── 爱心（情人节） ── */
.motif-hearts { opacity: 1; }
.floating-heart {
  position: absolute;
  bottom: -30px;
  opacity: 0;
  filter: blur(0.5px);
  animation: heartRise linear infinite;
}
.floating-heart::before {
  content: '';
  display: block;
  width: 100%;
  height: 100%;
  background: radial-gradient(
    circle at 30% 30%,
    color-mix(in srgb, var(--bg-highlight, #FFB6C1) 70%, transparent),
    color-mix(in srgb, var(--bg-ambient, #FF6B9D) 45%, transparent) 55%,
    transparent 78%
  );
  clip-path: path('M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z');
}

@keyframes heartRise {
  0% { transform: translate3d(0, 0, 0) scale(0.8); opacity: 0; }
  12% { opacity: 0.65; }
  88% { opacity: 0.35; }
  100% { transform: translate3d(var(--heart-drift, 15px), calc(-100vh - 50px), 0) scale(1.1); opacity: 0; }
}

/* ── 代码雨（程序员节） ── */
.motif-code { opacity: 1; }
.code-line {
  position: absolute;
  top: -120px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
  font-size: 13px;
  font-weight: 600;
  color: color-mix(in srgb, var(--bg-ambient, #70C6A6) 55%, transparent);
  text-shadow: 0 0 12px color-mix(in srgb, var(--bg-ambient, #70C6A6) 45%, transparent);
  opacity: 0;
  writing-mode: vertical-rl;
  letter-spacing: 0.2em;
  filter: blur(0.5px);
  animation: codeRain linear infinite;
}

@keyframes codeRain {
  0% { transform: translate3d(0, 0, 0); opacity: 0; }
  8% { opacity: 0.55; }
  92% { opacity: 0.18; }
  100% { transform: translate3d(0, calc(100vh + 140px), 0); opacity: 0; }
}

/* ── 星图轨道（周年庆） ── */
.motif-orbit { opacity: 1; }
.orbit {
  position: absolute;
  top: 50%;
  left: 50%;
  border: 1px solid color-mix(in srgb, var(--bg-ambient, #AFA2D4) 24%, transparent);
  border-radius: 50%;
  filter: blur(0.5px);
  transform: translate(-50%, -50%);
  animation: orbitRotate linear infinite;
}
.orbit-1 { width: 30vw; height: 20vw; max-width: 360px; max-height: 240px; animation-duration: 24s; }
.orbit-2 { width: 42vw; height: 26vw; max-width: 500px; max-height: 310px; animation-duration: 32s; opacity: 0.7; }
.orbit-3 { width: 54vw; height: 32vw; max-width: 640px; max-height: 380px; animation-duration: 44s; opacity: 0.5; }

@keyframes orbitRotate {
  0% { transform: translate(-50%, -50%) rotate(0deg); }
  100% { transform: translate(-50%, -50%) rotate(360deg); }
}

.orbit-dot {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--bg-highlight, #DCE6FF) 70%, transparent);
  box-shadow: 0 0 14px color-mix(in srgb, var(--bg-highlight, #DCE6FF) 50%, transparent);
  filter: blur(0.5px);
}
.dot-1 { animation: orbit1 12s linear infinite; }
.dot-2 { animation: orbit2 16s linear infinite; }
.dot-3 { animation: orbit3 22s linear infinite; }

@keyframes orbit1 {
  0% { transform: translate(-50%, -50%) rotate(0deg) translateX(15vw) rotate(0deg); }
  100% { transform: translate(-50%, -50%) rotate(360deg) translateX(15vw) rotate(-360deg); }
}
@keyframes orbit2 {
  0% { transform: translate(-50%, -50%) rotate(120deg) translateX(21vw) rotate(-120deg); }
  100% { transform: translate(-50%, -50%) rotate(480deg) translateX(21vw) rotate(-480deg); }
}
@keyframes orbit3 {
  0% { transform: translate(-50%, -50%) rotate(240deg) translateX(27vw) rotate(-240deg); }
  100% { transform: translate(-50%, -50%) rotate(600deg) translateX(27vw) rotate(-600deg); }
}

@media (min-width: 1024px) {
  @keyframes orbit1 {
    0% { transform: translate(-50%, -50%) rotate(0deg) translateX(180px) rotate(0deg); }
    100% { transform: translate(-50%, -50%) rotate(360deg) translateX(180px) rotate(-360deg); }
  }
  @keyframes orbit2 {
    0% { transform: translate(-50%, -50%) rotate(120deg) translateX(250px) rotate(-120deg); }
    100% { transform: translate(-50%, -50%) rotate(480deg) translateX(250px) rotate(-480deg); }
  }
  @keyframes orbit3 {
    0% { transform: translate(-50%, -50%) rotate(240deg) translateX(320px) rotate(-240deg); }
    100% { transform: translate(-50%, -50%) rotate(600deg) translateX(320px) rotate(-600deg); }
  }
}

/* ═══════════════════════════════════════════════════════════════════
 *  暗角 vignette
 * ═══════════════════════════════════════════════════════════════════ */
.bg-vignette {
  position: absolute;
  inset: 0;
  z-index: 4;
  pointer-events: none;
  background: radial-gradient(
    ellipse at 50% 45%,
    transparent 0%,
    transparent 42%,
    rgba(0, 0, 0, 0.42) 86%,
    rgba(0, 0, 0, 0.72) 100%
  );
}

/* ═══════════════════════════════════════════════════════════════════
 *  节日主题色微调
 * ═══════════════════════════════════════════════════════════════════ */

/* 春节/国庆：酒红底 + 灯笼星火 */
.theme-spring_festival .bg-base,
.theme-national_day .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 45%,
      #2A0A0A 0%,
      rgba(26, 5, 5, 0.92) 24%,
      rgba(10, 3, 3, 0.72) 48%,
      rgba(0, 0, 0, 0.96) 74%,
      #000 100%
    );
}

/* 元宵节：暖橙底 + 灯影 */
.theme-lantern_festival .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 48%,
      #2A1208 0%,
      rgba(30, 14, 8, 0.9) 26%,
      rgba(12, 6, 4, 0.7) 50%,
      rgba(0, 0, 0, 0.96) 76%,
      #000 100%
    );
}

/* 端午/立春：墨绿底 + 竹叶 */
.theme-dragon_boat .bg-base,
.theme-li_chun .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 45%,
      #081A0E 0%,
      rgba(10, 24, 16, 0.9) 26%,
      rgba(5, 12, 10, 0.7) 52%,
      rgba(0, 0, 0, 0.96) 78%,
      #000 100%
    );
}

/* 七夕：深紫底 + 鹊桥 */
.theme-qixi .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 45%,
      #1E0A22 0%,
      rgba(26, 10, 30, 0.9) 26%,
      rgba(10, 5, 16, 0.7) 52%,
      rgba(0, 0, 0, 0.96) 78%,
      #000 100%
    );
}

/* 中秋/冬至：藏蓝底 + 月晕 */
.theme-mid_autumn .bg-base,
.theme-dong_zhi .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 40%,
      #0A1020 0%,
      rgba(10, 16, 28, 0.9) 26%,
      rgba(5, 8, 18, 0.7) 52%,
      rgba(0, 0, 0, 0.96) 78%,
      #000 100%
    );
}

/* 圣诞/元旦：藏蓝底 + 雪花 */
.theme-christmas .bg-base,
.theme-new_year .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 40%,
      #081020 0%,
      rgba(10, 18, 32, 0.9) 26%,
      rgba(5, 10, 20, 0.7) 52%,
      rgba(0, 0, 0, 0.96) 78%,
      #000 100%
    );
}

/* 重阳/秋分/夏至：秋褐底 + 落叶 */
.theme-double_ninth .bg-base,
.theme-qiu_fen .bg-base,
.theme-xia_zhi .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 45%,
      #24180C 0%,
      rgba(28, 20, 10, 0.9) 26%,
      rgba(12, 8, 5, 0.7) 52%,
      rgba(0, 0, 0, 0.96) 78%,
      #000 100%
    );
}

/* 情人节：玫红底 + 爱心 */
.theme-valentine .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 45%,
      #220A14 0%,
      rgba(28, 10, 18, 0.9) 26%,
      rgba(12, 5, 10, 0.7) 52%,
      rgba(0, 0, 0, 0.96) 78%,
      #000 100%
    );
}

/* 程序员节：纯黑底 + 代码雨 */
.theme-programmers_day .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 45%,
      #050A08 0%,
      rgba(5, 12, 10, 0.92) 28%,
      rgba(0, 0, 0, 0.96) 68%,
      #000 100%
    );
}

/* 周年庆：深紫蓝底 + 星图轨道 */
.theme-anniversary .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 42%,
      #120A2A 0%,
      rgba(18, 12, 42, 0.9) 26%,
      rgba(8, 6, 20, 0.7) 52%,
      rgba(0, 0, 0, 0.96) 78%,
      #000 100%
    );
}

/* 物候兜底：保持酒红微光，色温由光晕接管 */
.theme-spring-sprout .bg-base,
.theme-rain-ripple .bg-base,
.theme-thunder-crack .bg-base,
.theme-equinox-balance .bg-base,
.theme-clear-rain .bg-base,
.theme-rice-rain .bg-base,
.theme-tomato-vine .bg-base,
.theme-rice-wheat-fill .bg-base,
.theme-wheat-awn-seed .bg-base,
.theme-solar-arc .bg-base,
.theme-heat-haze .bg-base,
.theme-lotus-heat .bg-base,
.theme-autumn-leaf .bg-base,
.theme-cooling-cloud .bg-base,
.theme-dew-beads .bg-base,
.theme-autumn-balance .bg-base,
.theme-cold-dew .bg-base,
.theme-frost-vein .bg-base,
.theme-winter-mist .bg-base,
.theme-snow-mist .bg-base,
.theme-snow-field .bg-base,
.theme-yang-return .bg-base,
.theme-cold-ridge .bg-base,
.theme-ice-ring .bg-base {
  background:
    radial-gradient(
      ellipse at 50% 45%,
      #1A0A0A 0%,
      rgba(18, 8, 8, 0.9) 26%,
      rgba(8, 4, 4, 0.7) 52%,
      rgba(0, 0, 0, 0.96) 78%,
      #000 100%
    );
}

/* 减少动画模式：冻结所有动效但保留静态氛围 */
@media (prefers-reduced-motion: reduce) {
  .bg-base,
  .bg-glow,
  .card-halo,
  .ember,
  .lantern,
  .water-ripple,
  .bamboo-leaf,
  .magpie-bridge,
  .shooting-star,
  .moon-glow,
  .snowflake,
  .maple-leaf,
  .floating-heart,
  .code-line,
  .orbit,
  .orbit-dot {
    animation: none !important;
  }
  .ember,
  .lantern,
  .water-ripple,
  .bamboo-leaf,
  .shooting-star,
  .snowflake,
  .maple-leaf,
  .floating-heart,
  .code-line {
    opacity: 0.35;
  }
  .motif-orbit .orbit,
  .motif-orbit .orbit-dot,
  .magpie-bridge,
  .moon-glow {
    opacity: 0.5;
  }
}

.animation-disabled .bg-base,
.animation-disabled .bg-glow,
.animation-disabled .card-halo,
.animation-disabled .ember,
.animation-disabled .lantern,
.animation-disabled .water-ripple,
.animation-disabled .bamboo-leaf,
.animation-disabled .magpie-bridge,
.animation-disabled .shooting-star,
.animation-disabled .moon-glow,
.animation-disabled .snowflake,
.animation-disabled .maple-leaf,
.animation-disabled .floating-heart,
.animation-disabled .code-line,
.animation-disabled .orbit,
.animation-disabled .orbit-dot {
  animation: none !important;
}

.animation-disabled .ember,
.animation-disabled .lantern,
.animation-disabled .water-ripple,
.animation-disabled .bamboo-leaf,
.animation-disabled .shooting-star,
.animation-disabled .snowflake,
.animation-disabled .maple-leaf,
.animation-disabled .floating-heart,
.animation-disabled .code-line {
  opacity: 0.35;
}

.animation-disabled .motif-orbit .orbit,
.animation-disabled .motif-orbit .orbit-dot,
.animation-disabled .magpie-bridge,
.animation-disabled .moon-glow {
  opacity: 0.5;
}
</style>
