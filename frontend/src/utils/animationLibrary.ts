/**
 * OmicHub 动态背景动画引擎 v5
 * 支持 19 种动画模式，Hero 和登录页共用，每次加载随机命中一种（互斥）。
 * 使用方式：initHeroAnimation(canvas) 或 initLoginAnimation(canvas)
 *
 * v5 变更（相对 v4 的 10 模式）：
 *  - 模式扩充至 20：新增 dna / constellation / flowfield / shards / hexgrid /
 *    waves / gravity / datastream / aurora / nebula，贴合「星尘 + 基因组学」语义。
 *  - 观感强化：所有模式之上叠加一层缓慢漂移的「极光氛围层」(drawAtmosphere)，
 *    并统一用 glowDot 多停径向渐变绘制发光点，粒子更通透、更亮、更有体积感。
 *  - 可访问性：尊重 prefers-reduced-motion，命中时只绘制一帧静态画面，不启动 rAF 循环。
 *
 * 注意：此文件按原生 JS 编写，通过 Vite 直接引入即可挂载到 window。
 * 装饰层契约见 ARCHITECTURE_DESIN/fontend.md §31 / §32：canvas 必须保持
 * position:absolute + pointer-events:none + aria-hidden，z-index:0，绝不可被父级通配选择器命中。
 */

export {}

