<script setup lang="ts">
import { computed } from 'vue'
import { NTabs, NTabPane } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import AdminCookieManagementView from '@/views/AdminCookieManagementView.vue'
import AdminCookiePricingView from '@/views/AdminCookiePricingView.vue'

const route = useRoute()
const router = useRouter()

const activeTab = computed({
  get: () => route.name === 'admin-biscuits-pricing' ? 'pricing' : 'accounts',
  set: (tab: string) => {
    void router.push({ name: tab === 'pricing' ? 'admin-biscuits-pricing' : 'admin-biscuits-accounts' })
  },
})
</script>

<template>
  <div class="admin-config-center">
    <PageHeader title="饼干中心" subtitle="集中管理账户余额、交易审计与计费策略" />
    <NTabs v-model:value="activeTab" type="line" animated class="admin-config-tabs">
      <NTabPane name="accounts" tab="账户管理">
        <AdminCookieManagementView embedded />
      </NTabPane>
      <NTabPane name="pricing" tab="定价管理">
        <AdminCookiePricingView embedded />
      </NTabPane>
    </NTabs>
  </div>
</template>
