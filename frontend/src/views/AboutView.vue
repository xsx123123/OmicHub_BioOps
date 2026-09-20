<script setup lang="ts">
import { ref, onBeforeUnmount, onMounted } from 'vue'
import { NIcon, NButton, useMessage } from 'naive-ui'
import { RocketOutline, FlaskOutline, ShieldCheckmarkOutline, TelescopeOutline, LogoGithub, SparklesOutline, ChatbubbleEllipsesOutline } from '@vicons/ionicons5'
import { useRouter } from 'vue-router'
import { useSiteConfigStore } from '@/stores/site-config'
// 彩蛋图片：猫猫踩地球插画
import catEarthLogo from '@/assets/ChatGPT_logo.png'

const router = useRouter()
const siteConfig = useSiteConfigStore()
const message = useMessage()

onMounted(() => {
  siteConfig.fetchSiteConfig()
})

// 彩蛋：点击蓝色星球触发隐藏弹窗
const showEasterEgg = ref(false)

// 打开彩蛋弹窗：顺带拉取站点文案（已加载则复用，确保文案可被 YAML 配置覆盖）
function openEasterEgg() {
  siteConfig.fetchSiteConfig()
  showEasterEgg.value = true
}

// ===== 召唤星际猫咪 =====
// 猫爪动画由全局 CatPawsOverlay 负责（App.vue 挂载），这里只派发事件 + 弹 Toast。
// playing 用于防连点：动画播放期间不重复派发。
const playing = ref(false)
let pawTimer: ReturnType<typeof setTimeout> | null = null

function summonCat() {
  if (playing.value) return
  // 确保 toast / 按钮文案已就绪（首次进入关于页即点按钮时可能尚未拉取）
  siteConfig.fetchSiteConfig()
  playing.value = true
  message.success(siteConfig.easterEggToast, { duration: 3500 })
  window.dispatchEvent(new CustomEvent('cygnusX:triggerCatPaws'))
  if (pawTimer) clearTimeout(pawTimer)
  pawTimer = setTimeout(() => {
    playing.value = false
  }, 7000)
}

onBeforeUnmount(() => {
  if (pawTimer) clearTimeout(pawTimer)
})

// 负相位延迟：让每颗星"开局即处于自己呼吸周期的随机中段"。
// 若用正延迟，动画开始前元素停留在基础样式（.star 无 opacity → 1.0 全亮），
// 随后逐颗跌到呼吸下限，开页前几秒会出现"满天亮星一颗颗暗下去"的级联，
// 用户感知为"高光消失"。负延迟从首帧起就是稳态夜空，无亮→暗跳变。
const stars = Array.from({ length: 160 }, (_, i) => {
  const size = Math.random() * 1 + 0.6
  const baseOpacity = Math.random() * 0.5 + 0.35
  const duration = Math.random() * 5 + 5

  const isBright = baseOpacity > 0.7
  // 十字高光稍微多一些、亮一些：保证任意时刻都有"几处高光"稳定可见，
  // 不会因闪烁集体变暗而让夜空显得发平。
  const hasCross = isBright && Math.random() > 0.7

  const crossScale = hasCross ? (size * baseOpacity * 0.9).toFixed(2) : 0

  return {
    id: i,
    top: Math.random() * 100,
    left: Math.random() * 100,
    size: size,
    opacity: baseOpacity,
    delay: -(Math.random() * duration),
    duration,
    hasCross: hasCross,
    crossScale: crossScale
  }
})

const shootingStars = Array.from({ length: 3 }, (_, i) => ({
  id: i,
  // 每颗仅在长周期中的短暂时刻划过，保持背景安静。
  // 首颗推迟到 ~7s 后：开页瞬间先呈现稳态高光夜空，流星随后才"添光"，
  // 避免一进来就和"高光"抢视觉、重现"流星出现→高光消失"的错觉。
  delay: 7 + i * 13 + Math.random() * 4,
  duration: 36 + Math.random() * 8,
  top: Math.random() * 50,
  left: Math.random() * 60,
  scale: 0.8 + Math.random() * 0.7,
}))

// 星云带：加宽、加多，不透明度*固定*在一个清晰可见的区间、只做极慢漂移，
// 让斜向紫蓝光雾成为"恒定底色"，任何时刻（含流星划过）都不会突然消失。
// 同样用负相位延迟：避免开页前几秒星云停在基础 opacity 1.0、动画启动后再跌回
// 0.7~0.95 的闪变（与星星同理的"高光消失"来源之一）。
const nebulaLayers = Array.from({ length: 4 }, (_, i) => {
  const duration = 24 + Math.random() * 22
  return {
    id: i,
    top: 10 + Math.random() * 60,
    left: -10 + Math.random() * 40,
    width: 70 + Math.random() * 30,
    height: 16 + Math.random() * 12,
    opacity: 0.7 + Math.random() * 0.25,
    delay: -(Math.random() * duration),
    duration,
  }
})
</script>

