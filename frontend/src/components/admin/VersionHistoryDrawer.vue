<script setup lang="ts">
/**
 * 版本历史抽屉（MCP 服务 / 技能共用）
 *
 * 父组件把后端返回的版本记录归一化为 VersionHistoryItem 数组传入，
 * 点击「回滚」时经 NPopconfirm 确认后以 rollback 事件回传原始条目，
 * 由父组件调用对应的回滚 API 并刷新列表。
 */
import { NButton, NDrawer, NDrawerContent, NEmpty, NPopconfirm, NScrollbar, NTag, NTooltip } from 'naive-ui'

export interface VersionHistoryItem {
  /** 行内主标识，如 v1.0.1 / r2 */
  label: string
  /** 主标识是否用主色 tag 突出（如 MCP 主版本） */
  primary?: boolean
  /** 次级文本，如技能条目附带的 version */
  subLabel?: string
  /** 来源 tag 文案（父组件已完成中文映射） */
  sourceLabel?: string
  /** 来源 tag 类型 */
  sourceType?: 'default' | 'info' | 'warning' | 'success' | 'error'
  changelog?: string
  createdBy?: string
  createdAt?: string
  /** 是否为服务当前生效版本；不能依赖历史列表的排序。 */
  isCurrent?: boolean
  /** 回滚确认弹窗中的目标描述，如 v1.0.1 / r2 */
  rollbackTarget: string
  /** 禁用回滚（如无配置快照） */
  rollbackDisabled?: boolean
  /** 禁用原因（tooltip 展示） */
  rollbackDisabledReason?: string
  /** 原始后端条目，随 rollback 事件回传 */
  raw: unknown
}

const props = withDefaults(
  defineProps<{
    show: boolean
    title: string
    items: VersionHistoryItem[]
    loading?: boolean
    rollingBack?: boolean
    emptyText?: string
  }>(),
  { loading: false, rollingBack: false, emptyText: '暂无版本记录' },
)

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'rollback', item: VersionHistoryItem): void
  /** 查看该版本与当前版本的 diff（父组件实现） */
  (e: 'diff', item: VersionHistoryItem): void
}>()

function formatTime(ts?: string): string {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    if (Number.isNaN(d.getTime())) return ts
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}
</script>

<template>
  <NDrawer
    :show="props.show"
    :width="480"
    placement="right"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <NDrawerContent :title="title" closable>
      <div v-if="loading" class="vh-empty">加载中...</div>
      <div v-else-if="!items.length" class="vh-empty">
        <NEmpty :description="emptyText" />
      </div>
      <NScrollbar v-else style="max-height: 100%">
        <div class="vh-list">
          <div v-for="(item, idx) in items" :key="idx" class="vh-item">
            <div class="vh-head">
              <NTag size="small" round :type="item.primary ? 'primary' : 'default'" :bordered="false">
                {{ item.label }}
              </NTag>
              <span v-if="item.subLabel" class="vh-sub">{{ item.subLabel }}</span>
              <NTag v-if="item.sourceLabel" size="tiny" :type="item.sourceType ?? 'info'" :bordered="false">
                {{ item.sourceLabel }}
              </NTag>
              <span class="vh-time">
                {{ formatTime(item.createdAt) }}<template v-if="item.createdBy"> · {{ item.createdBy }}</template>
              </span>
              <template v-if="!item.isCurrent">
                <span class="vh-action">
                  <NButton size="tiny" quaternary @click="emit('diff', item)">对比</NButton>
                </span>
                <NTooltip :disabled="!item.rollbackDisabled" trigger="hover">
                  <template #trigger>
                    <span class="vh-action">
                      <NPopconfirm
                        :disabled="item.rollbackDisabled"
                        @positive-click="emit('rollback', item)"
                      >
                        <template #trigger>
                          <NButton size="tiny" quaternary type="primary" :disabled="item.rollbackDisabled" :loading="rollingBack">
                            回滚
                          </NButton>
                        </template>
                        回滚到 {{ item.rollbackTarget }}？当前配置将被该版本快照覆盖
                      </NPopconfirm>
                    </span>
                  </template>
                  {{ item.rollbackDisabledReason }}
                </NTooltip>
              </template>
              <NTag v-else size="tiny" type="success" :bordered="false">当前</NTag>
            </div>
            <div v-if="item.changelog" class="vh-changelog">{{ item.changelog }}</div>
          </div>
        </div>
      </NScrollbar>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.vh-empty { padding: 32px 0; text-align: center; color: var(--neutral-text-3, #999); font-size: 13px; }
.vh-list { display: flex; flex-direction: column; }
.vh-item { padding: 10px 4px; border-bottom: 1px solid var(--n-border-color, #eee); }
.vh-item:last-child { border-bottom: none; }
.vh-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.vh-sub { font-size: 12px; color: var(--neutral-text-2, #666); }
.vh-time { font-size: 12px; color: var(--neutral-text-3, #999); flex: 1; min-width: 120px; }
.vh-action { display: inline-flex; }
.vh-changelog { margin-top: 6px; font-size: 12px; color: var(--neutral-text-2, #666); line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
</style>
