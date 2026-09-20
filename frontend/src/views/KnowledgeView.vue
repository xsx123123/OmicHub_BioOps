<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStorage } from '@vueuse/core'
import {
  NCard,
  NSpin,
  NButton,
  NSpace,
  NIcon,
  NPopconfirm,
  NTooltip,
  useMessage,
} from 'naive-ui'
import {
  CreateOutline,
  SaveOutline,
  CloseOutline,
  AddOutline,
  ChevronBackOutline,
  ChevronForwardOutline,
  DocumentTextOutline,
  HourglassOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import DocTree from '@/components/knowledge/DocTree.vue'
import DocReader from '@/components/knowledge/DocReader.vue'
import DocEditor from '@/components/knowledge/DocEditor.vue'
import DocCreateModal from '@/components/knowledge/DocCreateModal.vue'
import AuditPendingPanel from '@/components/knowledge/AuditPendingPanel.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { KnowledgeItem, KnowledgeDoc, DocTreeNode } from '@/types/knowledge'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const authStore = useAuthStore()

const navTitle = ref('实验室知识库')
const navItems = ref<KnowledgeItem[]>([])
const activeDoc = ref<KnowledgeDoc | null>(null)
const isEditMode = ref(false)
// 侧边栏默认折叠（图6 窄条样式），并把用户的展开/折叠选择持久化到 localStorage
const isNavigationCollapsed = useStorage('cygnusx:knowledge:sider-collapsed', true)

const loadingNav = ref(false)
const loadingDoc = ref(false)
const saving = ref(false)

const editBuffer = ref('')
const draftContent = ref('')
const draftSummary = ref('')

const showCreateModal = ref(false)
const showAuditPanel = ref(false)
const expandedKeys = ref<string[]>([])

const isAdmin = computed(() => authStore.isAdmin)

const documentTree = computed<DocTreeNode[]>(() => {
  const groups = new Map<string, KnowledgeItem[]>()
  for (const item of navItems.value) {
    const cat = item.category || '未分类'
    if (!groups.has(cat)) groups.set(cat, [])
    groups.get(cat)!.push(item)
  }
  return Array.from(groups.entries()).map(([cat, items]) => ({
    key: `cat:${cat}`,
    label: cat,
    isCategory: true,
    children: items.map((it) => ({
      key: `doc:${it.id}`,
      label: it.title,
      docId: it.id,
      status: it.status,
    })),
  }))
})

const existingCategories = computed(() =>
  [...new Set(navItems.value.map((item) => item.category).filter(Boolean))] as string[],
)

async function fetchNav() {
  loadingNav.value = true
  try {
    const res = await apiClient.get<{ title: string; items: KnowledgeItem[] }>(
      '/docs/knowledge',
    )
    navTitle.value = res.data.title
    navItems.value = res.data.items
  } catch {
    message.error('获取知识库目录失败')
    navItems.value = []
  } finally {
    loadingNav.value = false
  }
}

async function fetchDoc(docId: string) {
  loadingDoc.value = true
  try {
    const res = await apiClient.get<KnowledgeDoc>(`/docs/knowledge/${docId}`)
    activeDoc.value = res.data
  } catch {
    message.error('获取文档内容失败')
    activeDoc.value = null
  } finally {
    loadingDoc.value = false
  }
}

function selectDoc(docId: string) {
  if (isEditMode.value) {
    message.warning('请先保存或取消当前编辑')
    return
  }
  router.push({ name: 'knowledge-doc', params: { docId } })
}

function toggleNavigation() {
  isNavigationCollapsed.value = !isNavigationCollapsed.value
}

function startEdit() {
  if (!activeDoc.value) return
  editBuffer.value = activeDoc.value.content
  draftContent.value = activeDoc.value.content
  draftSummary.value = ''
  isEditMode.value = true
}

function cancelEdit() {
  draftContent.value = editBuffer.value
  draftSummary.value = ''
  isEditMode.value = false
}

async function saveDoc() {
  if (!activeDoc.value) return
  saving.value = true
  try {
    const res = await apiClient.put(`/docs/knowledge/${activeDoc.value.id}`, {
      content: draftContent.value,
      editSummary: draftSummary.value || undefined,
    })
    isEditMode.value = false
    message.success(res.data.message || '保存成功')
    await fetchDoc(activeDoc.value.id)
    await fetchNav()
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function deleteDoc() {
  if (!activeDoc.value) return
  try {
    await apiClient.delete(`/docs/knowledge/${activeDoc.value.id}`)
    message.success('文档已删除')
    activeDoc.value = null
    await fetchNav()
    // 删除后跳转到第一个文档，如果没有则清空路由参数
    if (documentTree.value.length > 0) {
      const firstLeaf = documentTree.value[0].children?.[0]
      if (firstLeaf?.docId) {
        await router.replace({ name: 'knowledge-doc', params: { docId: firstLeaf.docId } })
      } else {
        await router.replace({ name: 'knowledge' })
      }
    } else {
      await router.replace({ name: 'knowledge' })
    }
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '删除失败')
  }
}

function handleCreated(docId: string) {
  void fetchNav()
  router.push({ name: 'knowledge-doc', params: { docId } })
}

function handleAudited() {
  void fetchNav()
  if (activeDoc.value) {
    void fetchDoc(activeDoc.value.id)
  }
}

watch(
  () => route.params.docId as string | undefined,
  (docId) => {
    if (docId) {
      void fetchDoc(docId)
    }
  },
  { immediate: true },
)

onMounted(async () => {
  await fetchNav()
  const docId = route.params.docId as string | undefined
  if (!docId && documentTree.value.length > 0) {
    const firstLeaf = documentTree.value[0].children?.[0]
    if (firstLeaf?.docId) {
      router.replace({ name: 'knowledge-doc', params: { docId: firstLeaf.docId } })
    }
  }
})
</script>

<template>
  <!-- 单根节点：DefaultLayout 用 <Transition mode="out-in"> 包裹路由组件，
       fragment（多根）会导致 SPA 跳转时组件不挂载（vuejs/core#6656）→ 空白页。
       弹窗组件 teleport 到 body，移入 main 内不影响渲染位置 -->
  <main class="docs-layout page-container" aria-label="知识库">
    <!-- 左侧目录树 -->
    <div class="docs-sider" :class="{ 'docs-sider--collapsed': isNavigationCollapsed }">
      <NCard :bordered="false" class="arco-card nav-card">
        <div v-if="isNavigationCollapsed" class="collapsed-rail">
          <div class="collapsed-rail__header">
            <NTooltip placement="right" :delay="300">
              <template #trigger>
                <button
                  class="collapse-toggle-btn"
                  aria-label="展开文档导航"
                  aria-expanded="false"
                  aria-controls="knowledge-document-navigation"
                  title="展开文档导航"
                  @click="toggleNavigation"
                >
                  <NIcon :size="16"><ChevronForwardOutline /></NIcon>
                </button>
              </template>
              展开文档导航
            </NTooltip>
          </div>

          <div class="collapsed-rail__context" aria-hidden="true">
            <span class="collapsed-rail__icon">
              <NIcon :size="18"><DocumentTextOutline /></NIcon>
            </span>
          </div>

          <div class="collapsed-rail__actions">
            <NTooltip placement="right" :delay="300">
              <template #trigger>
                <button
                  class="collapsed-rail__action"
                  aria-label="新建文档"
                  @click="showCreateModal = true"
                >
                  <NIcon :size="18"><AddOutline /></NIcon>
                </button>
              </template>
              新建文档
            </NTooltip>
            <NTooltip v-if="isAdmin" placement="right" :delay="300">
              <template #trigger>
                <button
                  class="collapsed-rail__action"
                  aria-label="待审核文档"
                  @click="showAuditPanel = true"
                >
                  <NIcon :size="18"><HourglassOutline /></NIcon>
                </button>
              </template>
              待审核
            </NTooltip>
          </div>
        </div>

        <!-- ====== 展开态：原有导航 ====== -->
        <template v-else>
          <div class="nav-header">
            <div class="nav-title">{{ navTitle }}</div>
            <NButton
              quaternary
              circle
              size="small"
              class="nav-collapse-button"
              aria-label="收起文档导航"
              aria-expanded="true"
              aria-controls="knowledge-document-navigation"
              title="收起文档导航"
              @click="toggleNavigation"
            >
              <template #icon>
                <NIcon><ChevronBackOutline /></NIcon>
              </template>
            </NButton>
          </div>

          <div id="knowledge-document-navigation" class="nav-content">
            <NButton
              size="medium"
              type="primary"
              block
              class="create-doc-btn"
              @click="showCreateModal = true"
            >
              <template #icon><NIcon><AddOutline /></NIcon></template>
              新建文档
            </NButton>

            <div v-if="isAdmin" class="sider-menu">
              <div class="sider-menu-item" @click="showAuditPanel = true">
                <NIcon size="16"><HourglassOutline /></NIcon>
                <span>待审核</span>
              </div>
            </div>

            <NSpin :show="loadingNav" :aria-busy="loadingNav">
              <DocTree
                v-if="documentTree.length"
                :tree-data="documentTree"
                :active-id="activeDoc?.id"
                v-model:expanded-keys="expandedKeys"
                @select="selectDoc"
              />
              <EmptyState
                v-else
                :icon="DocumentTextOutline"
                title="暂无文档"
                description="创建第一篇文档，沉淀实验室知识。"
              >
                <template #actions>
                  <NButton size="small" type="primary" @click="showCreateModal = true">新建文档</NButton>
                </template>
              </EmptyState>
            </NSpin>
          </div>
        </template>
      </NCard>
    </div>

    <!-- 右侧主体 -->
    <div class="docs-main">
      <NCard :bordered="false" class="arco-card content-card">
        <!-- 顶部栏 -->
        <div class="content-header">
          <h2 class="doc-title">
            {{ activeDoc?.title || '请选择左侧文档' }}
          </h2>
          <NSpace v-if="activeDoc">
            <template v-if="!isEditMode">
              <NButton
                size="small"
                type="primary"
                ghost
                @click="startEdit"
              >
                <template #icon><NIcon><CreateOutline /></NIcon></template>
                编辑
              </NButton>
              <NPopconfirm v-if="isAdmin" @positive-click="deleteDoc">
                <template #trigger>
                  <NButton size="small" type="error" ghost>
                    <template #icon><NIcon><TrashOutline /></NIcon></template>
                    删除
                  </NButton>
                </template>
                确定删除该文档？此操作不可恢复。
              </NPopconfirm>
            </template>
            <template v-else>
              <NButton size="small" @click="cancelEdit">
                <template #icon><NIcon><CloseOutline /></NIcon></template>
                取消
              </NButton>
              <NButton size="small" type="primary" :loading="saving" @click="saveDoc">
                <template #icon><NIcon><SaveOutline /></NIcon></template>
                {{ isAdmin ? '保存并发布' : '提交审核' }}
              </NButton>
            </template>
          </NSpace>
        </div>

        <!-- 内容区 -->
        <NSpin :show="loadingDoc" :aria-busy="loadingDoc">
          <div v-if="activeDoc" class="content-body">
            <DocEditor
              v-if="isEditMode"
              v-model="draftContent"
              v-model:edit-summary="draftSummary"
              :is-admin="isAdmin"
            />
            <DocReader v-else :doc="activeDoc" @refresh="fetchDoc(activeDoc.id)" />
          </div>
          <EmptyState
            v-else
            :icon="DocumentTextOutline"
            title="选择一篇文档开始阅读"
            description="从左侧目录选择文档，或新建一篇文档开始记录。"
          />
        </NSpin>
      </NCard>
    </div>

    <DocCreateModal
      v-model:show="showCreateModal"
      :existing-categories="existingCategories"
      @created="handleCreated"
    />

    <AuditPendingPanel
      v-model:show="showAuditPanel"
      @audited="handleAudited"
    />
  </main>
</template>

<style scoped>
/* 面板浮于平台灰底之上：内边距露出 --neutral-bg，与 TasksView 等工作台页一致 */
.docs-layout {
  display: flex;
  gap: var(--space-lg);
  flex: 1;
  min-height: 0 !important;
  overflow: hidden;
  padding: var(--space-lg);
  background: var(--neutral-bg);
}

/* ============================================================
   侧边栏容器 — 宽度过渡 250ms ease-in-out
   ============================================================ */
.docs-sider {
  width: 240px;
  flex-shrink: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: width 250ms ease-in-out;
}

.docs-sider--collapsed {
  width: 56px;
}

/* 卡片容器：纵向滚动保留，显式阻断水平滚动条 */
.docs-sider :deep(.arco-card) {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  box-shadow: var(--shadow-card);
}

.docs-sider :deep(.n-card > .n-card-content) {
  padding: 16px 12px;
  transition: padding 250ms ease-in-out;
}

/* ============================================================
   折叠态 · 紧凑工具轨道
   ============================================================ */
.docs-sider--collapsed :deep(.arco-card) {
  display: flex;
  flex-direction: column;
  background: var(--neutral-card);
  border-color: var(--neutral-border);
  box-shadow: var(--shadow-card);
}

.docs-sider--collapsed :deep(.n-card > .n-card-content) {
  display: flex;
  flex: 1;
  min-height: 0;
  padding: 0;
}

.collapsed-rail {
  display: flex;
  flex: 1;
  width: 100%;
  min-height: 0;
  flex-direction: column;
  align-items: center;
  padding: var(--space-lg) 0;
}

.collapsed-rail__header,
.collapsed-rail__actions {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
}

.collapsed-rail__actions {
  flex-direction: column;
  gap: var(--space-md);
  padding-top: var(--space-lg);
}

.collapsed-rail__header {
  margin-bottom: var(--space-xl);
}

.collapse-toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  background: var(--neutral-card);
  color: var(--neutral-text-2);
  cursor: pointer;
  transition: background-color var(--motion-quick) ease-out,
    border-color var(--motion-quick) ease-out,
    color var(--motion-quick) ease-out,
    transform var(--motion-quick) ease-out;
}

.collapse-toggle-btn:hover {
  background: var(--neutral-hover);
  border-color: var(--arco-primary);
  color: var(--arco-primary);
}

.collapse-toggle-btn:active {
  transform: scale(0.96);
}

.collapse-toggle-btn:focus-visible {
  outline: 2px solid var(--arco-primary);
  outline-offset: 2px;
}

.collapsed-rail__context {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: var(--space-xs);
}

.collapsed-rail__icon,
.collapsed-rail__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: var(--radius-sm);
}

