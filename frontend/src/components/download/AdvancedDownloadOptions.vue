<script setup lang="ts">
/**
 * EBIDownload 高级选项折叠面板
 * 暴露底层 CLI 的 Filters（正则数组）与 Cleanup（无参 flag）能力。
 * - 默认收起，保持普通用户界面清爽
 * - 四个正则过滤项使用 NDynamicTags（回车生成 Tag，点击 × 删除）
 * - cleanup-sra 默认勾选并附 Tooltip；pe-only 默认不勾选
 */
import { computed } from 'vue'
import {
  NCollapse, NCollapseItem, NDynamicTags, NSwitch, NTooltip, NIcon, NTag,
} from 'naive-ui'
import { InformationCircleOutline } from '@vicons/ionicons5'
import type { AdvancedDownloadOptions } from '@/types/download'

const props = defineProps<{ modelValue: AdvancedDownloadOptions }>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: AdvancedDownloadOptions): void
}>()

// 双向绑定：以 props.modelValue 为唯一数据源，每次修改都产出新对象 emit 出去，
// 避免直接 mutate 父级状态，符合 v-model 单向数据流最佳实践。
const options = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', { ...val }),
})

/**
 * 通用：更新某个字段并 emit 新对象
 * @param key  要更新的字段名
 * @param value 新值
 */
function patch<K extends keyof AdvancedDownloadOptions>(key: K, value: AdvancedDownloadOptions[K]) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

/**
 * 标签数组更新处理：剔除空白项后再 patch
 * NDynamicTags 的 on-create 不支持返回 false 取消，因此在 update 阶段统一清洗，
 * 保证空字符串 / 纯空白不会被写入过滤器数组。
 */
function updateFilter(
  key: keyof Pick<AdvancedDownloadOptions, 'filter_sample' | 'filter_run' | 'exclude_sample' | 'exclude_run'>,
  raw: string[],
) {
  const cleaned = raw.map((s) => s.trim()).filter((s) => s.length > 0)
  patch(key, cleaned)
}

// ----- Filters 子项配置：驱动 v-for 渲染，避免四段重复模板 -----
interface FilterField {
  key: keyof Pick<AdvancedDownloadOptions, 'filter_sample' | 'filter_run' | 'exclude_sample' | 'exclude_run'>
  label: string
  flag: string
  placeholder: string
}
const filterFields: FilterField[] = [
  { key: 'filter_sample', label: 'Filter Sample', flag: '--filter-sample', placeholder: '支持正则 (如 SRR10.*)，按回车添加' },
  { key: 'filter_run', label: 'Filter Run', flag: '--filter-run', placeholder: '支持正则，按回车添加' },
  { key: 'exclude_sample', label: 'Exclude Sample', flag: '--exclude-sample', placeholder: '支持正则，按回车添加' },
  { key: 'exclude_run', label: 'Exclude Run', flag: '--exclude-run', placeholder: '支持正则，按回车添加' },
]

// 当前已配置的过滤器数量（用于折叠标题右侧的徽标提示）
const activeFilterCount = computed(
  () => filterFields.reduce((sum, f) => sum + options.value[f.key].length, 0),
)
</script>

