<script setup lang="ts">
import { h, ref, reactive, computed } from 'vue'
import {
  NButton, NDataTable, NDrawer, NDrawerContent, NForm, NFormItem, NInput,
  NSelect, NIcon, NTag, NSpace, NTooltip, NPopconfirm, NSwitch, NModal,
  NTabs, NTabPane, NCollapse, NCollapseItem, useMessage,
} from 'naive-ui'
import {
  RefreshOutline, BuildOutline, PulseOutline, AddOutline, TrashOutline,
  SettingsOutline, DocumentTextOutline, EllipsisHorizontalOutline,
  ChatboxOutline, FolderOpenOutline, AlertCircleOutline, TimeOutline,
  RocketOutline, SyncOutline,
} from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'
import type { McpService, McpTool, McpLogEntry, McpVersion } from '@/types/agent'
import VersionHistoryDrawer, { type VersionHistoryItem } from './VersionHistoryDrawer.vue'

const message = useMessage()
const store = useAgentHubStore()

const expandedRowKeys = ref<string[]>([])
const toolsCache = ref<Record<string, McpTool[]>>({})

// ===== 添加 MCP 抽屉 =====
const showAddDrawer = ref(false)
const addForm = reactive({
  name: '',
  description: '',
  transport: 'stdio' as 'stdio' | 'sse',
  command: '',
  args: '',
  url: '',
  envPairs: [{ key: '', value: '' }] as Array<{ key: string; value: string }>,
  registry: 'default',
  working_dir: '',
  timeout: 30,
})
const addLoading = ref(false)
const addTimeoutStr = ref('30')

function resetAddForm() {
  addForm.name = ''
  addForm.description = ''
  addForm.transport = 'stdio'
  addForm.command = ''
  addForm.args = ''
  addForm.url = ''
  addForm.envPairs = [{ key: '', value: '' }]
  addForm.registry = 'default'
  addForm.working_dir = ''
  addForm.timeout = 30
  addTimeoutStr.value = '30'
}

function addEnvPair() {
  addForm.envPairs.push({ key: '', value: '' })
}

function removeEnvPair(idx: number) {
  addForm.envPairs.splice(idx, 1)
}

async function handleAddSubmit() {
  if (!addForm.name.trim()) {
    message.warning('请填写服务名称')
    return
  }
  const env: Record<string, string> = {}
  addForm.envPairs.forEach((p) => {
    if (p.key.trim()) env[p.key.trim()] = p.value
  })

  const payload: Record<string, unknown> = {
    name: addForm.name.trim(),
    description: addForm.description.trim(),
    transport: addForm.transport,
    timeout: parseInt(addTimeoutStr.value, 10) || 30,
    registry: addForm.registry,
    working_dir: addForm.working_dir.trim(),
  }
  if (addForm.transport === 'stdio') {
    if (!addForm.command.trim()) {
      message.warning('Stdio 模式需填写启动命令')
      return
    }
    const args = addForm.args.trim() ? addForm.args.trim().split(/\s+/) : []
    payload.command = addForm.command.trim()
    if (args.length) payload.args = args
    if (Object.keys(env).length) payload.env = env
  } else {
    if (!addForm.url.trim()) {
      message.warning('SSE 模式需填写端点 URL')
      return
    }
    payload.url = addForm.url.trim()
  }

  addLoading.value = true
  try {
    await store.addMcpServer(payload as any)
    message.success('MCP 服务添加成功')
    showAddDrawer.value = false
    resetAddForm()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '添加失败')
  } finally {
    addLoading.value = false
  }
}

// ===== 配置 MCP 抽屉 =====
const showConfigDrawer = ref(false)
const configLoading = ref(false)
const activeTab = ref('general')
const editingMcp = ref<McpService | null>(null)
const configForm = reactive({
  name: '',
  description: '',
  transport: 'stdio' as 'stdio' | 'sse' | 'builtin',
  command: '',
  args: '',
  url: '',
  envPairs: [{ key: '', value: '' }] as Array<{ key: string; value: string }>,
  registry: 'default',
  working_dir: '',
  timeout: '30',
})

function parseEnvPairs(env: Record<string, string>) {
  const pairs = Object.entries(env || {})
  return pairs.length ? pairs.map(([key, value]) => ({ key, value })) : [{ key: '', value: '' }]
}

