<script setup lang="ts">
/**
 * SkillInvocationCard — 会话流内的技能调用卡片（Skill 调用可视化）。
 * 由 SSE skill 事件（invoked/completed/failed）驱动：
 *  - 加载中：spinner + 「正在加载技能…」
 *  - 成功：✓ + 耗时 + 摘要（可展开）
 *  - 失败：✗ + 错误原因，Agent 回退通用流程时标注 fallback
 * 同一消息内同技能多次调用合并计数（count），不刷屏。
 * 动画只用 opacity/transform，尊重 prefers-reduced-motion。
 */
import { computed, ref } from 'vue'
import { NTag, NIcon } from 'naive-ui'
import {
  CheckmarkCircleOutline, CloseCircleOutline, ChevronDownOutline,
} from '@vicons/ionicons5'
import type { SkillInvocationCard } from './types'

const props = defineProps<{ card: SkillInvocationCard }>()

const expanded = ref(false)

const SOURCE_LABELS: Record<string, string> = {
  market: '市场', github: 'GitHub', zip: 'ZIP', json: 'JSON', builtin: '内置',
  aliyun_official: '阿里云官方',
}

const statusText = computed(() => {
  if (props.card.status === 'running') return '正在加载技能…'
  if (props.card.status === 'error') return '技能加载失败'
  return props.card.summary || '技能已加载'
})

const durationText = computed(() => {
  const ms = props.card.duration_ms
  if (ms == null) return ''
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
})
</script>

<template>
  <div class="skill-card" :class="`skill-card--${card.status}`">
    <div class="skill-card-main" @click="expanded = !expanded">
      <span class="skill-card-icon">{{ card.icon }}</span>
      <div class="skill-card-info">
        <div class="skill-card-title">
          <span class="skill-card-name">{{ card.name }}</span>
          <NTag v-if="card.version" size="tiny" :bordered="false">v{{ card.version }}</NTag>
          <NTag
            v-if="card.source && SOURCE_LABELS[card.source]"
            size="tiny"
            :type="card.source === 'aliyun_official' ? 'info' : 'default'"
            :bordered="false"
          >
            {{ SOURCE_LABELS[card.source] }}
          </NTag>
          <NTag v-if="card.count > 1" size="tiny" round :bordered="false">×{{ card.count }}</NTag>
        </div>
        <div class="skill-card-status">
          <!-- 加载中 spinner -->
          <span v-if="card.status === 'running'" class="skill-spinner" aria-label="加载中" />
          <NIcon v-else-if="card.status === 'success'" :component="CheckmarkCircleOutline" size="13" color="#18a058" />
          <NIcon v-else :component="CloseCircleOutline" size="13" color="#d03050" />
          <span class="skill-card-status-text">{{ statusText }}</span>
          <span v-if="durationText" class="skill-card-duration">· {{ durationText }}</span>
          <span v-if="card.agent" class="skill-card-agent">· {{ card.agent }}</span>
        </div>
      </div>
      <NIcon class="skill-card-chevron" :class="{ 'is-expanded': expanded }" :component="ChevronDownOutline" size="14" />
    </div>
    <div v-if="expanded" class="skill-card-detail">
      <div class="skill-card-detail-row"><span>技能 ID</span><code>{{ card.skill_id }}</code></div>
      <div v-if="card.summary" class="skill-card-detail-row"><span>结果</span><em>{{ card.summary }}</em></div>
      <div v-if="card.error" class="skill-card-detail-row skill-card-error"><span>错误</span><em>{{ card.error }}</em></div>
      <div v-if="card.fallback" class="skill-card-detail-row skill-card-error">
        <span>回退</span><em>技能不可用，已回退通用能力</em>
      </div>
    </div>
  </div>
</template>

<style scoped>
.skill-card {
  margin: 8px 0;
  border: 1px solid var(--n-border-color, #e8e8e8);
  border-left: 3px solid var(--n-border-color, #d9d9d9);
  border-radius: 8px;
  background: var(--n-card-color, #fafafa);
  font-size: 12px;
  animation: skill-card-in 180ms ease-out;
}
.skill-card--running { border-left-color: #2080f0; }
.skill-card--success { border-left-color: #18a058; }
.skill-card--error { border-left-color: #d03050; }
@keyframes skill-card-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
.skill-card-main {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; cursor: pointer; user-select: none;
}
.skill-card-icon { font-size: 18px; line-height: 1; }
.skill-card-info { flex: 1; min-width: 0; }
.skill-card-title { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.skill-card-name { font-weight: 600; font-size: 13px; color: var(--n-text-color-1, #333); }
.skill-card-status { display: flex; align-items: center; gap: 5px; margin-top: 3px; color: var(--n-text-color-3, #999); }
.skill-card-duration, .skill-card-agent { color: var(--n-text-color-3, #bbb); }
.skill-card-chevron {
  color: var(--n-text-color-3, #999);
  transition: transform 150ms ease;
}
.skill-card-chevron.is-expanded { transform: rotate(180deg); }
.skill-card-detail {
  padding: 6px 12px 10px 40px;
  border-top: 1px dashed var(--n-border-color, #eee);
  color: var(--n-text-color-2, #666);
}
.skill-card-detail-row { display: flex; gap: 10px; margin-top: 4px; }
.skill-card-detail-row > span { flex-shrink: 0; width: 48px; color: var(--n-text-color-3, #999); }
.skill-card-detail-row em { font-style: normal; word-break: break-all; }
.skill-card-error em { color: #d03050; }
.skill-spinner {
  width: 12px; height: 12px; flex-shrink: 0;
  border: 2px solid rgba(32, 128, 240, 0.25);
  border-top-color: #2080f0;
  border-radius: 50%;
  animation: skill-spin 0.8s linear infinite;
}
@keyframes skill-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .skill-card { animation: none; }
  .skill-spinner { animation-duration: 1.6s; }
  .skill-card-chevron { transition: none; }
}
</style>
