<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NButton, NDrawer, NDrawerContent, NIcon, NInput, useMessage } from 'naive-ui'
import { CloseOutline, CreateOutline, SearchOutline, TimeOutline } from '@vicons/ionicons5'
import { formatDistanceToNow, parseISO } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import { useAgentHubStore, type AgentSession } from '@/stores/agentHub'

const props = withDefaults(defineProps<{
  show: boolean
  mode?: 'all' | 'chat' | 'studio'
}>(), { mode: 'all' })

const emit = defineEmits<{
  'update:show': [value: boolean]
  select: [session: AgentSession, messageId?: string]
}>()

const store = useAgentHubStore()
const message = useMessage()
const keyword = ref('')
const searching = ref(false)
const titleMatches = ref<AgentSession[]>([])
type ContentMatch = { session_id: string; title: string; title_locked: boolean; agent_id: string | null; model_id: string; mode: 'chat' | 'studio'; message_id: string; snippet: string; created_at: string; updated_at: string }
const contentMatches = ref<ContentMatch[]>([])
const editingId = ref('')
const editingTitle = ref('')
const sessionMap = computed(() => new Map(store.sessions.map((s) => [s.id, s])))
let searchTimer: ReturnType<typeof setTimeout> | null = null

const visibleSessions = computed(() => store.sessions.filter((s) => {
  if (props.mode === 'all') return true
  return props.mode === (s.mode || (store.studioSessionIds.has(s.id) ? 'studio' : 'chat'))
}))

const displaySessions = computed(() => {
  const sessions = keyword.value.trim() ? titleMatches.value : visibleSessions.value
  if (props.mode === 'all') return sessions
  return sessions.filter((s) => props.mode === (s.mode || (store.studioSessionIds.has(s.id) ? 'studio' : 'chat')))
})
const displayContentMatches = computed(() => props.mode === 'all'
  ? contentMatches.value
  : contentMatches.value.filter((item) => item.mode === props.mode))
const hasResults = computed(() => displaySessions.value.length || displayContentMatches.value.length)

function close() { emit('update:show', false) }

function relativeTime(value: string): string {
  try {
    return formatDistanceToNow(parseISO(value), { addSuffix: true, locale: zhCN })
  } catch {
    return ''
  }
}

function highlightSegments(value: string): Array<{ text: string; match: boolean }> {
  const query = keyword.value.trim()
  if (!query) return [{ text: value, match: false }]
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return value.split(new RegExp(`(${escaped})`, 'ig')).filter(Boolean).map((text) => ({
    text,
    match: text.toLocaleLowerCase() === query.toLocaleLowerCase(),
  }))
}

function onSearch(value: string) {
  keyword.value = value
  if (searchTimer) clearTimeout(searchTimer)
  if (!value.trim()) {
    titleMatches.value = []
    contentMatches.value = []
    return
  }
  searchTimer = setTimeout(async () => {
    searching.value = true
    try {
      const result = await store.searchSessions(value)
      titleMatches.value = result.title_matches
      contentMatches.value = result.content_matches
    } catch {
      titleMatches.value = []
      contentMatches.value = []
    } finally {
      searching.value = false
    }
  }, 300)
}

function startRename(session: AgentSession) {
  editingId.value = session.id
  editingTitle.value = session.title === '生成中...' ? '' : session.title
  void nextTick(() => document.querySelector<HTMLInputElement>('.session-title-editor input')?.focus())
}

async function saveRename(session: AgentSession) {
  if (!editingTitle.value.trim()) {
    editingId.value = ''
    return
  }
  try {
    await store.renameSession(session.id, editingTitle.value)
  } catch {
    message.warning('重命名失败，请稍后重试')
  }
  editingId.value = ''
}

async function removeSession(session: AgentSession) {
  if (!window.confirm(`确定删除“${session.title}”吗？删除后无法恢复。`)) return
  await store.deleteSession(session.id)
}

function selectSession(session: AgentSession, messageId?: string) {
  emit('select', session, messageId)
  close()
}

function selectContentMatch(item: ContentMatch) {
  const session = sessionMap.value.get(item.session_id) || {
    id: item.session_id,
    title: item.title,
    agent_id: item.agent_id || '',
    messages: [],
    created_at: item.created_at,
    updated_at: item.updated_at,
    mode: item.mode,
    title_locked: item.title_locked,
    model_id: item.model_id || undefined,
  }
  emit('select', session, item.message_id)
  close()
}

watch(() => props.show, (show) => {
  if (!show) {
    keyword.value = ''
    titleMatches.value = []
    contentMatches.value = []
    editingId.value = ''
  }
})
</script>