;(function () {
  // ========== 导出接口 ==========
  ;(window as any).initHeroAnimation = function (canvas: HTMLCanvasElement) {
    return initAnimation(canvas, 'hero')
  }

  ;(window as any).initLoginAnimation = function (canvas: HTMLCanvasElement) {
    return initAnimation(canvas, 'login')
  }

  // ========== 核心引擎 ==========
  function initAnimation(
    canvas: HTMLCanvasElement,
    context: 'hero' | 'login',
  ) {
    const maybeCtx = canvas.getContext('2d')
    if (!maybeCtx) return () => {}
    const ctx = maybeCtx

    let w = 0
    let h = 0
    let dpr = 1
    let animationId: number | null = null

    const CONFIG = {
      // hero 背景是抢眼的蓝紫渐变：动画要"压得住被看见"，但又必须**克制**——
      // 频率/速度过高或透明度过满都会喧宾夺主、抢标题与按钮。故速度取舒缓档、不透明度留余量。
      hero: { opacity: 0.82, density: 5000, speed: 0.8, glow: true },
      login: { opacity: 0.3, density: 10000, speed: 0.6, glow: true },
    }[context]

    // 减少动态：尊重系统偏好，装饰循环不启动，仅留一帧静态画面（见 §6.3 / §32.4）。
    const reduceMotion =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches

    function resize() {
      const rect = canvas.parentElement?.getBoundingClientRect()
      if (!rect) return
      dpr = window.devicePixelRatio || 1
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
      w = rect.width
      h = rect.height
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    resize()
    window.addEventListener('resize', resize)

    // 19 种模式，运行时随机命中一种（互斥运行，详见 §32.2 目录）。
    const MODES = [
      'particles',
      'stars',
      'aura',
      'orbitals',
      'meteor',
      'ripple',
      'firefly',
      'matrix',
      'bubbles',
      'dna',
      'constellation',
      'flowfield',
      'shards',
      'hexgrid',
      'waves',
      'gravity',
      'datastream',
      'aurora',
      'nebula',
    ]
    const currentMode = MODES[Math.floor(Math.random() * MODES.length)]
    console.log(`[Animation:${context}] Mode:`, currentMode)

    function random(min: number, max: number) {
      return Math.random() * (max - min) + min
    }

    // ---------- 共享绘制助手 ----------
    // 多停径向渐变发光点：内核亮、外圈柔，比 v4 的单色实心圆更有体积与通透感。
    function glowDot(
      x: number,
      y: number,
      r: number,
      alpha: number,
      core = '225, 230, 255',
      halo = '170, 185, 255',
    ) {
      if (alpha <= 0.001 || r <= 0) return
      const g = ctx.createRadialGradient(x, y, 0, x, y, r)
      g.addColorStop(0, `rgba(${core}, ${Math.min(1, alpha * 1.15)})`)
      g.addColorStop(0.35, `rgba(${core}, ${alpha * 0.55})`)
      g.addColorStop(1, `rgba(${halo}, 0)`)
      ctx.fillStyle = g
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
    }

    // 极光氛围层：2~3 团品牌色（蓝/靛/紫/青）大半径径向渐变，叠加模式缓慢漂移，
    // 给渐变底色注入"活的呼吸"。所有模式共享，置于模式绘制之下。save/restore 隔离合成模式。
    let atmosphere: any = null
    function ensureAtmosphere() {
      if (atmosphere) return atmosphere
      const palette = [
        '120, 160, 255', // 蓝
        '150, 120, 240', // 靛紫
        '110, 200, 230', // 青
        '180, 130, 235', // 紫
      ]
      const blobs = []
      const n = 3
      for (let i = 0; i < n; i++) {
        blobs.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.1 * CONFIG.speed,
          vy: (Math.random() - 0.5) * 0.1 * CONFIG.speed,
          r: Math.max(w, h) * (0.32 + Math.random() * 0.22),
          color: palette[i % palette.length],
          phase: Math.random() * Math.PI * 2,
          pulse: 0.0022 + Math.random() * 0.0022,
        })
      }
      atmosphere = { blobs }
      return atmosphere
    }
    function drawAtmosphere() {
      const a = ensureAtmosphere()
      ctx.save()
      ctx.globalCompositeOperation = 'lighter'
      a.blobs.forEach((b: any) => {
        b.x += b.vx
        b.y += b.vy
        b.phase += b.pulse
        if (b.x < -b.r) b.x = w + b.r
        if (b.x > w + b.r) b.x = -b.r
        if (b.y < -b.r) b.y = h + b.r
        if (b.y > h + b.r) b.y = -b.r
        const breathe = 0.5 + 0.5 * Math.sin(b.phase)
        const peak = (context === 'hero' ? 0.072 : 0.03) * breathe * CONFIG.opacity
        const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r)
        g.addColorStop(0, `rgba(${b.color}, ${peak})`)
        g.addColorStop(1, `rgba(${b.color}, 0)`)
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2)
        ctx.fill()
      })
      ctx.restore()
    }

    // ========== A. 粒子网络 ==========
    function initParticles() {
      const particles = []
      const count = Math.floor((w * h) / CONFIG.density)
      for (let i = 0; i < count; i++) {
        particles.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.4 * CONFIG.speed,
          vy: (Math.random() - 0.5) * 0.4 * CONFIG.speed,
          size: 1.5 + Math.random() * 2.5,
          opacity: 0.15 + Math.random() * 0.35,
          pulse: Math.random() * Math.PI * 2,
          pulseSpeed: (0.012 + Math.random() * 0.018) * CONFIG.speed,
        })
      }
      return { particles }
    }

    function drawParticles(state: any) {
      ctx.clearRect(0, 0, w, h)
      const connectDist = 130
      const maxConnections = 3
      ctx.lineWidth = 0.6

      for (let i = 0; i < state.particles.length; i++) {
        let connections = 0
        for (let j = i + 1; j < state.particles.length; j++) {
          if (connections >= maxConnections) break
          const dx = state.particles[i].x - state.particles[j].x
          const dy = state.particles[i].y - state.particles[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < connectDist) {
            const alpha = (1 - dist / connectDist) * 0.18 * CONFIG.opacity
            ctx.strokeStyle = `rgba(200, 210, 255, ${alpha})`
            ctx.beginPath()
            ctx.moveTo(state.particles[i].x, state.particles[i].y)
            ctx.lineTo(state.particles[j].x, state.particles[j].y)
            ctx.stroke()
            connections++
          }
        }
      }

      state.particles.forEach((p: any) => {
        p.x += p.vx
        p.y += p.vy
        p.pulse += p.pulseSpeed
        if (p.x < -10) p.x = w + 10
        if (p.x > w + 10) p.x = -10
        if (p.y < -10) p.y = h + 10
        if (p.y > h + 10) p.y = -10

        const alpha = p.opacity * (0.6 + 0.4 * Math.sin(p.pulse)) * CONFIG.opacity
        const size = p.size * (0.85 + 0.15 * Math.sin(p.pulse))
        glowDot(p.x, p.y, CONFIG.glow ? size * 2.6 : size, alpha)
      })
    }

    // ========== B. 星空粒子 ==========
    function initStars() {
      const stars = []
      const count = Math.floor((w * h) / (CONFIG.density * 0.7))
      for (let i = 0; i < count; i++) {
        const x = Math.random() * w
        const densityBias = x / w
        if (Math.random() > densityBias * 0.5 + 0.3) continue
        stars.push({
          x,
          y: Math.random() * h,
          size: 0.8 + Math.random() * 2.2,
          speed: (0.06 + Math.random() * 0.2) * CONFIG.speed,
          twinkle: Math.random() * Math.PI * 2,
          twinkleSpeed: (0.012 + Math.random() * 0.022) * CONFIG.speed,
          driftX: (Math.random() - 0.5) * 0.1,
        })
      }
      return { stars }
    }

    function drawStars(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.stars.forEach((s: any) => {
        s.y -= s.speed
        s.x += s.driftX
        s.twinkle += s.twinkleSpeed
        if (s.y < -5) {
          s.y = h + 5
          s.x = Math.random() * w
        }
        if (s.x < 0) s.x = w
        if (s.x > w) s.x = 0

        const alpha = (0.25 + 0.45 * Math.sin(s.twinkle)) * CONFIG.opacity
        glowDot(s.x, s.y, CONFIG.glow && s.size > 1.0 ? s.size * 3 : s.size, alpha)

        // 大星的四向 + 斜向星芒，强化"星尘"闪烁感
        if (s.size > 1.3) {
          ctx.strokeStyle = `rgba(220, 225, 255, ${alpha * 0.4})`
          ctx.lineWidth = 0.6
          const r = s.size * 3.4
          ctx.beginPath()
          ctx.moveTo(s.x - r, s.y)
          ctx.lineTo(s.x + r, s.y)
          ctx.moveTo(s.x, s.y - r)
          ctx.lineTo(s.x, s.y + r)
          ctx.stroke()
          ctx.strokeStyle = `rgba(220, 225, 255, ${alpha * 0.22})`
          const rd = r * 0.6
          ctx.beginPath()
          ctx.moveTo(s.x - rd, s.y - rd)
          ctx.lineTo(s.x + rd, s.y + rd)
          ctx.moveTo(s.x - rd, s.y + rd)
          ctx.lineTo(s.x + rd, s.y - rd)
          ctx.stroke()
        }
      })
    }

    // ========== C. 光晕脉冲 ==========
    function initAura() {
      const rings = []
      for (let i = 0; i < 4; i++) {
        rings.push({
          radius: 0,
          maxRadius: Math.max(w, h) * 0.7,
          speed: (0.3 + Math.random() * 0.25) * CONFIG.speed,
          delay: i * 70,
          age: -i * 70,
          opacity: (0.2 + Math.random() * 0.15) * CONFIG.opacity,
        })
      }
      const rays = []
      for (let i = 0; i < 10; i++) {
        rays.push({
          angle: (i / 10) * Math.PI * 2 + Math.random() * 0.5,
          length: 0,
          maxLength: Math.max(w, h) * 0.45,
          speed: (0.5 + Math.random() * 0.35) * CONFIG.speed,
          width: 0.5 + Math.random() * 0.8,
          delay: Math.random() * 200,
        })
      }
      return { rings, rays, cx: w * 0.5, cy: h * 0.5 }
    }

    function drawAura(state: any) {
      ctx.clearRect(0, 0, w, h)
      // 中心柔光核，让扩散环有"光源"
      glowDot(state.cx, state.cy, Math.min(w, h) * 0.18, 0.12 * CONFIG.opacity)
      state.rings.forEach((r: any) => {
        r.age++
        if (r.age < 0) return
        r.radius += r.speed
        if (r.radius > r.maxRadius) {
          r.radius = 0
          r.age = -r.delay
        }
        const progress = r.radius / r.maxRadius
        const alpha = r.opacity * (1 - progress) * (1 - progress)
        ctx.beginPath()
        ctx.arc(state.cx, state.cy, r.radius, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(200, 210, 255, ${alpha})`
        ctx.lineWidth = 1.5 * (1 - progress * 0.5)
        ctx.stroke()
      })

      state.rays.forEach((ray: any) => {
        ray.delay--
        if (ray.delay > 0) return
        ray.length += ray.speed
        if (ray.length > ray.maxLength) {
          ray.length = 0
          ray.delay = 100 + Math.random() * 150
          ray.angle += (Math.random() - 0.5) * 0.6
        }
        const progress = ray.length / ray.maxLength
        const alpha = 0.12 * (1 - progress) * CONFIG.opacity
        const x2 = state.cx + Math.cos(ray.angle) * ray.length
        const y2 = state.cy + Math.sin(ray.angle) * ray.length
        ctx.beginPath()
        ctx.moveTo(state.cx, state.cy)
        ctx.lineTo(x2, y2)
        ctx.strokeStyle = `rgba(200, 210, 255, ${alpha})`
        ctx.lineWidth = ray.width
        ctx.stroke()
      })
    }

    // ========== D. 轨道环 ==========
    function initOrbitals() {
      const rings = []
      const count = 3 + Math.floor(Math.random() * 2)
      for (let i = 0; i < count; i++) {
        rings.push({
          cx: w * 0.5 + (Math.random() - 0.5) * 60,
          cy: h * 0.5 + (Math.random() - 0.5) * 50,
          radius: 55 + i * 45 + Math.random() * 30,
          tilt: (Math.random() - 0.5) * 0.4,
          rotation: Math.random() * Math.PI * 2,
          rotSpeed: (Math.random() - 0.5) * 0.0025 * CONFIG.speed,
          opacity: (0.15 + Math.random() * 0.1) * CONFIG.opacity,
          dotAngle: Math.random() * Math.PI * 2,
          dotSpeed: (0.004 + Math.random() * 0.004) * CONFIG.speed,
        })
      }
      return { rings }
    }

    function drawOrbitals(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.rings.forEach((r: any) => {
        r.rotation += r.rotSpeed
        r.dotAngle += r.dotSpeed
        ctx.save()
        ctx.translate(r.cx, r.cy)
        ctx.rotate(r.rotation)
        ctx.scale(1, Math.cos(r.tilt))
        ctx.beginPath()
        ctx.arc(0, 0, r.radius, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(200, 210, 255, ${r.opacity})`
        ctx.lineWidth = 1
        ctx.stroke()
        const dotX = Math.cos(r.dotAngle) * r.radius
        const dotY = Math.sin(r.dotAngle) * r.radius
        glowDot(dotX, dotY, 6, 0.7 * CONFIG.opacity)
        ctx.restore()
      })
      glowDot(w * 0.5, h * 0.5, 12, 0.6 * CONFIG.opacity)
    }

    // ========== E. 流星雨 ==========
    function initMeteor() {
      const meteors = []
      const count = Math.floor((w * h) / (CONFIG.density * 1.5))
      for (let i = 0; i < count; i++) {
        meteors.push({
          x: Math.random() * w + w * 0.3,
          y: -Math.random() * h * 0.5,
          length: 30 + Math.random() * 60,
          speed: (2 + Math.random() * 3) * CONFIG.speed,
          angle: Math.PI * 0.7 + Math.random() * 0.3,
          opacity: 0,
          maxOpacity: (0.3 + Math.random() * 0.4) * CONFIG.opacity,
          life: 0,
          maxLife: 80 + Math.random() * 60,
          delay: Math.random() * 200,
        })
      }
      return { meteors }
    }

    function drawMeteor(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.meteors.forEach((m: any) => {
        m.delay--
        if (m.delay > 0) return
        m.life++
        if (m.life > m.maxLife) {
          m.life = 0
          m.delay = Math.random() * 150
          m.x = Math.random() * w + w * 0.2
          m.y = -Math.random() * 50
        }

        let alpha = m.maxOpacity
        if (m.life < 20) alpha = m.maxOpacity * (m.life / 20)
        else if (m.life > m.maxLife - 20)
          alpha = m.maxOpacity * ((m.maxLife - m.life) / 20)

        m.x += Math.cos(m.angle) * m.speed
        m.y += Math.sin(m.angle) * m.speed

        const tailX = m.x - Math.cos(m.angle) * m.length
        const tailY = m.y - Math.sin(m.angle) * m.length

        const gradient = ctx.createLinearGradient(m.x, m.y, tailX, tailY)
        gradient.addColorStop(0, `rgba(235, 240, 255, ${alpha})`)
        gradient.addColorStop(0.3, `rgba(200, 210, 255, ${alpha * 0.6})`)
        gradient.addColorStop(1, 'rgba(180, 190, 255, 0)')

        ctx.strokeStyle = gradient
        ctx.lineWidth = 1.8
        ctx.lineCap = 'round'
        ctx.beginPath()
        ctx.moveTo(m.x, m.y)
        ctx.lineTo(tailX, tailY)
        ctx.stroke()

        glowDot(m.x, m.y, 5, alpha)
      })
    }

    // ========== F. 脉冲波纹 ==========
    function initRipple() {
      const ripples = []
      for (let i = 0; i < 5; i++) {
        ripples.push({
          x: w * 0.5 + (Math.random() - 0.5) * w * 0.6,
          y: h * 0.5 + (Math.random() - 0.5) * h * 0.6,
          radius: 0,
          maxRadius: 80 + Math.random() * 120,
          speed: (0.5 + Math.random() * 0.5) * CONFIG.speed,
          opacity: 0,
          maxOpacity: (0.25 + Math.random() * 0.15) * CONFIG.opacity,
          life: 0,
          maxLife: 120,
          delay: i * 40,
        })
      }
      return { ripples }
    }

    function drawRipple(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.ripples.forEach((r: any) => {
        r.delay--
        if (r.delay > 0) return
        r.life++
        if (r.life > r.maxLife) {
          r.life = 0
          r.delay = Math.random() * 80
          r.radius = 0
          r.x = w * 0.5 + (Math.random() - 0.5) * w * 0.6
          r.y = h * 0.5 + (Math.random() - 0.5) * h * 0.6
        }

        r.radius += r.speed
        const progress = r.life / r.maxLife
        const alpha = r.maxOpacity * (1 - progress) * Math.sin(progress * Math.PI)

        // 三层同心回声，涟漪更有层次
        const echoes = [1, 0.62, 0.32]
        echoes.forEach((k, idx) => {
          if (r.radius * k < 4) return
          ctx.beginPath()
          ctx.arc(r.x, r.y, r.radius * k, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(200, 210, 255, ${alpha * (1 - idx * 0.3)})`
          ctx.lineWidth = 1.4 - idx * 0.3
          ctx.stroke()
        })
      })
    }

    // ========== G. 萤火虫群 ==========
    function initFirefly() {
      const fireflies = []
      const count = Math.floor((w * h) / (CONFIG.density * 1.2))
      for (let i = 0; i < count; i++) {
        fireflies.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.3 * CONFIG.speed,
          vy: (Math.random() - 0.5) * 0.3 * CONFIG.speed,
          size: 1.5 + Math.random() * 2,
          baseOpacity: (0.1 + Math.random() * 0.2) * CONFIG.opacity,
          blinkPhase: Math.random() * Math.PI * 2,
          blinkSpeed: (0.008 + Math.random() * 0.015) * CONFIG.speed,
          wanderPhase: Math.random() * Math.PI * 2,
        })
      }
      return { fireflies }
    }

    function drawFirefly(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.fireflies.forEach((f: any) => {
        f.x += f.vx + Math.sin(f.wanderPhase) * 0.2
        f.y += f.vy + Math.cos(f.wanderPhase) * 0.2
        f.wanderPhase += 0.005 * CONFIG.speed
        f.blinkPhase += f.blinkSpeed

        if (f.x < -10) f.x = w + 10
        if (f.x > w + 10) f.x = -10
        if (f.y < -10) f.y = h + 10
        if (f.y > h + 10) f.y = -10

        const blink = 0.3 + 0.7 * Math.sin(f.blinkPhase)
        const alpha = f.baseOpacity * blink
        glowDot(
          f.x,
          f.y,
          CONFIG.glow ? f.size * 4 : f.size,
          alpha,
          '240, 245, 200',
          '200, 220, 150',
        )
      })
    }

    // ========== H. 矩阵雨 ==========
    function initMatrix() {
      const columns: {
        x: number
        y: number
        speed: number
        chars: ('0' | '1')[]
        length: number
        opacity: number
        delay: number
      }[] = []
      const colCount = Math.floor(w / 15)
      const chars: ('0' | '1')[] = ['0', '1']
      for (let i = 0; i < colCount; i++) {
        columns.push({
          x: i * 15 + 7,
          y: Math.random() * h,
          speed: (1 + Math.random() * 2) * CONFIG.speed,
          chars: [],
          length: 5 + Math.floor(Math.random() * 15),
          opacity: (0.1 + Math.random() * 0.3) * CONFIG.opacity,
          delay: Math.random() * 100,
        })
        for (let j = 0; j < columns[i].length; j++) {
          columns[i].chars.push(chars[Math.floor(Math.random() * chars.length)])
        }
      }
      return { columns }
    }

    function drawMatrix(state: any) {
      const chars: ('0' | '1')[] = ['0', '1']
      ctx.clearRect(0, 0, w, h)
      ctx.font = '10px monospace'
      ctx.textAlign = 'center'

      state.columns.forEach((col: any) => {
        col.delay--
        if (col.delay > 0) return
        col.y += col.speed
        if (col.y > h + col.length * 12) {
          col.y = -col.length * 12
          col.delay = Math.random() * 50
          col.length = 5 + Math.floor(Math.random() * 15)
          col.chars = []
          for (let j = 0; j < col.length; j++) {
            col.chars.push(chars[Math.floor(Math.random() * chars.length)])
          }
        }

        for (let i = 0; i < col.chars.length; i++) {
          const y = col.y - i * 12
          if (y < -10 || y > h + 10) continue
          const headFade = i === 0 ? 1 : Math.max(0, 1 - (i / col.length) * 1.5)
          const alpha = col.opacity * headFade
          ctx.fillStyle = `rgba(180, 200, 255, ${alpha})`
          ctx.fillText(col.chars[i], col.x, y)
        }

        glowDot(col.x, col.y, 4, col.opacity)
      })
    }

    // ========== J. 气泡上升 ==========
    function initBubbles() {
      const bubbles = []
      const count = Math.floor((w * h) / (CONFIG.density * 1.5))
      for (let i = 0; i < count; i++) {
        bubbles.push({
          x: Math.random() * w,
          y: h + Math.random() * h * 0.5,
          radius: 3 + Math.random() * 12,
          speed: (0.3 + Math.random() * 0.8) * CONFIG.speed,
          wobble: Math.random() * Math.PI * 2,
          wobbleSpeed: (0.01 + Math.random() * 0.02) * CONFIG.speed,
          opacity: (0.1 + Math.random() * 0.2) * CONFIG.opacity,
          pulse: Math.random() * Math.PI * 2,
        })
      }
      return { bubbles }
    }

    function drawBubbles(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.bubbles.forEach((b: any) => {
        b.y -= b.speed
        b.wobble += b.wobbleSpeed
        b.pulse += 0.008 * CONFIG.speed
        b.x += Math.sin(b.wobble) * 0.3

        if (b.y < -b.radius * 2) {
          b.y = h + b.radius * 2
          b.x = Math.random() * w
        }

        const alpha = b.opacity * (0.7 + 0.3 * Math.sin(b.pulse))
        const radius = b.radius * (0.95 + 0.05 * Math.sin(b.pulse))

        ctx.globalAlpha = alpha * 0.3
        ctx.fillStyle = 'rgba(200, 210, 255, 0.3)'
        ctx.beginPath()
        ctx.arc(b.x, b.y, radius, 0, Math.PI * 2)
        ctx.fill()

        ctx.globalAlpha = alpha * 0.6
        ctx.strokeStyle = 'rgba(220, 230, 255, 0.5)'
        ctx.lineWidth = 0.8
        ctx.beginPath()
        ctx.arc(b.x, b.y, radius, 0, Math.PI * 2)
        ctx.stroke()

        ctx.globalAlpha = alpha * 0.8
        ctx.fillStyle = 'rgba(240, 245, 255, 0.7)'
        ctx.beginPath()
        ctx.arc(
          b.x - radius * 0.3,
          b.y - radius * 0.3,
          radius * 0.2,
          0,
          Math.PI * 2,
        )
        ctx.fill()
      })
      ctx.globalAlpha = 1
    }

    // ========== K. DNA 双螺旋（基因组学语义） ==========
    function initDna() {
      const strands = Math.max(1, Math.round(w / 520))
      const nodes: any[] = []
      for (let s = 0; s < strands; s++) {
        const cx = ((s + 0.5) / strands) * w
        const rows = Math.ceil(h / 18) + 2
        for (let i = 0; i < rows; i++) {
          nodes.push({
            cx,
            row: i,
            y: i * 18,
            phase: i * 0.34 + s * 1.7,
            amp: 34 + Math.random() * 12,
          })
        }
      }
      return { nodes, t: 0 }
    }

    function drawDna(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.t += 0.011 * CONFIG.speed
      const strandMap = new Map<number, any[]>()
      state.nodes.forEach((n: any) => {
        const ang = n.phase + state.t
        const depth = Math.sin(ang) // -1 后 / +1 前
        n.x = n.cx + Math.cos(ang) * n.amp
        n.depth = depth
        const list = strandMap.get(n.row) || []
        list.push(n)
        strandMap.set(n.row, list)
      })
      // 碱基对横档
      strandMap.forEach((pair) => {
        if (pair.length < 2) return
        const a = pair[0]
        const b = pair[1]
        const fade = Math.abs(a.depth) * 0.5 + 0.2
        ctx.strokeStyle = `rgba(200, 215, 255, ${fade * 0.32 * CONFIG.opacity})`
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.stroke()
      })
      // 核苷酸节点，按深度调亮度/大小，制造立体旋转感
      state.nodes.forEach((n: any) => {
        const bright = 0.45 + 0.55 * ((n.depth + 1) / 2)
        const alpha = bright * 0.6 * CONFIG.opacity
        const size = 1.4 + 1.5 * ((n.depth + 1) / 2)
        glowDot(n.x, n.y, CONFIG.glow ? size * 2.4 : size, alpha)
      })
    }

    // ========== L. 星座连线（数据节点网络） ==========
    function initConstellation() {
      const pts: any[] = []
      const count = Math.floor((w * h) / (CONFIG.density * 1.4))
      for (let i = 0; i < count; i++) {
        pts.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.22 * CONFIG.speed,
          vy: (Math.random() - 0.5) * 0.22 * CONFIG.speed,
          size: 1 + Math.random() * 2,
          pulse: Math.random() * Math.PI * 2,
        })
      }
      return { pts }
    }

    function drawConstellation(state: any) {
      ctx.clearRect(0, 0, w, h)
      const link = 150
      const pts = state.pts
      for (let i = 0; i < pts.length; i++) {
        const p = pts[i]
        p.x += p.vx
        p.y += p.vy
        p.pulse += 0.011 * CONFIG.speed
        if (p.x < 0 || p.x > w) p.vx *= -1
        if (p.y < 0 || p.y > h) p.vy *= -1
        for (let j = i + 1; j < pts.length; j++) {
          const q = pts[j]
          const dx = p.x - q.x
          const dy = p.y - q.y
          const d = Math.hypot(dx, dy)
          if (d < link) {
            const a = (1 - d / link) * 0.22 * CONFIG.opacity
            ctx.strokeStyle = `rgba(190, 205, 255, ${a})`
            ctx.lineWidth = 0.7
            ctx.beginPath()
            ctx.moveTo(p.x, p.y)
            ctx.lineTo(q.x, q.y)
            ctx.stroke()
          }
        }
      }
      pts.forEach((p: any) => {
        const a = (0.5 + 0.5 * Math.sin(p.pulse)) * 0.7 * CONFIG.opacity
        glowDot(p.x, p.y, CONFIG.glow ? p.size * 2.8 : p.size, a)
      })
    }

    // ========== M. 流场微粒（Perlin 风场感） ==========
    function initFlowfield() {
      const pts: any[] = []
      const count = Math.floor((w * h) / (CONFIG.density * 0.9))
      const spawn = () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        life: 0,
        maxLife: 80 + Math.random() * 120,
        px: 0,
        py: 0,
      })
      for (let i = 0; i < count; i++) {
        const p = spawn()
        p.px = p.x
        p.py = p.y
        pts.push(p)
      }
      return { pts, t: 0 }
    }

    function drawFlowfield(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.t += 0.0008 * CONFIG.speed
      const scale = 0.0042
      state.pts.forEach((p: any) => {
        const ang =
          Math.sin(p.x * scale + state.t * 60) * 1.8 +
          Math.cos(p.y * scale - state.t * 40) * 1.8
        p.px = p.x
        p.py = p.y
        p.x += Math.cos(ang) * 1.1 * CONFIG.speed
        p.y += Math.sin(ang) * 1.1 * CONFIG.speed
        p.life++
        if (p.life > p.maxLife || p.x < 0 || p.x > w || p.y < 0 || p.y > h) {
          p.x = Math.random() * w
          p.y = Math.random() * h
          p.px = p.x
          p.py = p.y
          p.life = 0
        }
        const fade = Math.sin((p.life / p.maxLife) * Math.PI)
        ctx.strokeStyle = `rgba(195, 210, 255, ${fade * 0.28 * CONFIG.opacity})`
        ctx.lineWidth = 0.8
        ctx.beginPath()
        ctx.moveTo(p.px, p.py)
        ctx.lineTo(p.x, p.y)
        ctx.stroke()
        glowDot(p.x, p.y, 1.6, fade * 0.5 * CONFIG.opacity)
      })
    }

    // ========== N. 漂浮碎片 / 棱光（晶体感） ==========
    function initShards() {
      const shards: any[] = []
      const count = Math.floor((w * h) / (CONFIG.density * 2.2))
      for (let i = 0; i < count; i++) {
        const size = 14 + Math.random() * 34
        shards.push({
          x: Math.random() * w,
          y: Math.random() * h,
          size,
          rot: Math.random() * Math.PI * 2,
          rotSpeed: (Math.random() - 0.5) * 0.004 * CONFIG.speed,
          vx: (Math.random() - 0.5) * 0.18 * CONFIG.speed,
          vy: (Math.random() - 0.5) * 0.18 * CONFIG.speed,
          sides: 3 + Math.floor(Math.random() * 3),
          shimmer: Math.random() * Math.PI * 2,
          opacity: (0.05 + Math.random() * 0.08) * CONFIG.opacity,
        })
      }
      return { shards }
    }

    function drawShards(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.shards.forEach((s: any) => {
        s.x += s.vx
        s.y += s.vy
        s.rot += s.rotSpeed
        s.shimmer += 0.011 * CONFIG.speed
        if (s.x < -s.size) s.x = w + s.size
        if (s.x > w + s.size) s.x = -s.size
        if (s.y < -s.size) s.y = h + s.size
        if (s.y > h + s.size) s.y = -s.size
        const shimmer = 0.6 + 0.4 * Math.sin(s.shimmer)
        ctx.save()
        ctx.translate(s.x, s.y)
        ctx.rotate(s.rot)
        ctx.beginPath()
        for (let k = 0; k < s.sides; k++) {
          const a = (k / s.sides) * Math.PI * 2
          const px = Math.cos(a) * s.size
          const py = Math.sin(a) * s.size
          if (k === 0) ctx.moveTo(px, py)
          else ctx.lineTo(px, py)
        }
        ctx.closePath()
        ctx.fillStyle = `rgba(190, 205, 255, ${s.opacity * shimmer * 0.5})`
        ctx.fill()
        ctx.strokeStyle = `rgba(220, 230, 255, ${s.opacity * shimmer * 1.6})`
        ctx.lineWidth = 0.8
        ctx.stroke()
        ctx.restore()
      })
    }

    // ========== O. 六边形网格呼吸（蜂窝 / 测序芯片感） ==========
    function initHexgrid() {
      const hexes: any[] = []
      const r = 30
      const dx = r * 1.5
      const dy = r * Math.sqrt(3)
      for (let col = -1; col * dx < w + r; col++) {
        for (let row = -1; row * dy < h + r; row++) {
          const x = col * dx
          const y = row * dy + (col % 2 ? dy / 2 : 0)
          hexes.push({
            x,
            y,
            phase: (x + y) * 0.012 + Math.random() * 0.6,
          })
        }
      }
      return { hexes, t: 0, r }
    }

    function drawHexgrid(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.t += 0.011 * CONFIG.speed
      const r = state.r
      state.hexes.forEach((hx: any) => {
        const pulse = 0.5 + 0.5 * Math.sin(state.t + hx.phase)
        const alpha = pulse * 0.16 * CONFIG.opacity
        if (alpha < 0.01) return
        ctx.beginPath()
        for (let k = 0; k < 6; k++) {
          const a = (Math.PI / 3) * k
          const px = hx.x + Math.cos(a) * r * 0.92
          const py = hx.y + Math.sin(a) * r * 0.92
          if (k === 0) ctx.moveTo(px, py)
          else ctx.lineTo(px, py)
        }
        ctx.closePath()
        ctx.strokeStyle = `rgba(195, 210, 255, ${alpha})`
        ctx.lineWidth = 0.9
        ctx.stroke()
        if (pulse > 0.82) {
          glowDot(hx.x, hx.y, 3, (pulse - 0.82) * 2 * CONFIG.opacity)
        }
      })
    }

    // ========== P. 正弦波带（信号 / 电泳图谱感） ==========
    function initWaves() {
      const bands = 4
      const waves: any[] = []
      for (let i = 0; i < bands; i++) {
        waves.push({
          y: ((i + 1) / (bands + 1)) * h,
          amp: 14 + Math.random() * 22,
          freq: 0.006 + Math.random() * 0.006,
          speed: (0.02 + Math.random() * 0.02) * CONFIG.speed,
          phase: Math.random() * Math.PI * 2,
          opacity: (0.12 + Math.random() * 0.12) * CONFIG.opacity,
        })
      }
      return { waves }
    }

    function drawWaves(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.waves.forEach((wv: any) => {
        wv.phase += wv.speed
        ctx.beginPath()
        for (let x = 0; x <= w; x += 6) {
          const y = wv.y + Math.sin(x * wv.freq + wv.phase) * wv.amp
          if (x === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }
        ctx.strokeStyle = `rgba(200, 215, 255, ${wv.opacity})`
        ctx.lineWidth = 1.3
        ctx.stroke()
        // 波峰亮点
        const peakX =
          ((Math.PI / 2 - wv.phase) / wv.freq + w * 2) % (w + 200)
        if (peakX >= 0 && peakX <= w) {
          glowDot(peakX, wv.y - wv.amp, 4, wv.opacity * 2.2)
        }
      })
    }

    // ========== Q. 引力井（轨道粒子 + 中心吸积） ==========
    function initGravity() {
      const cx = w * 0.5
      const cy = h * 0.5
      const bodies: any[] = []
      const count = Math.floor((w * h) / (CONFIG.density * 1.1))
      for (let i = 0; i < count; i++) {
        const r = 50 + Math.random() * Math.min(w, h) * 0.42
        const a = Math.random() * Math.PI * 2
        bodies.push({
          r,
          a,
          // 近似开普勒：近快远慢
          speed: (0.6 / Math.sqrt(r)) * CONFIG.speed * (Math.random() > 0.5 ? 1 : -1),
          size: 0.8 + Math.random() * 1.8,
          opacity: (0.2 + Math.random() * 0.3) * CONFIG.opacity,
        })
      }
      return { bodies, cx, cy, core: 0 }
    }

    function drawGravity(state: any) {
      ctx.clearRect(0, 0, w, h)
      state.core += 0.016 * CONFIG.speed
      const corePulse = 0.5 + 0.5 * Math.sin(state.core)
      glowDot(state.cx, state.cy, 16 + corePulse * 6, 0.5 * CONFIG.opacity)
      state.bodies.forEach((b: any) => {
        b.a += b.speed
        const x = state.cx + Math.cos(b.a) * b.r
        const y = state.cy + Math.sin(b.a) * b.r * 0.62 // 视角压扁成椭圆轨道
        glowDot(x, y, CONFIG.glow ? b.size * 2.6 : b.size, b.opacity)
      })
    }

    // ========== R. 数据流 / 上升光柱（上传 / 测序产出感） ==========
    function initDatastream() {
      const cols = Math.max(8, Math.floor(w / 34))
      const bars: any[] = []
      for (let i = 0; i < cols; i++) {
        bars.push({
          x: ((i + 0.5) / cols) * w,
          target: 0.2 + Math.random() * 0.7,
          cur: 0,
          phase: Math.random() * Math.PI * 2,
          speed: 0.01 + Math.random() * 0.02,
          hue: Math.random() > 0.5 ? '190, 210, 255' : '170, 180, 250',
        })
      }
      return { bars }
    }

    function drawDatastream(state: any) {
      ctx.clearRect(0, 0, w, h)
      const bw = Math.max(3, w / state.bars.length / 2.4)
      state.bars.forEach((b: any) => {
        b.phase += b.speed * CONFIG.speed * 0.6
        if (Math.random() < 0.01) b.target = 0.2 + Math.random() * 0.7
        b.cur += (b.target - b.cur) * 0.04
        const pulse = 0.7 + 0.3 * Math.sin(b.phase)
        const bh = b.cur * h * 0.7 * pulse
        const x = b.x - bw / 2
        const y = h - bh
        const g = ctx.createLinearGradient(0, y, 0, h)
        const a = 0.32 * CONFIG.opacity
        g.addColorStop(0, `rgba(${b.hue}, ${a})`)
        g.addColorStop(1, `rgba(${b.hue}, 0)`)
        ctx.fillStyle = g
        ctx.fillRect(x, y, bw, bh)
        glowDot(b.x, y, 3.5, 0.6 * CONFIG.opacity, b.hue, b.hue)
      })
    }

    // ========== S. 极光带（水平漂移色带） ==========
    function initAurora() {
      const bands = 3
      const ribbons: any[] = []
      for (let i = 0; i < bands; i++) {
        ribbons.push({
          baseY: h * (0.3 + i * 0.2),
          amp: 26 + Math.random() * 30,
          freq: 0.004 + Math.random() * 0.004,
          drift: (0.0032 + Math.random() * 0.0032) * CONFIG.speed,
          phase: Math.random() * Math.PI * 2,
          thick: 60 + Math.random() * 50,
          color: ['120, 200, 210', '150, 130, 240', '120, 160, 255'][i],
          opacity: (0.1 + Math.random() * 0.06) * CONFIG.opacity,
        })
      }
      return { ribbons }
    }

    function drawAurora(state: any) {
      ctx.clearRect(0, 0, w, h)
      ctx.save()
      ctx.globalCompositeOperation = 'lighter'
      state.ribbons.forEach((rb: any) => {
        rb.phase += rb.drift
        const grad = ctx.createLinearGradient(0, rb.baseY - rb.thick, 0, rb.baseY + rb.thick)
        grad.addColorStop(0, `rgba(${rb.color}, 0)`)
        grad.addColorStop(0.5, `rgba(${rb.color}, ${rb.opacity})`)
        grad.addColorStop(1, `rgba(${rb.color}, 0)`)
        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.moveTo(0, h)
        for (let x = 0; x <= w; x += 8) {
          const y =
            rb.baseY +
            Math.sin(x * rb.freq + rb.phase) * rb.amp +
            Math.sin(x * rb.freq * 2.3 + rb.phase * 1.7) * rb.amp * 0.3
          ctx.lineTo(x, y)
        }
        ctx.lineTo(w, h)
        ctx.closePath()
        ctx.fill()
      })
      ctx.restore()
    }

    // ========== T. 星云 / 深空雾（漂移柔光团） ==========
    function initNebula() {
      const clouds: any[] = []
      const count = 5 + Math.floor(Math.random() * 3)
      const palette = [
        '140, 120, 235',
        '110, 150, 250',
        '170, 130, 230',
        '120, 190, 220',
      ]
      for (let i = 0; i < count; i++) {
        clouds.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.07 * CONFIG.speed,
          vy: (Math.random() - 0.5) * 0.07 * CONFIG.speed,
          r: 70 + Math.random() * 150,
          color: palette[i % palette.length],
          pulse: Math.random() * Math.PI * 2,
          pulseSpeed: (0.003 + Math.random() * 0.0035) * CONFIG.speed,
          opacity: (0.06 + Math.random() * 0.06) * CONFIG.opacity,
        })
      }
      // 深空星点
      const dust: any[] = []
      const dc = Math.floor((w * h) / (CONFIG.density * 1.6))
      for (let i = 0; i < dc; i++) {
        dust.push({
          x: Math.random() * w,
          y: Math.random() * h,
          s: 0.5 + Math.random() * 1.3,
          tw: Math.random() * Math.PI * 2,
          tws: (0.005 + Math.random() * 0.01) * CONFIG.speed,
        })
      }
      return { clouds, dust }
    }

    function drawNebula(state: any) {
      ctx.clearRect(0, 0, w, h)
      ctx.save()
      ctx.globalCompositeOperation = 'lighter'
      state.clouds.forEach((c: any) => {
        c.x += c.vx
        c.y += c.vy
        c.pulse += c.pulseSpeed
        if (c.x < -c.r) c.x = w + c.r
        if (c.x > w + c.r) c.x = -c.r
        if (c.y < -c.r) c.y = h + c.r
        if (c.y > h + c.r) c.y = -c.r
        const breathe = 0.7 + 0.3 * Math.sin(c.pulse)
        const g = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, c.r)
        g.addColorStop(0, `rgba(${c.color}, ${c.opacity * breathe})`)
        g.addColorStop(1, `rgba(${c.color}, 0)`)
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(c.x, c.y, c.r, 0, Math.PI * 2)
        ctx.fill()
      })
      ctx.restore()
      state.dust.forEach((d: any) => {
        d.tw += d.tws
        const a = (0.3 + 0.5 * Math.sin(d.tw)) * CONFIG.opacity
        glowDot(d.x, d.y, d.s * 1.6, a)
      })
    }

    // ========== 调度器 ==========
    let state: any = null

    function initForMode() {
      switch (currentMode) {
        case 'particles':
          return initParticles()
        case 'stars':
          return initStars()
        case 'aura':
          return initAura()
        case 'orbitals':
          return initOrbitals()
        case 'meteor':
          return initMeteor()
        case 'ripple':
          return initRipple()
        case 'firefly':
          return initFirefly()
        case 'matrix':
          return initMatrix()
        case 'bubbles':
          return initBubbles()
        case 'dna':
          return initDna()
        case 'constellation':
          return initConstellation()
        case 'flowfield':
          return initFlowfield()
        case 'shards':
          return initShards()
        case 'hexgrid':
          return initHexgrid()
        case 'waves':
          return initWaves()
        case 'gravity':
          return initGravity()
        case 'datastream':
          return initDatastream()
        case 'aurora':
          return initAurora()
        case 'nebula':
          return initNebula()
        default:
          return initParticles()
      }
    }

    function drawForMode(s: any) {
      switch (currentMode) {
        case 'particles':
          return drawParticles(s)
        case 'stars':
          return drawStars(s)
        case 'aura':
          return drawAura(s)
        case 'orbitals':
          return drawOrbitals(s)
        case 'meteor':
          return drawMeteor(s)
        case 'ripple':
          return drawRipple(s)
        case 'firefly':
          return drawFirefly(s)
        case 'matrix':
          return drawMatrix(s)
        case 'bubbles':
          return drawBubbles(s)
        case 'dna':
          return drawDna(s)
        case 'constellation':
          return drawConstellation(s)
        case 'flowfield':
          return drawFlowfield(s)
        case 'shards':
          return drawShards(s)
        case 'hexgrid':
          return drawHexgrid(s)
        case 'waves':
          return drawWaves(s)
        case 'gravity':
          return drawGravity(s)
        case 'datastream':
          return drawDatastream(s)
        case 'aurora':
          return drawAurora(s)
        case 'nebula':
          return drawNebula(s)
        default:
          return drawParticles(s)
      }
    }

    function tick() {
      if (!state) state = initForMode()
      drawAtmosphere()
      drawForMode(state)
    }

    // 帧率封顶 ~60fps（累加器：余量进位、长期不漂移）。
    // 所有 per-frame 自增都按 60Hz 调参；若不限速，120/144Hz 屏上 rAF 翻倍，旋转/漂移/闪烁
    // 会比设计值快 2–2.4 倍，肉眼即「转太快」，而 60Hz 开发机上看不出来。封顶后各刷新率体感一致。
    // 切后台回前台的大 dt 经 `%=` 丢弃盈余、只补一帧，绝不突进追帧。
    let lastTs = 0
    let frameAcc = 0
    const FRAME_MS = 1000 / 60
    function animate(ts: number = performance.now()) {
      animationId = requestAnimationFrame(animate)
      if (!lastTs) lastTs = ts
      frameAcc += ts - lastTs
      lastTs = ts
      if (frameAcc < FRAME_MS) return
      frameAcc %= FRAME_MS
      tick()
    }

    if (reduceMotion) {
      // 减少动态：只绘一帧静态画面，不启动循环（§6.3 / §32.4）。
      state = initForMode()
      drawAtmosphere()
      drawForMode(state)
    } else {
      animate()
    }

    const onVisibility = () => {
      if (reduceMotion) return
      if (document.hidden) {
        if (animationId) cancelAnimationFrame(animationId)
      } else {
        animate()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      if (animationId) cancelAnimationFrame(animationId)
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }
})()
