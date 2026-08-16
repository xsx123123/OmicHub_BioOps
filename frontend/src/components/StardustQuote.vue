<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(defineProps<{
  placement?: 'overlay' | 'flow'
}>(), {
  placement: 'overlay',
})

const expanded = ref(false)

function toggleExpanded() {
  expanded.value = !expanded.value
}

function collapse() {
  expanded.value = false
}
</script>

<template>
  <div
    class="stardust-quote"
    :class="`stardust-quote--${props.placement}`"
    @mouseleave="collapse"
  >
    <button
      type="button"
      class="quote-en gilded breathe quote-trigger"
      @click="toggleExpanded"
      :aria-expanded="expanded"
      aria-controls="stardust-quote-detail"
      title="点击展开完整星尘引言，鼠标移开后自动收起"
    >
      "We are made of star-stuff"
    </button>
    <button
      type="button"
      class="quote-cn-short quote-trigger"
      @click="toggleExpanded"
      :aria-expanded="expanded"
      aria-controls="stardust-quote-detail"
    >
      我们只是借用了宇宙中的这些原子，短暂地体验了一次这个世界。
    </button>
    <div id="stardust-quote-detail" class="quote-cn-full" :class="{ expanded }">
      我们只是借用了宇宙中的这些碳、氢、氧原子几十年，用它们去短暂地体验了一次这个世界。
      组成我们大脑和身体的每一个原子，都来自几十亿年前远古恒星内部的核聚变爆炸。
      当生命结束时，我们并没有化为虚无，我们只是回到了那个浩瀚的宇宙中，换了一种方式继续存在。
    </div>
  </div>
</template>

<style scoped>
.stardust-quote {
  position: absolute;
  bottom: 32px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  text-align: center;
  max-width: 720px;
  padding: 0 24px;
  opacity: 1;
  pointer-events: auto;
}

.quote-trigger {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  font: inherit;
  text-align: inherit;
  cursor: pointer;
  transition: opacity 180ms ease-out, transform 180ms ease-out;
}
.quote-trigger:hover {
  opacity: 1;
  transform: scale(1.015);
}

.quote-trigger:focus-visible {
  outline: 2px solid rgba(181, 210, 255, 0.92);
  outline-offset: 5px;
  border-radius: 6px;
}

.quote-en {
  font-size: 13px;
  font-weight: 500;
  font-style: italic;
  letter-spacing: 1.5px;
  margin-bottom: 6px;
  font-family: Georgia, 'Times New Roman', serif;
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
  animation: shimmer 10s linear infinite;
  text-shadow: none;
  filter: drop-shadow(0 0 12px rgba(112, 181, 255, 0.78));
}

.breathe {
  animation: shimmer 10s linear infinite, breathe-glow 6s ease-in-out infinite;
}

.breathe-delayed {
  animation: shimmer 10s linear infinite, breathe-glow 6s ease-in-out infinite 1.5s;
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

.quote-cn-short {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.8;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  margin-bottom: 4px;
}
.quote-cn-short:hover {
  color: #ffffff;
}

.quote-cn-full {
  font-size: 13px;
  color: #ffffff;
  font-weight: 600;
  line-height: 1.9;
  text-shadow:
    0 1px 2px rgba(0, 0, 0, 0.5),
    0 2px 8px rgba(0, 0, 0, 0.4),
    0 0 12px rgba(0, 0, 0, 0.3);
  max-height: 0;
  opacity: 0;
  overflow: hidden;
  transition: max-height 0.6s ease, opacity 0.4s ease, margin-top 0.3s ease;
  margin-top: 0;
}

.quote-cn-full.expanded {
  max-height: 200px;
  opacity: 1;
  margin-top: 10px;
}

.stardust-quote--flow {
  position: relative;
  bottom: auto;
  left: auto;
  transform: none;
  flex: 0 0 auto;
  margin: 0 auto;
}

@media (prefers-reduced-motion: reduce) {
  .gilded,
  .breathe {
    animation: none;
  }

  .quote-trigger,
  .quote-cn-full {
    transition-duration: 1ms;
  }
}

@media (max-width: 768px) {
  .stardust-quote {
    bottom: 16px;
    max-width: 90%;
  }
  .quote-cn-short {
    font-size: 11px;
  }
  .quote-cn-full {
    font-size: 11px;
    font-weight: 600;
  }
}
</style>
