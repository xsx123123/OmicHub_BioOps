<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import {
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInputNumber,
  NSlider,
  NInput,
  NSwitch,
  NSpace,
  NDivider,
  NCollapse,
  NCollapseItem,
  NTag,
  NEmpty,
  NSpin,
  NButton,
  NIcon,
} from 'naive-ui'
import { RefreshOutline, ServerOutline } from '@vicons/ionicons5'
import { useMCPStore } from '@/stores/mcp'

const props = defineProps<{
  show: boolean
  temperature: number
  maxTokens: number
  systemPrompt: string
  contextLength: number
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'update:temperature': [value: number]
  'update:maxTokens': [value: number]
  'update:systemPrompt': [value: string]
  'update:contextLength': [value: number]
  reset: []
}>()

const mcpStore = useMCPStore()
const expandedTools = ref<string[]>([])

const localTemp = ref(props.temperature)
const localMaxTokens = ref(props.maxTokens)
const localSystemPrompt = ref(props.systemPrompt)
const localContextLength = ref(props.contextLength)

watch(() => props.temperature, (v) => (localTemp.value = v))
watch(() => props.maxTokens, (v) => (localMaxTokens.value = v))
watch(() => props.systemPrompt, (v) => (localSystemPrompt.value = v))
watch(() => props.contextLength, (v) => (localContextLength.value = v))

watch(localTemp, (v) => emit('update:temperature', v))
watch(localMaxTokens, (v) => emit('update:maxTokens', v))
watch(localSystemPrompt, (v) => emit('update:systemPrompt', v))
watch(localContextLength, (v) => emit('update:contextLength', v))

onMounted(() => {
  if (mcpStore.servers.length === 0) {
    mcpStore.fetchServers()
  }
})

function handleReset() {
  emit('reset')
}

async function refreshMcp() {
  await mcpStore.fetchServers()
}
</script>

<template>
  <NDrawer
    :show="show"
    :width="420"
    placement="right"
    @update:show="(v) => emit('update:show', v)"
  >
    <NDrawerContent title="聊天设置" closable>
      <NForm label-placement="top" size="small">
        <!-- ========== 模型参数 ========== -->
        <NFormItem label="Temperature">
          <div style="width: 100%">
            <NSlider
              v-model:value="localTemp"
              :min="0"
              :max="2"
              :step="0.1"
              :marks="{ 0: '0', 0.7: '0.7', 1: '1', 2: '2' }"
            />
            <div style="text-align: right; font-size: 12px; color: var(--n-text-color-3)">
              {{ localTemp.toFixed(1) }}
            </div>
          </div>
        </NFormItem>

        <NFormItem label="Max Tokens">
          <NInputNumber
            v-model:value="localMaxTokens"
            :min="100"
            :max="32768"
            :step="100"
            style="width: 100%"
          />
        </NFormItem>

        <NFormItem label="上下文消息数">
          <div style="width: 100%">
            <NSlider
              v-model:value="localContextLength"
              :min="2"
              :max="50"
              :step="2"
              :marks="{ 2: '2', 10: '10', 20: '20', 50: '50' }"
            />
            <div style="text-align: right; font-size: 12px; color: var(--n-text-color-3)">
              {{ localContextLength }} 条
            </div>
          </div>
        </NFormItem>

        <NFormItem label="自定义系统提示词">
          <NInput
            v-model:value="localSystemPrompt"
            type="textarea"
            placeholder="留空则使用助手默认提示词"
            :autosize="{ minRows: 4, maxRows: 12 }"
          />
        </NFormItem>

        <NSpace>
          <NButton size="small" @click="handleReset">
            <template #icon><NIcon :component="RefreshOutline" /></template>
            重置参数
          </NButton>
        </NSpace>

        <NDivider />
      </NForm>

      <!-- ========== MCP 服务器与工具 ========== -->
      <div class="section-title">
        <NIcon :component="ServerOutline" size="16" />
        <span>MCP 服务器</span>
        <NButton quaternary size="tiny" @click="refreshMcp" style="margin-left: auto">
          <template #icon><NIcon :component="RefreshOutline" /></template>
          刷新
        </NButton>
      </div>

      <NSpin :show="mcpStore.loading" size="small">
        <NEmpty
          v-if="mcpStore.servers.length === 0"
          description="暂无 MCP 服务器"
          size="small"
          style="padding: 20px 0"
        />
        <NCollapse v-else v-model:expanded-names="expandedTools" accordion>
          <NCollapseItem
            v-for="server in mcpStore.servers"
            :key="server.id"
            :name="server.id"
          >
            <template #header>
              <div class="mcp-header">
                <span class="mcp-name">{{ server.name }}</span>
                <NTag
                  :type="
                    server.status === 'online' ? 'success' :
                    server.status === 'starting' ? 'warning' : 'error'
                  "
                  size="tiny"
                  round
                >
                  {{ server.status }}
                </NTag>
                <NTag size="tiny" :bordered="false">
                  {{ server.tool_count }} 工具
                </NTag>
              </div>
            </template>

            <div class="mcp-desc">{{ server.description }}</div>
            <div class="mcp-tools">
              <NButton
                size="tiny"
                quaternary
                @click="mcpStore.fetchTools(server.id)"
              >
                加载工具列表
              </NButton>
              <div
                v-for="tool in mcpStore.toolsCache[server.id] || []"
                :key="tool.name"
                class="mcp-tool-item"
              >
                <div class="tool-name">{{ tool.name }}</div>
                <div class="tool-desc">{{ tool.description }}</div>
              </div>
              <NEmpty
                v-if="
                  !mcpStore.toolsCache[server.id] ||
                  mcpStore.toolsCache[server.id].length === 0
                "
                description="点击上方按钮加载工具"
                size="small"
              />
            </div>
          </NCollapseItem>
        </NCollapse>
      </NSpin>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--n-text-color-1);
}
.mcp-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mcp-name {
  font-size: 13px;
  font-weight: 500;
}
.mcp-desc {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-bottom: 8px;
}
.mcp-tools {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.mcp-tool-item {
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--n-color-hover, rgba(0, 0, 0, 0.03));
}
.tool-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--n-text-color-2);
  font-family: monospace;
}
.tool-desc {
  font-size: 11px;
  color: var(--n-text-color-3);
  margin-top: 2px;
}
</style>
