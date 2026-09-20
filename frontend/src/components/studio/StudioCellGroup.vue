<script setup lang="ts">
/**
 * StudioCellGroup — cell 时间线的一个 cell 组（WP3 任务 1）
 *
 * 头部显示 cell 序号 [1]/[2]… 与语言徽标，组间以视觉分隔（左边条 + 间距）区分；
 * 组内卡片沿用现有 ToolCallEntry 分发渲染（卡片内部实现不变，只改组织方式）。
 */
defineProps<{
  cellIndex: number
  language: string | null
}>()
</script>

<template>
  <section class="studio-cell-group">
    <header class="cell-group-header">
      <span class="cell-index">[{{ cellIndex }}]</span>
      <span v-if="language" class="cell-language">{{ language }}</span>
      <span class="cell-spacer" />
      <slot name="header-extra" />
    </header>
    <div class="cell-group-body">
      <slot />
    </div>
  </section>
</template>

<style scoped lang="scss">
.studio-cell-group {
  margin-top: 10px;
  border-left: 3px solid var(--chat-accent, #4f8ef7);
  border-radius: 0 8px 8px 0;
  background: color-mix(in srgb, var(--chat-accent, #4f8ef7) 4%, transparent);
  padding: 2px 0 8px;
}
.cell-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px 2px;
}
.cell-index {
  font-size: 11px;
  font-weight: 700;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: var(--chat-accent, #4f8ef7);
}
.cell-language {
  font-size: 10px;
  padding: 0 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--chat-accent, #4f8ef7) 12%, transparent);
  color: var(--chat-accent, #4f8ef7);
}
.cell-spacer { flex: 1; }
.cell-group-body {
  display: flex;
  flex-direction: column;
}
/* cell 组内卡片与组头的间距：卡片自带 margin-top，首卡贴头即可 */
.cell-group-body :deep(.studio-code-card:first-child) {
  margin-top: 6px;
}
</style>
