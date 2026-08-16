<script setup lang="ts">
import type { FlowGroupDefinition, FormValues, Parameter } from '@/types/schema'
import { useConditionEvaluator } from '@/composables/useConditionEvaluator'
import { NCollapse, NCollapseItem, NSwitch, NTooltip } from 'naive-ui'
import { computed } from 'vue'
import FormField from './FormField.vue'

const props = defineProps<{
  parameters: Parameter[]
  modelValue: FormValues
  groups?: FlowGroupDefinition[] | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: FormValues]
  openPathPicker: [paramName: string]
}>()

const { evaluate } = useConditionEvaluator()

const values = computed({
  get: () => props.modelValue || {},
  set: (v) => emit('update:modelValue', v),
})

const isVisible = (p: Parameter): boolean => {
  if (p.ui?.show_when) {
    const sw = p.ui.show_when
    if (sw.field && values.value[String(sw.field)] !== sw.value) return false
  }
  return evaluate(p.condition, values.value)
}

const flatParams = computed(() => {
  return [...props.parameters].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
})

interface GroupedParams {
  group: FlowGroupDefinition
  params: Parameter[]
  moduleSubgroups: Map<string, Parameter[]>
}

function inferGroup(p: Parameter): string {
  if (p.required) return 'basic'
  if (p.type === 'boolean') return 'modules'
  return 'advanced'
}

const groupedSections = computed<GroupedParams[]>(() => {
  if (!props.groups?.length) return []

  const groupDefs = props.groups
  const byGroup = new Map<string, Parameter[]>()

  for (const p of flatParams.value) {
    if (p.type === 'group') continue
    if (p.type === 'section') {
      const gid = p.ui?.group || inferGroup(p)
      const children = p.section_config?.parameters || []
      for (const child of children) {
        if (!byGroup.has(gid)) byGroup.set(gid, [])
        byGroup.get(gid)!.push(child)
      }
      continue
    }
    if (!isVisible(p)) continue
    const gid = p.ui?.group || inferGroup(p)
    if (!byGroup.has(gid)) byGroup.set(gid, [])
    byGroup.get(gid)!.push(p)
  }

  const result: GroupedParams[] = []
  for (const g of groupDefs) {
    const params = (byGroup.get(g.id) || []).sort(
      (a, b) => (a.ui?.order ?? a.order ?? 0) - (b.ui?.order ?? b.order ?? 0),
    )
    if (params.length === 0 && g.id !== 'modules') continue

    const subgroups = new Map<string, Parameter[]>()
    for (const p of params) {
      const sg = p.ui?.subgroup || ''
      if (!subgroups.has(sg)) subgroups.set(sg, [])
      subgroups.get(sg)!.push(p)
    }

    result.push({ group: g, params, moduleSubgroups: subgroups })
  }
  return result
})

const useGroupedLayout = computed(() => groupedSections.value.length > 0)

const ungroupedVisible = computed(() => {
  if (useGroupedLayout.value) return []
  return flatParams.value.filter((p) => isVisible(p))
})

function updateField(name: string, val: unknown) {
  values.value = { ...values.value, [name]: val }
}

function getFieldValue(p: Parameter): unknown {
  const cur = values.value[p.name]
  if (cur !== undefined) return cur
  if (p.default !== undefined) return p.default
  if (p.type === 'boolean') return false
  if (p.type === 'group') return []
  if (p.type === 'section') return {}
  return undefined
}

function getExclusiveDisabledState(p: Parameter): { disabled: boolean; reason: string } {
  if (p.ui?.exclusive) return { disabled: false, reason: '' }
  const exclusiveParam = flatParams.value.find(
    (ep) => ep.ui?.exclusive && getFieldValue(ep) === true,
  )
  if (exclusiveParam && exclusiveParam.name !== p.name) {
    return { disabled: true, reason: `「${exclusiveParam.label}」已开启，其余模块已禁用` }
  }
  return { disabled: false, reason: '' }
}

function handleOpenPathPicker(paramName: string) {
  emit('openPathPicker', paramName)
}
</script>

