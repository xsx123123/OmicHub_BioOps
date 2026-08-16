<script setup lang="ts">
/**
 * 星尘 AI 首页 hero：星星 + AI 结合的 canvas 动画（中心闪耀星 + 轨道彗星 +
 * 星尘粒子向心连线构成"神经网络"意象），旁边配打招呼文案。
 * 主题感知：每帧读取 data-theme 切换明暗配色；prefers-reduced-motion 时只渲染单帧。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'

defineProps<{ title: string; userName?: string }>()

/** 按本地时段问候：与 header 状态文案呼应，作为首页打招呼语 */
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h >= 5 && h < 11) return '早上好'
  if (h >= 11 && h < 13) return '中午好'
  if (h >= 13 && h < 18) return '下午好'
  return '晚上好'
})

const canvasRef = ref<HTMLCanvasElement>()
let raf = 0
let ro: ResizeObserver | null = null

interface Dust {
  /** 归一化坐标 0..1，resize 不丢位置 */
  x: number
  y: number
  r: number
  /** 闪烁相位 / 速度 */
  tw: number
  sp: number
  /** 漂移速度（归一化/秒） */
  vx: number
  vy: number
  ci: number
}

const DUST_N = 64

function makeDust(): Dust[] {
  // 简单可复现的伪随机即可，无需加密级随机
  const list: Dust[] = []
  for (let i = 0; i < DUST_N; i++) {
    list.push({
      x: Math.random(),
      y: Math.random(),
      r: 0.8 + Math.random() * 1.5,
      tw: Math.random() * Math.PI * 2,
      sp: 0.6 + Math.random() * 1.6,
      vx: (Math.random() - 0.5) * 0.012,
      vy: (Math.random() - 0.5) * 0.012,
      ci: Math.floor(Math.random() * 4),
    })
  }
  return list
}

let dust: Dust[] = []

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  dust = makeDust()
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const dpr = Math.min(2, window.devicePixelRatio || 1)
  const resize = () => {
    const size = canvas.clientWidth
    if (!size) return
    canvas.width = Math.round(size * dpr)
    canvas.height = Math.round(size * dpr)
  }
  resize()
  ro = new ResizeObserver(resize)
  ro.observe(canvas)

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const start = performance.now()
  const frame = (now: number) => {
    const t = (now - start) / 1000
    draw(ctx, canvas.width, t, dpr)
    if (!reduced) raf = requestAnimationFrame(frame)
  }
  raf = requestAnimationFrame(frame)
})

onUnmounted(() => {
  cancelAnimationFrame(raf)
  ro?.disconnect()
})

/** 四芒星（✦）凹边路径 */
function starPath(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(cx, cy - r)
  ctx.quadraticCurveTo(cx, cy, cx + r, cy)
  ctx.quadraticCurveTo(cx, cy, cx, cy + r)
  ctx.quadraticCurveTo(cx, cy, cx - r, cy)
  ctx.quadraticCurveTo(cx, cy, cx, cy - r)
  ctx.closePath()
}

