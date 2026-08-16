<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NModal,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NButton,
  NSpace,
  useMessage,
} from 'naive-ui'
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import type { DocCreateRequest } from '@/types/knowledge'

const props = defineProps<{
  show: boolean
  existingCategories: string[]
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  created: [docId: string]
}>()

const message = useMessage()
const authStore = useAuthStore()
const themeStore = useThemeStore()

const mdTheme = computed<'light' | 'dark'>(() => (themeStore.isDark ? 'dark' : 'light'))
const isAdmin = computed(() => authStore.isAdmin)

const form = ref<DocCreateRequest>({
  docId: '',
  title: '',
  category: '',
  content: '',
  editSummary: '',
})
const submitting = ref(false)
const categorySelect = ref('')

const categoryOptions = computed(() =>
  props.existingCategories.map((cat) => ({ label: cat, value: cat })),
)

const finalCategory = computed(() => form.value.category.trim() || categorySelect.value)

function resetForm() {
  form.value = {
    docId: '',
    title: '',
    category: '',
    content: '',
    editSummary: '',
  }
  categorySelect.value = ''
}

function handleClose() {
  emit('update:show', false)
  resetForm()
}

function validateDocId(id: string): boolean {
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id)
}

async function handleSubmit() {
  const docId = form.value.docId.trim()
  const title = form.value.title.trim()
  const category = finalCategory.value.trim()
  const content = form.value.content.trim()

  if (!docId || !validateDocId(docId)) {
    message.error('文档ID只能包含小写字母、数字和连字符')
    return
  }
  if (!title) {
    message.error('标题不能为空')
    return
  }
  if (!category) {
    message.error('分类不能为空')
    return
  }
  if (!content) {
    message.error('正文不能为空')
    return
  }

  submitting.value = true
  try {
    const payload: DocCreateRequest = {
      docId,
      title,
      category,
      content,
      editSummary: form.value.editSummary || (isAdmin.value ? '新建文档' : '提交新建文档'),
    }
    const res = await apiClient.post<{ docId: string }>('/docs/knowledge', payload)
    message.success(isAdmin.value ? '文档已发布' : '文档已提交，等待管理员审核')
    emit('created', res.data.docId)
    handleClose()
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

async function handleUploadImg(files: File[], callback: (urls: string[]) => void) {
  const urls: string[] = new Array(files.length)
  try {
    await Promise.all(
      files.map(async (file, index) => {
        const formData = new FormData()
        formData.append('file', file)
        const res = await apiClient.post<{ url: string }>('/docs/knowledge/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        urls[index] = res.data.url
      }),
    )
    callback(urls)
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '图片上传失败')
  }
}
</script>

<template>
  <NModal
    :show="props.show"
    preset="card"
    title="新建文档"
    style="width: 900px; max-width: 95vw;"
    :bordered="false"
    :segmented="{ content: true }"
    @update:show="(v) => emit('update:show', v)"
    @after-leave="resetForm"
  >
    <NForm label-placement="left" label-width="80">
      <NFormItem label="文档ID" required>
        <NInput v-model:value="form.docId" placeholder="如 rna-seq-guide" />
      </NFormItem>
      <NFormItem label="标题" required>
        <NInput v-model:value="form.title" placeholder="文档标题" />
      </NFormItem>
      <NFormItem label="分类" required>
        <NSpace align="center" style="width: 100%">
          <NSelect
            v-model:value="categorySelect"
            :options="categoryOptions"
            placeholder="选择已有分类"
            clearable
            style="width: 200px"
          />
          <span>或</span>
          <NInput
            v-model:value="form.category"
            placeholder="输入新分类"
            style="flex: 1"
          />
        </NSpace>
      </NFormItem>
      <NFormItem label="编辑摘要">
        <NInput v-model:value="form.editSummary" placeholder="简述本次变更" />
      </NFormItem>
      <NFormItem label="正文" required>
        <MdEditor
          v-model="form.content"
          :preview="false"
          :theme="mdTheme"
          :toolbars-exclude="['github', 'save', 'pageFullscreen', 'catalog']"
          :style="{ height: '400px' }"
          placeholder="在此编写 Markdown 文档…"
          @on-upload-img="handleUploadImg"
        />
      </NFormItem>
    </NForm>

    <template #footer>
      <NSpace justify="end">
        <NButton @click="handleClose">取消</NButton>
        <NButton type="primary" :loading="submitting" @click="handleSubmit">
          {{ isAdmin ? '保存并发布' : '提交审核' }}
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
:deep(.md-editor) {
  border-radius: 8px;
  border: 1px solid var(--neutral-border);
}
</style>