<template>
  <div class="about-page" role="main" aria-label="关于 CygnusX">
    <!-- 深空背景 -->
    <div class="space-bg" />

    <!-- 常驻呼吸高光：保证内容周围始终有柔和辉光，不随流星/闪烁而消失 -->
    <div class="ambient-core" />

    <!-- 星河/星云带 -->
    <div class="milky-way">
      <div
        v-for="n in nebulaLayers"
        :key="n.id"
        class="nebula-band"
        :style="{
          top: n.top + '%',
          left: n.left + '%',
          width: n.width + '%',
          height: n.height + '%',
          '--base-opacity': n.opacity,
          animationDelay: n.delay + 's',
          animationDuration: n.duration + 's',
        }"
      />
    </div>

    <!-- 星空 -->
    <div class="starfield">
      <div
        v-for="s in stars"
        :key="s.id"
        class="star"
        :class="{ 'has-cross': s.hasCross }"
        :style="{
          top: s.top + '%',
          left: s.left + '%',
          width: s.size + 'px',
          height: s.size + 'px',
          '--star-opacity': s.opacity,
          animationDelay: s.delay + 's',
          animationDuration: s.duration + 's',
          '--cross-scale': s.crossScale
        }"
      ></div>
    </div>

    <!-- 流星 -->
    <div class="shooting-stars">
      <div
        v-for="ss in shootingStars"
        :key="ss.id"
        class="shooting-star"
        :style="{
          top: ss.top + '%',
          left: ss.left + '%',
          animationDelay: ss.delay + 's',
          animationDuration: ss.duration + 's',
          '--star-scale': ss.scale
        }"
      />
    </div>

    <!-- 浮动光球 -->
    <div class="orb orb-1" />
    <div class="orb orb-2" />

    <!-- 内容 -->
    <div class="about-content">
      <!-- 旋转行星（点击触发隐藏彩蛋） -->
      <div class="planet-wrap" style="cursor: pointer" title="点我看看？" @click="openEasterEgg">
        <div class="planet" />
        <div class="planet-ring" />
        <div class="planet-orbit" aria-hidden="true"><span class="planet-moon" /></div>
      </div>

      <h1 class="about-title">CygnusX</h1>
      <p class="about-subtitle">天鹅座智能科研平台<span class="subtitle-llm">· LLM 深度赋能</span></p>

      <div class="about-quote-box">
        <p class="about-quote-title">We are made of star-stuff</p>
        <p class="about-quote">
          我们只是借用了宇宙中的这些碳、氢、氧原子几十年，用它们去短暂地体验了一次这个世界。
          组成我们大脑和身体的每一个原子，都来自几十亿年前远古恒星内部的核聚变爆炸。
          当生命结束时，我们并没有化为虚无，我们只是回到了那个浩瀚的宇宙中，换了一种方式继续存在。
        </p>
      </div>

      <!-- 特性 -->
      <div class="features">
        <div class="feature-item feature-item--primary animate-fade-in-up delay-100">
          <NIcon :size="24" class="feature-icon feature-icon--accent"><SparklesOutline /></NIcon>
          <div class="feature-text">
            <div class="feature-title">AI 智能分析</div>
            <div class="feature-desc">LLM 解读结果 · 自动生成报告</div>
          </div>
        </div>
        <div class="feature-item animate-fade-in-up delay-200">
          <NIcon :size="24" class="feature-icon feature-icon--accent"><ChatbubbleEllipsesOutline /></NIcon>
          <div class="feature-text">
            <div class="feature-title">智能问答</div>
            <div class="feature-desc">自然语言查询 · 对话式交互</div>
          </div>
        </div>
        <div class="feature-item animate-fade-in-up delay-200">
          <NIcon :size="24" class="feature-icon"><FlaskOutline /></NIcon>
          <div class="feature-text">
            <div class="feature-title">多组学分析</div>
            <div class="feature-desc">RNA-seq / ATAC-seq / 单细胞</div>
          </div>
        </div>
        <div class="feature-item animate-fade-in-up delay-300">
          <NIcon :size="24" class="feature-icon"><RocketOutline /></NIcon>
          <div class="feature-text">
            <div class="feature-title">Snakemake 流程</div>
            <div class="feature-desc">可复现、可扩展、自动化</div>
          </div>
        </div>
        <div class="feature-item animate-fade-in-up delay-400">
          <NIcon :size="24" class="feature-icon"><ShieldCheckmarkOutline /></NIcon>
          <div class="feature-text">
            <div class="feature-title">私有化部署</div>
            <div class="feature-desc">数据不出内网，安全可控</div>
          </div>
        </div>
        <div class="feature-item animate-fade-in-up delay-500">
          <NIcon :size="24" class="feature-icon"><TelescopeOutline /></NIcon>
          <div class="feature-text">
            <div class="feature-title">任务追踪</div>
            <div class="feature-desc">实时监控 / DAG 可视化</div>
          </div>
        </div>
      </div>

      <div class="about-actions">
        <NButton class="about-btn-primary" size="large" @click="router.push('/flows')">
          <template #icon>
            <NIcon><RocketOutline /></NIcon>
          </template>
          开始分析
        </NButton>
        <NButton class="about-btn-ghost" size="large" @click="router.push('/dashboard')">
          进入控制台
        </NButton>
        <NButton
          v-if="siteConfig.platformGithub"
          class="about-btn-ghost"
          size="large"
          tag="a"
          :href="siteConfig.platformGithub"
          target="_blank"
        >
          <template #icon>
            <NIcon><LogoGithub /></NIcon>
          </template>
          GitHub
        </NButton>
      </div>

      <!-- 底部 -->
      <div class="about-footer">
        <span class="about-brand">CygnusX</span>
        <span class="about-divider">·</span>
        <span>华中农业大学园艺林学学院 · 多组学分析平台</span>
        <div v-if="siteConfig.platformAuthor" class="about-credit">
          Designed by {{ siteConfig.platformAuthor }}
          <template v-if="siteConfig.platformEmail">
            <span class="about-divider">|</span>
            Contact: <a :href="`mailto:${siteConfig.platformEmail}`" class="about-credit-link">{{ siteConfig.platformEmail }}</a>
          </template>
        </div>
      </div>
    </div>

    <!-- 隐藏彩蛋弹窗：点击蓝色星球触发 -->
    <div
      v-if="showEasterEgg"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      @click="showEasterEgg = false"
    >
      <!-- 弹窗主体：深色毛玻璃，阻止点击冒泡到遮罩层 -->
      <div
        class="relative w-fit max-w-[90vw] rounded-2xl border border-white/10 bg-[#0B1121]/70 px-10 py-8 shadow-2xl backdrop-blur-md"
        @click.stop
      >
        <!-- 毛玻璃质感关闭按钮：悬浮光晕 + 旋转缩放动画 -->
        <button
          class="eg-close-btn group absolute right-4 top-4 flex h-9 w-9 cursor-pointer items-center justify-center rounded-full border border-white/15 bg-white/5 text-slate-300 backdrop-blur-sm transition-all duration-300 hover:border-cyan-300/60 hover:bg-cyan-300/10 hover:text-cyan-200 hover:shadow-[0_0_14px_rgba(103,232,249,0.55)]"
          aria-label="关闭"
          @click="showEasterEgg = false"
        >
          <span
            class="text-lg font-light leading-none transition-transform duration-300 group-hover:scale-110 group-hover:rotate-90"
          >
            ✕
          </span>
        </button>

        <img
          :src="catEarthLogo"
          alt="星际守护者"
          class="mx-auto block h-48 w-auto object-contain"
        />
        <p class="mt-6 max-w-[36rem] text-center text-lg font-bold leading-relaxed break-words text-white">
          {{ siteConfig.easterEggMessage }}
        </p>
      </div>
    </div>

    <!-- 悬浮召唤按钮：召唤星际猫咪 -->
    <button
      class="summon-cat-btn"
      :aria-label="siteConfig.easterEggButtonText"
      @click="summonCat"
    >
      <span class="summon-cat-btn__icon">🐾</span>
      <span class="summon-cat-btn__text">{{ siteConfig.easterEggButtonText }}</span>
    </button>

    <!-- 猫爪足迹覆盖层由全局 CatPawsOverlay（App.vue）渲染，本页不再自建 -->
  </div>
