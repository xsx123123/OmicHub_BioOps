<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import type { FestivalAnimationType } from '@/utils/festivalThemes'

interface Props {
  type: FestivalAnimationType | string
  duration?: number
  colors?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  duration: 10,
  colors: () => ['#D8E2FF', '#B8A6D9', '#C9A66B'],
})

const canvasRef = ref<HTMLCanvasElement | null>(null)
let rafId: number | null = null
let startedAt = 0
let ambientNodes: AmbientNode[] = []
let particleSystem: Particle[] = []
let targetParallaxX = 0
let targetParallaxY = 0
let parallaxX = 0
let parallaxY = 0

const reducedMotion = typeof window !== 'undefined'
  ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
  : false

interface AmbientNode {
  x: number
  y: number
  radius: number
  phase: number
  speed: number
  color: string
  orbit: number
  depth: number
}

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  size: number
  alpha: number
  color: string
  depth: number
  phase: number
  speed: number
  life: number
  maxLife: number
}

function resizeCanvas(canvas: HTMLCanvasElement) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = window.innerWidth * dpr
  canvas.height = window.innerHeight * dpr
  const ctx = canvas.getContext('2d')
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}

function getCtx() {
  const canvas = canvasRef.value
  if (!canvas) return null
  return canvas.getContext('2d')
}

