<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import {
  NButton, NDrawer, NDrawerContent, NEmpty, NForm, NFormItem, NIcon, NInput, NModal,
  NPopconfirm, NSpin, NSwitch, NTag, useMessage,
} from 'naive-ui'
import { AddOutline, BookOutline, DocumentTextOutline, TrashOutline } from '@vicons/ionicons5'
import { knowledgeBaseApi, type KnowledgeBase, type KnowledgeBaseDoc } from '@/api/admin/knowledgeBase'

const message = useMessage()
const bases = ref<KnowledgeBase[]>([])
const selectedId = ref('')
const loading = ref(false)
const saving = ref(false)
const form = reactive({ name: '', description: '', show_in_lab: true, ai_searchable: true, is_enabled: true })

const showCreate = ref(false)
const creating = ref(false)
const createForm = reactive({ id: '', name: '', description: '', show_in_lab: true, ai_searchable: true })

const showDocs = ref(false)
const docsLoading = ref(false)
const docs = ref<KnowledgeBaseDoc[]>([])

function fillForm(kb: KnowledgeBase | null) {
  if (!kb) return
  form.name = kb.name
  form.description = kb.description
  form.show_in_lab = kb.show_in_lab
  form.ai_searchable = kb.ai_searchable
  form.is_enabled = kb.is_enabled
}

const selected = () => bases.value.find((kb) => kb.id === selectedId.value) || null

async function load(keepSelection = true) {
  loading.value = true
  try {
    bases.value = await knowledgeBaseApi.list()
    if (!keepSelection || !bases.value.some((kb) => kb.id === selectedId.value)) {
      selectedId.value = bases.value[0]?.id || ''
    }
    fillForm(selected())
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '加载知识库列表失败')
  } finally {
    loading.value = false
  }
}

function select(kb: KnowledgeBase) {
  selectedId.value = kb.id
  fillForm(kb)
}