</template>

<style scoped>
/* 关闭按钮：空闲呼吸光晕，悬停时由 Tailwind 接管旋转/缩放/高亮 */
.eg-close-btn {
  animation: eg-close-pulse 2.4s ease-in-out infinite;
}
@keyframes eg-close-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(103, 232, 249, 0);
  }
  50% {
    box-shadow: 0 0 10px 1px rgba(103, 232, 249, 0.28);
  }
}
@keyframes shooting {
  0% {
    transform: translateX(0) translateY(0) rotate(35deg) scaleX(0) scale(var(--star-scale, 1));
    opacity: 0;
  }
  3% {
    opacity: 0.72;
    transform: translateX(36px) translateY(25px) rotate(35deg) scaleX(0.82) scale(var(--star-scale, 1));
  }
  9% {
    opacity: 0.62;
    transform: translateX(330px) translateY(231px) rotate(35deg) scaleX(1) scale(var(--star-scale, 1));
  }
  13% {
    transform: translateX(460px) translateY(322px) rotate(35deg) scaleX(0.42) scale(var(--star-scale, 1));
    opacity: 0;
  }
  100% {
    transform: translateX(600px) translateY(420px) rotate(35deg) scaleX(0.6) scale(var(--star-scale, 1));
    opacity: 0;
  }
}

