<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { NButton, NCheckbox, NIcon, NInput, NSelect, NTag, useMessage } from 'naive-ui'
import { AddOutline, CheckmarkCircleOutline, CloseOutline, HammerOutline } from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'

type McpMode = 'off' | 'auto' | 'manual'

const props = defineProps<{
  mode: McpMode
  extraServers: string[]
}>()

const emit = defineEmits<{
  update: [{ mode: McpMode; extraServers: string[] }]
  close: []
}>()

const agentHub = useAgentHubStore()
const message = useMessage()
const localMode = ref<McpMode>(props.mode)
const selectedIds = ref<string[]>([...props.extraServers])
const showCustomForm = ref(false)
const saving = ref(false)
const customError = ref('')
const customForm = reactive({
  name: '',
  description: '',
  transport: 'stdio' as 'stdio' | 'sse' | 'streamable_http',
  command: '',
  url: '',
})

watch(() => props.mode, (value) => { localMode.value = value })
watch(() => props.extraServers, (value) => { selectedIds.value = [...value] })

const defaultIds = computed(() => new Set(agentHub.currentAgent?.mcp_ids || []))
const defaultServers = computed(() => agentHub.mcps.filter((server) => defaultIds.value.has(server.id)))
const addableServers = computed(() => agentHub.mcps.filter(
  (server) => server.is_enabled && !defaultIds.value.has(server.id),
))
const selectedAddableIds = computed(() => selectedIds.value.filter(
  (id) => addableServers.value.some((server) => server.id === id),
))

function publish() {
  emit('update', {
    mode: localMode.value,
    extraServers: localMode.value === 'manual' ? [...selectedAddableIds.value] : [],
  })
}

function selectMode(mode: McpMode) {
  localMode.value = mode
  publish()
}

function toggleServer(id: string, checked: boolean) {
  selectedIds.value = checked
    ? [...new Set([...selectedIds.value, id])]
    : selectedIds.value.filter((value) => value !== id)
  publish()
}

function moveSelection(delta: number) {
  const modes: McpMode[] = ['off', 'auto', 'manual']
  const index = modes.indexOf(localMode.value)
  selectMode(modes[(index + delta + modes.length) % modes.length]!)
}

function selectCurrent() {
  publish()
}

defineExpose({ moveSelection, selectCurrent })

function resetCustomForm() {
  customForm.name = ''
  customForm.description = ''
  customForm.transport = 'stdio'
  customForm.command = ''
  customForm.url = ''
  customError.value = ''
}