<template>
  <NDrawer :show="show" :width="320" placement="left" @update:show="emit('update:show', $event)">
    <NDrawerContent closable>
      <template #header>
        <div class="history-heading"><NIcon><TimeOutline /></NIcon><span>历史会话</span></div>
      </template>
      <div class="history-drawer">
        <NInput
          :value="keyword"
          clearable
          placeholder="搜索会话标题或内容…"
          class="history-search"
          @update:value="onSearch"
        >
          <template #prefix><NIcon><SearchOutline /></NIcon></template>
        </NInput>

        <div v-if="searching" class="history-state">正在搜索…</div>
        <template v-else-if="hasResults">
          <section v-if="displaySessions.length" class="history-section">
            <h3>{{ keyword ? '标题匹配' : '最近会话' }}</h3>
            <div class="history-scroller">
              <div v-for="item in displaySessions" :key="item.id" class="history-item" :class="{ active: item.id === store.currentSessionId }">
                <button class="history-item-main" @click="selectSession(item)">
                  <span v-if="editingId !== item.id" class="history-title"><template v-for="(part, partIndex) in highlightSegments(item.title)" :key="partIndex"><mark v-if="part.match">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></span>
                  <NInput
                    v-else
                    v-model:value="editingTitle"
                    size="small"
                    class="session-title-editor"
                    @keyup.enter="saveRename(item)"
                    @keyup.esc="editingId = ''"
                    @blur="saveRename(item)"
                    @click.stop
                  />
                  <span class="history-time">{{ relativeTime(item.updated_at) }}</span>
                </button>
                <span v-if="item.mode === 'studio' || store.studioSessionIds.has(item.id)" class="mode-dot">工作台</span>
                <span v-if="item.overdrive" class="mode-dot mode-dot--overdrive">超频模式</span>
                <span v-if="item.workspace_archive" class="mode-dot mode-dot--archived">已归档</span>
                <div class="history-actions">
                  <NButton text size="tiny" title="重命名" @click.stop="startRename(item)"><NIcon><CreateOutline /></NIcon></NButton>
                  <NButton text size="tiny" title="删除" @click.stop="removeSession(item)"><NIcon><CloseOutline /></NIcon></NButton>
                </div>
              </div>
            </div>
          </section>
          <section v-if="displayContentMatches.length" class="history-section">
            <h3>内容匹配</h3>
            <button
              v-for="item in displayContentMatches"
              :key="`${item.session_id}-${item.message_id}`"
              class="content-match"
              @click="selectContentMatch(item)"
            >
              <strong><template v-for="(part, partIndex) in highlightSegments(item.title)" :key="partIndex"><mark v-if="part.match">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></strong>
              <span><template v-for="(part, partIndex) in highlightSegments(item.snippet)" :key="partIndex"><mark v-if="part.match">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></span>
            </button>
          </section>
        </template>
        <div v-else class="history-state">
          <div class="history-empty-art">✦ · ˚ ✧</div>
          {{ keyword ? '未找到相关会话' : '还没有历史会话，开始你的第一次分析吧' }}
        </div>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped lang="scss">
.history-heading { display: flex; align-items: center; gap: 8px; font-weight: 650; }
.history-drawer { display: flex; flex-direction: column; gap: 16px; height: 100%; }
.history-search { flex-shrink: 0; }
.history-section { display: flex; flex-direction: column; gap: 8px; min-height: 0; }
.history-section h3 { margin: 0 4px; color: var(--text-tertiary); font-size: 11px; font-weight: 600; }
.history-scroller { display: flex; flex: 1; min-height: 0; flex-direction: column; gap: 8px; overflow-y: auto; }
.history-item { position: relative; display: flex; align-items: center; gap: 4px; min-height: 56px; padding: 6px 4px 6px 10px; border-radius: 8px; transition: background .16s ease; }
.history-item:hover, .history-item.active { background: var(--brand-primary-light); }
.history-item-main { display: flex; flex: 1; min-width: 0; flex-direction: column; align-items: flex-start; gap: 4px; border: 0; background: transparent; text-align: left; cursor: pointer; }
.history-title { width: 100%; overflow: hidden; color: var(--text-primary); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.history-time { color: var(--text-tertiary); font-size: 11px; }
.history-actions { display: flex; opacity: 0; transition: opacity .16s ease; }
.history-item:hover .history-actions { opacity: 1; }
.mode-dot { flex-shrink: 0; color: var(--brand-primary); font-size: 10px; }
.mode-dot--overdrive { color: #e6a23c; }
.mode-dot--archived {
  padding: 0 6px;
  border: 1px solid var(--neutral-border, var(--chat-border));
  border-radius: 999px;
  color: var(--text-tertiary, var(--neutral-text-3));
  background: color-mix(in srgb, var(--neutral-text-3, #86909c) 8%, transparent);
  line-height: 15px;
}
.history-state { display: grid; flex: 1; place-content: center; justify-items: center; gap: 10px; color: var(--text-tertiary); font-size: 12px; text-align: center; line-height: 1.6; }
.history-empty-art { color: var(--brand-primary); font-size: 28px; }
.content-match { display: flex; flex-direction: column; gap: 4px; padding: 9px 10px; border: 1px solid var(--brand-primary-light); border-radius: 8px; background: var(--bg-card); text-align: left; cursor: pointer; }
.content-match:hover { border-color: var(--brand-primary); }
.content-match strong { overflow: hidden; color: var(--text-primary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.content-match span { display: -webkit-box; overflow: hidden; color: var(--text-secondary); font-size: 11px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
mark { padding: 0 1px; color: inherit; background: color-mix(in srgb, var(--brand-primary) 20%, transparent); }
</style>