/* 呼吸下限抬高（0.87）：配合负延迟，星点最暗时也接近满亮，
   夜空高光"恒定"，不会因集体走到波谷而发平。 */
@keyframes twinkle {
  0%, 100% {
    opacity: calc(var(--star-opacity, 0.55) * 0.87);
    transform: translate(-50%, -50%) scale(0.97);
  }
  50% {
    opacity: var(--star-opacity, 0.55);
    transform: translate(-50%, -50%) scale(1.04);
  }
}

/* 十字高光用更浅的呼吸下限（0.93），星芒始终清晰，不会闪没 */
@keyframes twinkleCross {
  0%, 100% {
    opacity: calc(var(--star-opacity, 0.7) * 0.93);
    transform: translate(-50%, -50%) scale(0.97);
  }
  50% {
    opacity: var(--star-opacity, 0.7);
    transform: translate(-50%, -50%) scale(1.06);
  }
}

@keyframes nebulaDrift {
  /* 不透明固定（仅 transform 极慢漂移）：星云高光被"钉住"，不会随相位发平而消失 */
  0%, 100% { transform: translateX(0) scale(1); opacity: var(--base-opacity, 0.7); }
  50% { transform: translateX(1.2%) scale(1.01); opacity: var(--base-opacity, 0.7); }
}

@keyframes ringSheen {
  0% { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}

@keyframes orbitSpin {
  from { transform: rotateX(66deg) rotateZ(0deg); }
  to { transform: rotateX(66deg) rotateZ(360deg); }
}

.about-page {
  position: relative;
  min-height: calc(100vh - 56px);
  margin: -24px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #11193c;
}

/* 深空蓝紫：以低饱和星云保留层次，不干扰正文阅读。 */
.space-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 56% 46% at 50% 26%, rgba(110, 140, 255, 0.16) 0%, transparent 60%),
    radial-gradient(ellipse at 16% 16%, rgba(90, 120, 255, 0.14) 0%, transparent 44%),
    radial-gradient(ellipse at 86% 82%, rgba(130, 98, 214, 0.14) 0%, transparent 48%),
    radial-gradient(ellipse at 6% 90%, rgba(80, 110, 220, 0.10) 0%, transparent 42%),
    radial-gradient(ellipse at 95% 14%, rgba(120, 104, 210, 0.10) 0%, transparent 42%),
    linear-gradient(150deg, #141d44 0%, #1c2556 50%, #221d4e 100%);
}

/* 常驻高光：在内容正中、右中、左上各铺一团柔光，不透明固定、绝不消失，
   让"几处高光"成为恒定底色，流星只是在其上叠加的瞬时光迹。 */
.ambient-core {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 60% 44% at 50% 22%, rgba(120, 150, 255, 0.32) 0%, transparent 62%),
    radial-gradient(ellipse 44% 42% at 82% 60%, rgba(152, 110, 236, 0.28) 0%, transparent 64%),
    radial-gradient(ellipse 40% 40% at 14% 26%, rgba(96, 130, 255, 0.28) 0%, transparent 62%);
  filter: blur(8px);
  /* screen 加性提亮：让辉光在较亮的暮光底上依然醒目成形（底越亮越需要 screen） */
  mix-blend-mode: screen;
  animation: ambientCoreBreathe 11s ease-in-out infinite;
  will-change: opacity, transform;
}
@keyframes ambientCoreBreathe {
  /* 不透明固定，仅 scale 微呼吸：辉光"钉住"为恒定底色，流星只是其上的瞬时光迹 */
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.03); }
}

/* 星河/星云带 */
.milky-way {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  transform: rotate(-15deg) scale(1.2);
}

.nebula-band {
  position: absolute;
  border-radius: 9999px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(150, 170, 255, 0.40) 25%,
    rgba(190, 150, 255, 0.52) 50%,
    rgba(150, 170, 255, 0.34) 75%,
    transparent 100%
  );
  filter: blur(40px);
  /* screen 加性：斜向星云在亮底上成为清晰、恒定的极光带 */
  mix-blend-mode: screen;
  animation: nebulaDrift ease-in-out infinite;
  --base-opacity: 0.85;
}