function openConfig(row: McpService) {
  editingMcp.value = row
  activeTab.value = 'general'
  configForm.name = row.name
  configForm.description = row.description
  configForm.transport = row.transport
  configForm.command = row.command
  configForm.args = (row.args || []).join(' ')
  configForm.url = row.url
  configForm.envPairs = parseEnvPairs(row.env)
  configForm.registry = row.registry || 'default'
  configForm.working_dir = row.working_dir || ''
  configForm.timeout = String(row.timeout ?? 30)
  showConfigDrawer.value = true
}

function addConfigEnvPair() {
  configForm.envPairs.push({ key: '', value: '' })
}

function removeConfigEnvPair(idx: number) {
  configForm.envPairs.splice(idx, 1)
}

// ===== 通用 Tab：按传输类型联动 =====
/** builtin（平台内置，进程内执行）或 stdio（外部本地进程）都归为「本地」一类 */
const configIsBuiltin = computed(() => editingMcp.value?.transport === 'builtin')
const configIsLocal = computed(
  () => configForm.transport === 'stdio' || configForm.transport === 'builtin',
)
const configIsOffline = computed(() => editingMcp.value?.status !== 'online')
const configTransportOptions = computed(() => {
  const opts: Array<{ label: string; value: string }> = [
    { label: 'Stdio（本地命令）', value: 'stdio' },
    { label: 'SSE（远程 HTTP）', value: 'sse' },
  ]
  if (configForm.transport === 'builtin') {
    opts.unshift({ label: 'Builtin（平台内置）', value: 'builtin' })
  }
  return opts
})

// ===== 工具 Tab：回填 + 重新发现 =====
const rediscoverLoading = ref(false)
/** 详情卡「工具」Tab 展示的工具：优先取重新发现后的缓存，否则取列表接口回填的快照 */
const configTools = computed<McpTool[]>(() => {
  if (!editingMcp.value) return []
  return toolsCache.value[editingMcp.value.id] ?? editingMcp.value.tools ?? []
})

async function handleRediscover() {
  if (!editingMcp.value) return
  const id = editingMcp.value.id
  rediscoverLoading.value = true
  try {
    const tools = await store.fetchMcpTools(id)
    toolsCache.value[id] = tools
    // 同步回详情卡与列表行，保持两处工具数据同源
    if (editingMcp.value) {
      editingMcp.value.tools = tools
      editingMcp.value.tool_count = tools.length
    }
    const row = store.mcps.find((m) => m.id === id)
    if (row) {
      row.tools = tools
      row.tool_count = tools.length
    }
    message.success(`重新发现完成，共 ${tools.length} 个工具`)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '重新发现失败，请检查服务连接')
  } finally {
    rediscoverLoading.value = false
  }
}

async function handleConfigSubmit() {
  if (!editingMcp.value) return
  const env: Record<string, string> = {}
  configForm.envPairs.forEach((p) => {
    if (p.key.trim()) env[p.key.trim()] = p.value
  })

  const payload: Record<string, unknown> = {
    description: configForm.description.trim(),
    transport: configForm.transport,
    timeout: parseInt(configForm.timeout, 10) || 30,
    registry: configForm.registry,
    working_dir: configForm.working_dir.trim(),
  }
  if (configForm.transport === 'builtin') {
    // 内置服务进程内执行，启动命令/参数/环境变量/URL 由平台管理，不下发以免清空
  } else if (configForm.transport === 'stdio') {
    payload.command = configForm.command.trim()
    payload.args = configForm.args.trim() ? configForm.args.trim().split(/\s+/) : []
    payload.url = ''
    if (Object.keys(env).length) payload.env = env
    else payload.env = {}
  } else {
    payload.url = configForm.url.trim()
    payload.command = ''
    payload.args = []
  }

  configLoading.value = true
  try {
    await store.updateMcpServer(editingMcp.value.id, payload)
    message.success('配置已保存')
    showConfigDrawer.value = false
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '保存失败')
  } finally {
    configLoading.value = false
  }
}

// ===== 日志弹窗 =====
const showLogModal = ref(false)
const logLoading = ref(false)
const logEntries = ref<McpLogEntry[]>([])
const logMcp = ref<McpService | null>(null)

async function openLogs(row: McpService) {
  logMcp.value = row
  showLogModal.value = true
  await loadLogs(row.id)
}

async function loadLogs(id: string) {
  logLoading.value = true
  try {
    logEntries.value = await store.fetchMcpLogs(id, 100)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载日志失败')
    logEntries.value = []
  } finally {
    logLoading.value = false
  }
}

function formatLogTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString()
  } catch {
    return ts
  }
}

