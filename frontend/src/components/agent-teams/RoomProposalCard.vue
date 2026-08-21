<script setup lang="ts">
/**
 * RoomProposalCard — room.proposal_confirm 房间级事件的立项确认卡（会话-工单解耦）
 *
 * execute 意图不再直接建 Case：先渲染本卡（目标/流程/参与部门摘要 + 选项按钮），
 * 用户裁决后经 confirm-proposal 端点消费（owner + pending 状态校验，confirm_token
 * 为可选二次校验，不再经事件流分发）。
 * new_case 卡选项为 确认立项/修改需求/取消；followup 卡（上一 Case 终态后再立项）
 * 选项为 基于上一 Case 继续/新建工单/取消。卡片已消费（status 非 pending）时
 * 渲染为只读结果态。
 */
import { computed } from 'vue'
import { NButton, NIcon, NTag } from 'naive-ui'
import { FlagOutline } from '@vicons/ionicons5'
import type { AgentTeamsRoleLabel } from '@/api/agentTeams'
import type { RoomProposal } from '@/utils/agentTeamsRoom'

const props = defineProps<{
  proposal: RoomProposal
  /** 角色元数据：participants（角色 id）映射为展示名。 */
  roleLabels?: Record<string, AgentTeamsRoleLabel>
}>()

const emit = defineEmits<{
  decision: [payload: { decision: 'confirm' | 'modify' | 'cancel'; followupMode?: 'continue' | 'new' }]
}>()

const pending = computed(() => props.proposal.status === 'pending')
const isFollowup = computed(() => props.proposal.proposalKind === 'followup')

const title = computed(() => (isFollowup.value ? '后续立项确认' : '立项确认'))

/** 已消费卡的只读结果文案（文本 + 状态色双表达，同审批卡约定）。 */
const resultText = computed(() => {
  switch (props.proposal.status) {
    case 'confirmed': return '已确认立项'
    case 'modify_requested': return '已退回修改需求'
    case 'superseded': return '已失效（被新的立项卡覆盖）'
    case 'cancelled': return '已取消'
    default: return ''
  }
})

const stageCount = computed(() => props.proposal.estimatedStages.length)

const participantNames = computed(() =>
  props.proposal.participants.map((participant) => props.roleLabels?.[participant]?.name || participant),
)

function choose(decision: 'confirm' | 'modify' | 'cancel', followupMode?: 'continue' | 'new') {
  if (!pending.value || props.proposal.submitting) return
  emit('decision', { decision, followupMode })
}
</script>

<template>
  <div class="room-proposal-card" :class="{ 'is-consumed': !pending }" aria-live="polite">
    <div class="rpc-header">
      <n-icon size="14" class="rpc-icon"><FlagOutline /></n-icon>
      <span class="rpc-title">{{ title }}</span>
      <n-tag v-if="proposal.flowLabel" size="tiny" :bordered="false" type="info">{{ proposal.flowLabel }}</n-tag>
      <n-tag v-if="proposal.confidence === 'ambiguous'" size="tiny" :bordered="false" type="warning">路径待确认</n-tag>
      <span v-if="resultText" class="rpc-result">{{ resultText }}</span>
    </div>
    <div class="rpc-body">
      <p v-if="proposal.objective" class="rpc-objective">{{ proposal.objective }}</p>
      <div class="rpc-meta">
        <span v-if="proposal.leadPlanner">规划者 {{ roleLabels?.[proposal.leadPlanner]?.name || proposal.leadPlanner }}</span>
        <span v-if="stageCount">预计 {{ stageCount }} 个阶段</span>
        <span v-if="proposal.routePath">{{ proposal.routePath === 'bridge_workflow' ? '标准流程' : '通用规划' }}</span>
      </div>
      <div v-if="participantNames.length" class="rpc-participants">
        <span class="rpc-label">参与协作</span>
        <n-tag v-for="name in participantNames" :key="name" size="tiny" :bordered="false" round>{{ name }}</n-tag>
      </div>
      <p v-if="isFollowup && proposal.sourceCaseId" class="rpc-source">基于上一 Case 的上下文继续协作。</p>
    </div>
    <div v-if="pending" class="rpc-actions" role="group" aria-label="立项确认选项">
      <template v-if="isFollowup">
        <NButton type="primary" size="small" :loading="proposal.submitting" @click="choose('confirm', 'continue')">基于上一 Case 继续</NButton>
        <NButton secondary size="small" :disabled="proposal.submitting" @click="choose('confirm', 'new')">新建工单</NButton>
        <NButton tertiary type="error" size="small" :disabled="proposal.submitting" @click="choose('cancel')">取消</NButton>
      </template>
      <template v-else>
        <NButton type="primary" size="small" :loading="proposal.submitting" @click="choose('confirm')">确认立项</NButton>
        <NButton secondary size="small" :disabled="proposal.submitting" @click="choose('modify')">修改需求</NButton>
        <NButton tertiary type="error" size="small" :disabled="proposal.submitting" @click="choose('cancel')">取消</NButton>
      </template>
    </div>
  </div>
</template>

<style scoped lang="scss">
/* 复用平台卡片变量体系（与 RouteDecisionCard / AskUserCard 同源），不新增独立样式。 */
.room-proposal-card {
  width: 100%;
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--chat-ai-card, var(--neutral-card));
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 12px;
  box-shadow: var(--chat-shadow-sm, var(--shadow-card));

  &.is-consumed {
    opacity: 0.78;
  }
}

.rpc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.rpc-icon {
  color: var(--chat-accent, var(--arco-primary));
  flex-shrink: 0;
}

.rpc-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--chat-text-primary, var(--neutral-text-1));
}

.rpc-result {
  margin-left: auto;
  font-size: 12px;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.rpc-body {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rpc-objective {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--chat-text-primary, var(--neutral-text-1));
  white-space: pre-wrap;
  word-break: break-word;
}

.rpc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: 12px;
  color: var(--chat-text-secondary, var(--neutral-text-2));
}

.rpc-participants {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.rpc-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.rpc-source {
  margin: 0;
  font-size: 12px;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.rpc-actions {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--chat-border, var(--neutral-border));
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