.collapsed-rail__icon {
  background: var(--neutral-hover);
  color: var(--arco-primary);
}

.collapsed-rail__action {
  border: 1px solid transparent;
  background: transparent;
  color: var(--neutral-text-2);
  cursor: pointer;
  transition: background-color var(--motion-quick) ease-out,
    border-color var(--motion-quick) ease-out,
    color var(--motion-quick) ease-out,
    transform var(--motion-quick) ease-out;
}

.collapsed-rail__action:hover {
  background: var(--neutral-hover);
  border-color: var(--neutral-border);
  color: var(--arco-primary);
}

.collapsed-rail__action:active {
  transform: scale(0.96);
}

.collapsed-rail__action:focus-visible {
  outline: 2px solid var(--arco-primary);
  outline-offset: 2px;
}

/* ============================================================
   展开态 · 导航头部
   ============================================================ */
.nav-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.nav-title {
  flex: 1;
  min-width: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--neutral-text-1);
  padding: 0;
  text-align: center;
}

.nav-collapse-button {
  flex-shrink: 0;
}

.nav-content {
  min-width: 0;
}

/* 新建文档：回归平台主按钮规范，仅保留布局间距 */
.create-doc-btn {
  margin-bottom: var(--space-sm);
}

/* 侧边栏菜单项（待审核、收藏夹等） */
.sider-menu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.sider-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 14px;
  color: var(--neutral-text-2);
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease;
  user-select: none;
}

