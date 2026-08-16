<script setup lang="ts">
import { NTabPane, NTabs } from 'naive-ui'
import AnnouncementManager from '@/components/admin/AnnouncementManager.vue'
import FestivalManager from '@/components/admin/FestivalManager.vue'
import NotificationManager from '@/components/admin/NotificationManager.vue'
import PageHeader from '@/components/PageHeader.vue'
</script>

<template>
  <div class="page-container">
    <PageHeader title="通知公告管理" subtitle="维护首页条幅、通知提醒与节日展示" />
    <NTabs type="line" animated>
      <NTabPane name="announcement" tab="首页条幅">
        <AnnouncementManager />
      </NTabPane>
      <NTabPane name="notification" tab="通知提醒">
        <NotificationManager />
      </NTabPane>
      <NTabPane name="festival" tab="节日彩蛋 ✨">
        <FestivalManager />
      </NTabPane>
    </NTabs>
  </div>
</template>

<style scoped>
.page-container {
  padding: 24px;
  min-height: 100%;
  background: var(--neutral-bg);
}
.page-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0 0 16px;
}
</style>