// ===== 版本历史抽屉 =====
const showVersionDrawer = ref(false)
const versionLoading = ref(false)
const versionRollingBack = ref(false)
const versionMcp = ref<McpService | null>(null)
const versionItems = ref<McpVersion[]>([])

const MCP_SOURCE_LABELS: Record<string, string> = {
  register: '初始注册',
  preset: '预设升级',
  builder: '构建发布',
  admin: '手工更新',
  rollback: '回滚',
  publish: '转正发布',
}
const MCP_SOURCE_TYPES: Record<string, 'info' | 'default' | 'warning' | 'success'> = {
  register: 'info',
  preset: 'success',
  builder: 'info',
  admin: 'default',
  rollback: 'warning',
  publish: 'success',
}

/** 归一化为共用抽屉组件的行模型 */
const versionDrawerItems = computed<VersionHistoryItem[]>(() =>
  versionItems.value.map((v) => ({
    label: `v${v.version}`,
    primary: v.is_major,
    sourceLabel: MCP_SOURCE_LABELS[v.source] ?? v.source,
    sourceType: MCP_SOURCE_TYPES[v.source] ?? 'default',
    changelog: v.changelog ?? '',
    createdBy: v.created_by,
    createdAt: v.created_at,
    isCurrent: v.version === versionMcp.value?.current_version,
    rollbackTarget: `v${v.version}`,
    rollbackDisabled: !v.has_config_snapshot,
    rollbackDisabledReason: '该版本无配置快照，无法回滚',
    raw: v,
  })),
)

async function openVersions(row: McpService) {
  versionMcp.value = row
  showVersionDrawer.value = true
  await loadVersions(row.id)
}

async function loadVersions(id: string) {
  versionLoading.value = true
  try {
    versionItems.value = await store.fetchMcpVersions(id)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载版本历史失败')
    versionItems.value = []
  } finally {
    versionLoading.value = false
  }
}

async function handleVersionRollback(item: VersionHistoryItem) {
  const v = item.raw as McpVersion
  if (!versionMcp.value) return
  versionRollingBack.value = true
  try {
    await store.rollbackMcpServer(versionMcp.value.id, v.version)
    versionMcp.value = store.mcps.find((m) => m.id === versionMcp.value?.id) ?? versionMcp.value
    message.success(`已回滚到 v${v.version}`)
    await loadVersions(versionMcp.value.id)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '回滚失败')
  } finally {
    versionRollingBack.value = false
  }
}

// ===== 表格操作 =====
async function handleSyncPresets() {
  try {
    await store.syncMcpPresets()
    message.success('内置 MCP 预设已同步（免重启生效）')
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '同步预设失败')
  }
}

async function handlePromote(row: McpService) {
  try {
    const res = await store.promoteMcpServer(row.id)
    message.success(`${row.name} 已转正为正式 MCP（v${res?.current_version ?? ''}）`)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '转正失败')
  }
}

