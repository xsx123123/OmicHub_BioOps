<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { NIcon } from 'naive-ui'
import {
  SearchOutline,
  AnalyticsOutline,
  FolderOutline,
  CodeSlashOutline,
  ExtensionPuzzleOutline,
  RocketOutline,
  BarChartOutline,
  GridOutline,
  DocumentTextOutline,
  HelpCircleOutline,
  PersonOutline,
  ChatbubbleEllipsesOutline,
  CompassOutline,
  PlayCircleOutline,
  SearchCircleOutline,
  ShieldCheckmarkOutline,
  LockOpenOutline,
  KeyOutline,
  FlagOutline,
} from '@vicons/ionicons5'
import type { AgentTemplate } from '@/types/agent'
import { recentRank } from './recentItems'

interface Props {
  query?: string
  /** / 面板「智能体」分组数据源（选中后插入 @mention 标签） */
  agents?: AgentTemplate[]
}

const props = withDefaults(defineProps<Props>(), {
  query: '',
  agents: () => [],
})

const emit = defineEmits<{
  select: [command: string]
  selectAgent: [agent: AgentTemplate]
  close: []
}>()

const listRef = ref<HTMLDivElement>()
const selectedIndex = ref(0)

interface Row {
  /** 唯一 id（最近使用记录键）；命令为 /xxx，智能体为 agent-<id> */
  id: string
  name: string
  description: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  icon: any
  shortcut?: string
  isCategory?: boolean
  agent?: AgentTemplate
}

/** 技能分组：能力调用命令（现有 /analysis、/rna、/go 等） */
const SKILL_COMMANDS: Row[] = [
  { id: '/rna', name: 'RNA-seq 分析', description: '差异表达基因分析', icon: BarChartOutline, shortcut: '/rna' },
  { id: '/go', name: 'GO 富集分析', description: '基因功能富集分析', icon: BarChartOutline, shortcut: '/go' },
  { id: '/kegg', name: 'KEGG 通路分析', description: '代谢通路富集分析', icon: BarChartOutline, shortcut: '/kegg' },
  { id: '/data', name: '查询项目数据', description: '查看您的实验数据', icon: FolderOutline, shortcut: '/data' },
  { id: '/task', name: '查看分析任务', description: '查看正在运行的任务', icon: DocumentTextOutline, shortcut: '/task' },
  { id: '/code', name: '代码执行', description: '在沙盒中执行 Python/R 代码', icon: CodeSlashOutline, shortcut: '/code' },
  { id: '/search', name: '文献搜索', description: '搜索 PubMed 等数据库', icon: SearchOutline, shortcut: '/search' },
  { id: '/plugin', name: '插件市场', description: '浏览可用插件', icon: ExtensionPuzzleOutline, shortcut: '/plugin' },
]

const AGENT_MODE_COMMANDS: Row[] = [
  { id: '/chat', name: 'Chat 模式', description: '普通对话与知识解释', icon: ChatbubbleEllipsesOutline, shortcut: '/chat' },
  { id: '/plan', name: 'Plan 模式', description: '制定计划，不直接执行分析', icon: CompassOutline, shortcut: '/plan' },
  { id: '/run', name: 'Execute 模式', description: '执行已确认的分析计划', icon: PlayCircleOutline, shortcut: '/run' },
  { id: '/research', name: 'Research 模式', description: '文献搜索、数据库查询与方法调研', icon: SearchCircleOutline, shortcut: '/research' },
  { id: '/goal', name: '设置任务目标', description: '为当前对话声明一个明确目标', icon: FlagOutline, shortcut: '/goal' },
  { id: '/goal start', name: '启动持久 Goal', description: '后台安全推进，并保留可恢复的执行状态', icon: FlagOutline, shortcut: '/goal start' },
  { id: '/goal status', name: '查看 Goal 状态', description: '显示当前会话的持久目标与执行时间线', icon: FlagOutline, shortcut: '/goal status' },
  { id: '/goal pause', name: '暂停 Goal', description: '暂停当前目标的后台续跑', icon: FlagOutline, shortcut: '/goal pause' },
  { id: '/goal resume', name: '继续 Goal', description: '恢复已暂停或等待补充的目标', icon: FlagOutline, shortcut: '/goal resume' },
  { id: '/goal cancel', name: '取消 Goal', description: '停止当前会话的持久目标', icon: FlagOutline, shortcut: '/goal cancel' },
]

