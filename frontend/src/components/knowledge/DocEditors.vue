<script setup lang="ts">
import { computed } from 'vue'
import { NAvatar, NSpace, NTag } from 'naive-ui'
import type { DocEditorInfo } from '@/types/knowledge'

const props = defineProps<{
  editors: DocEditorInfo[]
}>()

const MAX_VISIBLE = 3

const visibleEditors = computed(() => props.editors.slice(0, MAX_VISIBLE))
const hiddenCount = computed(() => Math.max(0, props.editors.length - MAX_VISIBLE))

function initials(name: string): string {
  return name.slice(0, 1).toUpperCase()
}
</script>

<template>
  <div class="doc-editors">
    <div class="section-title">👤 贡献者</div>
    <NSpace align="center" size="medium" wrap>
      <div
        v-for="editor in visibleEditors"
        :key="editor.userName"
        class="editor-card"
      >
        <NAvatar round size="small">{{ initials(editor.userName) }}</NAvatar>
        <div class="editor-info">
          <div class="editor-name">{{ editor.userName }}</div>
          <div class="editor-count">{{ editor.editCount }} 次编辑</div>
        </div>
      </div>
      <NTag v-if="hiddenCount > 0" round>+{{ hiddenCount }}</NTag>
    </NSpace>
  </div>
</template>

<style scoped>
.doc-editors {
  margin-top: 32px;
  padding-top: 24px;
  border-top: 1px solid var(--neutral-border);
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin-bottom: 12px;
}

.editor-card {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--neutral-hover);
  border-radius: 8px;
}

.editor-info {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.editor-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-text-1);
}

.editor-count {
  font-size: 12px;
  color: var(--neutral-text-3);
}
</style>