async function save() {
  const kb = selected()
  if (!kb) return
  saving.value = true
  try {
    const updated = await knowledgeBaseApi.update(kb.id, { ...form })
    bases.value = bases.value.map((item) => (item.id === updated.id ? updated : item))
    message.success('知识库配置已保存')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function create() {
  if (!createForm.id.trim() || !createForm.name.trim()) {
    message.warning('请填写知识库标识与名称')
    return
  }
  creating.value = true
  try {
    const created = await knowledgeBaseApi.create({ ...createForm })
    message.success(`知识库「${created.name}」已创建`)
    showCreate.value = false
    createForm.id = createForm.name = createForm.description = ''
    await load(false)
    selectedId.value = created.id
    fillForm(created)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

async function remove() {
  const kb = selected()
  if (!kb) return
  try {
    await knowledgeBaseApi.remove(kb.id)
    message.success(`知识库「${kb.name}」已删除`)
    await load(false)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '删除失败')
  }
}

async function openDocs() {
  const kb = selected()
  if (!kb) return
  showDocs.value = true
  docsLoading.value = true
  try {
    docs.value = await knowledgeBaseApi.docs(kb.id)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '加载文档列表失败')
  } finally {
    docsLoading.value = false
  }
}

function statusTag(status: number) {
  if (status === 1) return { label: '已发布', type: 'success' as const }
  if (status === 2) return { label: '待审核', type: 'warning' as const }
  return { label: '已拒绝', type: 'error' as const }
}

onMounted(load)
</script>

<template>
  <div class="kb-tab-page" :aria-busy="loading">
    <div class="tab-header">
      <span class="tab-hint">管理知识库的可见性与 AI 检索范围，新建或删除知识库前先选择左侧条目。</span>
    </div>

    <div class="kb-layout">
      <aside class="kb-list-card" aria-label="知识库列表">
        <div class="kb-list-head">
          <span class="kb-list-title">知识库</span>
          <span class="kb-list-count">{{ bases.length }}</span>
        </div>
        <div class="kb-list-body" role="listbox" aria-label="知识库列表">
          <div v-if="loading && bases.length === 0" class="kb-list-loading">
            <NSpin size="small" />
          </div>
          <button
            v-for="kb in bases" :key="kb.id" type="button" class="kb-item"
            :class="{ active: kb.id === selectedId }" role="option"
            :aria-selected="kb.id === selectedId" @click="select(kb)"
          >
            <NIcon class="kb-item-icon" :component="BookOutline" />
            <span class="kb-name">{{ kb.name }}</span>
            <NTag size="tiny" :bordered="false">{{ kb.doc_count }} 篇</NTag>
            <NTag v-if="!kb.is_enabled" size="tiny" type="error" :bordered="false">停用</NTag>
          </button>
          <NEmpty v-if="!loading && bases.length === 0" class="kb-list-empty" description="暂无知识库" />
        </div>
        <div class="kb-list-foot">
          <NButton dashed block size="small" @click="showCreate = true">
            <template #icon><NIcon :component="AddOutline" /></template>
            新建知识库
          </NButton>
        </div>
      </aside>

      <section v-if="selected()" class="kb-detail-card" aria-label="知识库配置">
        <header class="kb-detail-head">
          <div class="kb-avatar" aria-hidden="true">
            <NIcon :component="BookOutline" />
          </div>
          <div class="kb-head-text">
            <div class="kb-head-title">
              <h3>{{ selected()!.name }}</h3>
              <code class="kb-code">{{ selected()!.id }}</code>
              <NTag v-if="!selected()!.is_enabled" size="tiny" type="error" :bordered="false">已停用</NTag>
            </div>
            <p>控制该知识库在「实验室知识库」页的可见性与 AI 检索范围。</p>
          </div>
          <NButton secondary @click="openDocs">
            <template #icon><NIcon :component="DocumentTextOutline" /></template>
            查看文档（{{ selected()!.doc_count }}）
          </NButton>
        </header>

        <div class="kb-detail-body">
          <div class="kb-col-main">
            <h4 class="kb-section-title">基本信息</h4>
            <NForm label-placement="top" size="medium">
              <NFormItem label="名称">
                <NInput v-model:value="form.name" placeholder="知识库名称" />
              </NFormItem>
              <NFormItem label="描述">
                <NInput
                  v-model:value="form.description" type="textarea" :rows="3"
                  placeholder="简要说明该知识库的用途与收录范围"
                />
              </NFormItem>
            </NForm>
          </div>

          <div class="kb-col-side">
            <h4 class="kb-section-title">可见性与检索</h4>
            <div class="kb-settings">
              <div class="kb-setting">
                <div class="kb-setting-text">
                  <span class="kb-setting-label">在「实验室知识库」页面展示</span>
                  <span class="kb-setting-desc">关闭后仅用于 AI 检索，不对用户展示</span>
                </div>
                <NSwitch v-model:value="form.show_in_lab" />
              </div>
              <div class="kb-setting">
                <div class="kb-setting-text">
                  <span class="kb-setting-label">允许 AI 助手检索</span>
                  <span class="kb-setting-desc">开启后可被 knowledge_search 工具检索</span>
                </div>
                <NSwitch v-model:value="form.ai_searchable" />
              </div>
              <div class="kb-setting">
                <div class="kb-setting-text">
                  <span class="kb-setting-label">启用该知识库</span>
                  <span class="kb-setting-desc">停用后该库不可展示也不可检索</span>
                </div>
                <NSwitch v-model:value="form.is_enabled" />
              </div>
            </div>
          </div>
        </div>

        <footer class="kb-detail-foot">
          <NPopconfirm
            :disabled="selected()!.doc_count > 0"
            @positive-click="remove"
          >
            <template #trigger>
              <NButton
                tertiary type="error" :disabled="selected()!.doc_count > 0"
              >
                <template #icon><NIcon :component="TrashOutline" /></template>
                删除
              </NButton>
            </template>
            确认删除知识库「{{ selected()!.name }}」？该操作不可恢复。
          </NPopconfirm>
          <div class="kb-foot-right">
            <span v-if="selected()!.doc_count > 0" class="kb-foot-hint">知识库内仍有文档时不可删除</span>
            <NButton type="primary" :loading="saving" @click="save">保存配置</NButton>
          </div>
        </footer>
      </section>
      <section v-else class="kb-detail-card kb-detail-empty">
        <NEmpty description="选择左侧知识库进行配置" />
      </section>
    </div>

    <NModal v-model:show="showCreate" preset="card" title="新建知识库" style="width: 480px">
      <div class="field"><label>标识（小写字母/数字/连字符）</label><NInput v-model:value="createForm.id" placeholder="如 scseq、proteomics" /></div>
      <div class="field"><label>名称</label><NInput v-model:value="createForm.name" placeholder="如 单细胞知识库" /></div>
      <div class="field"><label>描述</label><NInput v-model:value="createForm.description" type="textarea" :rows="2" /></div>
      <div class="field-row"><label>在「实验室知识库」页面展示</label><NSwitch v-model:value="createForm.show_in_lab" /></div>
      <div class="field-row"><label>允许 AI 助手检索</label><NSwitch v-model:value="createForm.ai_searchable" /></div>
      <div class="panel-actions"><NButton type="primary" :loading="creating" @click="create">创建</NButton></div>
    </NModal>

    <NDrawer v-model:show="showDocs" :width="520">
      <NDrawerContent :title="`文档列表 - ${selected()?.name || ''}`" closable>
        <NEmpty v-if="!docsLoading && docs.length === 0" description="该知识库暂无文档" />
        <div v-for="doc in docs" :key="doc.doc_id" class="doc-item">
          <div class="doc-title">{{ doc.title }}</div>
          <div class="doc-meta">
            <span>{{ doc.category }}</span>
            <NTag size="tiny" :type="statusTag(doc.status).type" :bordered="false">{{ statusTag(doc.status).label }}</NTag>
            <code>{{ doc.doc_id }}</code>
          </div>
        </div>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.tab-header { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:14px; }
.tab-hint { font-size:12px; color:var(--neutral-text-3); }

/* 双卡片布局：列表 + 详情，共享同一内容边界 */
.kb-layout { display:grid; grid-template-columns:264px minmax(0, 1fr); gap:20px; align-items:start; }

/* 左侧知识库列表卡片 */
.kb-list-card { display:flex; flex-direction:column; min-height:460px; background:var(--neutral-card); border:1px solid var(--neutral-border); border-radius:12px; overflow:hidden; }
.kb-list-head { display:flex; align-items:center; justify-content:space-between; padding:14px 16px; border-bottom:1px solid var(--neutral-border); }
.kb-list-title { font-size:13px; font-weight:600; color:var(--neutral-text-1); }
.kb-list-count { font-size:12px; line-height:18px; color:var(--neutral-text-3); background:var(--neutral-hover); border-radius:9999px; padding:0 8px; }
.kb-list-body { flex:1; display:flex; flex-direction:column; gap:2px; padding:8px; overflow-y:auto; }
.kb-list-loading { display:flex; align-items:center; justify-content:center; min-height:120px; }
.kb-list-empty { margin:auto 0; padding:32px 0; }
.kb-item { position:relative; width:100%; display:flex; align-items:center; gap:8px; padding:8px 10px 8px 12px; border:0; border-radius:8px; background:transparent; color:var(--neutral-text-2); font-size:13px; text-align:left; cursor:pointer; transition:background-color 140ms ease-out, color 140ms ease-out; }
.kb-item:hover { background:var(--neutral-hover); color:var(--neutral-text-1); }
.kb-item:focus-visible { outline:2px solid var(--arco-primary); outline-offset:2px; }
.kb-item.active { background:var(--arco-primary-light); color:var(--arco-primary); font-weight:500; }
.kb-item.active::before { content:''; position:absolute; left:2px; top:50%; transform:translateY(-50%); width:3px; height:18px; border-radius:9999px; background:var(--arco-primary); }
.kb-item-icon { flex-shrink:0; font-size:16px; }
.kb-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.kb-list-foot { padding:12px; border-top:1px solid var(--neutral-border); }

/* 右侧详情卡片 */
.kb-detail-card { display:flex; flex-direction:column; min-height:460px; background:var(--neutral-card); border:1px solid var(--neutral-border); border-radius:12px; }
.kb-detail-head { display:flex; align-items:center; gap:14px; padding:20px 24px; border-bottom:1px solid var(--neutral-border); }
.kb-avatar { flex-shrink:0; width:40px; height:40px; display:flex; align-items:center; justify-content:center; border-radius:10px; background:var(--arco-primary-light); color:var(--arco-primary); font-size:20px; }
.kb-head-text { flex:1; min-width:0; }
.kb-head-title { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.kb-head-title h3 { margin:0; font-size:16px; line-height:24px; font-weight:600; color:var(--neutral-text-1); }
.kb-code { font-size:12px; font-weight:400; color:var(--neutral-text-3); background:var(--neutral-hover); border-radius:4px; padding:1px 6px; }
.kb-head-text p { margin:4px 0 0; font-size:12px; line-height:18px; color:var(--neutral-text-3); }

.kb-detail-body { flex:1; display:grid; grid-template-columns:minmax(0, 1fr) 320px; gap:24px; padding:24px; align-items:start; }
.kb-section-title { margin:0 0 16px; font-size:14px; line-height:22px; font-weight:600; color:var(--neutral-text-1); }

/* 设置分组：低强调填充面板，与主表单区分层级 */
.kb-settings { background:var(--neutral-bg); border:1px solid var(--neutral-border); border-radius:12px; padding:4px 16px; }
.kb-setting { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 0; }
.kb-setting + .kb-setting { border-top:1px solid var(--neutral-border); }
.kb-setting-text { display:flex; flex-direction:column; gap:2px; min-width:0; }
.kb-setting-label { font-size:13px; line-height:20px; font-weight:500; color:var(--neutral-text-1); }
.kb-setting-desc { font-size:12px; line-height:18px; color:var(--neutral-text-3); }

.kb-detail-foot { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 24px; border-top:1px solid var(--neutral-border); }
.kb-foot-right { display:flex; align-items:center; gap:12px; }
.kb-foot-hint { font-size:12px; color:var(--neutral-text-3); }
.kb-detail-empty { align-items:center; justify-content:center; }

/* 新建弹窗字段 */
.field,.field-row { margin:16px 0; }
.field label,.field-row label { display:block; margin-bottom:7px; font-size:13px; font-weight:500; color:var(--neutral-text-1); }
.field-row { display:flex; align-items:center; justify-content:space-between; }
.field-row label { margin:0; }
.panel-actions { display:flex; justify-content:flex-end; gap:12px; margin-top:24px; }

/* 文档抽屉 */
.doc-item { padding:10px 4px; border-bottom:1px solid var(--neutral-border); }
.doc-title { font-size:13px; color:var(--neutral-text-1); }
.doc-meta { display:flex; gap:8px; align-items:center; margin-top:4px; font-size:12px; color:var(--neutral-text-3); }

@media (max-width: 1024px) {
  .kb-detail-body { grid-template-columns:minmax(0, 1fr); }
}
@media (max-width: 860px) {
  .kb-layout { grid-template-columns:minmax(0, 1fr); }
  .kb-list-card { min-height:0; }
  .kb-list-body { flex-direction:row; flex-wrap:wrap; }
  .kb-item { width:auto; }
  .kb-detail-head { flex-wrap:wrap; }
  .kb-detail-foot { flex-wrap:wrap; }
}
</style>