.sider-menu-item:hover {
  background-color: var(--neutral-hover);
  color: var(--neutral-text-1);
}

.docs-sider :deep(.n-tree-node) {
  padding: 0 4px;
}

.docs-sider :deep(.n-tree-node-content) {
  padding: 6px 8px;
}

/* ============================================================
   右侧主体
   ============================================================ */
.docs-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.docs-main > :deep(.n-card) {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-card);
}

.docs-main > :deep(.n-card > .n-card-content) {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0 !important;
  overflow: hidden !important;
}

.docs-main > :deep(.n-card .n-spin-container) {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.docs-main > :deep(.n-card .n-spin-content) {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-lg);
  padding: var(--space-lg) var(--space-2xl);
  border-bottom: 1px solid var(--neutral-border);
  flex-shrink: 0;
  background-color: var(--neutral-card);
}

.doc-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin: 0;
  color: var(--neutral-text-1);
  font-size: var(--font-section-size);
  font-weight: var(--font-section-weight);
  letter-spacing: var(--font-section-spacing);
  line-height: var(--font-section-height);
}

.content-body {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--space-2xl);
  width: 100%;
  box-sizing: border-box;
  background-color: var(--neutral-card);
  color: var(--neutral-text-1);
}

.content-body::-webkit-scrollbar {
  width: 8px;
}
.content-body::-webkit-scrollbar-track {
  background: transparent;
}
.content-body::-webkit-scrollbar-thumb {
  background: rgba(29, 33, 41, 0.15);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: padding-box;
}
.content-body::-webkit-scrollbar-thumb:hover {
  background: rgba(29, 33, 41, 0.32);
  background-clip: padding-box;
}