async function toggleEnabled(row: McpService) {
  try {
    await store.toggleMcpStatus(row.id)
    message.success(`${row.name} 已${row.is_enabled ? '停用' : '启用'}`)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleTest(row: McpService) {
  try {
    const res = await store.testMcpServer(row.id)
    if (res.success) {
      message.success(`连接成功，发现 ${res.tool_count} 个工具`)
    } else {
      message.error(`连接失败: ${res.error || '未知错误'}`)
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '测试请求失败')
  }
}

async function handleDelete(row: McpService) {
  try {
    await store.removeMcpServer(row.id)
    delete toolsCache.value[row.id]
    message.success(`已删除 ${row.name}`)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '删除失败')
  }
}

async function loadToolsForRow(row: McpService) {
  if (toolsCache.value[row.id]) return
  try {
    toolsCache.value[row.id] = await store.fetchMcpTools(row.id)
  } catch {
    toolsCache.value[row.id] = []
  }
}

function handleExpand(row: McpService) {
  if (!expandedRowKeys.value.includes(row.id)) {
    loadToolsForRow(row)
  }
}

/** 从工具的 inputSchema 中提取「参数名: 类型」列表（用于标签展示） */
function schemaParams(t: McpTool): string[] {
  const schema = (t.input_schema || {}) as Record<string, any>
  const props = (schema.properties ?? {}) as Record<string, any>
  return Object.entries(props).map(([k, v]) => `${k}: ${v?.type ?? 'any'}`)
}

function renderTools(tools: McpTool[]) {
  if (!tools.length) return h('div', { class: 'tools-empty' }, '该服务暂无工具（展开时自动加载）')
  return h('div', { class: 'tools-grid' },
    tools.map((t) => {
      const params = schemaParams(t)
      return h('div', { class: 'tool-cell' }, [
        h('div', { class: 'tool-head' }, [
          h(NIcon, { component: BuildOutline, size: 14 }),
          h('span', { class: 'tool-name' }, t.name),
        ]),
        h('div', { class: 'tool-desc' }, t.description || '暂无描述'),
        params.length
          ? h(NCollapse, { class: 'tool-schema-collapse' }, {
              default: () =>
                h(NCollapseItem, { title: `参数 Schema（${params.length}）`, name: 'schema' }, {
                  default: () =>
                    h('div', { class: 'tool-schema' },
                      params.map((p) => h(NTag, { size: 'tiny', bordered: false }, { default: () => p })),
                    ),
                }),
            })
          : null,
      ])
    }),
  )
}

const expandColumn = {
  type: 'expand' as const,
  expandable: () => true,
  renderExpand: (row: McpService) => {
    const tools = toolsCache.value[row.id] ?? row.tools
    const count = row.tool_count || tools.length
    return h('div', { class: 'expand-panel' }, [
      h('div', { class: 'expand-title' }, `内部工具（${count}）`),
      renderTools(tools),
    ])
  },
}

const registryOptions = [
  { label: '默认', value: 'default' },
  { label: '清华大学', value: 'tsinghua' },
  { label: '阿里云', value: 'aliyun' },
  { label: '中科大', value: 'ustc' },
  { label: '华为云', value: 'huawei' },
  { label: '腾讯云', value: 'tencent' },
]

const columns = [
  {
    // 不设固定宽度：作为弹性列吸收多余空间，避免末尾「操作」列被拉伸出大片空白
    title: '服务', key: 'name',
    render: (row: McpService) =>
      h('div', { class: 'mcp-name' }, [
        h('span', { class: 'mcp-icon' }, '🔌'),
        h('div', { class: 'mcp-meta' }, [
          h('div', { class: 'mcp-title' }, [
            row.name,
            (row.current_version || row.version) && h(NTag, { size: 'tiny', round: true, style: 'margin-left: 6px' }, { default: () => `v${row.current_version || row.version}` }),
            row.pool === 'experimental' && h(NTag, { size: 'tiny', round: true, type: 'warning', bordered: false, style: 'margin-left: 4px' }, { default: () => '实验' }),
            row.pool === 'deprecated' && h(NTag, { size: 'tiny', round: true, type: 'error', bordered: false, style: 'margin-left: 4px' }, { default: () => '废弃' }),
          ]),
          h('div', { class: 'mcp-desc' }, row.description),
        ]),
      ]),
  },
  { title: '传输', key: 'transport', width: 90, render: (r: McpService) => h(NTag, { size: 'small', bordered: false }, { default: () => r.transport }) },
  {
    title: '状态', key: 'status', width: 140,
    render: (row: McpService) =>
      h('span', { class: 'status-dot' }, [
        h('span', { class: ['dot', row.status === 'online' ? 'online' : 'offline'] }),
        h('span', null, row.status === 'online' ? 'Online' : 'Offline'),
        h(NSwitch, {
          size: 'small',
          value: row.is_enabled,
          onUpdateValue: () => toggleEnabled(row),
        }),
      ]),
  },
  {
    title: '工具数', key: 'tool_count', width: 80,
    render: (r: McpService) => h('span', { class: 'tool-count' }, r.tool_count || r.tools.length),
  },
  { title: '预设', key: 'is_preset', width: 60, render: (r: McpService) => (r.is_preset ? '是' : '否') },
  {
    title: '操作', key: 'actions', width: 240,
    render: (row: McpService) =>
      h(NSpace, { size: 'small' }, {
        default: () => [
          h(NTooltip, null, {
            trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => openLogs(row) },
              { default: () => [h(NIcon, { component: DocumentTextOutline })] }),
            default: () => '日志',
          }),
          h(NTooltip, null, {
            trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => openConfig(row) },
              { default: () => [h(NIcon, { component: SettingsOutline })] }),
            default: () => '配置',
          }),
          h(NTooltip, null, {
            trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => handleTest(row) },
              { default: () => [h(NIcon, { component: BuildOutline })] }),
            default: () => '测试',
          }),
          h(NTooltip, null, {
            trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => openVersions(row) },
              { default: () => [h(NIcon, { component: TimeOutline })] }),
            default: () => '版本历史',
          }),
          row.pool === 'experimental' && h(NPopconfirm, { onPositiveClick: () => handlePromote(row) }, {
            trigger: () => h(NTooltip, null, {
              trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'success' },
                { default: () => [h(NIcon, { component: RocketOutline })] }),
              default: () => '转正为正式 MCP',
            }),
            default: () => `将 ${row.name} 转正为正式 MCP？转正后永久有效、不再受 TTL 限制。`,
          }),
          !row.is_preset && h(NPopconfirm, { onPositiveClick: () => handleDelete(row) }, {
            trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' },
              { default: () => [h(NIcon, { component: TrashOutline })] }),
            default: () => '确定删除该 MCP 服务？关联的 Agent 将自动解绑。',
          }),
        ],
      }),
  },
]
</script>