function draw(ctx: CanvasRenderingContext2D, px: number, t: number, dpr: number) {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark'
  const blue = dark ? '#7691FF' : '#2E5BFF'
  const purple = dark ? '#9A7BFF' : '#7B4DFF'
  const lineBase = dark ? 'rgba(118,145,255,' : 'rgba(46,91,255,'
  const palette = [blue, purple, '#38BDF8', dark ? '#FFFFFF' : '#8FA3FF']

  ctx.clearRect(0, 0, px, px)
  const c = px / 2
  const u = px / 240 // 以 240 设计稿为基准的缩放

  // 背景辉光
  const glow = ctx.createRadialGradient(c, c, 0, c, c, c * 0.95)
  glow.addColorStop(0, dark ? 'rgba(118,145,255,0.20)' : 'rgba(79,109,245,0.14)')
  glow.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, px, px)

  // 星尘粒子：漂移 + 闪烁；靠近中心的粒子与星连线（AI 网络意象）
  const dt = 1 / 60
  for (const d of dust) {
    d.x = (d.x + d.vx * dt + 1) % 1
    d.y = (d.y + d.vy * dt + 1) % 1
    const x = d.x * px
    const y = d.y * px
    const twinkle = 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(t * d.sp + d.tw))
    const dx = x - c
    const dy = y - c
    const dist = Math.hypot(dx, dy)
    const linkR = px * 0.34
    if (dist < linkR && dist > px * 0.09) {
      const a = (1 - dist / linkR) * (dark ? 0.30 : 0.22)
      ctx.strokeStyle = `${lineBase}${a.toFixed(3)})`
      ctx.lineWidth = u * 0.7
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(c, c)
      ctx.stroke()
    }
    ctx.globalAlpha = twinkle * (d.ci === 3 && !dark ? 0.55 : 0.9)
    ctx.fillStyle = palette[d.ci]
    ctx.beginPath()
    ctx.arc(x, y, d.r * u, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1

  // 双轨道环 + 轨道彗星
  const orbits = [
    { rx: px * 0.40, ry: px * 0.15, rot: -0.5 + t * 0.12, sp: 0.9, color: blue },
    { rx: px * 0.31, ry: px * 0.20, rot: 0.9 - t * 0.09, sp: -1.3, color: purple },
  ]
  for (const o of orbits) {
    ctx.strokeStyle = `${lineBase}${dark ? '0.22' : '0.16'})`
    ctx.lineWidth = u
    ctx.beginPath()
    ctx.ellipse(c, c, o.rx, o.ry, o.rot, 0, Math.PI * 2)
    ctx.stroke()
    // 彗星：主点 + 拖尾
    for (let k = 0; k < 7; k++) {
      const th = t * o.sp - k * 0.07
      const ex = Math.cos(th) * o.rx
      const ey = Math.sin(th) * o.ry
      const x = c + ex * Math.cos(o.rot) - ey * Math.sin(o.rot)
      const y = c + ex * Math.sin(o.rot) + ey * Math.cos(o.rot)
      ctx.globalAlpha = (1 - k / 7) * 0.85
      ctx.fillStyle = o.color
      ctx.beginPath()
      ctx.arc(x, y, (2.4 - k * 0.25) * u, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.globalAlpha = 1
  }

  // 中心闪耀星：呼吸缩放 + 光晕 + 白色星核
  const pulse = 1 + 0.06 * Math.sin(t * 2.1)
  const R = px * 0.16 * pulse
  ctx.save()
  ctx.shadowColor = dark ? 'rgba(154,123,255,0.85)' : 'rgba(123,77,255,0.65)'
  ctx.shadowBlur = R * 1.1
  const grad = ctx.createLinearGradient(c - R, c - R, c + R, c + R)
  grad.addColorStop(0, blue)
  grad.addColorStop(1, purple)
  ctx.fillStyle = grad
  starPath(ctx, c, c, R)
  ctx.fill()
  ctx.restore()
  ctx.fillStyle = 'rgba(255,255,255,0.95)'
  ctx.beginPath()
  ctx.arc(c, c, R * 0.16, 0, Math.PI * 2)
  ctx.fill()
  // 斜 45° 的小副星芒，增加"闪耀"感
  ctx.save()
  ctx.translate(c, c)
  ctx.rotate(Math.PI / 4 + 0.15 * Math.sin(t * 0.8))
  ctx.globalAlpha = 0.55 + 0.25 * Math.sin(t * 2.6)
  ctx.fillStyle = dark ? '#B9C6FF' : '#7B4DFF'
  starPath(ctx, 0, 0, R * 0.45)
  ctx.fill()
  ctx.restore()
  ctx.globalAlpha = 1
}
</script>

<template>
  <section class="stardust-hero">
    <div class="hero-visual">
      <canvas ref="canvasRef" aria-hidden="true"></canvas>
    </div>
    <div class="hero-greet">
      <h1 class="hero-title">{{ title }}</h1>
      <div class="hero-eyebrow">
        <span class="pulse-dot" aria-hidden="true"></span>
        {{ greeting }}<template v-if="userName">，{{ userName }}</template>，助手已就绪
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
.stardust-hero {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: clamp(18px, 3.5vw, 32px);
  padding: 4px 0 8px;
  animation: hero-in 480ms cubic-bezier(0.22, 0.8, 0.36, 1) both;
}
.hero-visual {
  width: clamp(128px, 18vw, 168px);
  aspect-ratio: 1;
  flex-shrink: 0;
}
.hero-visual canvas { display: block; width: 100%; height: 100%; }
.hero-greet { min-width: 0; max-width: 560px; }
.hero-eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: clamp(16px, 2vw, 19px);
  line-height: 1.45;
  font-weight: 600;
  color: var(--stardust-text-secondary);
}
.pulse-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
  background: var(--success-color, #18a058);
  animation: dot-breathe 1.8s ease-in-out infinite;
}
.hero-title {
  margin: 8px 0 6px;
  font-size: clamp(26px, 4vw, 34px);
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: -0.02em;
  background: var(--stardust-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
@keyframes hero-in {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: none; }
}
@keyframes dot-breathe {
  0%, 100% {
    opacity: 0.72;
    transform: scale(0.86);
    box-shadow: 0 0 0 0 rgba(24, 160, 88, 0.3);
  }
  50% {
    opacity: 1;
    transform: scale(1);
    box-shadow: 0 0 0 6px rgba(24, 160, 88, 0);
  }
}

@media (max-width: 640px) {
  .stardust-hero { flex-direction: column; text-align: center; gap: 12px; }
  .hero-greet { max-width: 100%; }
  .hero-eyebrow { justify-content: center; }
}
@media (prefers-reduced-motion: reduce) {
  .stardust-hero { animation: none; }
  .pulse-dot { animation: none; }
}
</style>
