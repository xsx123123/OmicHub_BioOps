<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NModal,
  NForm,
  NFormItem,
  NSelect,
  NRadioGroup,
  NRadio,
  NInputNumber,
  NInput,
  NSpace,
  NTag,
  useMessage,
} from 'naive-ui'
import type { CookieAccountRow } from '@/composables/useCookieAccounts'

const props = defineProps<{
  show: boolean
  accounts: CookieAccountRow[]
  /** 从表格行触发的预设用户，传入后选择框禁用 */
  presetUserId?: string | null
}>()

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'submit', payload: { userId: string; type: 'add' | 'deduct'; amount: number; remark: string }): void
}>()

const message = useMessage()

const userId = ref<string | null>(null)
const type = ref<'add' | 'deduct'>('add')
const amount = ref<number | null>(null)
const remark = ref('')

const userOptions = computed(() =>
  props.accounts.map(a => ({
    label: `${a.username}（${a.group}）`,
    value: a.user_id,
  })),
)

const isPreset = computed(() => !!props.presetUserId)
const selectedAccount = computed(() => props.accounts.find(a => a.user_id === userId.value) ?? null)

watch(
  () => props.show,
  (v) => {
    if (v) {
      userId.value = props.presetUserId ?? null
      type.value = 'add'
      amount.value = null
      remark.value = ''
    }
  },
)

function handleClose(v: boolean) {
  emit('update:show', v)
}

function handleSubmit() {
  if (!userId.value) {
    message.warning('请选择目标用户')
    return
  }
  if (!amount.value || amount.value <= 0 || !Number.isInteger(amount.value)) {
    message.warning('变更数量只能是正整数')
    return
  }
  emit('submit', {
    userId: userId.value,
    type: type.value,
    amount: amount.value,
    remark: remark.value.trim(),
  })
  emit('update:show', false)
}
</script>

<template>
  <NModal
    :show="show"
    @update:show="handleClose"
    preset="card"
    title="变更饼干余额"
    style="width: 520px; max-width: 92vw"
    :bordered="false"
  >
    <NForm label-placement="top" class="adjust-form">
      <NFormItem label="选择用户" required>
        <NSelect
          v-model:value="userId"
          :options="userOptions"
          :disabled="isPreset"
          :placeholder="isPreset ? '' : '搜索并选择用户'"
          filterable
        />
        <div v-if="selectedAccount" class="preset-hint">
          当前余额
          <NTag size="small" round :type="selectedAccount.balance < 50 ? 'warning' : 'success'">
            {{ selectedAccount.balance }} 🥫
          </NTag>
          · 所属 {{ selectedAccount.group }}
        </div>
      </NFormItem>

      <NFormItem label="操作类型" required>
        <NRadioGroup v-model:value="type">
          <NRadio value="add">增加（充值 / 补贴）</NRadio>
          <NRadio value="deduct">扣除（消耗 / 调账）</NRadio>
        </NRadioGroup>
      </NFormItem>

      <NFormItem label="变更数量" required>
        <NInputNumber
          v-model:value="amount"
          :min="1"
          :step="1"
          :precision="0"
          placeholder="请输入正整数"
          style="width: 100%"
        >
          <template #suffix>🥫</template>
        </NInputNumber>
      </NFormItem>

      <NFormItem label="操作备注">
        <NInput
          v-model:value="remark"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
          placeholder="例如：测试 10x 流程算力补贴 / 人工调账"
          maxlength="120"
          show-count
        />
      </NFormItem>
    </NForm>

    <template #footer>
      <NSpace justify="end">
        <n-button @click="handleClose(false)">取消</n-button>
        <n-button type="primary" @click="handleSubmit">确认变更</n-button>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.adjust-form {
  padding-top: 4px;
}
.preset-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--neutral-text-2, #86909c);
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
