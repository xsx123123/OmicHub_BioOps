<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NModal, NButton, NCheckbox, NTag, NSpin, useMessage } from 'naive-ui'
import apiClient from '@/api/client'
import { useModulesStore } from '@/stores/modules'
import type { ModuleRegistryItem } from '@/types'

interface TargetUser {
  id: string
  email: string
  disabled_modules?: string[]
}

const props = defineProps<{ show: boolean; user: TargetUser | null }>()
const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const modulesStore = useModulesStore()
const saving = ref(false)
// 勾选 = 开通；存「已开通」模块 key 列表
const enabledKeys = ref<string[]>([])

// 只渲染可锁模块（禁止写死模块名）；AI 模块置顶
const lockableModules = computed<ModuleRegistryItem[]>(() =>
  [...modulesStore.registry.filter((m) => m.lockable)].sort(
    (a, b) => Number(b.ai) - Number(a.ai),
  ),
)

// 打开时拉注册表并按用户 disabled_modules 初始化勾选状态（不在列表中 = 开通 = 勾选）
watch(
  () => props.show,
  async (v) => {
    if (!v) return
    await modulesStore.ensureLoaded()
    const disabled = props.user?.disabled_modules ?? []
    enabledKeys.value = modulesStore.registry
      .filter((m) => m.lockable && !disabled.includes(m.key))
      .map((m) => m.key)
  },
)

function close() {
  emit('update:show', false)
}

async function handleSave() {
  if (!props.user) return
  saving.value = true
  try {
    // 未勾选 = 禁用
    const disabled = lockableModules.value
      .filter((m) => !enabledKeys.value.includes(m.key))
      .map((m) => m.key)
    await apiClient.put(`/admin/users/${props.user.id}/modules`, {
      disabled_modules: disabled,
    })
    message.success('模块权限已更新')
    emit('success')
    close()
  } catch (error: any) {
    // 失败不关闭弹窗，保留当前勾选状态供调整后重试
    const detail = error?.response?.data?.detail
    if (error?.response?.status === 401) {
      message.error(detail || '当前登录态已失效，请重新登录后再保存')
    } else {
      message.error(detail || '保存失败')
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <NModal
    :show="props.show"
    :auto-focus="false"
    :mask-closable="true"
    transform-origin="center"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div class="module-modal">
      <h3 class="module-title">模块权限 - {{ props.user?.email || '' }}</h3>
      <p class="module-desc">勾选 = 开通该模块，取消勾选 = 禁用；禁用后用户侧显示锁定，接口同步拦截。</p>

      <NSpin :show="!modulesStore.loaded">
        <div class="module-list">
          <div v-for="mod in lockableModules" :key="mod.key" class="module-row">
            <NCheckbox
              :checked="enabledKeys.includes(mod.key)"
              @update:checked="(checked: boolean) => {
                enabledKeys = checked
                  ? [...enabledKeys, mod.key]
                  : enabledKeys.filter((k) => k !== mod.key)
              }"
            >
              <span class="module-name">{{ mod.name }}</span>
            </NCheckbox>
            <NTag v-if="mod.ai" size="small" type="warning" round>AI</NTag>
          </div>
          <p v-if="modulesStore.loaded && lockableModules.length === 0" class="module-empty">
            暂无可配置模块
          </p>
        </div>
      </NSpin>

      <div class="module-footer">
        <span class="module-count">已开通 {{ enabledKeys.length }} / 共 {{ lockableModules.length }} 个模块</span>
        <div class="module-actions">
          <NButton @click="close">取消</NButton>
          <NButton type="primary" :loading="saving" @click="handleSave">保存</NButton>
        </div>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.module-modal {
  width: 480px;
  max-width: calc(100vw - 32px);
  background: var(--neutral-card, #fff);
  border-radius: 12px;
  padding: 24px;
  box-sizing: border-box;
}
.module-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  word-break: break-all;
}
.module-desc {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
}
.module-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
}
.module-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
}
.module-row:hover {
  background: var(--neutral-hover, #f2f3f5);
}
.module-name {
  font-size: 14px;
  color: var(--neutral-text-1, #1d2129);
}
.module-empty {
  margin: 12px 0;
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
  text-align: center;
}
.module-footer {
  margin-top: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.module-count {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}
.module-actions {
  display: flex;
  gap: 8px;
}
</style>
