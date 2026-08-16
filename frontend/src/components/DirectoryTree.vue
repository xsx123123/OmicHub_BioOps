<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import { NButton, NDropdown, NEmpty, NIcon, NSpin, NTree, useDialog, useMessage } from 'naive-ui'
import type { TreeOption } from 'naive-ui'
import { FolderOutline, AddOutline, TrashOutline, FolderOpenOutline, EllipsisHorizontalOutline, CreateOutline, LockClosedOutline, OpenOutline } from '@vicons/ionicons5'
import apiClient from '@/api/client'
import type { Directory } from '@/types'

const props = defineProps<{
  modelValue: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'refresh-files'): void
}>()

const message = useMessage()
const dialog = useDialog()
const directories = ref<Directory[]>([])
const loading = ref(false)

/** 不再按硬编码白名单隐藏文件夹，所有目录树节点均可见 */
const visibleDirectories = computed(() => directories.value)

/** 选中目录："" = 根 */
const selected = computed({
  get: () => props.modelValue,
  set: (v: string) => emit('update:modelValue', v),
})

/** 把扁平目录列表组装成树 */
const treeData = computed<TreeOption[]>(() => {
  const root: TreeOption = {
    key: '',
    label: '根目录',
    children: [],
  }
  const nodeMap = new Map<string, TreeOption>()
  nodeMap.set('', root)
  for (const d of visibleDirectories.value) {
    const node: TreeOption = { key: d.path, label: d.name, children: [] }
    nodeMap.set(d.path, node)
  }
  for (const d of visibleDirectories.value) {
    const parent = nodeMap.get(d.parent_path ?? '') ?? root
    parent.children!.push(nodeMap.get(d.path)!)
  }
  return [root]
})

const selectedKeys = computed(() => [selected.value || ''])

/** 节点标签仅展示目录名，避免将文件数量误解为目录名的一部分。 */
function renderLabel({ option }: { option: TreeOption }) {
  return h('span', { class: 'tree-label' }, option.label as string)
}

function handleSelect(keys: string[]) {
  const k = keys[0] ?? ''
  selected.value = k
  emit('refresh-files')
}

async function fetchDirectories() {
  loading.value = true
  try {
    const res = await apiClient.get<Directory[]>('/files/directories')
    directories.value = res.data
  } catch {
    message.error('获取目录列表失败')
  } finally {
    loading.value = false
  }
}

function openCreateModal(parentPath: string) {
  dialog.create({
    title: '新建目录',
    content: () =>
      h('div', { style: 'padding: 8px 0' }, [
        h('p', { style: 'color:#86909c;font-size:13px;margin:0 0 8px' }, `父目录：${parentPath || '根目录'}`),
        h('input', {
          id: '__dir_name_input',
          placeholder: '输入目录名（支持多级如 projA/sub）',
          style: 'width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px;outline:none',
          autofocus: true,
        }),
      ]),
    positiveText: '创建',
    negativeText: '取消',
    onPositiveClick: async () => {
      const input = document.getElementById('__dir_name_input') as HTMLInputElement
      const name = input?.value?.trim() || ''
      if (!name) {
        message.warning('目录名不能为空')
        return false
      }
      const fullPath = parentPath ? `${parentPath}/${name}` : name
      try {
        await apiClient.post('/files/directories', { path: fullPath })
        message.success('目录已创建')
        await fetchDirectories()
      } catch (e: any) {
        message.error(e.response?.data?.detail || '创建失败')
        return false
      }
    },
  })
}

