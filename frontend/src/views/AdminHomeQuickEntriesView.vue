<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NIcon,
  NInput,
  NSelect,
  NSpace,
  NTooltip,
  useMessage,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import {
  AddOutline,
  ArrowDownOutline,
  ArrowUpOutline,
  RefreshOutline,
  SaveOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import AdminTOTPConfirmModal from '@/components/AdminTOTPConfirmModal.vue'
import PageHeader from '@/components/PageHeader.vue'
import apiClient from '@/api/client'
import type { HomeQuickEntry, QuickEntryColor, SiteSettings } from '@/types'
import {
  createHomeQuickEntry,
  defaultHomeQuickEntries,
  homeQuickEntryIconOptions,
  homeQuickRouteCatalog,
  normalizeHomeQuickEntries,
  quickEntryBgColors,
  quickEntryColorOptions,
  quickEntryIconColors,
  resolveHomeQuickEntryIcon,
} from '@/config/homeQuickEntries'

const message = useMessage()
const entries = ref<HomeQuickEntry[]>(defaultHomeQuickEntries.map((entry) => ({ ...entry })))
const loading = ref(false)
const saving = ref(false)
const totpModalVisible = ref(false)
const totpLoading = ref(false)

const iconOptions: SelectOption[] = homeQuickEntryIconOptions
const colorOptions = quickEntryColorOptions

const previewEntries = computed(() => entries.value.map((entry) => ({
  ...entry,
  iconComponent: resolveHomeQuickEntryIcon(entry.icon),
})))

function routeOptionsFor(currentIndex: number): SelectOption[] {
  const selectedRoutes = new Set(
    entries.value
      .filter((_entry, index) => index !== currentIndex)
      .map((entry) => entry.to),
  )
  return homeQuickRouteCatalog.map((entry) => ({
    label: entry.title,
    value: entry.to,
    disabled: selectedRoutes.has(entry.to),
  }))
}

function renderIconLabel(option: SelectOption) {
  const iconName = String(option.value || '')
  return h('div', { class: 'select-icon-label' }, [
    h(NIcon, { size: 16 }, { default: () => h(resolveHomeQuickEntryIcon(iconName)) }),
    h('span', null, String(option.label || iconName)),
  ])
}

async function fetchSettings() {
  loading.value = true
  try {
    const res = await apiClient.get<SiteSettings>('/platform/config')
    entries.value = normalizeHomeQuickEntries(res.data.home_quick_entries).map((entry) => ({ ...entry }))
  } catch (e: any) {
    message.error(e.response?.data?.detail || '加载首页入口配置失败')
  } finally {
    loading.value = false
  }
}

function onRouteChange(index: number, to: string) {
  entries.value[index] = createHomeQuickEntry(to)
}

function addEntry() {
  if (entries.value.length >= 8) {
    message.warning('最多展示 8 个快捷入口')
    return
  }
  const selected = new Set(entries.value.map((entry) => entry.to))
  const candidate = homeQuickRouteCatalog.find((entry) => !selected.has(entry.to)) || homeQuickRouteCatalog[0]
  entries.value.push(createHomeQuickEntry(candidate.to))
}

function removeEntry(index: number) {
  if (entries.value.length <= 1) {
    message.warning('至少保留 1 个快捷入口')
    return
  }
  entries.value.splice(index, 1)
}

function moveEntry(index: number, direction: -1 | 1) {
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= entries.value.length) return
  const list = [...entries.value]
  const current = list[index]
  list[index] = list[nextIndex]
  list[nextIndex] = current
  entries.value = list
}

function resetDefaults() {
  entries.value = defaultHomeQuickEntries.map((entry) => ({ ...entry }))
}

function setColor(index: number, color: QuickEntryColor) {
  entries.value[index].icon_bg = color
}

