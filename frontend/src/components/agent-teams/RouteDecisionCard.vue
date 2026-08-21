<script setup lang="ts">
/**
 * RouteDecisionCard — room.route_decision 事件的路由决策卡（优化项 O1）
 *
 * 高置信（confidence=high）：默认折叠为一行（路径 + 规划者 + 预计阶段数），
 * 点击展开查看命中关键词、Planner 评分明细、预计阶段与参与 Agent。
 * 模糊（confidence=ambiguous）场景不渲染本卡片——由房间视图改用 AskUserCard
 * 选项式确认卡承载（复用澄清卡片的点选-回传链路）。
 */
import { computed, ref } from 'vue'
import { NIcon, NTag } from 'naive-ui'
import { ChevronForwardOutline, CompassOutline } from '@vicons/ionicons5'
import type { RoomRouteDecision } from '@/utils/agentTeamsRoom'

const props = defineProps<{ decision: RoomRouteDecision }>()

const collapsed = ref(true)
function toggle() {
  collapsed.value = !collapsed.value
}

const pathLabel = computed(() => (props.decision.path === 'bridge_workflow' ? '标准流程' : '通用规划'))

/** Planner 评分按得分降序展示。 */
const sortedScores = computed(() =>
  Object.entries(props.decision.plannerScores || {}).sort((a, b) => b[1] - a[1]),
)
</script>

<template>
  <div class="route-decision-card">
    <div
      class="rdc-header"
      role="button"
      :aria-expanded="!collapsed"
      tabindex="0"
      @click="toggle"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
    >
      <n-icon size="14" class="rdc-icon"><CompassOutline /></n-icon>
      <span class="rdc-tool-name">路由决策</span>
      <span class="rdc-divider">|</span>
      <n-tag size="tiny" :bordered="false" :type="decision.path === 'bridge_workflow' ? 'success' : 'info'">
        {{ pathLabel }}
      </n-tag>
      <span class="rdc-summary">
        已选择「{{ decision.flowLabel }}」 · 规划者 {{ decision.leadPlanner }} · 预计 {{ decision.estimatedStages.length }} 个阶段
      </span>
      <n-icon size="13" class="rdc-arrow" :class="{ rotated: !collapsed }">
        <ChevronForwardOutline />
      </n-icon>
    </div>
    <div v-show="!collapsed" class="rdc-body">
      <div class="rdc-section">
        <span class="rdc-label">命中关键词</span>
        <div v-if="decision.matchedHints.length" class="rdc-tags">
          <n-tag v-for="hint in decision.matchedHints" :key="hint" size="tiny" :bordered="false" round>{{ hint }}</n-tag>
        </div>
        <span v-else class="rdc-empty">（无直接命中，按通用路径规划）</span>
      </div>
      <div v-if="sortedScores.length" class="rdc-section">
        <span class="rdc-label">Planner 评分</span>
        <ul class="rdc-list">
          <li v-for="[agent, score] in sortedScores" :key="agent">
            <span class="rdc-agent">{{ agent }}</span>
            <span class="rdc-score">{{ score }}</span>
          </li>
        </ul>
      </div>
      <div v-if="decision.estimatedStages.length" class="rdc-section">
        <span class="rdc-label">预计阶段</span>
        <ul class="rdc-list">
          <li v-for="(stage, index) in decision.estimatedStages" :key="stage.key">
            {{ index + 1 }}. {{ stage.title }}（{{ stage.key }}）
          </li>
        </ul>
      </div>
      <div v-if="decision.participants.length" class="rdc-section">
        <span class="rdc-label">参与 Agent</span>
        <div class="rdc-tags">
          <n-tag v-for="agent in decision.participants" :key="agent" size="tiny" :bordered="false">{{ agent }}</n-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
/* 复用平台卡片变量体系（与 AskUserCard 同源），不新增独立样式。 */
.route-decision-card {
  width: 100%;
  margin-top: 10px;
  padding: 8px 12px;
  background: var(--chat-ai-card, var(--neutral-card));
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 12px;
  box-shadow: var(--chat-shadow-sm, var(--shadow-card));
}

.rdc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.rdc-icon {
  color: var(--chat-accent, var(--arco-primary));
  flex-shrink: 0;
}

.rdc-tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--chat-text-primary, var(--neutral-text-1));
  flex-shrink: 0;
}

.rdc-divider {
  font-size: 12px;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.rdc-summary {
  font-size: 12px;
  line-height: 1.5;
  color: var(--chat-text-secondary, var(--neutral-text-2));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rdc-arrow {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--chat-text-muted, var(--neutral-text-3));
  transition: transform 0.2s ease;

  &.rotated {
    transform: rotate(90deg);
  }
}

.rdc-body {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--chat-border, var(--neutral-border));
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rdc-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rdc-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.rdc-empty {
  font-size: 12px;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.rdc-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.rdc-list {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--chat-text-primary, var(--neutral-text-1));
}

.rdc-agent {
  color: var(--chat-text-primary, var(--neutral-text-1));
}

.rdc-score {
  margin-left: 6px;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

@media (prefers-reduced-motion: reduce) {
  .rdc-arrow {
    transition: none;
  }
}
</style>