<template>
  <div class="resource-tab">
    <div class="tab-header">
      <span class="tab-hint">点击服务行可展开查看其内部工具列表，透视底层能力。</span>
      <NSpace>
        <NButton size="small" quaternary @click="store.fetchMcps()">
          <template #icon><NIcon :component="RefreshOutline" /></template>
          刷新
        </NButton>
        <NTooltip>
          <template #trigger>
            <NButton size="small" quaternary @click="handleSyncPresets">
              <template #icon><NIcon :component="SyncOutline" /></template>
              同步预设
            </NButton>
          </template>
          重新同步内置 MCP（platform/tools/pipelines）工具清单，新增内置工具免重启容器生效
        </NTooltip>
        <NButton type="primary" size="small" @click="showAddDrawer = true">
          <template #icon><NIcon :component="AddOutline" /></template>
          添加 MCP 服务
        </NButton>
      </NSpace>
    </div>
    <NDataTable
      :columns="[expandColumn, ...columns]"
      :data="store.mcps"
      :row-key="(r: McpService) => r.id"
      :bordered="false"
      size="small"
      v-model:expanded-row-keys="expandedRowKeys"
      @expand="handleExpand"
    />

    <!-- 添加 MCP 服务抽屉 -->
    <NDrawer v-model:show="showAddDrawer" :width="520" placement="right" @close="resetAddForm">
      <NDrawerContent title="添加 MCP 服务" closable>
        <NForm label-placement="left" :label-width="90">
          <NFormItem label="服务名称" required>
            <NInput v-model:value="addForm.name" placeholder="例如：SequenceServer BLAST" />
          </NFormItem>

          <NFormItem label="传输方式">
            <NSelect v-model:value="addForm.transport" :options="[
              { label: 'Stdio（本地命令）', value: 'stdio' },
              { label: 'SSE（远程 HTTP）', value: 'sse' },
            ]" />
          </NFormItem>

          <template v-if="addForm.transport === 'stdio'">
            <NFormItem label="启动命令" required>
              <NInput v-model:value="addForm.command" placeholder="例如：npx、python、uvx" />
            </NFormItem>
            <NFormItem label="启动参数">
              <NInput v-model:value="addForm.args" placeholder="例如：-y @modelcontextprotocol/server-filesystem /path" />
            </NFormItem>
            <NFormItem label="包管理源">
              <NSelect v-model:value="addForm.registry" :options="registryOptions" />
            </NFormItem>
            <NFormItem label="环境变量">
              <div class="env-pairs">
                <div v-for="(pair, idx) in addForm.envPairs" :key="idx" class="env-row">
                  <NInput v-model:value="pair.key" placeholder="KEY" size="small" style="flex: 1" />
                  <NInput v-model:value="pair.value" placeholder="VALUE" size="small" style="flex: 1" />
                  <NButton size="tiny" quaternary type="error" @click="removeEnvPair(idx)" :disabled="addForm.envPairs.length <= 1">
                    <template #icon><NIcon :component="TrashOutline" /></template>
                  </NButton>
                </div>
                <NButton size="tiny" text type="primary" @click="addEnvPair">+ 添加环境变量</NButton>
              </div>
            </NFormItem>
          </template>

          <template v-else>
            <NFormItem label="SSE 端点 URL" required>
              <NInput v-model:value="addForm.url" placeholder="https://your-mcp-server.com/sse" />
            </NFormItem>
          </template>

          <NFormItem label="服务描述">
            <NInput v-model:value="addForm.description" type="textarea" :rows="2" placeholder="描述该 MCP 服务的功能..." />
          </NFormItem>

          <NFormItem label="工作目录">
            <NInput v-model:value="addForm.working_dir" placeholder="MCP 进程工作目录（可选）" />
          </NFormItem>

          <NFormItem label="超时(秒)">
            <NInput v-model:value="addTimeoutStr" placeholder="30" />
          </NFormItem>
        </NForm>

        <template #footer>
          <NSpace justify="end">
            <NButton @click="showAddDrawer = false">取消</NButton>
            <NButton type="primary" :loading="addLoading" @click="handleAddSubmit">确认添加</NButton>
          </NSpace>
        </template>
      </NDrawerContent>
    </NDrawer>

    <!-- 配置 MCP 服务抽屉 -->
    <NDrawer v-model:show="showConfigDrawer" :width="560" placement="right">
      <NDrawerContent closable>
        <template #header>
          <NSpace align="center" size="small">
            <span>{{ editingMcp?.name }}</span>
            <NTag v-if="editingMcp?.version" size="small" round>v{{ editingMcp.version }}</NTag>
            <NButton size="tiny" text @click="editingMcp && openLogs(editingMcp)">
              <template #icon><NIcon :component="DocumentTextOutline" /></template>
              日志
            </NButton>
          </NSpace>
        </template>

        <NTabs v-model:value="activeTab" type="line" animated>
          <NTabPane tab="通用" name="general">
            <NForm label-placement="left" :label-width="90">
              <NFormItem label="服务名称">
                <NTooltip>
                  <template #trigger>
                    <span class="field-fill">
                      <NInput v-model:value="configForm.name" disabled />
                    </span>
                  </template>
                  服务名称创建后不可修改
                </NTooltip>
              </NFormItem>

              <NFormItem label="传输方式">
                <NTooltip :disabled="!configIsBuiltin">
                  <template #trigger>
                    <span class="field-fill">
                      <NSelect
                        v-model:value="configForm.transport"
                        :options="configTransportOptions"
                        :disabled="configIsBuiltin"
                      />
                    </span>
                  </template>
                  内置服务的传输方式由平台决定，不可更改
                </NTooltip>
              </NFormItem>

              <template v-if="configIsLocal">
                <div v-if="configIsBuiltin" class="builtin-note">
                  <NIcon :component="AlertCircleOutline" :size="14" />
                  <span>平台内置服务，进程内执行。启动命令 / 参数 / 环境变量由平台统一管理，无需手动配置。</span>
                </div>
                <NFormItem label="启动命令">
                  <NInput v-model:value="configForm.command" :disabled="configIsBuiltin" placeholder="例如：npx、python、uvx" />
                </NFormItem>
                <NFormItem label="启动参数">
                  <NInput v-model:value="configForm.args" type="textarea" :rows="2" :disabled="configIsBuiltin" placeholder="参数以空格或换行分隔" />
                </NFormItem>
                <NFormItem label="包管理源">
                  <NSelect v-model:value="configForm.registry" :options="registryOptions" :disabled="configIsBuiltin" />
                </NFormItem>
                <NFormItem label="环境变量">
                  <div class="env-pairs">
                    <div v-for="(pair, idx) in configForm.envPairs" :key="idx" class="env-row">
                      <NInput v-model:value="pair.key" placeholder="KEY" size="small" :disabled="configIsBuiltin" style="flex: 1" />
                      <NInput v-model:value="pair.value" placeholder="VALUE" size="small" :disabled="configIsBuiltin" style="flex: 1" />
                      <NButton size="tiny" quaternary type="error" @click="removeConfigEnvPair(idx)" :disabled="configIsBuiltin || configForm.envPairs.length <= 1">
                        <template #icon><NIcon :component="TrashOutline" /></template>
                      </NButton>
                    </div>
                    <NButton v-if="!configIsBuiltin" size="tiny" text type="primary" @click="addConfigEnvPair">+ 添加环境变量</NButton>
                  </div>
                </NFormItem>
              </template>

              <template v-else>
                <NFormItem label="SSE 端点 URL">
                  <NInput v-model:value="configForm.url" placeholder="https://your-mcp-server.com/sse" />
                </NFormItem>
              </template>

              <NFormItem label="服务描述">
                <NInput v-model:value="configForm.description" type="textarea" :rows="2" />
              </NFormItem>

              <NFormItem label="工作目录">
                <NInput v-model:value="configForm.working_dir" placeholder="MCP 进程工作目录（可选）" />
              </NFormItem>

              <NFormItem label="超时(秒)">
                <NInput v-model:value="configForm.timeout" placeholder="30" />
              </NFormItem>
            </NForm>
          </NTabPane>

          <NTabPane tab="工具" name="tools">
            <div v-if="editingMcp" class="tools-panel">
              <div class="tools-toolbar">
                <span class="tools-count">共 {{ configTools.length }} 个工具</span>
                <span v-if="configIsOffline" class="tools-offline">
                  <NIcon :component="AlertCircleOutline" :size="13" />
                  服务当前离线，展示为最近一次的发现结果
                </span>
                <NTooltip :disabled="!configIsOffline">
                  <template #trigger>
                    <span class="tools-rediscover">
                      <NButton size="tiny" :loading="rediscoverLoading" :disabled="configIsOffline" @click="handleRediscover">
                        <template #icon><NIcon :component="RefreshOutline" /></template>
                        重新发现
                      </NButton>
                    </span>
                  </template>
                  服务离线，暂不能重新发现
                </NTooltip>
              </div>

              <div v-if="!configTools.length" class="tab-empty">
                <NIcon :component="BuildOutline" :size="36" class="tab-empty-icon" />
                <div class="tab-empty-title">暂无工具</div>
                <div class="tab-empty-desc">
                  {{ configIsOffline ? '服务当前离线，尚未获取到工具列表' : '尚未发现该服务的工具，可尝试重新发现' }}
                </div>
                <NButton v-if="!configIsOffline" size="small" type="primary" :loading="rediscoverLoading" @click="handleRediscover">
                  <template #icon><NIcon :component="RefreshOutline" /></template>
                  重新发现
                </NButton>
              </div>

              <div v-else class="tools-grid">
                <div v-for="t in configTools" :key="t.name" class="tool-cell">
                  <div class="tool-head">
                    <NIcon :component="BuildOutline" :size="14" />
                    <span class="tool-name">{{ t.name }}</span>
                  </div>
                  <div class="tool-desc">{{ t.description || '暂无描述' }}</div>
                  <NCollapse v-if="schemaParams(t).length" class="tool-schema-collapse">
                    <NCollapseItem :title="`参数 Schema（${schemaParams(t).length}）`" name="schema">
                      <div class="tool-schema">
                        <NTag v-for="p in schemaParams(t)" :key="p" size="tiny" :bordered="false">{{ p }}</NTag>
                      </div>
                    </NCollapseItem>
                  </NCollapse>
                </div>
              </div>
            </div>
          </NTabPane>

          <NTabPane tab="提示" name="prompts">
            <div class="tab-empty">
              <NIcon :component="ChatboxOutline" :size="36" class="tab-empty-icon" />
              <div class="tab-empty-title">暂无提示词</div>
              <div class="tab-empty-desc">平台暂未支持 MCP 提示词发现（prompts/list），将在后续版本提供。</div>
            </div>
          </NTabPane>

          <NTabPane tab="资源" name="resources">
            <div class="tab-empty">
              <NIcon :component="FolderOpenOutline" :size="36" class="tab-empty-icon" />
              <div class="tab-empty-title">暂无资源</div>
              <div class="tab-empty-desc">平台暂未支持 MCP 资源发现（resources/list），将在后续版本提供。</div>
            </div>
          </NTabPane>
        </NTabs>

        <template #footer>
          <NSpace justify="end">
            <NButton @click="showConfigDrawer = false">取消</NButton>
            <NButton type="primary" :loading="configLoading" @click="handleConfigSubmit">保存</NButton>
          </NSpace>
        </template>
      </NDrawerContent>
    </NDrawer>

    <!-- 版本历史抽屉 -->
    <VersionHistoryDrawer
      v-model:show="showVersionDrawer"
      :title="`版本历史 · ${versionMcp?.name || ''}`"
      :items="versionDrawerItems"
      :loading="versionLoading"
      :rolling-back="versionRollingBack"
      @rollback="handleVersionRollback"
    />

    <!-- 日志弹窗 -->
    <NModal v-model:show="showLogModal" preset="card" :title="`${logMcp?.name || 'MCP'} 运行日志`" style="width: 720px">      <div class="log-container">
        <div v-if="logLoading" class="log-empty">加载中...</div>
        <div v-else-if="!logEntries.length" class="log-empty">暂无日志，点击"测试"可产生新日志。</div>
        <div v-else class="log-list">
          <div v-for="(log, idx) in logEntries" :key="idx" class="log-entry">
            <span class="log-time">{{ formatLogTime(log.timestamp) }}</span>
            <span class="log-level" :class="log.level">{{ log.level }}</span>
            <span class="log-message">{{ log.message }}</span>
          </div>
        </div>
      </div>

      <template #footer>
        <NSpace justify="end">
          <NButton size="small" @click="showLogModal = false">关闭</NButton>
          <NButton v-if="logMcp" size="small" type="primary" @click="loadLogs(logMcp.id)">刷新</NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.tab-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
