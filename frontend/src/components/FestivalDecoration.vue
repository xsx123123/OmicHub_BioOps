<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  decoration: string
  themeColor?: string
  phenology?: string
}

const props = withDefaults(defineProps<Props>(), {
  themeColor: '#9fb7d7',
  phenology: '',
})

const decorationClass = computed(() => `decoration-${props.decoration}`)
const phenologyClass = computed(() => (props.phenology ? `phenology-${props.phenology}` : ''))
const decorationStyle = computed(() => ({ '--decoration-color': props.themeColor }))

const nodes = Array.from({ length: 9 }, (_, index) => ({
  id: index,
  left: `${(index * 23 + 9) % 100}%`,
  top: `${(index * 31 + 13) % 100}%`,
  size: `${18 + (index % 4) * 12}px`,
  delay: `${(index % 5) * 0.42}s`,
}))

const threads = Array.from({ length: 6 }, (_, index) => ({
  id: index,
  left: `${8 + index * 17}%`,
  top: `${16 + (index % 3) * 19}%`,
  delay: `${index * 0.28}s`,
  rotation: `${-18 + index * 7}deg`,
}))
</script>

<template>
  <div class="festival-decoration" :class="[decorationClass, phenologyClass]" :style="decorationStyle">
    <div class="texture-lattice" />
    <div class="motif motif-primary" />
    <div class="motif motif-secondary" />
    <div class="motif motif-tertiary" />

    <span
      v-for="node in nodes"
      :key="node.id"
      class="soft-node"
      :style="{
        left: node.left,
        top: node.top,
        width: node.size,
        height: node.size,
        animationDelay: node.delay,
      }"
    />

    <span
      v-for="thread in threads"
      :key="thread.id"
      class="light-thread"
      :style="{
        left: thread.left,
        top: thread.top,
        rotate: thread.rotation,
        animationDelay: thread.delay,
      }"
    />
  </div>
</template>

<style scoped>
.festival-decoration {
  --decoration-color: #9fb7d7;
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
  border-radius: inherit;
  color: var(--decoration-color);
}

.texture-lattice {
  position: absolute;
  inset: 1px;
  border-radius: inherit;
  opacity: 0.18;
  mix-blend-mode: soft-light;
  background-image:
    linear-gradient(color-mix(in srgb, var(--decoration-color) 22%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--decoration-color) 16%, transparent) 1px, transparent 1px);
  background-size: 42px 42px, 42px 42px;
  mask-image: radial-gradient(circle at 50% 38%, black 0%, transparent 74%);
  animation: latticeDrift 18s cubic-bezier(0.22, 1, 0.36, 1) infinite alternate;
}

.motif,
.soft-node,
.light-thread {
  position: absolute;
  display: block;
}

.motif {
  border: 1px solid color-mix(in srgb, var(--decoration-color) 34%, transparent);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 0 38px color-mix(in srgb, var(--decoration-color) 18%, transparent);
  opacity: 0.42;
  filter: blur(0.15px);
  animation: motifBreathe 9s cubic-bezier(0.2, 0.8, 0.2, 1) infinite alternate;
}

.motif-primary {
  top: -92px;
  right: -72px;
  width: 240px;
  height: 240px;
  border-radius: 50%;
  background: radial-gradient(circle at 34% 32%, color-mix(in srgb, var(--decoration-color) 16%, transparent), transparent 58%);
}

.motif-secondary {
  left: -80px;
  bottom: -92px;
  width: 250px;
  height: 180px;
  border-radius: 48% 52% 58% 42%;
  background: radial-gradient(circle at 66% 42%, color-mix(in srgb, var(--decoration-color) 13%, transparent), transparent 64%);
  animation-delay: -2.8s;
}

.motif-tertiary {
  left: 50%;
  top: 9%;
  width: 280px;
  height: 76px;
  border-radius: 999px;
  transform: translateX(-50%) rotate(-7deg);
  border-color: color-mix(in srgb, var(--decoration-color) 20%, transparent);
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--decoration-color) 12%, transparent), transparent);
  filter: blur(8px);
  opacity: 0.24;
}

.soft-node {
  border-radius: 999px;
  background: radial-gradient(circle, color-mix(in srgb, var(--decoration-color) 34%, rgba(255,255,255,0.24)) 0%, transparent 68%);
  opacity: 0.16;
  filter: blur(7px);
  mix-blend-mode: screen;
  animation: nodeBreathe 8.5s cubic-bezier(0.22, 1, 0.36, 1) infinite alternate;
}

.light-thread {
  width: 78px;
  height: 1px;
  transform-origin: left center;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--decoration-color) 44%, rgba(255,255,255,0.4)), transparent);
  opacity: 0.22;
  filter: blur(0.2px);
  animation: threadFloat 10s cubic-bezier(0.2, 0.8, 0.2, 1) infinite alternate;
}

