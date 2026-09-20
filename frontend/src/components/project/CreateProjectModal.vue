<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NModal, NForm, NFormItem, NInput, NButton, NSpace, useMessage } from 'naive-ui'
import { projectsApi, type ProjectItem } from '@/api/projects'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  created: [project: ProjectItem]
}>()

const message = useMessage()

const form = reactive({
  name: '',
  customer: '',
  description: '',
})
const submitting = ref(false)

function resetForm() {
  form.name = ''
  form.customer = ''
  form.description = ''
}

function handleClose() {
  emit('update:show', false)
}

async function handleSubmit() {
  const name = form.name.trim()
  if (!name) {
    message.warning('请填写项目名称')
    return
  }
  submitting.value = true
  try {
    const project = await projectsApi.createProject({
      name,
      customer: form.customer.trim() || undefined,
      description: form.description.trim() || undefined,
    })
    message.success(`项目「${project.name}」已创建`)
    emit('created', project)
    handleClose()
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '创建项目失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <NModal
    :show="props.show"
    preset="card"
    title="新建项目"
    style="width: 480px; max-width: 92vw;"
    :bordered="false"
    :segmented="{ content: true }"
    @update:show="(v) => emit('update:show', v)"
    @after-leave="resetForm"
  >
    <NForm label-placement="left" label-width="80">
      <NFormItem label="项目名称" required>
        <NInput
          v-model:value="form.name"
          placeholder="如 TP53 突变分析"
          maxlength="200"
          autofocus
          @keyup.enter="handleSubmit"
        />
      </NFormItem>
      <NFormItem label="客户">
        <NInput v-model:value="form.customer" placeholder="客户名称（可选）" maxlength="200" />
      </NFormItem>
      <NFormItem label="描述">
        <NInput
          v-model:value="form.description"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          placeholder="项目背景或分析目标（可选）"
          maxlength="2000"
        />
      </NFormItem>
    </NForm>

    <template #footer>
      <NSpace justify="end">
        <NButton @click="handleClose">取消</NButton>
        <NButton type="primary" :loading="submitting" @click="handleSubmit">创建项目</NButton>
      </NSpace>
    </template>
  </NModal>
</template>