const PERMISSION_COMMANDS: Row[] = [
  { id: '/safe', name: 'Safe 权限', description: '仅对话和知识解释，不访问数据', icon: ShieldCheckmarkOutline, shortcut: '/safe' },
  { id: '/read', name: 'Read 权限', description: '读取工作区、样本和分析结果', icon: LockOpenOutline, shortcut: '/read' },
  { id: '/analysis', name: 'Analysis 权限', description: '读取数据、调用 Pipeline 并生成结果', icon: AnalyticsOutline, shortcut: '/analysis' },
  { id: '/full', name: 'Full 权限', description: '允许修改文件和管理任务', icon: KeyOutline, shortcut: '/full' },
]

/** 内置命令分组（平台内置，非技能） */
const BUILTIN_COMMANDS: Row[] = [
  { id: '/agent', name: 'Agent 模式', description: '切换到 Agent 自主模式', icon: RocketOutline, shortcut: '/agent' },
  { id: '/help', name: '使用帮助', description: '查看 AI 助手使用指南', icon: HelpCircleOutline, shortcut: '/help' },
  { id: '/grid', name: '数据表格', description: '查看数据表格视图', icon: GridOutline, shortcut: '/grid' },
]

const CATEGORY = (id: string, name: string): Row => ({ id, name, description: '', icon: null, isCategory: true })

function matches(q: string, name: string, description: string, id: string): boolean {
  if (!q) return true
  return (
    name.toLowerCase().includes(q) ||
    description.toLowerCase().includes(q) ||
    id.toLowerCase().includes(q)
  )
}

/** 组内排序：最近使用置顶，其余按名称 */
function sortRows(rows: Row[]): Row[] {
  return [...rows].sort(
    (a, b) =>
      recentRank('slash', a.id) - recentRank('slash', b.id) ||
      a.name.localeCompare(b.name, 'zh'),
  )
}

const rows = computed<Row[]>(() => {
  const q = props.query.toLowerCase().trim()

  const skills = sortRows(
    SKILL_COMMANDS.filter((c) => matches(q, c.name, c.description, c.id)),
  )
  const agentRows = sortRows(
    props.agents
      .filter((a) => matches(q, a.name, a.description || '', a.name))
      .map<Row>((a) => ({
        id: `agent-${a.id}`,
        name: a.name,
        description: a.description || '指定此智能体处理本条消息',
        icon: PersonOutline,
        shortcut: `/${a.name}`,
        agent: a,
      })),
  )
  const builtins = sortRows(
    BUILTIN_COMMANDS.filter((c) => matches(q, c.name, c.description, c.id)),
  )
  const modes = sortRows(AGENT_MODE_COMMANDS.filter((c) => matches(q, c.name, c.description, c.id)))
  const permissions = sortRows(PERMISSION_COMMANDS.filter((c) => matches(q, c.name, c.description, c.id)))

  const result: Row[] = []
  if (modes.length) {
    result.push(CATEGORY('category-modes', 'Agent 模式'))
    result.push(...modes)
  }
  if (permissions.length) {
    result.push(CATEGORY('category-permissions', 'Permission'))
    result.push(...permissions)
  }
  if (skills.length) {
    result.push(CATEGORY('category-skills', '技能'))
    result.push(...skills)
  }
  if (agentRows.length) {
    result.push(CATEGORY('category-agents', '智能体'))
    result.push(...agentRows)
  }
  if (builtins.length) {
    result.push(CATEGORY('category-builtin', '内置命令'))
    result.push(...builtins)
  }
  return result
})

const selectableCommands = computed(() => rows.value.filter((row) => !row.isCategory))

watch(
  () => props.query,
  () => {
    selectedIndex.value = 0
  },
)

function handleSelect(row: Row) {
  if (row.isCategory) return
  if (row.agent) {
    emit('selectAgent', row.agent)
    return
  }
  emit('select', row.id)
}

function scrollToSelected() {
  nextTick(() => {
    const activeEl = listRef.value?.querySelector('.command-item.active')
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  })
}

function moveSelection(delta: number) {
  selectedIndex.value =
    (selectedIndex.value + delta + selectableCommands.value.length) % Math.max(selectableCommands.value.length, 1)
  scrollToSelected()
}

function selectCurrent() {
  const row = selectableCommands.value[selectedIndex.value]
  if (row) handleSelect(row)
}