function confirmDelete(dir: Directory) {
  dialog.error({
    title: '删除目录',
    content: `确认删除目录「${dir.path}」？该目录下的文件会移回根目录。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await apiClient.delete('/files/directories', { params: { path: dir.path } })
        message.success('目录已删除')
        // 若删除的是当前打开目录或其祖先目录，回退到根目录
        if (
          selected.value === dir.path ||
          (dir.path && selected.value.startsWith(dir.path + '/'))
        ) {
          selected.value = ''
        }
        // 重新拉取整棵目录树（新数组引用，触发重渲染）
        await fetchDirectories()
        emit('refresh-files')
      } catch (e: any) {
        message.error(e.response?.data?.detail || '删除失败')
      }
    },
  })
}

/** 重命名目录 — TODO: 后端重命名端点就绪后接入 PUT /files/directories/rename */
function renameDirectory(dir: Directory) {
  message.info('重命名功能即将上线')
}

/** 悬浮内联操作的下拉选项 —— 系统目录仅保留新建子目录 */
function inlineMenuOptions(dir: Directory) {
  if (dir.is_system) {
    return [{ label: '新建子目录', key: 'create', icon: () => h(NIcon, null, { default: () => h(AddOutline) }) }]
  }
  return [
    { label: '重命名', key: 'rename', icon: () => h(NIcon, null, { default: () => h(CreateOutline) }) },
    { label: '删除目录', key: 'delete', icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) },
  ]
}

function handleInlineMenu(key: string, dir: Directory) {
  if (key === 'create') openCreateModal(dir.path)
  else if (key === 'rename') renameDirectory(dir)
  else if (key === 'delete') confirmDelete(dir)
}

/** 节点前缀图标：系统目录灰色文件夹、用户目录黄色文件夹 */
function renderPrefix({ option }: { option: TreeOption }) {
  const path = String(option.key ?? '')
  if (!path) return null
  const dir = directories.value.find((d) => d.path === path)
  const color = dir?.is_system ? '#86909c' : '#FFB020'
  return h(NIcon, { size: 15, color, style: 'margin-right:4px' }, { default: () => h(FolderOutline) })
}

/** 节点悬浮时右侧内联显示 + / ⋯ */
function renderSuffix({ option }: { option: TreeOption }) {
  const path = String(option.key ?? '')
  const dir = path ? directories.value.find((d) => d.path === path) : null
  const buttons: ReturnType<typeof h>[] = []

  buttons.push(
    h(
      NButton,
      {
        size: 'tiny',
        quaternary: true,
        title: '新建子目录',
        onClick: (e: MouseEvent) => {
          e.stopPropagation()
          openCreateModal(path)
        },
      },
      { icon: () => h(NIcon, null, { default: () => h(AddOutline) }) },
    ),
  )

  if (dir) {
    buttons.push(
      h(
        NDropdown,
        {
          trigger: 'click',
          options: inlineMenuOptions(dir),
          placement: 'bottom-end',
          onSelect: (key: string) => handleInlineMenu(key, dir),
        },
        {
          default: () =>
            h(
              NButton,
              {
                size: 'tiny',
                quaternary: true,
                title: '更多操作',
                onClick: (e: MouseEvent) => e.stopPropagation(),
              },
              { icon: () => h(NIcon, null, { default: () => h(EllipsisHorizontalOutline) }) },
            ),
        },
      ),
    )
  }

  return h('div', { class: 'inline-actions', onClick: (e: MouseEvent) => e.stopPropagation() }, buttons)
}

/** 右键上下文菜单（n-dropdown 手动定位） */
const contextMenu = reactive({ show: false, x: 0, y: 0, path: '', isSystem: false })

const contextMenuOptions = computed(() => {
  const opts = [
    { label: '打开', key: 'open', icon: () => h(NIcon, null, { default: () => h(OpenOutline) }) },
    { label: '新建子目录', key: 'create', icon: () => h(NIcon, null, { default: () => h(AddOutline) }) },
  ]
  // 系统目录锁定：不允许删除
  if (!contextMenu.isSystem) {
    opts.push({ label: '删除', key: 'delete', icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) })
  }
  return opts
})

function onContextMenuSelect(key: string) {
  contextMenu.show = false
  const path = contextMenu.path
  if (key === 'open') {
    selected.value = path
    emit('refresh-files')
  } else if (key === 'create') {
    openCreateModal(path)
  } else if (key === 'delete') {
    const dir = directories.value.find((d) => d.path === path)
    if (dir) confirmDelete(dir)
  }
}

function handleContextMenu(option: TreeOption, e: MouseEvent) {
  e.preventDefault()
  const path = String(option.key ?? '')
  if (!path) return // 根目录不弹菜单
  const dir = directories.value.find((d) => d.path === path)
  contextMenu.path = path
  contextMenu.isSystem = !!dir?.is_system
  contextMenu.x = e.clientX
  contextMenu.y = e.clientY
  contextMenu.show = true
}

function nodeProps({ option }: { option: TreeOption }) {
  return {
    onContextmenu: (e: MouseEvent) => handleContextMenu(option, e),
  }
}

defineExpose({ refresh: fetchDirectories, openCreateModal })
onMounted(fetchDirectories)
</script>

<template>
  <div class="directory-tree">
    <div class="tree-header">
      <span class="tree-title">
        <NIcon :size="16"><FolderOpenOutline /></NIcon>
        目录
      </span>
      <NButton size="tiny" quaternary title="在根目录下新建" @click="openCreateModal('')">
        <template #icon><NIcon><AddOutline /></NIcon></template>
      </NButton>
    </div>
    <NSpin :show="loading">
      <NTree
        block-line
        expand-on-click
        show-line
        :indent="20"
        :data="treeData"
        :selected-keys="selectedKeys"
        :default-expanded-keys="['']"
        :render-prefix="renderPrefix"
        :render-label="renderLabel"
        :render-suffix="renderSuffix"
        @update:selected-keys="handleSelect"
        :node-props="nodeProps"
      />
    </NSpin>
    <NDropdown
      placement="bottom-start"
      trigger="manual"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :show="contextMenu.show"
      :options="contextMenuOptions"
      @select="onContextMenuSelect"
      @clickoutside="contextMenu.show = false"
    />
  </div>
</template>

<style scoped>
.directory-tree {
  width: 100%;
  height: 100%;
  flex-shrink: 0;
  padding: 12px;
  box-sizing: border-box;
  overflow-y: auto;
  overflow-x: hidden;
}
.tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.tree-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-2, #4e5969);
}
.tree-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
/* 悬浮内联操作：默认隐藏，hover 节点时显现 */
.inline-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s ease;
  margin-left: 4px;
}
.directory-tree :deep(.n-tree-node:hover) .inline-actions,
.directory-tree :deep(.n-tree-node--selected) .inline-actions {
  opacity: 1;
}
/* 节点 hover / 选中高亮 */
.directory-tree :deep(.n-tree-node-content) {
  border-radius: 6px;
  transition: background-color 0.15s ease;
  padding: 2px 4px;
}
.directory-tree :deep(.n-tree-node-content:hover) {
  background-color: var(--neutral-bg, #f2f3f8);
}
.directory-tree :deep(.n-tree-node--selected .n-tree-node-content),
.directory-tree :deep(.n-tree-node--selected > .n-tree-node-content) {
  background-color: rgba(22, 93, 255, 0.12);
}
/* 连线虚线化 */
.directory-tree :deep(.n-tree-node-content__indent::before),
.directory-tree :deep(.n-tree-node-content__indent::after) {
  border-left-style: dashed !important;
  border-left-color: var(--neutral-border, #e5e6eb) !important;
}
</style>