/* 星空 */
.starfield {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}

.star {
  position: absolute;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 0 4px 1px rgba(190, 209, 255, 0.34);
  animation: twinkle linear infinite alternate;
  transform: translate(-50%, -50%);
}

/* 十字星芒单独走 twinkleCross：下限更高，星芒始终清晰，分布稳定 */
.star.has-cross {
  animation-name: twinkleCross;
}

.star.has-cross::before,
.star.has-cross::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  pointer-events: none;
  transform: translate(-50%, -50%) scale(var(--cross-scale));
  /* 给星芒叠一层柔光晕，即便呼吸到低点也保留"高光"印象 */
  filter: drop-shadow(0 0 3px rgba(186, 208, 255, 0.55));
}

.star.has-cross::before {
  width: 40px;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(107, 141, 214, 0.8) 40%,
    rgba(255, 255, 255, 1) 50%,
    rgba(107, 141, 214, 0.8) 60%,
    transparent 100%
  );
}

.star.has-cross::after {
  width: 1px;
  height: 40px;
  background: linear-gradient(
    180deg,
    transparent 0%,
    rgba(107, 141, 214, 0.8) 40%,
    rgba(255, 255, 255, 1) 50%,
    rgba(107, 141, 214, 0.8) 60%,
    transparent 100%
  );
}

/* 流星 */
.shooting-stars {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  overflow: hidden;
}
.shooting-star {
  position: absolute;
  width: 112px;
  height: 1px;
  border-radius: 50%;
  opacity: 0;
  animation: shooting linear infinite;
  transform-origin: left center;
}
.shooting-star::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(to left, rgba(255, 255, 255, 0.74), rgba(147, 171, 255, 0.42), transparent);
  border-radius: 50%;
  filter: drop-shadow(0 0 4px rgba(194, 211, 255, 0.52));
}
.shooting-star::after {
  content: '';
  position: absolute;
  right: -3px;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 0 8px 1px rgba(255, 255, 255, 0.6), 0 0 14px 3px rgba(128, 153, 255, 0.30);
}

/* 浮动光球：常驻柔光，缓慢漂移+呼吸，作为边缘恒定的高光 */
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
  opacity: 0.3;
  mix-blend-mode: screen;
  pointer-events: none;
  z-index: 0;
  animation: orbBreathe 14s ease-in-out infinite;
  will-change: transform, opacity;
}
.orb-1 {
  width: 280px;
  height: 280px;
  background: #5b7cff;
  top: 8%;
  left: 3%;
}
.orb-2 {
  width: 220px;
  height: 220px;
  background: #8b6be8;
  bottom: 10%;
  right: 5%;
  animation-delay: -6s;
}
@keyframes orbBreathe {
  /* 不透明固定，仅漂移+缩放：边缘高光恒定，不随呼吸发平 */
  0%, 100% { opacity: 0.3; transform: translate3d(0, 0, 0) scale(1); }
  50% { opacity: 0.3; transform: translate3d(2%, -2%, 0) scale(1.08); }
}

/* 内容容器 */
.about-content {
  position: relative;
  z-index: 2;
  max-width: 720px;
  width: 100%;
  padding: 40px 32px;
  text-align: center;
}

/* 旋转行星：preserve-3d 让"球体圆盘(z=0)"与"倾斜 66° 的环/轨平面"
   共享同一 3D 渲染上下文，按真实深度逐像素排序——于是卫星公转到后弧时
   被不透明球体遮挡、到前弧时掠过球面，光环也呈土星式前后包裹（后弧藏于球后、
   前弧浮于球前）。perspective 给环/卫星加轻微近大远小的纵深，球体本身在 z=0 不受影响。
   注：祖先 .about-page 的 overflow:hidden 只把整个 wrap 压平合成到页面，
   wrap 内部这套 3D 遮挡在压平前已算好，故不受影响。 */
.planet-wrap {
  position: relative;
  width: 92px;
  height: 92px;
  margin: 0 auto 26px;
  transform-style: preserve-3d;
  perspective: 520px;
}
/* 发光行星：固定左上受光 + 大气辉光，静态球体（不整球自转，避免明暗面翻滚）。
   完全不透明，在 3D 上下文里充当"遮挡体"——后弧卫星/环在此圆盘之后即不可见。 */