defineExpose({ moveSelection, selectCurrent })
</script>

<template>
  <div
    class="slash-command-menu"
  >
    <div class="menu-header">
      <span class="header-title">/ 唤起</span>
      <span class="header-sub">输入 / 筛选技能或指定本条消息的智能体</span>
    </div>

    <div ref="listRef" v-animate-list.200 class="command-list">
      <div
        v-for="row in rows"
        :key="row.id"
        class="command-item"
        :class="{
          active: !row.isCategory && selectableCommands[selectedIndex]?.id === row.id,
          category: row.isCategory,
          'is-agent': !!row.agent,
        }"
        @click="handleSelect(row)"
        @mouseenter="!row.isCategory && (selectedIndex = selectableCommands.findIndex((item) => item.id === row.id))"
      >
        <template v-if="row.isCategory">
          <span class="category-label">{{ row.name }}</span>
        </template>
        <template v-else>
          <div class="command-icon" :class="{ 'agent-icon': !!row.agent }">
            <n-icon size="18"><component :is="row.icon" /></n-icon>
          </div>
          <div class="command-info">
            <div class="command-name">{{ row.name }}</div>
            <div class="command-desc">{{ row.description }}</div>
          </div>
          <div class="command-shortcut">{{ row.shortcut || row.id }}</div>
        </template>
      </div>

      <div v-if="rows.length === 0" class="menu-empty">
        没有匹配的技能或智能体
      </div>
    </div>

    <div class="menu-footer">
      <div class="footer-hint">
        <kbd>↑</kbd><kbd>↓</kbd> 导航
      </div>
      <div class="footer-hint">
        <kbd>Enter</kbd> 选择
      </div>
      <div class="footer-hint">
        <kbd>Esc</kbd> 关闭
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.slash-command-menu {
  position: absolute;
  left: -1px;
  right: -1px;
  bottom: calc(100% - 1px);
  z-index: 0;
  width: auto;
  max-width: none;
  background: var(--chat-input-bg);
  border: 1px solid var(--chat-input-border);
  border-bottom: none;
  border-radius: var(--chat-radius-xl, 20px) var(--chat-radius-xl, 20px) 0 0;
  box-shadow: none;
  max-height: 320px;
  overflow: hidden;
  transform-origin: bottom;

  .menu-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--chat-input-border);

    .header-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--chat-text-primary);
    }

    .header-sub {
      font-size: 12px;
      color: var(--chat-text-secondary);
    }
  }

  .command-list {
    max-height: 220px;
    overflow-y: auto;
    padding: 4px;

    .command-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.15s ease;
      color: var(--chat-text-primary);

      &:hover,
      &.active {
        background: var(--chat-surface-hover);
      }

      &.category {
        padding: 6px 12px;
        cursor: default;
        pointer-events: none;

        &:hover {
          background: transparent;
        }

        .category-label {
          font-size: 11px;
          color: var(--chat-text-muted);
          text-transform: uppercase;
          letter-spacing: 1px;
          font-weight: 500;
        }
      }

      .command-icon {
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--icon-blue-bg, rgba(79, 142, 247, 0.1));
        border-radius: 8px;
        color: var(--chat-accent);
        flex-shrink: 0;

        &.agent-icon {
          background: var(--icon-purple-bg, rgba(124, 111, 212, 0.12));
          color: var(--icon-visualization, #7c6fd4);
        }
      }

      .command-info {
        flex: 1;
        min-width: 0;

        .command-name {
          font-size: 14px;
          font-weight: 500;
        }

        .command-desc {
          font-size: 12px;
          color: var(--chat-text-muted);
          margin-top: 1px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }

      .command-shortcut {
        font-size: 12px;
        color: var(--chat-text-muted);
        font-family: 'Courier New', monospace;
        flex-shrink: 0;
      }
    }

    .menu-empty {
      padding: 24px;
      text-align: center;
      font-size: 13px;
      color: var(--chat-text-muted);
    }
  }

  .menu-footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 16px;
    padding: 8px 14px;
    border-top: 1px solid var(--chat-input-border);
    background: transparent;

    .footer-hint {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
      color: var(--chat-text-muted);

      kbd {
        display: inline-block;
        padding: 2px 6px;
        background: var(--chat-surface-hover);
        border: 1px solid var(--chat-border);
        border-radius: 4px;
        font-size: 11px;
        font-family: inherit;
      }
    }
  }
}

</style>