<template>
  <div v-if="useGroupedLayout" class="grouped-form">
    <template v-for="section in groupedSections" :key="section.group.id">
      <!-- Collapsible group (e.g. advanced params) -->
      <div v-if="section.group.collapsible" class="adv-collapse-wrap">
        <NCollapse
          :default-expanded-names="section.group.collapsed ? [] : ['adv']"
          class="adv-collapse"
          :trigger-areas="['main', 'arrow']"
        >
          <NCollapseItem name="adv">
            <template #header>
              <div class="group-header group-header--collapsible">
                <span class="group-bar" />
                <span class="group-title">{{ section.group.title }}</span>
                <span v-if="section.group.desc" class="group-desc">{{ section.group.desc }}</span>
              </div>
            </template>
            <div class="group-grid group-grid--in-collapse">
              <div
                v-for="p in section.params"
                :key="p.name"
                :class="['field-cell', { 'field-cell--full': (p.ui?.span ?? 1) === 2 }]"
              >
                <label class="field-label">
                  {{ p.label }}
                  <span v-if="p.required" class="req-star">*</span>
                </label>
                <FormField
                  :parameter="p"
                  :model-value="getFieldValue(p)"
                  @update:model-value="(v) => updateField(p.name, v)"
                  @open-path-picker="handleOpenPathPicker"
                />
                <span v-if="p.help_text" class="field-help">{{ p.help_text }}</span>
              </div>
            </div>
          </NCollapseItem>
        </NCollapse>
      </div>

      <!-- Normal group -->
      <section v-else class="form-group">
        <div class="group-header">
          <span class="group-bar" />
          <span class="group-title">{{ section.group.title }}</span>
          <span v-if="section.group.desc" class="group-desc">{{ section.group.desc }}</span>
        </div>

        <!-- Modules group: card grid -->
        <div v-if="section.group.id === 'modules'" class="modules-area">
          <template v-for="[sgName, sgParams] in section.moduleSubgroups" :key="sgName">
            <div v-if="sgName" class="subgroup-title">{{ sgName }}</div>
            <div class="module-cards">
              <NTooltip
                v-for="p in sgParams"
                :key="p.name"
                :disabled="!getExclusiveDisabledState(p).disabled"
                trigger="hover"
                placement="top"
              >
                <template #trigger>
                  <div
                    :class="[
                      'module-card',
                      { 'module-card--on': getFieldValue(p) === true },
                      { 'module-card--disabled': getExclusiveDisabledState(p).disabled },
                    ]"
                  >
                    <div class="module-card-top">
                      <NSwitch
                        :value="getFieldValue(p) as boolean"
                        :disabled="getExclusiveDisabledState(p).disabled"
                        size="small"
                        @update:value="(v: boolean) => updateField(p.name, v)"
                      />
                      <span class="module-card-name">{{ p.label }}</span>
                    </div>
                    <span v-if="p.help_text" class="module-card-help">{{ p.help_text }}</span>
                  </div>
                </template>
                {{ getExclusiveDisabledState(p).reason }}
              </NTooltip>
            </div>
          </template>
        </div>

        <!-- Normal group: dual-column grid -->
        <div v-else class="group-grid">
          <div
            v-for="p in section.params"
            :key="p.name"
            :class="['field-cell', { 'field-cell--full': (p.ui?.span ?? 1) === 2 }]"
          >
            <label class="field-label">
              {{ p.label }}
              <span v-if="p.required" class="req-star">*</span>
            </label>
            <FormField
              :parameter="p"
              :model-value="getFieldValue(p)"
              @update:model-value="(v) => updateField(p.name, v)"
              @open-path-picker="handleOpenPathPicker"
            />
            <span v-if="p.help_text" class="field-help">{{ p.help_text }}</span>
          </div>
        </div>
      </section>
    </template>
  </div>

  <!-- Flat fallback layout (no groups defined) -->
  <div v-else class="flat-form">
    <template v-for="p in ungroupedVisible" :key="p.name">
      <div class="flat-field">
        <label class="field-label">
          {{ p.label }}
          <span v-if="p.required" class="req-star">*</span>
        </label>
        <template v-if="p.type !== 'group' && p.type !== 'section'">
          <FormField
            :parameter="p"
            :model-value="getFieldValue(p)"
            @update:model-value="(v) => updateField(p.name, v)"
            @open-path-picker="handleOpenPathPicker"
          />
          <span v-if="p.help_text" class="field-help">{{ p.help_text }}</span>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.grouped-form {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.group-header--collapsible {
  margin-bottom: 0;
  width: 100%;
}

.group-bar {
  width: 4px;
  height: 18px;
  border-radius: 2px;
  background: var(--brand-primary);
  flex-shrink: 0;
}

.group-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

.group-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: 2px;
}

.group-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 20px;
}

.group-grid--in-collapse {
  padding-top: 4px;
}

@media (max-width: 768px) {
  .group-grid {
    grid-template-columns: 1fr;
  }
}

.field-cell--full {
  grid-column: 1 / -1;
}

.field-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.4;
}

.req-star {
  color: #e5484d;
  margin-left: 2px;
}

.field-help {
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.4;
}

.subgroup-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
  margin-top: 14px;
  padding-left: 2px;
}

.subgroup-title:first-child {
  margin-top: 0;
}

.modules-area {
  display: flex;
  flex-direction: column;
}

.module-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}

.module-card {
  padding: 12px 16px;
  border: 1px solid var(--stardust-border-soft, rgba(46, 91, 255, 0.08));
  border-radius: 8px;
  background: var(--bg-card);
  transition: border-color 0.2s, background 0.2s;
  cursor: default;
}

.module-card:hover:not(.module-card--disabled) {
  border-color: rgba(76, 111, 255, 0.25);
}

.module-card--on {
  border-color: var(--brand-primary);
  background: rgba(76, 111, 255, 0.04);
}

.module-card--disabled {
  opacity: 0.45;
}

.module-card-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.module-card-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.module-card-help {
  display: block;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 6px;
  line-height: 1.4;
}

/* Advanced collapse: gray bg bar + tight layout */
.adv-collapse-wrap {
  border-radius: 8px;
  overflow: hidden;
}

.adv-collapse :deep(.n-collapse-item) {
  margin: 0;
  border: none;
}

.adv-collapse :deep(.n-collapse-item__header) {
  padding: 10px 16px !important;
  background: var(--bg-page, #f5f6fa);
  border-radius: 8px;
  height: auto !important;
  font-size: inherit !important;
}

.adv-collapse :deep(.n-collapse-item__header-main) {
  flex: 1;
}

.adv-collapse :deep(.n-collapse-item__content) {
  transition: all 200ms ease;
}

.adv-collapse :deep(.n-collapse-item__content-inner) {
  padding: 16px 0 0 !important;
}

.adv-collapse :deep(.n-collapse-item-arrow) {
  font-size: 16px;
  color: var(--text-tertiary);
}

.flat-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.flat-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