.planet {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: radial-gradient(circle at 34% 30%, #b6c6ff 0%, #7189ef 32%, #3450c4 62%, #141a52 100%);
  box-shadow:
    0 0 22px rgba(120, 150, 255, 0.45),
    0 0 50px rgba(92, 122, 232, 0.25),
    inset -7px -8px 16px rgba(0, 0, 0, 0.5),
    inset 4px 4px 10px rgba(186, 204, 255, 0.28);
}
/* 光环：mask 裁出的连续倾斜渐变真环（66° 不再压成线），流光靠背景位移而非几何旋转。
   与球体同处 3D 上下文：环平面被球体圆盘沿水平中线切开，自动呈现土星式前后遮挡。 */
.planet-ring {
  position: absolute;
  inset: -12px;
  border-radius: 50%;
  transform: rotateX(66deg);
  padding: 2.5px;
  background: linear-gradient(
    115deg,
    rgba(205, 220, 255, 0.9) 0%,
    rgba(150, 172, 255, 0.12) 38%,
    rgba(176, 150, 255, 0.10) 62%,
    rgba(210, 222, 255, 0.85) 100%
  );
  background-size: 220% 220%;
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  filter: drop-shadow(0 0 4px rgba(150, 180, 255, 0.55));
  animation: ringSheen 7s linear infinite;
}
/* 沿环轨公转的小卫星：轨道与光环同尺寸同倾斜，故目视正好沿环椭圆运行。
   公转时 z 值正负交替：后弧落入球体圆盘之后被真实遮挡，前弧掠过球面，
   穿过球缘时由平面相交几何裁剪，呈现平滑"钻到球后/探出球前"的掠过感。 */
.planet-orbit {
  position: absolute;
  inset: -12px;
  border-radius: 50%;
  transform: rotateX(66deg);
  pointer-events: none;
  animation: orbitSpin 9s linear infinite;
}
.planet-moon {
  position: absolute;
  top: -3px;
  left: 50%;
  width: 7px;
  height: 7px;
  margin-left: -3.5px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, #ffffff, #c2d4ff 55%, #7f9bf0 100%);
  box-shadow: 0 0 8px 2px rgba(184, 206, 255, 0.7);
}

/* 标题 */
.about-title {
  font-size: 42px;
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: 1px;
  background: linear-gradient(90deg, #d9e2ff, #a8bbff, #d9e2ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.about-subtitle {
  font-size: 18px;
  color: #d6def8;
  margin: 0 0 24px;
  font-weight: 500;
}
.subtitle-llm {
  margin-left: 8px;
  font-weight: 600;
  color: #aebfff;
  text-shadow: 0 0 10px rgba(117, 143, 255, 0.22);
}

/* 引言：无边框磨砂"题记"块——去掉整圈亮描边/白内高光/hover 白闪（旧版像被框选），
   仅以顶/底两条两端渐隐的细光痕 + 柔投影成形；正文靠文字阴影在星场上保持可读。 */
.about-quote-box {
  position: relative;
  overflow: hidden;
  background: linear-gradient(180deg, rgba(26, 36, 80, 0.46) 0%, rgba(17, 25, 60, 0.32) 100%);
  backdrop-filter: saturate(140%) blur(14px);
  -webkit-backdrop-filter: saturate(140%) blur(14px);
  border: 0;
  box-shadow: 0 14px 44px rgba(6, 10, 34, 0.42);
  border-radius: 16px;
  padding: 26px 30px 24px;
  margin-bottom: 28px;
}
/* 顶/底渐隐光痕：有意为之的"题记框"线索，而非矩形描边 */
.about-quote-box::before,
.about-quote-box::after {
  content: '';
  position: absolute;
  left: 14%;
  right: 14%;
  height: 1px;
  pointer-events: none;
}
.about-quote-box::before {
  top: 0;
  background: linear-gradient(90deg, transparent, rgba(178, 204, 255, 0.5), transparent);
}
.about-quote-box::after {
  bottom: 0;
  background: linear-gradient(90deg, transparent, rgba(150, 178, 255, 0.26), transparent);
}

/* 题记英文行：对齐权威 StardustQuote 的 gilded 流光 + 衬线显示体，
   与正文无衬线构成"展示体/正文体"配对（§33.1#5）；辉光恒定，仅流光平移，不呼吸、不消失。 */
.about-quote-title {
  font-family: Georgia, 'Times New Roman', 'Songti SC', serif;
  font-size: 18px;
  font-weight: 600;
  font-style: italic;
  letter-spacing: 1.5px;
  margin: 0 0 18px;
  padding-bottom: 14px;
  position: relative;
  text-align: center;
  text-indent: 0;
  background: linear-gradient(
    90deg,
    rgba(238, 248, 255, 0.92) 0%,
    #ffffff 24%,
    #6fb4ff 50%,
    #ffffff 76%,
    rgba(238, 248, 255, 0.92) 100%
  );
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 0 10px rgba(112, 181, 255, 0.55));
  animation: shimmer 10s linear infinite;
}
/* 标题下一道居中渐隐细分隔线：编辑式题记节奏 */
.about-quote-title::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: 0;
  transform: translateX(-50%);
  width: 56px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(150, 185, 255, 0.7), transparent);
}

