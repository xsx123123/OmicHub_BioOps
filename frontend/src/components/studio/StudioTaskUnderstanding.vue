<script setup lang="ts">
import type { StudioTaskUnderstanding } from '@/utils/studioPresentation'

defineProps<{ understanding: StudioTaskUnderstanding }>()
</script>

<template>
  <section class="task-understanding" aria-label="任务理解">
    <div class="understanding-heading">
      <span class="understanding-mark" aria-hidden="true">✦</span>
      <div><strong>任务理解</strong><span>已从你的研究目标中提取</span></div>
      <span class="understanding-status">{{ understanding.status }}</span>
    </div>
    <dl>
      <div><dt>任务</dt><dd>{{ understanding.task }}</dd></div>
      <div><dt>领域</dt><dd>{{ understanding.domain }}</dd></div>
      <div><dt>目标</dt><dd>{{ understanding.goal }}</dd></div>
    </dl>
  </section>
</template>

<style scoped>
.task-understanding { box-sizing: border-box; margin: 4px 24px 18px; padding: 14px 16px; border: 1px solid var(--border-subtle, var(--chat-border)); border-radius: 14px; background: var(--surface-card, var(--chat-surface)); box-shadow: var(--shadow-sm, 0 6px 20px rgba(30, 50, 100, .06)); }
.understanding-heading { display: flex; align-items: center; gap: 10px; }
.understanding-heading div { display: flex; flex-direction: column; min-width: 0; }
.understanding-heading strong { font-size: 13px; color: var(--text-primary, var(--chat-text-primary)); }
.understanding-heading div span { font-size: 11px; color: var(--text-tertiary, var(--chat-text-muted)); }
.understanding-mark { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 10px; background: var(--brand-primary-light, var(--chat-surface-hover)); color: var(--brand-primary, var(--stardust-blue)); }
.understanding-status { margin-left: auto; padding: 3px 8px; border-radius: 999px; background: var(--success-bg, var(--chat-surface-hover)); color: var(--success-color, var(--brand-primary)); font-size: 11px; white-space: nowrap; }
dl { display: grid; gap: 7px; margin: 12px 0 0; }
dl div { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 8px; }
dt { color: var(--text-tertiary, var(--chat-text-muted)); font-size: 11px; }
dd { margin: 0; color: var(--text-secondary, var(--chat-text-secondary)); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
</style>
