<script setup lang="ts">
import { NButton, NIcon, NTooltip } from 'naive-ui'
import { ArrowBackOutline } from '@vicons/ionicons5'
import { useRouter } from 'vue-router'

const router = useRouter()

withDefaults(defineProps<{
  title: string
  subtitle?: string
  backTo?: string
  backLabel?: string
  /**
   * 紧凑变体：垂直 padding 压缩至 12px、副标题内联为标题旁 12px 灰字。
   * 供需要最大化内容区高度的页面（如基因组浏览器）使用；默认 false，其余页面行为不变。
   */
  compact?: boolean
}>(), {
  subtitle: '',
  backTo: '',
  backLabel: '返回上一页',
  compact: false,
})
</script>

<template>
  <header class="page-header" :class="{ 'page-header--compact': compact }">
    <div class="page-header-main">
      <NTooltip v-if="backTo" placement="bottom" :delay="300">
        <template #trigger>
          <NButton
            circle
            secondary
            size="large"
            class="page-header-back"
            :aria-label="backLabel"
            @click="router.push(backTo)"
          >
            <template #icon><NIcon :size="22"><ArrowBackOutline /></NIcon></template>
          </NButton>
        </template>
        {{ backLabel }}
      </NTooltip>
      <div v-if="$slots.leading" class="page-header-leading">
        <slot name="leading" />
      </div>
      <div class="page-header-copy">
        <h1>{{ title }}</h1>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
    </div>
    <div v-if="$slots.actions" class="page-header-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}

.page-header-main {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}

.page-header-back {
  flex: 0 0 auto;
}

.page-header-leading {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  padding-top: 2px;
}

.page-header-copy h1 {
  margin: 0;
  color: var(--text-primary);
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.33;
}

.page-header-copy p {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.57;
}

.page-header-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
}

/* ===== 紧凑变体（仅显式传入 compact 的页面生效）===== */
.page-header--compact {
  align-items: center;
  margin-bottom: 0;
  padding: 12px 0;
}

.page-header--compact .page-header-copy {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.page-header--compact .page-header-copy h1 {
  flex: 0 0 auto;
}

.page-header--compact .page-header-copy p {
  margin: 0;
  min-width: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-tertiary, var(--text-secondary));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
    gap: 12px;
  }

  .page-header-actions {
    width: 100%;
  }

  /* 紧凑变体：窄屏下副标题允许换行到标题下方，避免被过度省略 */
  .page-header--compact .page-header-copy {
    flex-wrap: wrap;
    row-gap: 2px;
  }

  .page-header--compact .page-header-copy p {
    flex-basis: 100%;
    white-space: normal;
  }
}
</style>