<template>
  <NCollapse :default-expanded-names="[]" accordion display="flex" class="advanced-panel">
    <NCollapseItem name="advanced">
      <!-- 标题：左侧文字 + 已配置过滤器数量徽标 -->
      <template #header>
        <span class="panel-title">高级选项 (Advanced Options)</span>
        <NTag v-if="activeFilterCount > 0" size="small" round type="info" class="count-badge">
          {{ activeFilterCount }} 条过滤规则
        </NTag>
      </template>

      <!-- 过滤器区域：Include / Exclude 左右两列 -->
      <div class="filters-grid">
        <!-- 包含规则 -->
        <div class="filter-column include">
          <div class="column-header">
            <span class="column-title">包含规则 (Include)</span>
            <span class="column-hint">仅保留匹配的记录</span>
          </div>
          <div
            v-for="field in filterFields.slice(0, 2)"
            :key="field.key"
            class="filter-item"
          >
            <div class="filter-label">
              <span>{{ field.label }}</span>
              <code class="cli-flag">{{ field.flag }}</code>
            </div>
            <NDynamicTags
              :value="options[field.key]"
              type="success"
              :input-props="{ placeholder: field.placeholder }"
              :max="50"
              @update:value="(v: string[]) => updateFilter(field.key, v)"
            />
          </div>
        </div>

        <!-- 排除规则 -->
        <div class="filter-column exclude">
          <div class="column-header">
            <span class="column-title">排除规则 (Exclude)</span>
            <span class="column-hint">剔除匹配的记录</span>
          </div>
          <div
            v-for="field in filterFields.slice(2, 4)"
            :key="field.key"
            class="filter-item"
          >
            <div class="filter-label">
              <span>{{ field.label }}</span>
              <code class="cli-flag">{{ field.flag }}</code>
            </div>
            <NDynamicTags
              :value="options[field.key]"
              type="warning"
              :input-props="{ placeholder: field.placeholder }"
              :max="50"
              @update:value="(v: string[]) => updateFilter(field.key, v)"
            />
          </div>
        </div>
      </div>

      <!-- 分隔线 -->
      <div class="section-divider" />

      <!-- 开关选项 -->
      <div class="toggles-wrap">
        <div class="toggle-item">
          <div class="toggle-meta">
            <div class="toggle-title-row">
              <span class="toggle-title">转换后清理 .sra 中间文件</span>
              <NTooltip placement="top" trigger="hover">
                <template #trigger>
                  <NIcon :size="14" class="tip-icon"><InformationCircleOutline /></NIcon>
                </template>
                启用 --cleanup-sra：FASTQ 转换完成后自动删除 .sra 文件，可节省大量磁盘空间（通常约为原始数据的 50%~70%）。
              </NTooltip>
            </div>
            <code class="cli-flag">--cleanup-sra</code>
          </div>
          <NSwitch
            :value="options.cleanup_sra"
            @update:value="(v: boolean) => patch('cleanup_sra', v)"
          />
        </div>

        <div class="toggle-item">
          <div class="toggle-meta">
            <div class="toggle-title-row">
              <span class="toggle-title">仅下载双端数据</span>
            </div>
            <code class="cli-flag">--pe-only</code>
          </div>
          <NSwitch
            :value="options.pe_only"
            @update:value="(v: boolean) => patch('pe_only', v)"
          />
        </div>
      </div>
    </NCollapseItem>
  </NCollapse>
</template>

<style scoped>
.advanced-panel {
  width: 100%;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.count-badge {
  margin-left: 8px;
}

/* ---- Filters 两列布局 ---- */
.filters-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 24px;
}

.filter-column {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--neutral-bg, #f7f8fa);
  border: 1px solid var(--neutral-border, #eef0f3);
}

.column-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 2px;
}

.column-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.column-hint {
  font-size: 12px;
  color: var(--neutral-text-3);
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.filter-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--neutral-text-2);
}

.cli-flag {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--neutral-fill, #eef0f3);
  color: var(--neutral-text-3);
}

.section-divider {
  height: 1px;
  margin: 18px 0 14px;
  background: var(--neutral-border, #eef0f3);
}

/* ---- Toggles ---- */
.toggles-wrap {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.toggle-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--neutral-bg, #f7f8fa);
  border: 1px solid var(--neutral-border, #eef0f3);
}

.toggle-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.toggle-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.toggle-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-text-1);
}

.tip-icon {
  color: var(--neutral-text-3);
  cursor: help;
}

/* 窄屏下两列退化为单列，保持可读性 */
@media (max-width: 720px) {
  .filters-grid {
    grid-template-columns: 1fr;
  }
}
</style>