:root[data-theme="dark"] .content-body::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.16);
  background-clip: padding-box;
}
:root[data-theme="dark"] .content-body::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.28);
  background-clip: padding-box;
}

/* ============================================================
   无障碍三件套
   ============================================================ */
@media (prefers-reduced-motion: reduce) {
  .docs-sider,
  .docs-sider :deep(.n-card > .n-card-content),
  .collapse-toggle-btn,
  .collapsed-rail__action {
    transition: none;
  }
  .collapse-toggle-btn:active,
  .collapsed-rail__action:active {
    transform: none;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .docs-sider--collapsed :deep(.arco-card),
  .collapse-toggle-btn,
  .collapsed-rail__icon {
    background: var(--neutral-card);
  }
}

@media (prefers-contrast: more) {
  .collapse-toggle-btn,
  .collapsed-rail__icon,
  .collapsed-rail__action {
    border-color: currentColor;
  }
}

@media (forced-colors: active) {
  .docs-sider--collapsed :deep(.arco-card),
  .collapse-toggle-btn,
  .collapsed-rail__icon,
  .collapsed-rail__action {
    border-color: CanvasText;
    background: Canvas;
    color: CanvasText;
    box-shadow: none;
  }
}

/* ============================================================
   移动端
   ============================================================ */
@media (max-width: 768px) {
  .docs-layout {
    flex-direction: column;
  }
  .docs-sider {
    width: 100%;
  }

  .docs-sider.docs-sider--collapsed {
    width: 100%;
  }
}
</style>