async function createCustomMcp() {
  customError.value = ''
  if (!customForm.name.trim()) {
    customError.value = '请输入 MCP 名称'
    return
  }
  if (customForm.transport === 'stdio' && !customForm.command.trim()) {
    customError.value = '请输入启动命令'
    return
  }
  if (customForm.transport !== 'stdio' && !customForm.url.trim()) {
    customError.value = '请输入服务 URL'
    return
  }
  saving.value = true
  try {
    const created = await agentHub.addMcpServer({
      name: customForm.name.trim(),
      description: customForm.description.trim(),
      transport: customForm.transport,
      command: customForm.transport === 'stdio' ? customForm.command.trim() : undefined,
      url: customForm.transport === 'stdio' ? undefined : customForm.url.trim(),
    })
    const result = await agentHub.testMcpServer(created.id)
    if (!result.success) {
      await agentHub.removeMcpServer(created.id)
      customError.value = result.error || 'MCP 连通性校验失败，请检查配置'
      return
    }
    selectedIds.value = [...new Set([...selectedIds.value, created.id])]
    localMode.value = 'manual'
    publish()
    showCustomForm.value = false
    resetCustomForm()
    message.success('MCP 已添加并通过连通性校验')
  } catch (error: any) {
    customError.value = error?.response?.data?.detail || error?.message || 'MCP 创建失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="mcp-selection-menu" role="dialog" aria-label="MCP 工具选择">
    <div class="mcp-menu-header">
      <div class="mcp-menu-title"><n-icon size="17"><HammerOutline /></n-icon><span>MCP 工具</span></div>
      <n-button text class="mcp-close" aria-label="关闭" @click="emit('close')"><n-icon size="18"><CloseOutline /></n-icon></n-button>
    </div>

    <div class="mcp-mode-list">
      <button class="mcp-mode-row" :class="{ active: localMode === 'off' }" @click="selectMode('off')">
        <span class="mode-mark" />
        <span><strong>关闭</strong><small>本次对话不使用 MCP 工具</small></span>
      </button>
      <button class="mcp-mode-row" :class="{ active: localMode === 'auto' }" @click="selectMode('auto')">
        <span class="mode-mark" />
        <span><strong>自动</strong><small>由 AI 根据当前 Agent 自动发现并使用</small></span>
      </button>
      <button class="mcp-mode-row" :class="{ active: localMode === 'manual' }" @click="selectMode('manual')">
        <span class="mode-mark" />
        <span><strong>手动选择</strong><small>固定使用默认 MCP，并追加你选择的服务</small></span>
      </button>
    </div>

    <div v-if="localMode === 'manual'" class="mcp-server-section">
      <div v-if="defaultServers.length" class="mcp-group-title">Agent 默认 MCP</div>
      <div v-for="server in defaultServers" :key="`default-${server.id}`" class="mcp-server-row is-default">
        <n-checkbox :checked="true" disabled />
        <n-icon size="16"><CheckmarkCircleOutline /></n-icon>
        <span class="server-copy"><strong>{{ server.name }}</strong><small>{{ server.description || 'Agent 默认服务' }}</small></span>
        <n-tag size="small" :bordered="false">默认</n-tag>
      </div>
      <div class="mcp-group-title">可追加 MCP</div>
      <div v-for="server in addableServers" :key="server.id" class="mcp-server-row">
        <n-checkbox :checked="selectedIds.includes(server.id)" @update:checked="toggleServer(server.id, $event)" />
        <span class="server-copy"><strong>{{ server.name }}</strong><small>{{ server.description || 'MCP 服务' }}</small></span>
        <n-tag size="small" :bordered="false">MCP</n-tag>
      </div>
      <div v-if="!addableServers.length" class="mcp-empty">暂无其他已配置 MCP 服务</div>

      <div v-if="!showCustomForm" class="mcp-add-entry" role="button" tabindex="0" @click="showCustomForm = true">
        <n-icon size="16"><AddOutline /></n-icon> 添加自定义 MCP...
      </div>
      <div v-else class="mcp-custom-form">
        <n-input v-model:value="customForm.name" size="small" placeholder="MCP 名称" />
        <n-input v-model:value="customForm.description" size="small" placeholder="描述（可选）" />
        <n-select v-model:value="customForm.transport" size="small" :options="[
          { label: 'Stdio（本地命令）', value: 'stdio' },
          { label: 'SSE（远程 HTTP）', value: 'sse' },
          { label: 'Streamable HTTP', value: 'streamable_http' },
        ]" />
        <n-input v-if="customForm.transport === 'stdio'" v-model:value="customForm.command" size="small" placeholder="启动命令，例如 uvx" />
        <n-input v-else v-model:value="customForm.url" size="small" placeholder="服务 URL" />
        <div v-if="customError" class="mcp-form-error">{{ customError }}</div>
        <div class="mcp-form-actions">
          <n-button size="small" quaternary @click="showCustomForm = false; resetCustomForm()">取消</n-button>
          <n-button size="small" type="primary" :loading="saving" @click="createCustomMcp">保存并校验</n-button>
        </div>
      </div>
    </div>

    <div class="mcp-menu-footer"><span><kbd>Esc</kbd> 关闭</span><span><kbd>↑</kbd><kbd>↓</kbd> 选择 <kbd>Enter</kbd> 确认</span></div>
  </div>
</template>

<style scoped lang="scss">
.mcp-selection-menu {
  position: absolute;
  z-index: 0;
  left: -1px;
  right: -1px;
  bottom: calc(100% - 1px);
  overflow: hidden;
  color: var(--chat-text-primary);
  background: var(--chat-input-bg);
  border: 1px solid var(--chat-input-border);
  border-bottom: none;
  border-radius: var(--chat-radius-xl, 20px) var(--chat-radius-xl, 20px) 0 0;
}
.mcp-menu-header, .mcp-menu-footer { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; }
.mcp-menu-header { border-bottom: 1px solid var(--chat-border); }
.mcp-menu-title { display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 650; }
.mcp-close { color: var(--chat-text-muted); }
.mcp-mode-list, .mcp-server-section { padding: 8px 10px; }
.mcp-mode-row { display: flex; width: 100%; gap: 10px; padding: 8px 9px; text-align: left; color: inherit; background: transparent; border: 0; border-radius: 9px; cursor: pointer; }
.mcp-mode-row:hover, .mcp-mode-row.active { background: var(--chat-surface-hover); }
.mcp-mode-row.active .mode-mark { border-color: var(--chat-accent); box-shadow: inset 0 0 0 4px var(--chat-input-bg); background: var(--chat-accent); }
.mode-mark { flex: 0 0 14px; width: 14px; height: 14px; margin-top: 2px; border: 1px solid var(--chat-text-muted); border-radius: 50%; }
.mcp-mode-row span:last-child, .server-copy { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.mcp-mode-row strong, .server-copy strong { font-size: 13px; font-weight: 600; }
.mcp-mode-row small, .server-copy small { overflow: hidden; color: var(--chat-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.mcp-group-title { margin: 8px 4px 5px; color: var(--chat-text-muted); font-size: 11px; font-weight: 600; }
.mcp-server-row { display: flex; align-items: center; gap: 8px; min-height: 38px; padding: 5px 4px; }
.mcp-server-row > .n-icon { color: var(--chat-accent); }
.server-copy { flex: 1; }
.mcp-empty { padding: 8px 4px; color: var(--chat-text-muted); font-size: 12px; }
.mcp-add-entry { display: flex; align-items: center; gap: 5px; padding: 9px 4px 3px; color: var(--chat-accent); font-size: 12px; cursor: pointer; }
.mcp-custom-form { display: grid; gap: 7px; padding: 8px 4px 2px; }
.mcp-form-error { color: var(--chat-error, #dc2626); font-size: 12px; line-height: 1.4; }
.mcp-form-actions { display: flex; justify-content: flex-end; gap: 6px; }
.mcp-menu-footer { border-top: 1px solid var(--chat-border); color: var(--chat-text-muted); font-size: 11px; }
kbd { padding: 1px 5px; border: 1px solid var(--chat-border); border-radius: 4px; background: var(--chat-surface); font-size: 10px; }
@media (max-width: 640px) { .mcp-selection-menu { max-height: min(70vh, 520px); overflow-y: auto; } .mcp-menu-footer { display: none; } }
</style>