.tab-hint { font-size: 12px; color: var(--n-text-color-3, #999); }
.env-pairs { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.env-row { display: flex; gap: 6px; align-items: center; }
:deep(.mcp-name) { display: flex; align-items: center; gap: 10px; }
:deep(.mcp-icon) { font-size: 18px; }
:deep(.mcp-title) { font-weight: 600; display: flex; align-items: center; }
:deep(.mcp-desc) { font-size: 12px; color: var(--neutral-text-3, #999); }
:deep(.status-dot) { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; }
:deep(.status-dot .dot) { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
:deep(.status-dot .dot.online) { background: #18a058; box-shadow: 0 0 6px #18a05880; }
:deep(.status-dot .dot.offline) { background: #d03050; }
:deep(.tool-count) { font-weight: 600; color: var(--n-color-primary, #4f8ef7); }
:deep(.expand-panel) { padding: 8px 12px 16px; }
:deep(.expand-title) { font-size: 12px; color: var(--neutral-text-3, #999); margin-bottom: 10px; }
:deep(.tools-grid) { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
:deep(.tool-cell) { background: var(--neutral-hover, rgba(0,0,0,0.02)); border: 1px solid var(--n-border-color, #eee); border-radius: 8px; padding: 10px 12px; }
:deep(.tool-head) { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
:deep(.tool-name) { font-weight: 600; font-size: 13px; font-family: monospace; }
:deep(.tool-desc) { font-size: 12px; color: var(--neutral-text-2, #666); margin-bottom: 6px; }
:deep(.tool-schema) { display: flex; flex-wrap: wrap; gap: 4px; }
:deep(.tools-empty) { font-size: 12px; color: var(--neutral-text-3, #999); }

.tools-panel { padding: 8px 0; }
.field-fill { display: block; width: 100%; }
.builtin-note {
  display: flex; align-items: flex-start; gap: 6px;
  padding: 8px 10px; margin-bottom: 12px;
  font-size: 12px; line-height: 1.5; color: var(--neutral-text-2, #666);
  background: rgba(79, 142, 247, 0.08); border: 1px solid rgba(79, 142, 247, 0.2);
  border-radius: 6px;
}
.builtin-note .n-icon { flex-shrink: 0; margin-top: 2px; color: #4f8ef7; }

.tools-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.tools-count { font-size: 13px; font-weight: 600; color: var(--neutral-text-1, #333); }
.tools-offline { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: #ff8a30; }
.tools-rediscover { display: inline-flex; margin-left: auto; }

.tab-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 6px; padding: 40px 24px; text-align: center;
}
.tab-empty-icon { color: var(--neutral-text-3, #ccc); margin-bottom: 4px; }
.tab-empty-title { font-size: 14px; font-weight: 500; color: var(--neutral-text-2, #666); }
.tab-empty-desc { font-size: 12px; color: var(--neutral-text-3, #999); max-width: 320px; line-height: 1.6; }
.tab-empty .n-button { margin-top: 10px; }

.tool-schema-collapse { margin-top: 4px; }
:deep(.tool-schema-collapse .n-collapse-item__header) { font-size: 12px; }
:deep(.tool-schema-collapse .n-collapse-item__content-wrapper .n-collapse-item__content-inner) { padding-top: 6px; }

.log-container { max-height: 480px; overflow-y: auto; }
.log-empty { padding: 24px; text-align: center; color: var(--neutral-text-3, #999); font-size: 13px; }
.log-list { font-family: var(--kimi-font-mono, monospace); font-size: 13px; }
.log-entry { display: flex; align-items: flex-start; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--n-border-color, #eee); }
.log-entry:last-child { border-bottom: none; }
.log-time { color: var(--neutral-text-3, #999); white-space: nowrap; flex-shrink: 0; }
.log-level { padding: 1px 6px; border-radius: 4px; font-size: 11px; font-weight: 500; flex-shrink: 0; text-transform: uppercase; }
.log-level.info { background: rgba(79, 142, 247, 0.15); color: #4f8ef7; }
.log-level.stderr { background: rgba(255, 138, 48, 0.15); color: #ff8a30; }
.log-level.warn { background: rgba(250, 204, 21, 0.15); color: #d4a017; }
.log-level.error { background: rgba(208, 48, 80, 0.15); color: #d03050; }
.log-message { color: var(--neutral-text-1, #333); word-break: break-all; }
</style>
