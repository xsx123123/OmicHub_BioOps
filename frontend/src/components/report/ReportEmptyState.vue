<script setup lang="ts">
import { NButton, NEmpty, NIcon, NTag } from 'naive-ui'
import { useRouter } from 'vue-router'
import { FlaskOutline } from '@vicons/ionicons5'

const router = useRouter()

const supportedTypes = [
  'RNA-seq 差异表达',
  'ATAC-seq 染色质可及性',
  'ChIP-seq 峰值分析',
  'WGBS 甲基化分析',
]
</script>

<template>
  <div class="empty-state">
    <NEmpty description="暂无报告" size="huge">
      <template #extra>
        <div class="empty-description">
          <p class="empty-title">暂无报告</p>
          <p class="empty-subtitle">前往分析中心提交任务，生成你的第一份分析报告</p>
          <div class="empty-tips">
            <p>支持的报告类型：</p>
            <div class="tip-tags">
              <NTag v-for="type in supportedTypes" :key="type" size="small" round>{{ type }}</NTag>
            </div>
          </div>
          <NButton type="primary" size="large" @click="router.push('/flows')">
            <template #icon>
              <NIcon :component="FlaskOutline" />
            </template>
            前往分析中心
          </NButton>
        </div>
      </template>
    </NEmpty>
  </div>
</template>

<style scoped>
.empty-state {
  padding: 48px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.empty-description {
  text-align: center;
}
.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-color-1);
  margin: 0 0 8px;
}
.empty-subtitle {
  font-size: 14px;
  color: var(--text-color-2);
  margin: 0 0 20px;
}
.empty-tips {
  background: var(--action-color);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 24px;
}
.empty-tips p {
  font-size: 13px;
  color: var(--text-color-3);
  margin: 0 0 8px;
}
.tip-tags {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
}
</style>