.about-quote {
  font-size: 14px;
  line-height: 1.95;
  color: #eef2ff;
  text-align: justify;
  margin: 0;
  text-indent: 2em;
  /* 文字阴影晕：在更亮的星场/磨砂底上保证正文对比（对齐 StardustQuote 做法） */
  text-shadow:
    0 1px 2px rgba(4, 8, 24, 0.55),
    0 2px 10px rgba(4, 8, 24, 0.4);
}

/* 特性：玻璃面板 */
.features {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 28px;
}
/* 特性卡片：与引言框同一套磨砂配方（同半透渐变 + 同模糊/饱和 + 去硬边 + 同柔投影 + 同渐隐光痕），
   仅圆角保留 12px（卡片级，对引言面板 16px 形成 §3.3 圆角层级，避免"全场一个值"）。 */
.feature-item {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(26, 36, 80, 0.46) 0%, rgba(17, 25, 60, 0.32) 100%);
  backdrop-filter: saturate(140%) blur(14px);
  -webkit-backdrop-filter: saturate(140%) blur(14px);
  border: 0;
  box-shadow: 0 12px 36px rgba(6, 10, 34, 0.40);
  transition: transform 0.25s ease, box-shadow 0.25s ease, filter 0.25s ease;
  text-align: left;
}
/* 与引言框一致的顶/底渐隐光痕 */
.feature-item::before,
.feature-item::after {
  content: '';
  position: absolute;
  left: 14%;
  right: 14%;
  height: 1px;
  pointer-events: none;
}
.feature-item::before {
  top: 0;
  background: linear-gradient(90deg, transparent, rgba(178, 204, 255, 0.5), transparent);
}
.feature-item::after {
  bottom: 0;
  background: linear-gradient(90deg, transparent, rgba(150, 178, 255, 0.22), transparent);
}
/* 悬停：无描边闪烁，改为整体微提亮 + 上浮 + 加深投影的"点亮"反馈 */
.feature-item:hover {
  transform: translateY(-2px);
  filter: brightness(1.08);
  box-shadow: 0 16px 40px rgba(6, 10, 34, 0.5);
}
/* 主推卡片：AI 智能分析——材质与其余卡片完全相同，仅以品牌色光痕 + 柔品牌辉光区分主次 */
.feature-item--primary {
  box-shadow:
    0 12px 36px rgba(6, 10, 34, 0.40),
    0 0 24px rgba(99, 130, 255, 0.20);
}
.feature-item--primary::before {
  background: linear-gradient(90deg, transparent, rgba(150, 182, 255, 0.9), transparent);
}
.feature-item--primary:hover {
  box-shadow:
    0 16px 40px rgba(6, 10, 34, 0.5),
    0 0 30px rgba(99, 130, 255, 0.30);
}
.feature-icon {
  color: #aebfff;
  flex-shrink: 0;
}
.feature-icon--accent {
  color: #c3d0ff;
}
/* 功能标题：青蓝渐变（非斜体，与卡片标题层级一致） */
.feature-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.5px;
  background: linear-gradient(90deg, #dbe4ff, #aac0ff, #dbe4ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  filter: drop-shadow(0 1px 2px rgba(4, 8, 24, 0.45));
}
.feature-desc {
  font-size: 12px;
  color: #c6d2ef;
  margin-top: 2px;
  /* 更通透的磨砂底上保护小字对比 */
  text-shadow: 0 1px 2px rgba(4, 8, 24, 0.55);
}

/* 操作按钮 */
.about-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
  margin-bottom: 32px;
}

