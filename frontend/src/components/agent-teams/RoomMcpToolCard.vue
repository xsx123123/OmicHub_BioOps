<script setup lang="ts">
import { computed } from 'vue'
import McpToolCallCard from '@/components/ai-chat/McpToolCallCard.vue'
import type { ToolCall } from '@/components/ai-chat/types'
import type { RoomDebugTrace, RoomToolInfo } from '@/utils/agentTeamsRoom'

const props = defineProps<{
  tool: RoomToolInfo
  count?: number
  debugTrace?: RoomDebugTrace
}>()

const toolCall = computed<ToolCall>(() => {
  const count = props.count || 1
  const name = count > 1 ? `${props.tool.name} ×${count}` : props.tool.name
  const duration = props.tool.durationMs !== undefined ? ` · ${props.tool.durationMs}ms` : ''
  const state = props.tool.status === 'running'
    ? '正在调用'
    : props.tool.status === 'failed'
      ? '调用失败'
      : '调用完成'
  return {
    id: `room-tool-${name}`,
    name,
    arguments: count > 1 ? { count } : {},
    result: props.debugTrace?.resultSummary
      ? { summary: props.debugTrace.resultSummary }
      : undefined,
    mcpServer: '协作室 MCP',
    purpose: `${count > 1 ? `本轮已合并 ${count} 次相同工具调用 · ` : ''}${state}${duration}`,
    status: props.tool.status === 'running'
      ? 'running'
      : props.tool.status === 'failed'
        ? 'error'
        : 'success',
  }
})
</script>

<template>
  <div class="room-mcp-tool-card">
    <McpToolCallCard :tool="toolCall" />
  </div>
</template>

<style scoped>
.room-mcp-tool-card { width: 100%; min-width: 0; }
</style>