function hashSource(source: string) {
  let hash = 2166136261
  for (let i = 0; i < source.length; i++) {
    hash ^= source.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function seeded(seed: number) {
  let value = seed || 1
  return () => {
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

function normalizeColor(input: string | undefined, fallback = '#D8E2FF') {
  const color = (input || fallback).trim()
  if (/^#[0-9a-f]{6}$/i.test(color)) {
    const n = Number.parseInt(color.slice(1), 16)
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
  }
  if (/^#[0-9a-f]{3}$/i.test(color)) {
    const r = Number.parseInt(color[1] + color[1], 16)
    const g = Number.parseInt(color[2] + color[2], 16)
    const b = Number.parseInt(color[3] + color[3], 16)
    return { r, g, b }
  }
  const match = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i)
  if (match) {
    return { r: Number(match[1]), g: Number(match[2]), b: Number(match[3]) }
  }
  return normalizeColor(fallback, '#D8E2FF')
}

function rgba(input: string | undefined, alpha: number) {
  const { r, g, b } = normalizeColor(input)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function hexToRgba(input: string | undefined, alpha: number) {
  const { r, g, b } = normalizeColor(input)
  return { r, g, b, a: alpha }
}

/* ═════════════════════════════════════════════════════════════════
 *  LAYER 3 · 环境基底：极大模糊、缓慢流体渐变
 * ═════════════════════════════════════════════════════════════════ */
function drawEnvironmentWash(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const colors = props.colors.length ? props.colors : ['#D8E2FF']
  const primary = colors[0]
  const secondary = colors[1] || primary
  const tertiary = colors[2] || secondary

  ctx.save()
  ctx.globalCompositeOperation = 'source-over'

  // 缓慢漂移的径向光晕
  const phase = Math.sin(time * 0.025) * 0.5
  const phase2 = Math.cos(time * 0.018) * 0.5
  const cx1 = w * (0.35 + phase * 0.12)
  const cy1 = h * (0.32 + phase2 * 0.1)
  const cx2 = w * (0.78 - phase2 * 0.1)
  const cy2 = h * (0.68 + phase * 0.08)

  const g1 = ctx.createRadialGradient(cx1, cy1, 0, cx1, cy1, Math.max(w, h) * 0.65)
  g1.addColorStop(0, rgba(primary, 0.045))
  g1.addColorStop(0.55, rgba(secondary, 0.028))
  g1.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g1
  ctx.fillRect(0, 0, w, h)

  const g2 = ctx.createRadialGradient(cx2, cy2, 0, cx2, cy2, Math.max(w, h) * 0.55)
  g2.addColorStop(0, rgba(tertiary, 0.038))
  g2.addColorStop(0.62, rgba(primary, 0.022))
  g2.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g2
  ctx.fillRect(0, 0, w, h)

  // 极淡的全屏线性洗光
  const sweep = ctx.createLinearGradient(0, 0, w, h)
  const sweepPhase = 0.5 + Math.sin(time * 0.045) * 0.5
  sweep.addColorStop(0, rgba(primary, 0.028))
  sweep.addColorStop(Math.min(0.92, 0.34 + sweepPhase * 0.18), rgba(secondary, 0.045))
  sweep.addColorStop(1, rgba(primary, 0.018))
  ctx.fillStyle = sweep
  ctx.fillRect(0, 0, w, h)

  ctx.restore()
}

/* ═════════════════════════════════════════════════════════════════
 *  LAYER 2 · 环境散景：中等模糊、缓慢呼吸
 * ═════════════════════════════════════════════════════════════════ */
function initAmbientField() {
  const seed = hashSource(String(props.type))
  const random = seeded(seed)
  const colors = props.colors.length ? props.colors : ['#D8E2FF']
  ambientNodes = Array.from({ length: 7 }, (_, index) => ({
    x: 0.08 + random() * 0.84,
    y: 0.08 + random() * 0.74,
    radius: 120 + random() * 260,
    phase: random() * Math.PI * 2,
    speed: 0.05 + random() * 0.06,
    color: colors[index % colors.length],
    orbit: 8 + random() * 22,
    depth: 0.28 + random() * 0.72,
  }))
}

function drawAmbientBokeh(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  ctx.globalCompositeOperation = 'screen'
  for (const node of ambientNodes) {
    const depthShift = node.depth * 34
    const driftX = Math.cos(time * node.speed + node.phase) * node.orbit + parallaxX * depthShift
    const driftY = Math.sin(time * node.speed * 0.78 + node.phase) * node.orbit + parallaxY * depthShift
    const x = node.x * w + driftX
    const y = node.y * h + driftY
    const breathe = 0.72 + Math.sin(time * node.speed * 1.4 + node.phase) * 0.08
    const depthScale = 0.82 + node.depth * 0.58
    const radius = node.radius * breathe * depthScale
    const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius)
    gradient.addColorStop(0, rgba(node.color, 0.24 + node.depth * 0.12))
    gradient.addColorStop(0.48, rgba(node.color, 0.09 + node.depth * 0.05))
    gradient.addColorStop(1, rgba(node.color, 0))
    ctx.fillStyle = gradient
    ctx.beginPath()
    ctx.arc(x, y, radius, 0, Math.PI * 2)
    ctx.fill()
  }
}

/* ═════════════════════════════════════════════════════════════════
 *  粒子系统
 * ═════════════════════════════════════════════════════════════════ */
function initParticles(w: number, h: number) {
  const seed = hashSource(String(props.type) + '_particles')
  const random = seeded(seed)
  const colors = props.colors.length ? props.colors : ['#D8E2FF']
  particleSystem = Array.from({ length: 24 }, () => ({
    x: random() * w,
    y: random() * h,
    vx: (random() - 0.5) * 0.3,
    vy: (random() - 0.5) * 0.3,
    size: 1 + random() * 2.5,
    alpha: 0.28 + random() * 0.32,
    color: colors[Math.floor(random() * colors.length)],
    depth: 0.2 + random() * 0.8,
    phase: random() * Math.PI * 2,
    speed: 0.04 + random() * 0.08,
    life: random() * 1000,
    maxLife: 800 + random() * 1200,
  }))
}

function updateAndDrawParticles(ctx: CanvasRenderingContext2D, w: number, h: number, time: number, renderer?: ParticleRenderer) {
  ctx.globalCompositeOperation = 'screen'
  for (const p of particleSystem) {
    p.life += 16
    if (p.life > p.maxLife) {
      p.life = 0
      p.x = Math.random() * w
      p.y = Math.random() * h
    }
    const normalized = p.life / p.maxLife
    const fade = Math.sin(normalized * Math.PI)
    const depthShift = p.depth * 12
    const px = p.x + parallaxX * depthShift + Math.cos(time * p.speed + p.phase) * 8
    const py = p.y + parallaxY * depthShift + Math.sin(time * p.speed * 0.7 + p.phase) * 6

    if (renderer) {
      renderer(ctx, p, px, py, time, fade, w, h)
    } else {
      ctx.fillStyle = rgba(p.color, p.alpha * fade)
      ctx.beginPath()
      ctx.arc(px, py, p.size, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}

type ParticleRenderer = (
  ctx: CanvasRenderingContext2D,
  p: Particle,
  x: number,
  y: number,
  time: number,
  fade: number,
  w: number,
  h: number,
) => void

/* ═════════════════════════════════════════════════════════════════
 *  通用绘制工具
 * ═════════════════════════════════════════════════════════════════ */
function strokeLine(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, color: string, alpha: number, width = 1) {
  ctx.lineWidth = width
  ctx.strokeStyle = rgba(color, alpha)
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.stroke()
}

function strokeBezier(ctx: CanvasRenderingContext2D, x1: number, y1: number, cp1x: number, cp1y: number, cp2x: number, cp2y: number, x2: number, y2: number, color: string, alpha: number) {
  ctx.strokeStyle = rgba(color, alpha)
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, x2, y2)
  ctx.stroke()
}

function strokeArc(ctx: CanvasRenderingContext2D, x: number, y: number, rx: number, ry: number, rotation: number, start: number, end: number, color: string, alpha: number, width = 1) {
  ctx.lineWidth = width
  ctx.strokeStyle = rgba(color, alpha)
  ctx.beginPath()
  ctx.ellipse(x, y, rx, ry, rotation, start, end)
  ctx.stroke()
}

function hasAny(source: string, keywords: string[]) {
  return keywords.some((keyword) => source.includes(keyword))
}

/* ═════════════════════════════════════════════════════════════════
 *  节日/节气专属渲染器
 * ═════════════════════════════════════════════════════════════════ */
interface FestivalRenderer {
  name: string
  motif: (ctx: CanvasRenderingContext2D, w: number, h: number, time: number) => void
  particles?: ParticleRenderer
}

/* ── 春节：星火余烬 ── */
function drawSpringFestival(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#D8B46A'
  const secondary = props.colors[1] || '#8C3B3B'
  ctx.save()
  ctx.lineCap = 'round'
  // 底部余烬上升
  for (let i = 0; i < 12; i++) {
    const seed = hashSource(`spring_${i}`)
    const rnd = seeded(seed)
    const x = w * (0.1 + rnd() * 0.8)
    const baseY = h * (0.82 + rnd() * 0.12)
    const height = 40 + rnd() * 90
    const progress = (time * (0.08 + rnd() * 0.06) + rnd() * 10) % 10
    const t = progress / 10
    const y = baseY - t * height
    const alpha = (1 - t) * (0.12 + rnd() * 0.08)
    const width = 0.8 + rnd() * 1.2
    strokeLine(ctx, x, y, x, y - height * 0.18, primary, alpha, width)
  }
  // 顶部春联飞白
  for (let i = 0; i < 5; i++) {
    const seed = hashSource(`spring_top_${i}`)
    const rnd = seeded(seed)
    const y = h * (0.06 + rnd() * 0.12)
    const x1 = w * (0.15 + rnd() * 0.2)
    const length = w * (0.25 + rnd() * 0.35)
    const drift = Math.sin(time * 0.12 + i) * 6
    ctx.strokeStyle = rgba(secondary, 0.06 + rnd() * 0.04)
    ctx.lineWidth = 1.2
    ctx.beginPath()
    ctx.moveTo(x1, y + drift)
    ctx.quadraticCurveTo(x1 + length * 0.5, y - 8 + drift, x1 + length, y + drift)
    ctx.stroke()
  }
  ctx.restore()
}

/* ── 元宵节：灯影水晕 ── */
function drawLanternFestival(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#C9985A'
  const secondary = props.colors[1] || '#E3D5C3'
  ctx.save()
  // 水面灯影
  for (let i = 0; i < 7; i++) {
    const seed = hashSource(`lantern_${i}`)
    const rnd = seeded(seed)
    const x = w * (0.12 + rnd() * 0.76)
    const y = h * (0.62 + rnd() * 0.22)
    const rx = 60 + rnd() * 90
    const ry = 18 + rnd() * 14
    const phase = rnd() * Math.PI * 2
    const breathe = 0.6 + Math.sin(time * 0.12 + phase) * 0.25
    strokeArc(ctx, x, y, rx * breathe, ry * breathe, 0, 0, Math.PI * 2, primary, 0.06 + rnd() * 0.04)
  }
  // 上升的暖光点
  for (let i = 0; i < 9; i++) {
    const seed = hashSource(`lantern_rise_${i}`)
    const rnd = seeded(seed)
    const progress = (time * (0.05 + rnd() * 0.04) + rnd() * 20) % 16
    const t = progress / 16
    const x = w * (0.1 + rnd() * 0.8) + Math.sin(time * 0.2 + i) * 12
    const y = h * (0.9 - t * 0.75)
    const alpha = (1 - t) * (0.15 + rnd() * 0.1)
    const radius = 2 + rnd() * 3
    ctx.fillStyle = rgba(i % 3 === 0 ? secondary : primary, alpha)
    ctx.beginPath()
    ctx.arc(x, y, radius, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

/* ── 端午节：水痕与粽叶脉 ── */
function drawDragonBoat(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#84A78B'
  const secondary = props.colors[1] || '#5C4A34'
  ctx.save()
  ctx.lineCap = 'round'
  // 斜向水痕
  for (let i = 0; i < 4; i++) {
    const seed = hashSource(`boat_wake_${i}`)
    const rnd = seeded(seed)
    const progress = (time * (0.08 + rnd() * 0.04) + i * 4) % 14
    const t = progress / 14
    const startX = -w * 0.2 + t * w * 1.4
    const y = h * (0.45 + rnd() * 0.35)
    const alpha = (1 - Math.abs(t - 0.5) * 2) * 0.1
    ctx.strokeStyle = rgba(primary, alpha)
    ctx.lineWidth = 2 + rnd() * 2
    ctx.beginPath()
    ctx.moveTo(startX, y)
    ctx.lineTo(startX + w * 0.18, y - h * 0.06)
    ctx.stroke()
  }
  // 底部叶脉
  for (let i = 0; i < 6; i++) {
    const x = w * (0.1 + i * 0.16)
    const y = h * (0.88 + Math.sin(i * 1.3) * 0.02)
    const drift = Math.sin(time * 0.1 + i) * 6
    strokeLine(ctx, x, y + drift, x + w * 0.12, y - h * 0.04 + drift, primary, 0.07, 1)
    for (let j = 1; j <= 3; j++) {
      const tx = x + j * w * 0.03
      strokeLine(ctx, tx, y + drift, tx + w * 0.03, y - h * 0.02 + drift, primary, 0.05, 0.8)
    }
  }
  ctx.restore()
}

/* ── 七夕：星河鹊桥 ── */
function drawQixi(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#B894B5'
  const secondary = props.colors[1] || '#E9D9E8'
  ctx.save()
  // 鹊桥拱形
  const bridgeY = h * 0.42
  ctx.strokeStyle = rgba(primary, 0.24)
  ctx.lineWidth = 2
  ctx.shadowColor = rgba(primary, 0.12)
  ctx.shadowBlur = 24
  ctx.beginPath()
  ctx.moveTo(w * 0.12, h * 0.72)
  ctx.bezierCurveTo(w * 0.32, bridgeY - h * 0.18, w * 0.68, bridgeY - h * 0.18, w * 0.88, h * 0.72)
  ctx.stroke()
  ctx.shadowBlur = 0
  // 桥两侧更亮
  ctx.strokeStyle = rgba(secondary, 0.16)
  ctx.beginPath()
  ctx.moveTo(w * 0.12, h * 0.72)
  ctx.quadraticCurveTo(w * 0.5, bridgeY - h * 0.22, w * 0.88, h * 0.72)
  ctx.stroke()
  ctx.restore()
}

function qixiParticles(ctx: CanvasRenderingContext2D, p: Particle, x: number, y: number, time: number, fade: number, w: number, h: number) {
  // 靠近桥的位置更密集
  const bridgeY = h * 0.42
  const t = x / w
  const bridgeHeight = bridgeY - h * 0.18 * 4 * t * (1 - t)
  const dist = Math.abs(y - bridgeHeight)
  const density = Math.max(0.2, 1 - dist / (h * 0.25))
  ctx.fillStyle = rgba(p.color, p.alpha * fade * density)
  ctx.beginPath()
  ctx.arc(x, y, p.size * (0.8 + p.depth * 0.5), 0, Math.PI * 2)
  ctx.fill()
}

/* ── 中秋节：月升潮涌 ── */
function drawMidAutumn(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#DAD0BA'
  const secondary = props.colors[1] || '#C99655'
  ctx.save()
  // 巨大月晕
  const moonX = w * 0.72
  const moonY = h * 0.22
  const moonRadius = Math.min(w, h) * 0.28
  const breathe = 0.92 + Math.sin(time * 0.08) * 0.08
  const g = ctx.createRadialGradient(moonX, moonY, 0, moonX, moonY, moonRadius * breathe)
  g.addColorStop(0, rgba(primary, 0.16))
  g.addColorStop(0.45, rgba(primary, 0.18))
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.beginPath()
  ctx.arc(moonX, moonY, moonRadius * breathe, 0, Math.PI * 2)
  ctx.fill()
  // 底部水纹
  for (let i = 0; i < 4; i++) {
    const progress = (time * 0.15 + i * 2.5) % 8
    const t = progress / 8
    const rx = (w * 0.15 + i * w * 0.08) * (1 + t * 0.6)
    const ry = rx * 0.18
    const alpha = (1 - t) * 0.09
    const y = h * (0.78 + i * 0.04)
    strokeArc(ctx, w * 0.5, y, rx, ry, 0, 0, Math.PI * 2, i % 2 ? secondary : primary, alpha)
  }
  ctx.restore()
}

/* ── 重阳节：远山菊落 ── */
function drawDoubleNinth(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#BF9258'
  const secondary = props.colors[1] || '#D8B06F'
  ctx.save()
  ctx.lineJoin = 'round'
  // 山脊线
  for (let ridge = 0; ridge < 4; ridge++) {
    const baseY = h * (0.62 + ridge * 0.08)
    const amp = 16 + ridge * 10
    ctx.strokeStyle = rgba(primary, 0.07 - ridge * 0.012)
    ctx.lineWidth = 2 - ridge * 0.3
    ctx.beginPath()
    ctx.moveTo(w * 0.06, baseY)
    for (let i = 0; i <= 8; i++) {
      const x = w * (0.06 + i * 0.12)
      const peak = baseY - Math.sin(i * 1.25 + ridge + time * 0.045) * amp - amp * 0.4
      ctx.lineTo(x, peak)
    }
    ctx.stroke()
  }
  // 飘落菊瓣
  for (let i = 0; i < 5; i++) {
    const seed = hashSource(`chrysanthemum_${i}`)
    const rnd = seeded(seed)
    const progress = (time * (0.04 + rnd() * 0.03) + rnd() * 20) % 18
    const t = progress / 18
    const x = w * (0.1 + rnd() * 0.8) + Math.sin(time * 0.3 + i) * 30
    const y = h * (0.05 + t * 0.75)
    const alpha = (1 - t) * 0.12
    const rotation = time * 0.2 + i
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rotation)
    ctx.fillStyle = rgba(i % 2 ? secondary : primary, alpha)
    ctx.beginPath()
    ctx.ellipse(0, 0, 10 + rnd() * 6, 4 + rnd() * 2, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
  }
  ctx.restore()
}

/* ── 元旦：黎明曙光 ── */
function drawNewYear(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#9AB2D9'
  const secondary = props.colors[1] || '#D5C8F1'
  ctx.save()
  // 扇形曙光
  const breathe = 0.7 + Math.sin(time * 0.11) * 0.2
  const g = ctx.createRadialGradient(0, h, 0, 0, h, w * 1.2)
  g.addColorStop(0, rgba(primary, 0.16 * breathe))
  g.addColorStop(0.35, rgba(secondary, 0.08 * breathe))
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.beginPath()
  ctx.moveTo(0, h)
  ctx.arc(0, h, w * 1.1, -Math.PI * 0.45, -Math.PI * 0.05)
  ctx.closePath()
  ctx.fill()
  // 星轨弧线
  for (let i = 0; i < 3; i++) {
    const cx = w * (0.2 + i * 0.3)
    const cy = h * (0.12 + i * 0.06)
    const r = w * (0.12 + i * 0.05)
    const start = time * 0.03 + i
    strokeArc(ctx, cx, cy, r, r * 0.3, -0.2, start, start + Math.PI * 0.8, secondary, 0.06 - i * 0.015, 1.2)
  }
  ctx.restore()
}

/* ── 劳动节：田垄与麦芒 ── */
function drawLaborDay(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#C69F5E'
  const secondary = props.colors[1] || '#8E98A8'
  ctx.save()
  // 透视田垄
  const breathe = 1 + Math.sin(time * 0.08) * 0.02
  for (let i = -4; i <= 4; i++) {
    const x = w * 0.5 + i * w * 0.08 * breathe
    ctx.strokeStyle = rgba(primary, 0.06 - Math.abs(i) * 0.008)
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(x, h * 0.65)
    ctx.lineTo(x + i * w * 0.04, h)
    ctx.stroke()
  }
  // 横向田埂
  for (let i = 0; i < 4; i++) {
    const y = h * (0.72 + i * 0.08)
    const drift = Math.sin(time * 0.06 + i) * 4
    strokeLine(ctx, w * 0.1, y + drift, w * 0.9, y + drift, primary, 0.05, 1)
  }
  ctx.restore()
}

function laborDayParticles(ctx: CanvasRenderingContext2D, p: Particle, x: number, y: number, time: number, fade: number, w: number, h: number) {
  // 麦芒形：只在下半屏
  if (y < h * 0.4) return
  ctx.strokeStyle = rgba(p.color, p.alpha * fade)
  ctx.lineWidth = 1
  const len = 8 + p.depth * 10
  const angle = -Math.PI * 0.45 + Math.sin(time * 0.5 + p.phase) * 0.15
  ctx.beginPath()
  ctx.moveTo(x, y)
  ctx.lineTo(x + Math.cos(angle) * len, y + Math.sin(angle) * len)
  ctx.stroke()
}

/* ── 国庆节：山河星火 ── */
function drawNationalDay(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#CFAE6B'
  const secondary = props.colors[1] || '#9B4E4A'
  ctx.save()
  // 山河轮廓
  for (let ridge = 0; ridge < 4; ridge++) {
    const baseY = h * (0.68 + ridge * 0.07)
    const amp = 20 + ridge * 12
    ctx.strokeStyle = rgba(ridge < 2 ? secondary : primary, 0.08 - ridge * 0.015)
    ctx.lineWidth = 2.5 - ridge * 0.4
    ctx.beginPath()
    ctx.moveTo(w * 0.04, baseY)
    for (let i = 0; i <= 10; i++) {
      const x = w * (0.04 + i * 0.1)
      const peak = baseY - Math.sin(i * 1.15 + ridge + time * 0.04) * amp - amp * 0.35
      ctx.lineTo(x, peak)
    }
    ctx.stroke()
  }
  ctx.restore()
}

function nationalDayParticles(ctx: CanvasRenderingContext2D, p: Particle, x: number, y: number, time: number, fade: number, w: number, h: number) {
  // 星火上升
  const py = (y - time * (0.3 + p.depth * 0.4) * 10) % h
  const realY = py < 0 ? py + h : py
  const alpha = (1 - realY / h) * p.alpha * fade
  ctx.fillStyle = rgba(p.color, alpha)
  ctx.beginPath()
  ctx.arc(x + parallaxX * p.depth * 6, realY, p.size * (1 + p.depth), 0, Math.PI * 2)
  ctx.fill()
}

/* ── 情人节：双星环绕 ── */
function drawValentine(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#C99AAE'
  const secondary = props.colors[1] || '#D9A9BC'
  ctx.save()
  // 中心光晕
  const cx = w * 0.5
  const cy = h * 0.45
  const breathe = 0.85 + Math.sin(time * 0.1) * 0.12
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.min(w, h) * 0.35 * breathe)
  g.addColorStop(0, rgba(primary, 0.18))
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.beginPath()
  ctx.arc(cx, cy, Math.min(w, h) * 0.35 * breathe, 0, Math.PI * 2)
  ctx.fill()
  // 双星轨道
  const orbitRx = Math.min(w, h) * 0.22
  const orbitRy = orbitRx * 0.45
  const angle1 = time * 0.08
  const angle2 = angle1 + Math.PI
  const x1 = cx + Math.cos(angle1) * orbitRx
  const y1 = cy + Math.sin(angle1) * orbitRy
  const x2 = cx + Math.cos(angle2) * orbitRx
  const y2 = cy + Math.sin(angle2) * orbitRy
  // 连线
  ctx.strokeStyle = rgba(secondary, 0.16)
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.quadraticCurveTo(cx, cy - orbitRy * 0.3, x2, y2)
  ctx.stroke()
  // 星点
  for (const [x, y, color] of [[x1, y1, primary], [x2, y2, secondary]] as [number, number, string][]) {
    const gg = ctx.createRadialGradient(x, y, 0, x, y, 18)
    gg.addColorStop(0, rgba(color, 0.32))
    gg.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = gg
    ctx.beginPath()
    ctx.arc(x, y, 18, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

/* ── 圣诞节：窗棂霜花与落雪 ── */
function drawChristmas(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#97B5AC'
  const secondary = props.colors[1] || '#D7E4EA'
  ctx.save()
  // 四角霜花
  const corners = [[0, 0], [w, 0], [0, h], [w, h]]
  corners.forEach(([cx, cy], idx) => {
    const branches = 6
    const length = Math.min(w, h) * 0.14
    ctx.strokeStyle = rgba(primary, 0.08 + Math.sin(time * 0.07 + idx) * 0.02)
    ctx.lineWidth = 1
    for (let i = 0; i < branches; i++) {
      const angle = (i / branches) * Math.PI * 2 + idx * 0.3
      const x2 = cx + Math.cos(angle) * length
      const y2 = cy + Math.sin(angle) * length
      strokeLine(ctx, cx, cy, x2, y2, primary, 0.07, 1)
      for (let j = 1; j <= 2; j++) {
        const t = j / 3
        const bx = cx + (x2 - cx) * t
        const by = cy + (y2 - cy) * t
        const twigAngle = angle + (j % 2 ? 0.5 : -0.5)
        strokeLine(ctx, bx, by, bx + Math.cos(twigAngle) * length * 0.25, by + Math.sin(twigAngle) * length * 0.25, primary, 0.05, 0.8)
      }
    }
  })
  ctx.restore()
}

function christmasParticles(ctx: CanvasRenderingContext2D, p: Particle, x: number, y: number, time: number, fade: number, w: number, h: number) {
  // 雪花飘落
  const speed = 0.2 + p.depth * 0.3
  const py = (y + time * speed * 10) % h
  const sway = Math.sin(time * 0.5 + p.phase) * 8
  ctx.fillStyle = rgba(p.color, p.alpha * fade)
  ctx.beginPath()
  ctx.arc(x + sway + parallaxX * p.depth * 4, py, p.size * (0.8 + p.depth * 0.6), 0, Math.PI * 2)
  ctx.fill()
}

/* ── 程序员节：数据流瀑布 ── */
function drawProgrammersDay(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#70C6A6'
  ctx.save()
  // 电路节点网格
  const cols = 5
  const rows = 4
  for (let i = 0; i <= cols; i++) {
    for (let j = 0; j <= rows; j++) {
      const x = w * (0.1 + i * 0.2)
      const y = h * (0.7 + j * 0.08)
      const pulse = 0.5 + Math.sin(time * 0.8 + i + j) * 0.5
      ctx.fillStyle = rgba(primary, 0.08 * pulse)
      ctx.beginPath()
      ctx.arc(x, y, 1.5 + pulse, 0, Math.PI * 2)
      ctx.fill()
    }
  }
  ctx.restore()
}

function programmersDayParticles(ctx: CanvasRenderingContext2D, p: Particle, x: number, y: number, time: number, fade: number, w: number, h: number) {
  // 数据流短线
  const len = 8 + p.depth * 14
  const speed = 1 + p.depth * 2
  const py = (y + time * speed * 8) % h
  const tilt = parallaxX * 0.1
  ctx.strokeStyle = rgba(p.color, p.alpha * fade)
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(x + parallaxX * p.depth * 3, py)
  ctx.lineTo(x + parallaxX * p.depth * 3 + tilt, py + len)
  ctx.stroke()
}

/* ── 周年庆：星图轨道 ── */
function drawAnniversary(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#AFA2D4'
  const secondary = props.colors[1] || '#DCE6FF'
  ctx.save()
  const cx = w * 0.5
  const cy = h * 0.45
  // 同心轨道
  for (let i = 0; i < 4; i++) {
    const r = 60 + i * 55
    const rx = r * (1.1 + i * 0.05)
    const ry = r * (0.7 - i * 0.05)
    const rot = -0.18 + Math.sin(time * 0.02 + i) * 0.03
    strokeArc(ctx, cx, cy, rx, ry, rot, 0, Math.PI * 2, i % 2 ? secondary : primary, 0.06 - i * 0.008, 1)
    // 轨道上的星点
    const angle = time * (0.06 - i * 0.01) + i * 1.5
    const sx = cx + Math.cos(angle) * rx
    const sy = cy + Math.sin(angle) * ry
    ctx.fillStyle = rgba(i % 2 ? secondary : primary, 0.25)
    ctx.beginPath()
    ctx.arc(sx, sy, 2 + i * 0.5, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

/* ═════════════════════════════════════════════════════════════════
 *  24 节气物候渲染器
 * ═════════════════════════════════════════════════════════════════ */

function drawSpringSprout(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#98B590'
  ctx.save()
  for (let i = 0; i < 7; i++) {
    const rootX = w * (0.15 + i * 0.11)
    const rootY = h * (0.86 + Math.sin(i) * 0.02)
    const grow = 0.92 + Math.sin(time * 0.14 + i) * 0.08
    const stem = h * (0.1 + (i % 3) * 0.025) * grow
    ctx.strokeStyle = rgba(primary, 0.24)
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(rootX, rootY)
    ctx.bezierCurveTo(rootX - 10, rootY - stem * 0.35, rootX + 8, rootY - stem * 0.65, rootX, rootY - stem)
    ctx.stroke()
    ctx.beginPath()
    ctx.ellipse(rootX - 9, rootY - stem * 0.55, 16, 5, -0.5, 0, Math.PI * 2)
    ctx.stroke()
    ctx.beginPath()
    ctx.ellipse(rootX + 11, rootY - stem * 0.72, 18, 5.5, 0.45, 0, Math.PI * 2)
    ctx.stroke()
  }
  ctx.restore()
}

function drawRainRipple(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#93AFC2'
  const secondary = props.colors[1] || '#E8F0F2'
  ctx.save()
  ctx.lineCap = 'round'
  // 雨线
  for (let i = 0; i < 16; i++) {
    const seed = hashSource(`rain_${i}`)
    const rnd = seeded(seed)
    const x = w * ((i * 0.071 + rnd() * 0.04 + 1) % 1)
    const y = h * (0.06 + (i % 6) * 0.14) + Math.sin(time * 0.12 + i) * 10
    strokeLine(ctx, x, y, x - 7, y + 38, primary, 0.07, 1)
  }
  // 涟漪
  for (let i = 0; i < 5; i++) {
    const x = w * (0.2 + i * 0.16)
    const y = h * (0.72 + Math.sin(time * 0.08 + i) * 0.04)
    const rx = (40 + i * 22) * (0.9 + Math.sin(time * 0.18 + i) * 0.1)
    const ry = rx * 0.28
    strokeArc(ctx, x, y, rx, ry, 0, 0, Math.PI * 2, secondary, 0.05)
  }
  ctx.restore()
}

function drawThunderCrack(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#A3B88A'
  ctx.save()
  // 稀疏闪电
  const flash = Math.sin(time * 0.25) > 0.92 ? 0.18 : 0.02
  if (flash > 0.05) {
    ctx.strokeStyle = rgba(primary, flash)
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(w * 0.65, h * 0.08)
    ctx.lineTo(w * 0.58, h * 0.28)
    ctx.lineTo(w * 0.62, h * 0.32)
    ctx.lineTo(w * 0.52, h * 0.55)
    ctx.stroke()
  }
  // 底部萌发芽点
  for (let i = 0; i < 9; i++) {
    const x = w * (0.12 + i * 0.1)
    const y = h * (0.88 + Math.sin(time * 0.3 + i) * 0.02)
    const pulse = 0.5 + Math.sin(time * 0.6 + i) * 0.5
    ctx.fillStyle = rgba(primary, 0.1 * pulse)
    ctx.beginPath()
    ctx.arc(x, y, 1.5 + pulse, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

function drawEquinoxBalance(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#B2BE9C'
  const secondary = props.colors[1] || '#F1F4E7'
  ctx.save()
  const cx = w * 0.5
  const cy = h * 0.42
  // 天平弧线
  ctx.strokeStyle = rgba(primary, 0.24)
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.arc(cx, cy, Math.min(w, h) * 0.22, Math.PI * 0.85, Math.PI * 0.15, true)
  ctx.stroke()
  // 左右对称光带
  const swing = Math.sin(time * 0.1) * h * 0.03
  strokeLine(ctx, w * 0.15, cy - h * 0.05 + swing, w * 0.35, cy + h * 0.02 + swing, primary, 0.07, 1.5)
  strokeLine(ctx, w * 0.65, cy + h * 0.02 - swing, w * 0.85, cy - h * 0.05 - swing, primary, 0.07, 1.5)
  // 中心垂线
  strokeLine(ctx, cx, cy - h * 0.08, cx, cy + h * 0.08, secondary, 0.06, 1)
  ctx.restore()
}

function drawClearRain(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#9FB7B0'
  ctx.save()
  ctx.lineCap = 'round'
  // 倾斜雨线
  for (let i = 0; i < 20; i++) {
    const seed = hashSource(`clear_rain_${i}`)
    const rnd = seeded(seed)
    const x = w * ((i * 0.06 + rnd() * 0.04 + 1) % 1)
    const y = h * (0.05 + (i % 7) * 0.13) + Math.sin(time * 0.1 + i) * 8
    strokeLine(ctx, x, y, x - 12, y + 46, primary, 0.075, 1)
  }
  // 底部淡烟
  const g = ctx.createLinearGradient(0, h * 0.75, 0, h)
  g.addColorStop(0, 'rgba(0,0,0,0)')
  g.addColorStop(1, rgba(primary, 0.18))
  ctx.fillStyle = g
  ctx.fillRect(0, h * 0.75, w, h * 0.25)
  ctx.restore()
}

function drawRiceRain(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#9BB68A'
  const secondary = props.colors[1] || '#DCE9CF'
  drawRainRipple(ctx, w, h, time)
  ctx.save()
  // 稻穗轮廓
  for (let i = 0; i < 5; i++) {
    const x = w * (0.18 + i * 0.16)
    const y = h * (0.82 + Math.sin(i) * 0.02)
    const height = h * (0.08 + (i % 3) * 0.015)
    ctx.strokeStyle = rgba(primary, 0.24)
    ctx.lineWidth = 1.2
    ctx.beginPath()
    ctx.moveTo(x, y)
    ctx.bezierCurveTo(x - 6, y - height * 0.35, x + 4, y - height * 0.7, x, y - height)
    ctx.stroke()
    const headY = y - height
    ctx.beginPath()
    ctx.moveTo(x, headY)
    ctx.bezierCurveTo(x + 8, headY + 6, x + 14, headY + 14, x + 24, headY + 22)
    ctx.stroke()
    for (let a = 0; a < 4; a++) {
      const t = a / 4
      const ax = x + 24 * t
      const ay = headY + 6 + 14 * t
      strokeLine(ctx, ax, ay, ax + 10, ay - 10 - a * 2, secondary, 0.05, 0.8)
    }
  }
  ctx.restore()
}

function drawTomatoVine(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#CDB676'
  ctx.save()
  for (let vine = 0; vine < 4; vine++) {
    const y = h * (0.62 + vine * 0.07)
    ctx.strokeStyle = rgba(primary, 0.20)
    ctx.lineWidth = 1.2
    ctx.beginPath()
    ctx.moveTo(w * 0.1, y)
    for (let i = 0; i <= 7; i++) {
      const x = w * (0.1 + i * 0.12)
      const wave = Math.sin(i * 1.2 + time * 0.12 + vine) * 14
      if (i === 0) ctx.moveTo(x, y + wave)
      else ctx.quadraticCurveTo(x - w * 0.05, y - wave, x, y + wave)
    }
    ctx.stroke()
    for (let leaf = 1; leaf < 7; leaf += 2) {
      const x = w * (0.1 + leaf * 0.12)
      const ly = y + Math.sin(leaf * 1.2 + time * 0.12 + vine) * 14
      ctx.beginPath()
      ctx.ellipse(x, ly, 22, 7, leaf % 4 ? 0.55 : -0.55, 0, Math.PI * 2)
      ctx.stroke()
    }
  }
  ctx.restore()
}

function drawRiceWheatFill(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#B9B77D'
  ctx.save()
  for (let row = 0; row < 3; row++) {
    const baseY = h * (0.78 + row * 0.05)
    for (let i = 0; i < 6; i++) {
      const x = w * (0.18 + i * 0.11 + row * 0.02)
      const height = h * (0.09 + (i % 3) * 0.018) * (0.96 + Math.sin(time * 0.1 + i + row) * 0.04)
      ctx.strokeStyle = rgba(primary, 0.24)
      ctx.lineWidth = 1.2
      ctx.beginPath()
      ctx.moveTo(x, baseY)
      ctx.bezierCurveTo(x - 6, baseY - height * 0.32, x + 4, baseY - height * 0.7, x, baseY - height)
      ctx.stroke()
      const headY = baseY - height
      ctx.beginPath()
      ctx.moveTo(x, headY)
      ctx.bezierCurveTo(x + 8, headY + 6, x + 16, headY + 16, x + 26, headY + 24)
      ctx.stroke()
      // 饱满籽粒
      for (let g = 0; g < 5; g++) {
        const t = g / 5
        const gx = x + 26 * t
        const gy = headY + 6 + 16 * t
        const pulse = 0.5 + Math.sin(time * 0.4 + g + i) * 0.3
        ctx.fillStyle = rgba(primary, 0.12 * pulse)
        ctx.beginPath()
        ctx.arc(gx, gy, 1.5, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }
  ctx.restore()
}

function drawWheatAwnSeed(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#C4A669'
  ctx.save()
  for (let row = 0; row < 3; row++) {
    const baseY = h * (0.76 + row * 0.05)
    for (let i = 0; i < 6; i++) {
      const x = w * (0.18 + i * 0.11 + row * 0.02)
      const height = h * (0.1 + (i % 3) * 0.02) * (0.96 + Math.sin(time * 0.1 + i + row) * 0.04)
      ctx.strokeStyle = rgba(primary, 0.16)
      ctx.lineWidth = 1.2
      ctx.beginPath()
      ctx.moveTo(x, baseY)
      ctx.bezierCurveTo(x - 6, baseY - height * 0.32, x + 4, baseY - height * 0.7, x, baseY - height)
      ctx.stroke()
      const headY = baseY - height
      ctx.beginPath()
      ctx.moveTo(x, headY)
      ctx.bezierCurveTo(x + 8, headY + 6, x + 16, headY + 16, x + 28, headY + 26)
      ctx.stroke()
      for (let a = 0; a < 5; a++) {
        const t = a / 5
        const ax = x + 28 * t
        const ay = headY + 6 + 16 * t
        strokeLine(ctx, ax, ay, ax + 14, ay - 14 - a * 2, primary, 0.07, 0.9)
      }
    }
  }
  ctx.restore()
}

function drawSolarArc(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#D0B06F'
  const secondary = props.colors[1] || '#F6E8C0'
  ctx.save()
  // 正午巨大弧形
  const cx = w * 0.5
  const cy = h * 0.92
  const r = Math.min(w, h) * 0.75
  const arcPhase = Math.sin(time * 0.06) * 0.04
  ctx.strokeStyle = rgba(primary, 0.24)
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.arc(cx, cy, r, Math.PI * (0.95 + arcPhase), Math.PI * (0.05 - arcPhase), true)
  ctx.stroke()
  // 放射光线
  for (let i = 0; i < 7; i++) {
    const angle = Math.PI * 0.85 + i * Math.PI * 0.05
    const x1 = cx + Math.cos(angle) * r * 0.85
    const y1 = cy + Math.sin(angle) * r * 0.85
    const x2 = cx + Math.cos(angle) * r * 1.05
    const y2 = cy + Math.sin(angle) * r * 1.05
    strokeLine(ctx, x1, y1, x2, y2, secondary, 0.06 + Math.sin(time * 0.12 + i) * 0.02, 1)
  }
  ctx.restore()
}

function drawHeatHaze(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#C99C68'
  ctx.save()
  for (let i = 0; i < 6; i++) {
    const y = h * (0.35 + i * 0.1)
    const phase = time * 0.12 + i
    ctx.strokeStyle = rgba(primary, 0.16)
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(w * 0.1, y)
    for (let x = 0; x <= 10; x++) {
      const px = w * (0.1 + x * 0.08)
      const py = y + Math.sin(x * 0.8 + phase) * (8 + i * 2)
      ctx.lineTo(px, py)
    }
    ctx.stroke()
  }
  ctx.restore()
}

function drawLotusHeat(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#C28A63'
  const secondary = props.colors[1] || '#E7B88D'
  ctx.save()
  // 荷叶轮廓
  for (let i = 0; i < 5; i++) {
    const x = w * (0.2 + i * 0.16)
    const y = h * (0.72 + Math.sin(i * 0.8) * 0.04)
    const rx = 34 + i * 6
    const ry = rx * 0.35
    ctx.strokeStyle = rgba(primary, 0.20)
    ctx.lineWidth = 1.2
    ctx.beginPath()
    ctx.ellipse(x, y, rx, ry, Math.sin(time * 0.05 + i) * 0.1, 0, Math.PI * 2)
    ctx.stroke()
    // 叶脉
    for (let j = -2; j <= 2; j++) {
      strokeLine(ctx, x, y, x + j * rx * 0.25, y - ry * 0.7, secondary, 0.05, 0.8)
    }
  }
  // 水波纹
  for (let i = 0; i < 4; i++) {
    const progress = (time * 0.18 + i * 2) % 6
    const t = progress / 6
    const rx = (w * 0.12 + i * w * 0.06) * (1 + t * 0.5)
    const ry = rx * 0.2
    strokeArc(ctx, w * 0.5, h * 0.85, rx, ry, 0, 0, Math.PI * 2, primary, (1 - t) * 0.06)
  }
  ctx.restore()
}

function drawAutumnLeaf(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#C59A70'
  const secondary = props.colors[1] || '#E5C09A'
  ctx.save()
  // 一枚落叶飘落
  const progress = (time * 0.07) % 16
  const t = progress / 16
  const x = w * (0.2 + t * 0.6) + Math.sin(time * 0.4) * 40
  const y = h * (-0.1 + t * 0.9)
  const rotation = time * 0.25
  const alpha = 0.12 + Math.sin(time * 0.2) * 0.04
  ctx.save()
  ctx.translate(x, y)
  ctx.rotate(rotation)
  ctx.fillStyle = rgba(primary, alpha)
  ctx.beginPath()
  ctx.ellipse(0, 0, 28, 12, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = rgba(secondary, alpha * 0.6)
  ctx.lineWidth = 0.8
  ctx.beginPath()
  ctx.moveTo(-22, 0)
  ctx.lineTo(22, 0)
  ctx.stroke()
  ctx.restore()
  ctx.restore()
}

function drawCoolingCloud(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#B98F73'
  ctx.save()
  for (let i = 0; i < 5; i++) {
    const y = h * (0.18 + i * 0.12)
    const phase = time * 0.06 + i
    ctx.strokeStyle = rgba(primary, 0.06 - i * 0.008)
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(w * 0.05, y)
    for (let x = 0; x <= 12; x++) {
      const px = w * (0.05 + x * 0.08)
      const py = y + Math.sin(x * 0.6 + phase) * (10 + i * 3)
      ctx.lineTo(px, py)
    }
    ctx.stroke()
  }
  ctx.restore()
}

function drawDewBeads(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#B8A890'
  const secondary = props.colors[1] || '#F1EBE0'
  ctx.save()
  // 草叶
  for (let i = 0; i < 9; i++) {
    const x = w * (0.12 + i * 0.1)
    const y = h * (0.82 + Math.sin(i) * 0.02)
    const height = h * (0.08 + (i % 3) * 0.02)
    ctx.strokeStyle = rgba(primary, 0.20)
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(x, y)
    ctx.bezierCurveTo(x - 4, y - height * 0.35, x + 3, y - height * 0.7, x, y - height)
    ctx.stroke()
    // 露珠
    const dewY = y - height
    const pulse = 0.5 + Math.sin(time * 0.5 + i) * 0.4
    ctx.fillStyle = rgba(secondary, 0.18 * pulse)
    ctx.beginPath()
    ctx.arc(x, dewY, 2 + pulse, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

function drawAutumnBalance(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#C7905E'
  ctx.save()
  // 对称山脊
  for (let ridge = 0; ridge < 3; ridge++) {
    const baseY = h * (0.58 + ridge * 0.08)
    const amp = 14 + ridge * 8
    ctx.strokeStyle = rgba(primary, 0.07 - ridge * 0.01)
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(w * 0.1, baseY)
    for (let i = 0; i <= 5; i++) {
      const x = w * (0.1 + i * 0.16)
      const peak = baseY - Math.sin(i * 1.1 + ridge + time * 0.05) * amp - amp * 0.35
      ctx.lineTo(x, peak)
    }
    ctx.stroke()
  }
  // 落叶
  for (let i = 0; i < 3; i++) {
    const progress = (time * 0.05 + i * 5) % 14
    const t = progress / 14
    const x = w * (0.15 + i * 0.3) + Math.sin(time * 0.3 + i) * 20
    const y = h * (0.05 + t * 0.65)
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(time * 0.2 + i)
    ctx.fillStyle = rgba(primary, (1 - t) * 0.1)
    ctx.beginPath()
    ctx.ellipse(0, 0, 16, 6, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
  }
  ctx.restore()
}

function drawColdDew(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#A88772'
  ctx.save()
  // 稀疏霜枝
  const originX = w * 0.75
  const originY = h * 0.18
  for (let branch = 0; branch < 6; branch++) {
    const angle = -1.8 + branch * 0.38 + Math.sin(time * 0.06 + branch) * 0.02
    const length = Math.min(w, h) * (0.18 + branch * 0.015)
    const endX = originX + Math.cos(angle) * length
    const endY = originY + Math.sin(angle) * length
    strokeLine(ctx, originX, originY, endX, endY, primary, 0.07, 1)
    for (let twig = 1; twig < 4; twig++) {
      const t = twig / 4
      const bx = originX + (endX - originX) * t
      const by = originY + (endY - originY) * t
      const twigAngle = angle + (twig % 2 ? 0.6 : -0.6)
      strokeLine(ctx, bx, by, bx + Math.cos(twigAngle) * length * 0.12, by + Math.sin(twigAngle) * length * 0.12, primary, 0.05, 0.8)
    }
  }
  // 露珠
  for (let i = 0; i < 8; i++) {
    const x = w * (0.2 + i * 0.09)
    const y = h * (0.75 + Math.sin(i * 1.2) * 0.04)
    const pulse = 0.5 + Math.sin(time * 0.4 + i) * 0.4
    ctx.fillStyle = rgba(primary, 0.12 * pulse)
    ctx.beginPath()
    ctx.arc(x, y, 1.8 + pulse * 0.8, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

function drawFrostVein(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#B28368'
  ctx.save()
  // 霜裂纹生长
  const corners = [[0, 0], [w, 0], [0, h], [w, h]]
  corners.forEach(([cx, cy], idx) => {
    const branches = 5
    const length = Math.min(w, h) * (0.18 + Math.sin(time * 0.05 + idx) * 0.02)
    for (let i = 0; i < branches; i++) {
      const angle = (i / branches) * Math.PI * 2 + idx * 0.5
      const x2 = cx + Math.cos(angle) * length
      const y2 = cy + Math.sin(angle) * length
      strokeLine(ctx, cx, cy, x2, y2, primary, 0.07 + Math.sin(time * 0.08 + idx + i) * 0.02, 1)
      for (let j = 1; j <= 2; j++) {
        const t = j / 3
        const bx = cx + (x2 - cx) * t
        const by = cy + (y2 - cy) * t
        const twigAngle = angle + (j % 2 ? 0.45 : -0.45)
        strokeLine(ctx, bx, by, bx + Math.cos(twigAngle) * length * 0.2, by + Math.sin(twigAngle) * length * 0.2, primary, 0.05, 0.8)
      }
    }
  })
  ctx.restore()
}

function drawWinterMist(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#9CAAC0'
  ctx.save()
  // 雾气光斑缓慢漂移
  for (let i = 0; i < 6; i++) {
    const seed = hashSource(`winter_mist_${i}`)
    const rnd = seeded(seed)
    const x = w * (0.1 + rnd() * 0.8) + Math.sin(time * 0.04 + i) * 30
    const y = h * (0.2 + rnd() * 0.6) + Math.cos(time * 0.03 + i) * 20
    const r = 80 + rnd() * 160
    const breathe = 0.7 + Math.sin(time * 0.08 + i) * 0.2
    const g = ctx.createRadialGradient(x, y, 0, x, y, r)
    g.addColorStop(0, rgba(primary, 0.06 * breathe))
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

function drawSnowMist(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#A8B7C8'
  ctx.save()
  ctx.lineCap = 'round'
  for (let i = 0; i < 18; i++) {
    const seed = hashSource(`snow_mist_${i}`)
    const rnd = seeded(seed)
    const progress = (time * (0.05 + rnd() * 0.04) + rnd() * 20) % 14
    const t = progress / 14
    const x = w * (0.05 + rnd() * 0.9) + Math.sin(time * 0.25 + i) * 15
    const y = h * (-0.05 + t * 1.1)
    const alpha = (1 - t) * 0.12
    strokeLine(ctx, x, y, x - 2, y + 10, primary, alpha, 1)
  }
  ctx.restore()
}

function drawSnowField(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#B7C2D1'
  ctx.save()
  // 雪原起伏
  for (let ridge = 0; ridge < 4; ridge++) {
    const baseY = h * (0.72 + ridge * 0.06)
    const amp = 12 + ridge * 8
    ctx.strokeStyle = rgba(primary, 0.08 - ridge * 0.012)
    ctx.lineWidth = 2 - ridge * 0.3
    ctx.beginPath()
    ctx.moveTo(w * 0.05, baseY)
    for (let i = 0; i <= 10; i++) {
      const x = w * (0.05 + i * 0.09)
      const peak = baseY - Math.sin(i * 0.9 + ridge + time * 0.04) * amp - amp * 0.4
      ctx.lineTo(x, peak)
    }
    ctx.stroke()
  }
  // 细雪
  drawSnowMist(ctx, w, h, time)
  ctx.restore()
}

function drawYangReturn(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#AEBBD1'
  const secondary = props.colors[1] || '#DCE5F3'
  ctx.save()
  // 底部暗色中微光回归
  const cx = w * 0.5
  const cy = h * 0.25
  const breathe = 0.75 + Math.sin(time * 0.07) * 0.15
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.min(w, h) * 0.4 * breathe)
  g.addColorStop(0, rgba(secondary, 0.12))
  g.addColorStop(0.6, rgba(primary, 0.16))
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.beginPath()
  ctx.arc(cx, cy, Math.min(w, h) * 0.4 * breathe, 0, Math.PI * 2)
  ctx.fill()
  // 底部地平线微光
  const horizon = ctx.createLinearGradient(0, h * 0.85, 0, h)
  horizon.addColorStop(0, 'rgba(0,0,0,0)')
  horizon.addColorStop(1, rgba(primary, 0.05 + Math.sin(time * 0.1) * 0.02))
  ctx.fillStyle = horizon
  ctx.fillRect(0, h * 0.85, w, h * 0.15)
  ctx.restore()
}

function drawColdRidge(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#9CAEC7'
  ctx.save()
  for (let ridge = 0; ridge < 5; ridge++) {
    const baseY = h * (0.55 + ridge * 0.07)
    const amp = 18 + ridge * 10
    ctx.strokeStyle = rgba(primary, 0.07 - ridge * 0.009)
    ctx.lineWidth = 2 - ridge * 0.25
    ctx.beginPath()
    ctx.moveTo(w * 0.04, baseY)
    for (let i = 0; i <= 10; i++) {
      const x = w * (0.04 + i * 0.1)
      const peak = baseY - Math.sin(i * 1.05 + ridge + time * 0.035) * amp - amp * 0.4
      ctx.lineTo(x, peak)
    }
    ctx.stroke()
  }
  ctx.restore()
}

function drawIceRing(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const primary = props.colors[0] || '#8FA3BD'
  ctx.save()
  const cx = w * 0.5
  const cy = h * 0.45
  for (let i = 0; i < 5; i++) {
    const r = 60 + i * 50
    const rx = r * (1 + i * 0.04)
    const ry = r * (0.85 - i * 0.03)
    const rot = Math.sin(time * 0.03 + i) * 0.05
    const alpha = 0.07 - i * 0.008
    strokeArc(ctx, cx, cy, rx, ry, rot, 0, Math.PI * 2, primary, alpha, 1)
    // 裂纹
    if (i < 3) {
      const angle = time * 0.1 + i * 1.2
      const x1 = cx + Math.cos(angle) * rx * 0.3
      const y1 = cy + Math.sin(angle) * ry * 0.3
      const x2 = cx + Math.cos(angle) * rx * 0.8
      const y2 = cy + Math.sin(angle) * ry * 0.8
      strokeLine(ctx, x1, y1, x2, y2, primary, alpha * 0.6, 0.8)
    }
  }
  ctx.restore()
}

/* ═════════════════════════════════════════════════════════════════
 *  兜底渲染器（基于关键词，保留原逻辑精华）
 * ═════════════════════════════════════════════════════════════════ */
function drawMeasuredGrid(ctx: CanvasRenderingContext2D, w: number, h: number, time: number, color: string) {
  const gap = 52
  const offset = Math.sin(time * 0.16) * 7
  ctx.strokeStyle = rgba(color, 0.26)
  ctx.lineWidth = 1
  ctx.shadowBlur = 14
  ctx.shadowColor = rgba(color, 0.18)
  for (let x = -gap; x < w + gap; x += gap) {
    ctx.beginPath()
    ctx.moveTo(x + offset, h * 0.14)
    ctx.lineTo(x + offset + 24, h * 0.86)
    ctx.stroke()
  }
  ctx.strokeStyle = rgba(color, 0.09)
  for (let y = h * 0.24; y < h * 0.84; y += 54) {
    ctx.beginPath()
    ctx.moveTo(w * 0.16, y + Math.sin(time * 0.12 + y) * 2)
    ctx.lineTo(w * 0.84, y + Math.sin(time * 0.12 + y) * 2)
    ctx.stroke()
  }
  ctx.shadowBlur = 0
}

function drawSilkThreads(ctx: CanvasRenderingContext2D, w: number, h: number, time: number, primary: string, secondary: string) {
  ctx.strokeStyle = rgba(secondary, 0.32)
  ctx.lineWidth = 1.2
  ctx.shadowColor = rgba(primary, 0.34)
  ctx.shadowBlur = 20
  ctx.beginPath()
  ctx.moveTo(w * 0.12, h * 0.28)
  ctx.bezierCurveTo(w * 0.34, h * 0.12 + Math.sin(time * 0.08) * 8, w * 0.62, h * 0.54, w * 0.88, h * 0.3)
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(w * 0.18, h * 0.78)
  ctx.bezierCurveTo(w * 0.38, h * 0.58, w * 0.58, h * 0.94 + Math.cos(time * 0.07) * 10, w * 0.82, h * 0.72)
  ctx.stroke()
  ctx.shadowBlur = 0
}

function drawFallbackMotif(ctx: CanvasRenderingContext2D, w: number, h: number, time: number) {
  const type = String(props.type)
  const primary = props.colors[0] || '#D8E2FF'
  const secondary = props.colors[1] || primary
  ctx.save()
  ctx.lineWidth = 1
  ctx.shadowColor = rgba(primary, 0.24)
  ctx.shadowBlur = 16
  if (hasAny(type, ['code', 'gears', 'lattice'])) {
    drawMeasuredGrid(ctx, w, h, time, primary)
  } else {
    drawSilkThreads(ctx, w, h, time, primary, secondary)
  }
  ctx.restore()
}

/* ═════════════════════════════════════════════════════════════════
 *  渲染器路由表
 * ═════════════════════════════════════════════════════════════════ */
const FESTIVAL_RENDERERS: Record<string, FestivalRenderer> = {
  spring_festival: { name: '春节·星火余烬', motif: drawSpringFestival },
  lantern_festival: { name: '元宵·灯影水晕', motif: drawLanternFestival },
  dragon_boat: { name: '端午·水痕粽脉', motif: drawDragonBoat },
  qixi: { name: '七夕·星河鹊桥', motif: drawQixi, particles: qixiParticles },
  mid_autumn: { name: '中秋·月升潮涌', motif: drawMidAutumn },
  double_ninth: { name: '重阳·远山菊落', motif: drawDoubleNinth },
  new_year: { name: '元旦·黎明曙光', motif: drawNewYear },
  labor_day: { name: '劳动节·田垄麦芒', motif: drawLaborDay, particles: laborDayParticles },
  national_day: { name: '国庆·山河星火', motif: drawNationalDay, particles: nationalDayParticles },
  valentine: { name: '情人节·双星环绕', motif: drawValentine },
  christmas: { name: '圣诞·窗棂霜雪', motif: drawChristmas, particles: christmasParticles },
  programmers_day: { name: '程序员节·数据流瀑', motif: drawProgrammersDay, particles: programmersDayParticles },
  anniversary: { name: '周年庆·星图轨道', motif: drawAnniversary },
  // 四季基础主题（24 节气按春夏秋冬复用）
  li_chun: { name: '立春·嫩芽破土', motif: drawSpringSprout },
  xia_zhi: { name: '夏至·日轨最高', motif: drawSolarArc },
  qiu_fen: { name: '秋分·昼夜再均', motif: drawAutumnBalance },
  dong_zhi: { name: '冬至·一阳来复', motif: drawYangReturn },
  // 24 节气 phenology
  'spring-sprout': { name: '立春·嫩芽破土', motif: drawSpringSprout },
  'rain-ripple': { name: '雨水·雨滴落湖', motif: drawRainRipple },
  'thunder-crack': { name: '惊蛰·春雷裂空', motif: drawThunderCrack },
  'equinox-balance': { name: '春分·昼夜均分', motif: drawEquinoxBalance },
  'clear-rain': { name: '清明·斜雨纷纷', motif: drawClearRain },
  'rice-rain': { name: '谷雨·稻雨润谷', motif: drawRiceRain },
  'tomato-vine': { name: '立夏·藤蔓延展', motif: drawTomatoVine },
  'rice-wheat-fill': { name: '小满·麦粒灌浆', motif: drawRiceWheatFill },
  'wheat-awn-seed': { name: '芒种·麦芒初露', motif: drawWheatAwnSeed },
  'solar-arc': { name: '夏至·日轨最高', motif: drawSolarArc },
  'heat-haze': { name: '小暑·暑气蒸腾', motif: drawHeatHaze },
  'lotus-heat': { name: '大暑·荷风送香', motif: drawLotusHeat },
  'autumn-leaf': { name: '立秋·一叶知秋', motif: drawAutumnLeaf },
  'cooling-cloud': { name: '处暑·暑退云轻', motif: drawCoolingCloud },
  'dew-beads': { name: '白露·草尖露珠', motif: drawDewBeads },
  'autumn-balance': { name: '秋分·昼夜再均', motif: drawAutumnBalance },
  'cold-dew': { name: '寒露·寒露凝霜', motif: drawColdDew },
  'frost-vein': { name: '霜降·霜裂纹', motif: drawFrostVein },
  'winter-mist': { name: '立冬·冬雾弥漫', motif: drawWinterMist },
  'snow-mist': { name: '小雪·微雪如烟', motif: drawSnowMist },
  'snow-field': { name: '大雪·雪原起伏', motif: drawSnowField },
  'yang-return': { name: '冬至·一阳来复', motif: drawYangReturn },
  'cold-ridge': { name: '小寒·寒山脊', motif: drawColdRidge },
  'ice-ring': { name: '大寒·冰环', motif: drawIceRing },
}

const PHENOLOGY_ALIASES: Record<string, string> = {
  'spring-scroll': 'spring_festival',
  'lantern-orbit': 'lantern_festival',
  'reed-river': 'dragon_boat',
  'star-bridge': 'qixi',
  'moon-tide': 'mid_autumn',
  'chrysanthemum-slope': 'double_ninth',
  'dawn-ring': 'new_year',
  'grain-grid': 'labor_day',
  'mountain-dawn': 'national_day',
  'silk-knot': 'valentine',
  'winter-window': 'christmas',
  'code-lattice': 'programmers_day',
  'nebula-orbit': 'anniversary',
}

function resolveRenderer(type: string): FestivalRenderer {
  const direct = FESTIVAL_RENDERERS[type]
  if (direct) return direct
  const aliased = PHENOLOGY_ALIASES[type]
  if (aliased) return FESTIVAL_RENDERERS[aliased]
  // 尝试按 phenology 关键词匹配
  for (const key of Object.keys(FESTIVAL_RENDERERS)) {
    if (type.includes(key)) return FESTIVAL_RENDERERS[key]
  }
  return { name: 'fallback', motif: drawFallbackMotif }
}

/* ═════════════════════════════════════════════════════════════════
 *  主渲染循环
 * ═════════════════════════════════════════════════════════════════ */
function renderFrame(ctx: CanvasRenderingContext2D) {
  const w = window.innerWidth
  const h = window.innerHeight
  const rawTime = (performance.now() - startedAt) / 1000
  const time = rawTime * 1.4 // 整体提速，让动效更易被感知

  ctx.clearRect(0, 0, w, h)

  // 物理惯性视差
  parallaxX += (targetParallaxX - parallaxX) * 0.055
  parallaxY += (targetParallaxY - parallaxY) * 0.055

  // Layer 3: 环境基底
  drawEnvironmentWash(ctx, w, h, time)

  // Layer 2: 环境散景
  drawAmbientBokeh(ctx, w, h, time)

  // 节日/节气意象层
  const renderer = resolveRenderer(String(props.type))
  ctx.globalCompositeOperation = 'screen'
  ctx.save()
  ctx.globalAlpha = 1.35
  renderer.motif(ctx, w, h, time)
  ctx.restore()

  // Layer 1: 微光粒子
  ctx.save()
  ctx.globalAlpha = 1.25
  if (renderer.particles) {
    updateAndDrawParticles(ctx, w, h, time, renderer.particles)
  } else {
    updateAndDrawParticles(ctx, w, h, time)
  }
  ctx.restore()

  ctx.globalCompositeOperation = 'source-over'
}

function handleResize() {
  const canvas = canvasRef.value
  if (!canvas) return
  resizeCanvas(canvas)
  initAmbientField()
  initParticles(window.innerWidth, window.innerHeight)
}

function handlePointerMove(event: PointerEvent) {
  const w = window.innerWidth || 1
  const h = window.innerHeight || 1
  targetParallaxX = (event.clientX / w - 0.5) * 0.8
  targetParallaxY = (event.clientY / h - 0.5) * 0.8
}

function startAnimation() {
  const canvas = canvasRef.value
  if (!canvas) return
  resizeCanvas(canvas)
  initAmbientField()
  initParticles(window.innerWidth, window.innerHeight)
  startedAt = performance.now()

  const ctx = getCtx()
  if (!ctx) return

  if (reducedMotion) {
    // 减少动画模式下仍渲染一帧静态环境，避免背景完全空白
    renderFrame(ctx)
    return
  }

  const loop = () => {
    renderFrame(ctx)
    rafId = requestAnimationFrame(loop)
  }

  loop()
}

onMounted(() => {
  startAnimation()
  window.addEventListener('resize', handleResize)
  window.addEventListener('pointermove', handlePointerMove, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('pointermove', handlePointerMove)
  if (rafId) cancelAnimationFrame(rafId)
})
</script>

<template>
  <canvas
    ref="canvasRef"
    class="festival-effect-canvas"
    aria-hidden="true"
  />
</template>

<style scoped>
.festival-effect-canvas {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: 0.92;
  filter: blur(2px) saturate(1.12);
  transform: scale(1.06);
  transform-origin: center;
  animation: canvasBreathe 7s cubic-bezier(0.37, 0, 0.63, 1) infinite;
}

@keyframes canvasBreathe {
  0%, 100% { opacity: 0.88; transform: scale(1.06); }
  50% { opacity: 0.98; transform: scale(1.07); }
}

@media (prefers-reduced-motion: reduce) {
  .festival-effect-canvas {
    animation: none;
  }
}
</style>