/* 渐变背景上的按钮：遵循设计规范 §5.7（白底主按钮 + 毛玻璃次按钮） */
.n-button.about-btn-primary {
  background-color: rgba(255, 255, 255, 0.95);
  color: #4C6FFF;
  font-weight: 700;
  letter-spacing: 0.3px;
  border: none;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.3), 0 4px 20px rgba(0, 0, 0, 0.2);
  transition: all 0.2s ease;
}
.n-button.about-btn-primary:hover,
.n-button.about-btn-primary:focus {
  background-color: #ffffff;
  color: #4C6FFF;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.45), 0 6px 24px rgba(0, 0, 0, 0.22);
  transform: translateY(-1px);
}
.n-button.about-btn-ghost {
  background-color: rgba(255, 255, 255, 0.15);
  color: #ffffff;
  font-weight: 700;
  letter-spacing: 0.3px;
  border: 1.5px solid rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1);
  transition: all 0.2s ease;
}
.n-button.about-btn-ghost:hover,
.n-button.about-btn-ghost:focus {
  background-color: rgba(255, 255, 255, 0.25);
  border-color: rgba(255, 255, 255, 0.8);
  color: #ffffff;
}
/* Naive 的描边由内部两个元素绘制，隐藏以免与外发光叠成两圈（规范 §5.7 踩坑记录） */
.about-btn-primary :deep(.n-button__border),
.about-btn-primary :deep(.n-button__state-border),
.about-btn-ghost :deep(.n-button__border),
.about-btn-ghost :deep(.n-button__state-border) {
  display: none;
}
.about-btn-primary :deep(.n-button__icon),
.about-btn-ghost :deep(.n-button__icon) {
  margin-right: 8px;
}

/* 减少透明度：毛玻璃回退为实色（规范 §4.2） */
@media (prefers-reduced-transparency: reduce) {
  .about-quote-box,
  .feature-item {
    background: #1b2552;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
  .n-button.about-btn-ghost {
    background-color: #26366f;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

/* 底部 */
.about-footer {
  font-size: 13px;
  color: #dcebfb;
  border-top: 1px solid rgba(255, 255, 255, 0.25);
  padding-top: 20px;
}
.about-brand {
  font-weight: 700;
  color: #ffffff;
}
.about-divider {
  margin: 0 8px;
}
.about-credit {
  margin-top: 8px;
  font-size: 12px;
  color: #c4dcf5;
}
.about-credit-link {
  color: #a5f3fc;
  text-decoration: none;
  transition: color 0.2s ease;
}
.about-credit-link:hover {
  color: #ffffff;
}

@media (max-width: 640px) {
  .about-content { padding: 24px 20px; }
  .about-title { font-size: 32px; }
  .about-subtitle { font-size: 16px; }
  .about-quote { font-size: 13px; }
  .about-quote-title { font-size: 14px; margin-bottom: 10px; }
  .about-quote-box { padding: 16px 20px; }
  .features { grid-template-columns: 1fr; }
  .about-actions {
    flex-direction: column;
    align-items: center;
  }
}

/* ===== 悬浮召唤按钮 ===== */
.summon-cat-btn {
  position: fixed;
  right: 36px;
  bottom: 36px;
  z-index: 90;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 22px;
  border: none;
  border-radius: 9999px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  box-shadow: 0 4px 20px rgba(102, 126, 234, 0.45);
  transition: transform 0.25s ease, box-shadow 0.25s ease;
  animation: summon-pulse 2.8s ease-in-out infinite;
}
.summon-cat-btn:hover {
  transform: translateY(-2px) scale(1.04);
  box-shadow: 0 8px 28px rgba(118, 75, 162, 0.6);
}
.summon-cat-btn:active {
  transform: translateY(0) scale(0.98);
}
.summon-cat-btn__icon {
  font-size: 18px;
  display: inline-block;
  animation: paw-wiggle 1.6s ease-in-out infinite;
}
@keyframes summon-pulse {
  0%, 100% { box-shadow: 0 4px 20px rgba(102, 126, 234, 0.35); }
  50% { box-shadow: 0 4px 28px rgba(118, 75, 162, 0.65); }
}
@keyframes paw-wiggle {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(-12deg); }
  75% { transform: rotate(12deg); }
}

@media (max-width: 640px) {
  .summon-cat-btn {
    right: 16px;
    bottom: 16px;
    padding: 10px 16px;
    font-size: 13px;
  }
}

/* 减少动画：冻结背景动效，但保留静态高光，夜空不发平 */
@media (prefers-reduced-motion: reduce) {
  .nebula-band,
  .orb,
  .ambient-core,
  .star,
  .star.has-cross,
  .shooting-star,
  .planet-ring,
  .planet-orbit {
    animation: none !important;
  }
  .ambient-core { opacity: 1; }
  .orb { opacity: 0.3; }
  /* 减少动画下用各自"呼吸稳态值"钉住透明度，静态夜空与动效夜空观感一致，
     不会因动画关闭而退回基础 opacity 1.0 的过曝满亮。 */
  .star { opacity: var(--star-opacity, 0.55); }
  .star.has-cross { opacity: var(--star-opacity, 0.7); }
  .nebula-band { opacity: var(--base-opacity, 0.85); }
}
</style>