.decoration-spring_couplets .motif-primary,
.decoration-dawn_banner .motif-primary,
.decoration-national_banner .motif-primary {
  border-radius: 34% 66% 46% 54%;
  transform: rotate(-14deg);
}
.decoration-spring_couplets .motif-secondary,
.decoration-national_banner .motif-secondary {
  width: 310px;
  height: 86px;
  border-radius: 999px;
  transform: rotate(-12deg);
}

.decoration-lanterns .motif-primary,
.decoration-moon_rabbit .motif-primary,
.decoration-snowflake .motif-primary {
  border-radius: 50%;
  background:
    radial-gradient(circle at 42% 36%, rgba(255,255,255,0.16), transparent 22%),
    radial-gradient(circle, color-mix(in srgb, var(--decoration-color) 13%, transparent), transparent 63%);
}
.decoration-lanterns .motif-tertiary,
.decoration-moon_rabbit .motif-tertiary {
  opacity: 0.36;
  filter: blur(3px);
}

.decoration-bamboo .motif-tertiary,
.decoration-sprout .motif-tertiary {
  width: 190px;
  height: 190px;
  border-radius: 44% 56% 48% 52%;
  transform: translateX(-50%) rotate(22deg) skewY(-8deg);
}
.decoration-bamboo .light-thread,
.decoration-sprout .light-thread {
  height: 64px;
  width: 1px;
  background: linear-gradient(180deg, transparent, color-mix(in srgb, var(--decoration-color) 42%, rgba(255,255,255,0.24)), transparent);
}

.decoration-stars_heart .motif-primary,
.decoration-hearts .motif-primary,
.decoration-galaxy .motif-primary {
  border-radius: 50%;
  transform: rotate(-18deg) scaleX(1.42);
  background: radial-gradient(circle at 50% 50%, transparent 42%, color-mix(in srgb, var(--decoration-color) 12%, transparent) 58%, transparent 72%);
}
.decoration-stars_heart .motif-secondary,
.decoration-hearts .motif-secondary,
.decoration-galaxy .motif-secondary {
  border-radius: 50%;
  transform: rotate(18deg) scaleX(1.26);
}

.decoration-chrysanthemum .motif-primary,
.decoration-maple .motif-primary {
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background:
    repeating-conic-gradient(from 22deg, color-mix(in srgb, var(--decoration-color) 14%, transparent) 0 7deg, transparent 7deg 18deg),
    radial-gradient(circle, transparent 0 42%, color-mix(in srgb, var(--decoration-color) 10%, transparent) 44%, transparent 68%);
  mask-image: radial-gradient(circle, transparent 0 28%, black 34%, transparent 76%);
}

.decoration-tools .texture-lattice,
.decoration-terminal .texture-lattice {
  opacity: 0.25;
  background-size: 24px 24px, 24px 24px;
  mask-image: linear-gradient(transparent, black 20%, black 80%, transparent);
}
.decoration-tools .motif-tertiary,
.decoration-terminal .motif-tertiary {
  height: 120px;
  border-radius: 18px;
  filter: blur(0.2px);
  transform: translateX(-50%) rotate(0deg);
  background: linear-gradient(135deg, color-mix(in srgb, var(--decoration-color) 10%, transparent), transparent);
}

.decoration-christmas_tree .motif-tertiary,
.decoration-snowflake .motif-tertiary,
.decoration-snowflake .motif-secondary {
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--decoration-color) 18%, transparent), rgba(255,255,255,0.08), transparent);
  filter: blur(12px);
}

.decoration-sun .motif-primary {
  border-radius: 50%;
  background: radial-gradient(circle, color-mix(in srgb, var(--decoration-color) 16%, rgba(255,255,255,0.10)), transparent 58%);
}
.decoration-sun .motif-secondary {
  border-radius: 50%;
  background: conic-gradient(from 0deg, transparent, color-mix(in srgb, var(--decoration-color) 12%, transparent), transparent, color-mix(in srgb, var(--decoration-color) 10%, transparent), transparent);
  opacity: 0.22;
}