function validateEntries(): boolean {
  const seen = new Set<string>()
  for (const entry of entries.value) {
    if (!entry.to || !entry.to.startsWith('/')) {
      message.warning('请选择有效页面')
      return false
    }
    if (!entry.title.trim()) {
      message.warning('入口标题不能为空')
      return false
    }
    if (seen.has(entry.to)) {
      message.warning('同一个页面不能重复添加')
      return false
    }
    seen.add(entry.to)
  }
  return true
}

function openSaveConfirm() {
  if (!validateEntries()) return
  totpModalVisible.value = true
}

async function confirmSave(code: string) {
  totpLoading.value = true
  saving.value = true
  try {
    const payload = entries.value.map((entry) => ({
      ...entry,
      title: entry.title.trim(),
      desc: entry.desc.trim(),
    }))
    const res = await apiClient.patch<SiteSettings>(
      '/admin/platform-config',
      { home_quick_entries: payload },
      { headers: { 'X-TOTP-Code': code } },
    )
    entries.value = normalizeHomeQuickEntries(res.data.home_quick_entries).map((entry) => ({ ...entry }))
    totpModalVisible.value = false
    message.success('首页快捷入口已保存')
  } catch (e: any) {
    message.error(e.response?.data?.detail || '保存失败')
  } finally {
    totpLoading.value = false
    saving.value = false
  }
}

onMounted(fetchSettings)
</script>

<template>
  <div class="page-container">
    <PageHeader title="首页入口管理" subtitle="维护首页展示的快捷入口与排序">
      <template #actions>
      <NButton type="primary" :loading="saving" @click="openSaveConfirm">
        <template #icon>
          <NIcon><SaveOutline /></NIcon>
        </template>
        保存配置
      </NButton>
      </template>
    </PageHeader>

    <NCard title="快捷入口" :bordered="false" class="arco-card manager-card">
      <template #header-extra>
        <NSpace :size="8">
          <NTooltip placement="bottom">
            <template #trigger>
              <NButton circle quaternary :disabled="loading || saving" @click="resetDefaults">
                <NIcon><RefreshOutline /></NIcon>
              </NButton>
            </template>
            恢复默认
          </NTooltip>
          <NTooltip placement="bottom">
            <template #trigger>
              <NButton circle quaternary :disabled="loading || saving || entries.length >= 8" @click="addEntry">
                <NIcon><AddOutline /></NIcon>
              </NButton>
            </template>
            添加入口
          </NTooltip>
        </NSpace>
      </template>

      <div class="entry-list" :class="{ loading }">
        <div v-for="(entry, index) in entries" :key="`${entry.to}-${index}`" class="entry-row">
          <div class="entry-order">{{ index + 1 }}</div>

          <div class="field route-field">
            <label>页面</label>
            <NSelect
              :value="entry.to"
              :options="routeOptionsFor(index)"
              filterable
              @update:value="(value) => onRouteChange(index, String(value))"
            />
            <span class="route-path">{{ entry.to }}</span>
          </div>

          <div class="field title-field">
            <label>标题</label>
            <NInput v-model:value="entry.title" :maxlength="24" show-count />
          </div>

          <div class="field desc-field">
            <label>描述</label>
            <NInput v-model:value="entry.desc" :maxlength="80" show-count />
          </div>

          <div class="field icon-field">
            <label>图标</label>
            <NSelect
              v-model:value="entry.icon"
              :options="iconOptions"
              :render-label="renderIconLabel"
              filterable
            />
          </div>

          <div class="field color-field">
            <label>颜色</label>
            <div class="color-swatches">
              <button
                v-for="color in colorOptions"
                :key="color.value"
                type="button"
                class="color-swatch"
                :class="{ active: entry.icon_bg === color.value }"
                :title="color.label"
                :style="{ background: quickEntryBgColors[color.value], color: quickEntryIconColors[color.value] }"
                @click="setColor(index, color.value)"
              />
            </div>
          </div>

          <div class="row-actions">
            <NTooltip placement="bottom">
              <template #trigger>
                <NButton circle quaternary :disabled="index === 0" @click="moveEntry(index, -1)">
                  <NIcon><ArrowUpOutline /></NIcon>
                </NButton>
              </template>
              上移
            </NTooltip>
            <NTooltip placement="bottom">
              <template #trigger>
                <NButton circle quaternary :disabled="index === entries.length - 1" @click="moveEntry(index, 1)">
                  <NIcon><ArrowDownOutline /></NIcon>
                </NButton>
              </template>
              下移
            </NTooltip>
            <NTooltip placement="bottom">
              <template #trigger>
                <NButton circle quaternary type="error" :disabled="entries.length <= 1" @click="removeEntry(index)">
                  <NIcon><TrashOutline /></NIcon>
                </NButton>
              </template>
              删除
            </NTooltip>
          </div>
        </div>
      </div>

      <div class="preview-panel">
        <div class="preview-title">首页预览</div>
        <div class="preview-grid">
          <div v-for="entry in previewEntries" :key="entry.to" class="preview-entry">
            <div
              class="preview-icon"
              :style="{ background: quickEntryBgColors[entry.icon_bg], color: quickEntryIconColors[entry.icon_bg] }"
            >
              <NIcon :size="22">
                <component :is="entry.iconComponent" />
              </NIcon>
            </div>
            <div class="preview-text">
              <div class="preview-entry-title">{{ entry.title }}</div>
              <div class="preview-entry-desc">{{ entry.desc }}</div>
            </div>
          </div>
        </div>
      </div>
    </NCard>

    <AdminTOTPConfirmModal
      v-model:show="totpModalVisible"
      title="保存首页快捷入口"
      description="修改首页展示入口会影响所有用户，请输入当前 6 位 TOTP 验证码以继续。"
      confirm-text="确认保存"
      :loading="totpLoading"
      @confirm="confirmSave"
    />
  </div>
