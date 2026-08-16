<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const props = withDefaults(defineProps<{
  variant?: 'deep' | 'dawn'
}>(), {
  variant: 'deep',
})

const canvasRef = ref<HTMLCanvasElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)

let animationId: number | null = null
let shootTimer: ReturnType<typeof setTimeout> | null = null
let flareTimer: ReturnType<typeof setTimeout> | null = null
let motionQuery: MediaQueryList | null = null

const emit = defineEmits<{
  tick: [time: number]
}>()

onMounted(() => {
  const canvasEl = canvasRef.value
  const containerEl = containerRef.value
  if (!canvasEl || !containerEl) return

  const ctx2d = canvasEl.getContext('2d')
  if (!ctx2d) return

  const canvas = canvasEl
  const container = containerEl
  const ctx = ctx2d

  const isMobile = window.innerWidth < 768
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  let reducedMotion = motionQuery.matches

  const STAR_COUNT = isMobile ? 48 : 96
  const PARTICLE_COUNT = isMobile ? 12 : 24
  const CONNECTION_DIST = 120
  const FLARE_COUNT = isMobile ? 3 : 6

  let w = 0
  let h = 0
  let dpr = 1
  let time = 0
  const palette = props.variant === 'dawn'
    ? {
        star: '51, 90, 151',
        particle: '72, 122, 196',
        connection: '103, 145, 205',
        shooting: '69, 111, 178',
      }
    : {
        star: '211, 230, 255',
        particle: '137, 184, 255',
        connection: '122, 173, 255',
        shooting: '190, 220, 255',
      }

  interface Star {
    x: number
    y: number
    r: number
    alpha: number
    speed: number
    dir: number
    flare: number
    targetFlare: number
  }

  interface Particle {
    x: number
    y: number
    vx: number
    vy: number
    r: number
  }

  interface ShootingStar {
    x: number
    y: number
    vx: number
    vy: number
    life: number
    tail: { x: number; y: number }[]
  }

  const stars: Star[] = []
  const particles: Particle[] = []
  let shootingStar: ShootingStar | null = null
  const mouse = { x: -1000, y: -1000 }

  function resize() {
    const rect = container.getBoundingClientRect()
    dpr = window.devicePixelRatio || 1
    w = rect.width
    h = rect.height
    canvas.width = w * dpr
    canvas.height = h * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  resize()

  function initStars() {
    stars.length = 0
    for (let i = 0; i < STAR_COUNT; i++) {
      stars.push({
        x: Math.random() * w,
        y: Math.random() * h,
        r: Math.random() * 1.5 + 0.3,
        alpha: Math.random(),
        speed: Math.random() * 0.003 + 0.0015,
        dir: Math.random() > 0.5 ? 1 : -1,
        flare: 0,
        targetFlare: 0,
      })
    }
  }

  function rotateStarbursts() {
    stars.forEach((star) => {
      star.targetFlare = 0
    })

    const candidates = stars
      .filter((star) => star.r >= 0.75 && star.alpha >= 0.45)
      .sort(() => Math.random() - 0.5)

    candidates.slice(0, FLARE_COUNT).forEach((star) => {
      star.targetFlare = Math.random() * 3 + 3
    })
  }

  function scheduleStarburstRotation() {
    if (reducedMotion) return
    if (flareTimer) clearTimeout(flareTimer)

    flareTimer = setTimeout(() => {
      rotateStarbursts()
      scheduleStarburstRotation()
    }, 18000 + Math.random() * 12000)
  }

  function initParticles() {
    particles.length = 0
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      particles.push({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
        r: Math.random() * 1.4 + 0.6,
      })
    }
  }

  initStars()
  initParticles()
  rotateStarbursts()
  scheduleStarburstRotation()

  function onMouseMove(e: MouseEvent) {
    const rect = container.getBoundingClientRect()
    mouse.x = e.clientX - rect.left
    mouse.y = e.clientY - rect.top
  }

  function onMouseLeave() {
    mouse.x = -1000
    mouse.y = -1000
  }

  container.addEventListener('mousemove', onMouseMove)
  container.addEventListener('mouseleave', onMouseLeave)
  window.addEventListener('resize', resize)

  function spawnShootingStar() {
    if (reducedMotion) return
    if (!shootingStar && w > 0 && h > 0) {
      shootingStar = {
        x: Math.random() * w * 0.5,
        y: Math.random() * h * 0.3,
        vx: 2 + Math.random() * 1.4,
        vy: 0.8 + Math.random() * 0.9,
        life: 1,
        tail: [],
      }
    }
    shootTimer = setTimeout(spawnShootingStar, 9000 + Math.random() * 8000)
  }
  spawnShootingStar()

  let isPaused = false

  function onVisibilityChange() {
    isPaused = document.hidden
    if (isPaused && animationId) {
      cancelAnimationFrame(animationId)
      animationId = null
      return
    }
    if (!isPaused && !animationId) {
      animate()
    }
  }
  document.addEventListener('visibilitychange', onVisibilityChange)

  function onMotionPreferenceChange(event: MediaQueryListEvent) {
    reducedMotion = event.matches
    if (reducedMotion) {
      if (animationId) cancelAnimationFrame(animationId)
      animationId = null
      if (shootTimer) clearTimeout(shootTimer)
      shootTimer = null
      if (flareTimer) clearTimeout(flareTimer)
      flareTimer = null
      shootingStar = null
      animate()
      return
    }

    spawnShootingStar()
    rotateStarbursts()
    scheduleStarburstRotation()
    if (!isPaused && !animationId) animate()
  }
  motionQuery.addEventListener('change', onMotionPreferenceChange)

  function animate() {
    if (isPaused) {
      animationId = null
      return
    }

    if (!reducedMotion) time += 0.016
    emit('tick', time)

    ctx.clearRect(0, 0, w, h)

    // 1. 呼吸星星
    stars.forEach((s) => {
      if (!reducedMotion) {
        s.alpha += s.speed * s.dir
        if (s.alpha > 1 || s.alpha < 0.2) s.dir *= -1
        s.flare += (s.targetFlare - s.flare) * 0.007
      }
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(${palette.star}, ${s.alpha * 0.72})`
      ctx.fill()

      if (s.flare > 0.08) {
        const flareLength = s.flare * (0.45 + s.alpha * 0.35)
        ctx.beginPath()
        ctx.moveTo(s.x - flareLength, s.y)
        ctx.lineTo(s.x + flareLength, s.y)
        ctx.moveTo(s.x, s.y - flareLength)
        ctx.lineTo(s.x, s.y + flareLength)
        ctx.strokeStyle = `rgba(${palette.star}, ${s.alpha * 0.5})`
        ctx.lineWidth = 0.65
        ctx.stroke()

        const halo = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, flareLength * 1.8)
        halo.addColorStop(0, `rgba(${palette.star}, ${s.alpha * 0.18})`)
        halo.addColorStop(1, `rgba(${palette.star}, 0)`)
        ctx.fillStyle = halo
        ctx.fillRect(s.x - flareLength * 1.8, s.y - flareLength * 1.8, flareLength * 3.6, flareLength * 3.6)
      }
    })

    // 2. 网络粒子 + 鼠标引力
    particles.forEach((p, i) => {
      if (!reducedMotion) {
        p.x += p.vx
        p.y += p.vy
        if (p.x < 0 || p.x > w) p.vx *= -1
        if (p.y < 0 || p.y > h) p.vy *= -1
      }

      const dx = mouse.x - p.x
      const dy = mouse.y - p.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (!reducedMotion && dist < 150) {
        p.vx += dx * 0.0003
        p.vy += dy * 0.0003
      }
      p.vx *= 0.99
      p.vy *= 0.99

      ctx.beginPath()
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(${palette.particle}, 0.42)`
      ctx.fill()

      for (let j = i + 1; j < particles.length; j++) {
        const p2 = particles[j]
        const d = Math.sqrt((p.x - p2.x) ** 2 + (p.y - p2.y) ** 2)
        if (d < CONNECTION_DIST) {
          ctx.beginPath()
          ctx.moveTo(p.x, p.y)
          ctx.lineTo(p2.x, p2.y)
          ctx.strokeStyle = `rgba(${palette.connection}, ${0.13 * (1 - d / CONNECTION_DIST)})`
          ctx.lineWidth = 0.7
          ctx.stroke()
        }
      }
    })

    // 3. 流星
    if (!reducedMotion && shootingStar) {
      shootingStar.x += shootingStar.vx
      shootingStar.y += shootingStar.vy
      shootingStar.life -= 0.015
      shootingStar.tail.push({ x: shootingStar.x, y: shootingStar.y })
      if (shootingStar.tail.length > 15) shootingStar.tail.shift()

      ctx.beginPath()
      for (let i = 0; i < shootingStar.tail.length - 1; i++) {
        const t = shootingStar.tail[i]
        const t2 = shootingStar.tail[i + 1]
        ctx.moveTo(t.x, t.y)
        ctx.lineTo(t2.x, t2.y)
      }
      ctx.strokeStyle = `rgba(${palette.shooting}, ${shootingStar.life * 0.55})`
      ctx.lineWidth = 1.5
      ctx.stroke()

      ctx.beginPath()
      ctx.arc(shootingStar.x, shootingStar.y, 2, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(${palette.star}, ${shootingStar.life})`
      ctx.shadowBlur = 9
      ctx.shadowColor = props.variant === 'dawn' ? '#6f9dde' : '#8fb7ff'
      ctx.fill()
      ctx.shadowBlur = 0

      if (shootingStar.life <= 0) shootingStar = null
    }

    animationId = reducedMotion ? null : requestAnimationFrame(animate)
  }

  animate()

  onUnmounted(() => {
    if (animationId) cancelAnimationFrame(animationId)
    animationId = null
    if (shootTimer) clearTimeout(shootTimer)
    if (flareTimer) clearTimeout(flareTimer)
    flareTimer = null
    container.removeEventListener('mousemove', onMouseMove)
    container.removeEventListener('mouseleave', onMouseLeave)
    window.removeEventListener('resize', resize)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    motionQuery?.removeEventListener('change', onMotionPreferenceChange)
  })
})

onUnmounted(() => {
  if (animationId) {
    cancelAnimationFrame(animationId)
    animationId = null
  }
  if (shootTimer) {
    clearTimeout(shootTimer)
    shootTimer = null
  }
  if (flareTimer) {
    clearTimeout(flareTimer)
    flareTimer = null
  }
})
</script>

<template>
  <div ref="containerRef" class="starfield-container" :class="`starfield-container--${props.variant}`">
    <canvas ref="canvasRef" class="starfield-canvas" />
  </div>
</template>

<style scoped>
.starfield-container {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  overflow: hidden;
  isolation: isolate;
  background:
    radial-gradient(circle at 18% 18%, rgba(136, 180, 255, 0.28), transparent 30%),
    radial-gradient(circle at 82% 82%, rgba(124, 142, 236, 0.18), transparent 34%),
    linear-gradient(145deg, #163662 0%, #24518a 48%, #4776ac 100%);
}

.starfield-container::before {
  content: '';
  position: absolute;
  inset: -18%;
  z-index: 0;
  background:
    radial-gradient(ellipse at 28% 26%, rgba(146, 190, 255, 0.22), transparent 35%),
    radial-gradient(ellipse at 76% 70%, rgba(143, 151, 244, 0.14), transparent 38%);
  filter: blur(28px);
  opacity: 0.72;
  animation: aurora-drift 28s cubic-bezier(0.45, 0, 0.55, 1) infinite alternate;
}

.starfield-container--dawn {
  background:
    radial-gradient(circle at 14% 20%, rgba(255, 255, 255, 0.72), transparent 30%),
    radial-gradient(circle at 88% 76%, rgba(245, 143, 157, 0.16), transparent 34%),
    linear-gradient(132deg, #e8f4ff 0%, #eef5ff 49%, #fae9ec 100%);
}

.starfield-container--dawn::before {
  background:
    radial-gradient(ellipse at 25% 30%, rgba(112, 170, 255, 0.2), transparent 36%),
    radial-gradient(ellipse at 76% 68%, rgba(243, 130, 147, 0.14), transparent 40%);
  filter: blur(34px);
  opacity: 0.68;
  animation-duration: 44s;
}

.starfield-canvas {
  position: relative;
  z-index: 1;
  display: block;
  width: 100%;
  height: 100%;
}

@keyframes aurora-drift {
  from { transform: translate3d(-2%, -1%, 0) scale(1); }
  to { transform: translate3d(2%, 1%, 0) scale(1.04); }
}

@media (prefers-reduced-motion: reduce) {
  .starfield-container::before {
    animation: none;
  }
}
</style>