.phenology-rain-ripple .motif-tertiary,
.phenology-clear-rain .motif-tertiary,
.phenology-grain-rain .motif-tertiary,
.phenology-rice-rain .motif-tertiary {
  width: 320px;
  height: 118px;
  border-radius: 999px;
  border-color: color-mix(in srgb, var(--decoration-color) 22%, transparent);
  background: repeating-radial-gradient(ellipse at center, transparent 0 18px, color-mix(in srgb, var(--decoration-color) 14%, transparent) 19px 20px, transparent 21px 38px);
  filter: blur(1px);
}
.phenology-rain-ripple .light-thread,
.phenology-clear-rain .light-thread,
.phenology-snow-mist .light-thread {
  width: 1px;
  height: 86px;
  background: linear-gradient(180deg, transparent, color-mix(in srgb, var(--decoration-color) 38%, rgba(255,255,255,0.22)), transparent);
}
.phenology-thunder-crack .motif-tertiary {
  width: 260px;
  height: 120px;
  border-radius: 16px;
  clip-path: polygon(0 44%, 36% 44%, 26% 8%, 82% 54%, 48% 54%, 62% 96%);
  background: color-mix(in srgb, var(--decoration-color) 20%, transparent);
  filter: blur(5px);
}
.phenology-spring-sprout .motif-tertiary,
.phenology-wheat-fill .motif-tertiary,
.phenology-rice-wheat-fill .motif-tertiary,
.phenology-awn-seed .motif-tertiary,
.phenology-wheat-awn-seed .motif-tertiary,
.phenology-lotus-breath .motif-tertiary,
.phenology-tomato-vine .motif-tertiary,
.phenology-lotus-heat .motif-tertiary {
  width: 210px;
  height: 210px;
  border-radius: 58% 42% 56% 44%;
  transform: translateX(-50%) rotate(28deg) skewY(-10deg);
  background:
    radial-gradient(ellipse at 42% 28%, color-mix(in srgb, var(--decoration-color) 18%, transparent), transparent 48%),
    linear-gradient(140deg, transparent 0 48%, color-mix(in srgb, var(--decoration-color) 18%, transparent) 49% 51%, transparent 52%);
}
.phenology-frost-vein .texture-lattice,
.phenology-ice-ring .texture-lattice,
.phenology-cold-ridge .texture-lattice,
.phenology-cold-dew .texture-lattice,
.phenology-winter-mist .texture-lattice,
.phenology-snow-field .texture-lattice {
  opacity: 0.24;
  background-image:
    linear-gradient(34deg, transparent 0 42%, color-mix(in srgb, var(--decoration-color) 24%, transparent) 43% 44%, transparent 45%),
    linear-gradient(116deg, transparent 0 58%, color-mix(in srgb, var(--decoration-color) 18%, transparent) 59% 60%, transparent 61%);
  background-size: 82px 82px, 128px 128px;
}
.phenology-moon-tide .motif-primary,
.phenology-yang-return .motif-primary,
.phenology-solar-arc .motif-primary,
.phenology-lantern-orbit .motif-primary {
  border-radius: 50%;
  background:
    radial-gradient(circle at 42% 36%, rgba(255,255,255,0.18), transparent 18%),
    radial-gradient(circle, transparent 42%, color-mix(in srgb, var(--decoration-color) 16%, transparent) 46%, transparent 68%);
}
.phenology-mountain-dawn .motif-secondary,
.phenology-autumn-leaf .motif-secondary,
.phenology-autumn-balance .motif-secondary,
.phenology-chrysanthemum-slope .motif-secondary {
  width: 330px;
  height: 118px;
  border-radius: 18px 18px 42px 42px;
  background:
    linear-gradient(135deg, transparent 0 48%, color-mix(in srgb, var(--decoration-color) 14%, transparent) 49% 50%, transparent 51%),
    linear-gradient(45deg, transparent 0 58%, color-mix(in srgb, var(--decoration-color) 10%, transparent) 59% 60%, transparent 61%);
}
.phenology-star-bridge .motif-primary,
.phenology-nebula-orbit .motif-primary,
.phenology-silk-knot .motif-primary {
  transform: rotate(-18deg) scaleX(1.52);
  border-radius: 50%;
  background: radial-gradient(circle at 50% 50%, transparent 42%, color-mix(in srgb, var(--decoration-color) 14%, transparent) 58%, transparent 74%);
}

@keyframes motifBreathe {
  0% { opacity: 0.28; transform: translate3d(0, 0, 0) scale(0.985); }
  100% { opacity: 0.48; transform: translate3d(-5px, 7px, 0) scale(1.018); }
}

@keyframes nodeBreathe {
  0% { opacity: 0.08; transform: translate3d(0, 0, 0) scale(0.92); }
  100% { opacity: 0.2; transform: translate3d(8px, -10px, 0) scale(1.08); }
}

@keyframes threadFloat {
  0% { opacity: 0.12; transform: translate3d(0, 0, 0) scaleX(0.86); }
  100% { opacity: 0.3; transform: translate3d(8px, -8px, 0) scaleX(1.04); }
}

@keyframes latticeDrift {
  0% { background-position: 0 0, 0 0; opacity: 0.12; }
  100% { background-position: 18px -14px, -12px 16px; opacity: 0.22; }
}

@media (max-width: 640px) {
  .motif-primary { width: 190px; height: 190px; }
  .motif-secondary { width: 200px; height: 150px; }
  .motif-tertiary { width: 210px; }
  .soft-node { filter: blur(8px); }
}

@media (prefers-reduced-motion: reduce) {
  .festival-decoration *,
  .festival-decoration *::before,
  .festival-decoration *::after {
    animation: none !important;
  }
}
</style>