</template>

<style scoped>
.page-container {
  min-height: 100%;
  padding: 24px;
  background: var(--neutral-bg);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.page-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0;
}

.manager-card {
  padding: 0;
}

.entry-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.entry-list.loading {
  opacity: 0.55;
  pointer-events: none;
}

.entry-row {
  display: grid;
  grid-template-columns: 40px minmax(180px, 1.2fr) minmax(150px, 0.8fr) minmax(180px, 1fr) minmax(150px, 0.8fr) 136px 120px;
  gap: 12px;
  align-items: start;
  padding: 14px;
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  background: var(--neutral-bg);
}

.entry-order {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--arco-primary);
  background: var(--arco-primary-light);
}

.field {
  min-width: 0;
}

.field label {
  display: block;
  font-size: 12px;
  line-height: 18px;
  color: var(--neutral-text-3);
  margin-bottom: 6px;
}

.route-path {
  display: block;
  margin-top: 5px;
  font-size: 12px;
  line-height: 16px;
  color: var(--neutral-text-4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.select-icon-label) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.color-swatches {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 34px;
  align-items: center;
}

.color-swatch {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1px solid var(--neutral-border);
  cursor: pointer;
  position: relative;
}

.color-swatch.active::after {
  content: '';
  position: absolute;
  inset: 7px;
  border-radius: 50%;
  background: currentColor;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 24px;
}

.preview-panel {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--neutral-border);
}

.preview-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin-bottom: 12px;
}

.preview-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.preview-entry {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  background: var(--neutral-bg);
}

.preview-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.preview-text {
  min-width: 0;
}

.preview-entry-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--neutral-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-entry-desc {
  margin-top: 3px;
  font-size: 12px;
  color: var(--neutral-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1280px) {
  .entry-row {
    grid-template-columns: 40px 1fr 1fr;
  }

  .desc-field,
  .icon-field,
  .color-field,
  .row-actions {
    grid-column: span 1;
  }

  .preview-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .page-container {
    padding: 16px;
  }

  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .entry-row,
  .preview-grid {
    grid-template-columns: 1fr;
  }

  .entry-order {
    width: 100%;
  }

  .row-actions {
    padding-top: 0;
  }
}
</style>
