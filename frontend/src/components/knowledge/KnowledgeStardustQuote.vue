<template>
  <figure class="knowledge-stardust-quote" aria-label="卡尔·萨根引言">
    <span class="quote-orbit quote-orbit--one" aria-hidden="true" />
    <span class="quote-orbit quote-orbit--two" aria-hidden="true" />
    <span class="quote-star quote-star--one" aria-hidden="true" />
    <span class="quote-star quote-star--two" aria-hidden="true" />
    <span class="quote-star quote-star--three" aria-hidden="true" />

    <div class="quote-content">
      <div class="quote-kicker">FROM STARDUST, TO DISCOVERY</div>
      <blockquote>
        <p class="quote-lead">We are made of star-stuff.</p>
        <p>
          我们只是借用了宇宙中的这些碳、氢、氧原子几十年，用它们去短暂地体验了一次这个世界。组成我们大脑和身体的每一个原子，都来自几十亿年前远古恒星内部的核聚变爆炸。当生命结束时，我们并没有化为虚无，我们只是回到了那个浩瀚的宇宙中，换了一种方式继续存在。
        </p>
      </blockquote>
      <figcaption>—— 卡尔·萨根 <cite>（Carl Sagan）</cite></figcaption>
    </div>
  </figure>
</template>

<style scoped>
.knowledge-stardust-quote {
  --quote-accent: var(--stardust-blue);
  --quote-accent-soft: var(--stardust-bg-soft);
  --quote-border: var(--stardust-border-soft);
  --quote-glow: var(--stardust-glow);
  position: relative;
  isolation: isolate;
  overflow: hidden;
  margin: 4px 0 36px;
  padding: 32px 44px 30px;
  border: 1px solid var(--quote-border);
  border-radius: var(--radius-card);
  background:
    radial-gradient(circle at 92% 12%, var(--quote-glow), transparent 24%),
    radial-gradient(circle at 4% 100%, var(--quote-accent-soft), transparent 34%),
    var(--neutral-card);
  box-shadow: var(--stardust-card-shadow);
}

.knowledge-stardust-quote::before {
  position: absolute;
  z-index: -1;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(118deg, transparent 4%, var(--quote-accent-soft) 48%, transparent 80%);
  background-size: 220% 100%;
  content: '';
  opacity: 0.55;
  animation: quote-light-sweep 14s linear infinite;
}

.quote-content {
  position: relative;
  z-index: 1;
  max-width: 880px;
}

.quote-kicker {
  margin-bottom: 14px;
  color: var(--quote-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
}

blockquote {
  position: relative;
  margin: 0;
  padding-left: 25px;
  border: 0;
}

blockquote::before {
  position: absolute;
  top: -14px;
  left: -3px;
  color: var(--quote-accent);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 64px;
  font-weight: 700;
  line-height: 1;
  content: '“';
  opacity: 0.72;
}

blockquote::after {
  position: absolute;
  top: 8px;
  bottom: 7px;
  left: 0;
  width: 2px;
  border-radius: 999px;
  background: linear-gradient(to bottom, transparent, var(--quote-accent), transparent);
  content: '';
  transform-origin: center;
  animation: quote-rail-pulse 4.8s ease-in-out infinite;
}

.quote-lead {
  margin: 0 0 10px;
  color: var(--neutral-text-1);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: clamp(22px, 2.2vw, 30px);
  font-style: italic;
  font-weight: 600;
  letter-spacing: -0.025em;
  line-height: 1.24;
}

blockquote p:not(.quote-lead) {
  max-width: 760px;
  margin: 0;
  color: var(--neutral-text-2);
  font-size: 15px;
  line-height: 1.9;
}

figcaption {
  margin-top: 18px;
  padding-left: 25px;
  color: var(--neutral-text-2);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-align: right;
}

cite {
  color: var(--neutral-text-3);
  font-style: normal;
  font-weight: 400;
}

.quote-orbit,
.quote-star {
  position: absolute;
  z-index: 0;
  pointer-events: none;
}

.quote-orbit {
  border: 1px solid var(--quote-border);
  border-radius: 50%;
}

.quote-orbit--one {
  top: -126px;
  right: -88px;
  width: 300px;
  height: 300px;
  animation: quote-orbit-drift 18s ease-in-out infinite;
}

.quote-orbit--two {
  right: 86px;
  bottom: -160px;
  width: 260px;
  height: 260px;
  opacity: 0.72;
  animation: quote-orbit-drift 22s ease-in-out infinite reverse;
}

.quote-star {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--quote-accent);
  box-shadow: 0 0 0 3px var(--quote-accent-soft), 0 0 14px var(--quote-glow);
  animation: quote-star-twinkle 3.8s ease-in-out infinite;
}

.quote-star--one {
  top: 24px;
  right: 56px;
}

.quote-star--two {
  top: 112px;
  right: 146px;
  animation-delay: -1.4s;
}

.quote-star--three {
  right: 26px;
  bottom: 38px;
  animation-delay: -2.3s;
}

@keyframes quote-light-sweep {
  from { background-position: 180% 0; }
  to { background-position: -80% 0; }
}

@keyframes quote-rail-pulse {
  0%, 100% { opacity: 0.45; transform: scaleY(0.82); }
  50% { opacity: 1; transform: scaleY(1); }
}

@keyframes quote-orbit-drift {
  0%, 100% { transform: translate3d(0, 0, 0) rotate(0deg); }
  50% { transform: translate3d(-8px, 7px, 0) rotate(5deg); }
}

@keyframes quote-star-twinkle {
  0%, 100% { opacity: 0.28; transform: scale(0.72); }
  50% { opacity: 1; transform: scale(1.18); }
}

@media (max-width: 680px) {
  .knowledge-stardust-quote {
    margin-bottom: 28px;
    padding: 26px 24px 24px;
  }

  .quote-kicker {
    font-size: 10px;
  }

  blockquote {
    padding-left: 20px;
  }

  blockquote p:not(.quote-lead) {
    font-size: 14px;
    line-height: 1.82;
  }

  figcaption {
    padding-left: 20px;
  }

  .quote-orbit--one {
    right: -146px;
  }

  .quote-orbit--two,
  .quote-star--two {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .knowledge-stardust-quote::before,
  blockquote::after,
  .quote-orbit,
  .quote-star {
    animation: none;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .knowledge-stardust-quote {
    background: var(--neutral-card);
  }

  .knowledge-stardust-quote::before,
  .quote-orbit,
  .quote-star {
    display: none;
  }
}

@media (forced-colors: active) {
  .knowledge-stardust-quote {
    border-color: CanvasText;
    box-shadow: none;
  }

  .quote-kicker,
  .quote-lead {
    color: CanvasText;
  }
}
</style>
