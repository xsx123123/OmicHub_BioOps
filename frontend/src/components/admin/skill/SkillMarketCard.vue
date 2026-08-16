<script setup lang="ts">
import { NButton, NIcon, NTag, NSwitch, NTooltip, NPopconfirm } from 'naive-ui'
import {
  RefreshOutline, TimeOutline, TrashOutline, TerminalOutline,
} from '@vicons/ionicons5'
import type { SkillMarketplaceItem } from '@/types/skill'
import type { SkillItem } from '@/types/agent'

const props = defineProps<{
  item: SkillMarketplaceItem | SkillItem
  installing?: boolean
  /** installed skill management mode */
  managed?: boolean
}>()

const emit = defineEmits<{
  install: []
  toggle: []
  delete: []
  checkUpdate: []
  versions: []
  invocations: []
}>()

const SOURCE_LABELS: Record<string, string> = {
  builtin: '平台内置',
  aliyun_official: '阿里云官方',
  github: 'GitHub',
  zip: 'ZIP',
  markdown: 'Markdown',
  json: 'JSON',
  market: '市场',
}

function isMarketItem(item: SkillMarketplaceItem | SkillItem): item is SkillMarketplaceItem {
  return 'installed' in item
}

const source = () => {
  const it = props.item
  if (isMarketItem(it)) return it.source ?? 'builtin'
  return it.source ?? 'builtin'
}
</script>

<template>
  <div class="skill-market-card">
    <div class="card-icon">{{ item.icon }}</div>
    <div class="card-body">
      <div class="card-head">
        <span class="card-name">{{ item.name }}</span>
        <NTag size="tiny" :bordered="false" :type="source() === 'aliyun_official' ? 'info' : 'default'">
          {{ SOURCE_LABELS[source()] ?? source() }}
        </NTag>
        <NTag v-if="(item as SkillMarketplaceItem).official" size="tiny" type="info" round :bordered="false">官方</NTag>
        <NTag v-if="item.version" size="tiny" :bordered="false">v{{ item.version }}</NTag>
        <NTag v-if="item.category" size="tiny" round :bordered="false">{{ item.category }}</NTag>
        <NTooltip v-if="item.has_scripts" trigger="hover">
          <template #trigger>
            <NTag size="tiny" type="warning" round :bordered="false">
              <template #icon><NIcon :component="TerminalOutline" /></template>
              含脚本
            </NTag>
          </template>
          该技能包含可执行脚本，挂载前请先审查脚本内容
        </NTooltip>
      </div>
      <NTooltip trigger="hover" :style="{ maxWidth: '360px' }">
        <template #trigger>
          <div class="card-desc">{{ item.description }}</div>
        </template>
        {{ item.description }}
      </NTooltip>
      <div v-if="!isMarketItem(item) && ((item as SkillItem).author || (item as SkillItem).source_url)" class="card-meta">
        <span v-if="(item as SkillItem).author">✍️ {{ (item as SkillItem).author }}</span>
      </div>
    </div>
    <div class="card-actions">
      <template v-if="managed && !isMarketItem(item)">
        <NSwitch size="small" :value="(item as SkillItem).is_active" @update:value="emit('toggle')" />
        <NTooltip v-if="(item as SkillItem).source === 'github' || (item as SkillItem).source === 'aliyun_official'" trigger="hover">
          <template #trigger>
            <NButton size="tiny" quaternary @click="emit('checkUpdate')">
              <template #icon><NIcon :component="RefreshOutline" /></template>
            </NButton>
          </template>
          检查上游更新
        </NTooltip>
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton size="tiny" quaternary @click="emit('versions')">
              <template #icon><NIcon :component="TimeOutline" /></template>
            </NButton>
          </template>
          版本历史
        </NTooltip>
        <NPopconfirm @positive-click="emit('delete')">
          <template #trigger>
            <NButton size="tiny" quaternary type="error">
              <template #icon><NIcon :component="TrashOutline" /></template>
            </NButton>
          </template>
          确定删除该技能？
        </NPopconfirm>
      </template>
      <template v-else>
        <NButton
          size="small"
          :type="isMarketItem(item) && item.installed ? 'default' : 'primary'"
          :loading="installing"
          @click="emit('install')"
        >
          {{ isMarketItem(item) && item.installed ? '重新安装' : '安装' }}
        </NButton>
      </template>
    </div>
  </div>
</template>

<style scoped>
.skill-market-card {
  display: flex;
  gap: 14px;
  padding: 20px 24px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  box-shadow: var(--shadow-card, 0 1px 4px rgba(0, 0, 0, 0.04));
  transition: transform 220ms var(--motion-spring, cubic-bezier(0.34, 1.56, 0.64, 1)),
              box-shadow 220ms var(--motion-spring, cubic-bezier(0.34, 1.56, 0.64, 1));
}
.skill-market-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-card-hover, 0 4px 16px rgba(0, 0, 0, 0.08));
}
@media (prefers-reduced-motion: reduce) {
  .skill-market-card { transition: none; }
  .skill-market-card:hover { transform: none; }
}
.card-icon {
  font-size: 28px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-primary-light, rgba(76, 111, 255, 0.08));
  border-radius: 12px;
  flex-shrink: 0;
}
.card-body { flex: 1; min-width: 0; }
.card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.card-name { font-weight: 500; font-size: 16px; line-height: 24px; }
.card-desc {
  font-size: 13px;
  line-height: 20px;
  color: var(--neutral-text-2, #666);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-meta { margin-top: 6px; font-size: 11px; color: var(--neutral-text-3, #aaa); }
.card-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex-shrink: 0; justify-content: center; }
</style>
