<script setup lang="ts">
/**
 * 全局充值/扣减弹窗 — 「用户管理」与「饼干账户管理」共用。
 * 预设 userId 时锁定用户（行内快捷充值）；否则提供用户选择（顶部主动分配）。
 * 统一调 POST /admin/cookies/accounts/{userId}/adjust，按带符号金额记账。
 *
 * 候选用户列表直接拉取 /admin/users（所有注册用户），避免只有已开通饼干钱包的用户
 * 才出现在下拉框里，导致「已有用户选不到」。
 */
import { computed, ref, watch } from 'vue'
import {
  NModal, NForm, NFormItem, NSelect, NRadioGroup, NRadio, NInputNumber,
  NInput, NSpace, NTag, useMessage,
} from 'naive-ui'
import { useAdminCookieStore } from '@/stores/adminCookie'
import apiClient from '@/api/client'
import { displayName } from '@/utils/displayName'

interface RechargeUserOption {
  id: string
  username: string
  nickname?: string | null
  email: string
  role: string
  status: string
  lab_group: string | null
  cookie_balance: number
  cookie_status: string | null
}

const props = defineProps<{
  show: boolean
  /** 行内触发时预设的用户 ID（锁定，不可改） */
  userId?: string | null
}>()

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'success'): void
}>()

const message = useMessage()
const store = useAdminCookieStore()

const userId = ref<string | null>(null)
const type = ref<'add' | 'deduct'>('add')
const amount = ref<number | null>(null)
const remark = ref('')
const submitting = ref(false)
const userLoading = ref(false)
const users = ref<RechargeUserOption[]>([])

const isPreset = computed(() => !!props.userId)

// 选项来源：所有注册用户（含未开通饼干钱包的用户），避免「已有用户」选不到
const userOptions = computed(() =>
  users.value.map((u) => ({
    label: `${displayName(u)}（${u.email}）`,
    value: u.id,
  })),
)
const selectedUser = computed(() => users.value.find((u) => u.id === userId.value) ?? null)

watch(
  () => props.show,
  async (v) => {
    if (v) {
      userId.value = props.userId ?? null
      type.value = 'add'
      amount.value = null
      remark.value = ''
      // 打开时拉取全部用户，不依赖饼干账户列表
      userLoading.value = true
      try {
        const res = await apiClient.get<RechargeUserOption[]>('/admin/users', {
          params: { limit: 1000 },
        })
        users.value = res.data
      } catch (e: any) {
        message.error(e?.response?.data?.detail || '用户列表加载失败')
        users.value = []
      } finally {
        userLoading.value = false
      }
    }
  },
)

async function handleSubmit() {
  if (!userId.value) {
    message.warning('请选择目标用户')
    return
  }
  if (!amount.value || amount.value <= 0 || !Number.isInteger(amount.value)) {
    message.warning('变更数量只能是正整数')
    return
  }
  submitting.value = true
  try {
    const signed = type.value === 'add' ? amount.value : -amount.value
    await store.adjust(userId.value, signed, remark.value.trim())
    message.success(`已${type.value === 'add' ? '充值' : '扣除'} ${amount.value} 🥫`)
    emit('update:show', false)
    emit('success')
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '操作失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <NModal
    :show="show"
    @update:show="(v) => emit('update:show', v)"
    preset="card"
    title="充值 / 变更饼干余额"
    style="width: 520px; max-width: 92vw"
    :bordered="false"
  >
    <NForm label-placement="top" class="recharge-form">
      <NFormItem label="选择用户" required>
        <NSelect
          v-model:value="userId"
          :options="userOptions"
          :disabled="isPreset"
          :placeholder="isPreset ? '' : '搜索并选择用户'"
          :loading="userLoading"
          filterable
        />
        <div v-if="selectedUser" class="preset-hint">
          当前余额
          <NTag size="small" round :type="(selectedUser.cookie_balance ?? 0) < 50 ? 'warning' : 'success'">
            {{ selectedUser.cookie_balance ?? 0 }} 🥫
          </NTag>
          <template v-if="selectedUser.lab_group"> · {{ selectedUser.lab_group }}</template>
        </div>
      </NFormItem>

      <NFormItem label="操作类型" required>
        <NRadioGroup v-model:value="type">
          <NRadio value="add">增加（充值 / 补贴）</NRadio>
          <NRadio value="deduct">扣除（消耗 / 调账）</NRadio>
        </NRadioGroup>
      </NFormItem>

      <NFormItem label="变更数量" required>
        <NInputNumber v-model:value="amount" :min="1" :step="1" :precision="0" placeholder="请输入正整数" style="width: 100%">
          <template #suffix>🥫</template>
        </NInputNumber>
      </NFormItem>

      <NFormItem label="操作备注">
        <NInput v-model:value="remark" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="例如：测试 10x 流程算力补贴 / 人工调账" maxlength="120" show-count />
      </NFormItem>
    </NForm>

    <template #footer>
      <NSpace justify="end">
        <NButton @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" :loading="submitting" @click="handleSubmit">确认变更</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.recharge-form { padding-top: 4px; }
.preset-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--neutral-text-2, #86909c);
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
