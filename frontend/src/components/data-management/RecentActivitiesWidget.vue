<script setup lang="ts">
/**
 * 近期活跃轨迹 —— 从 files（上传）+ directories（建文件夹）按 created_at 推导，NTimeline 渲染
 */
import { computed } from 'vue'
import { NTimeline, NEmpty } from 'naive-ui'
import type { DataFile, Directory } from '@/types'

const props = defineProps<{
  files: DataFile[]
  directories: Directory[]
}>()

interface Activity {
  type: 'upload' | 'folder'
  title: string
  time: string
  color: string
}

function relTime(iso: string): string {
  const now = Date.now()
  const t = new Date(iso).getTime()
  const diff = Math.max(0, now - t)
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

const activities = computed<Activity[]>(() => {
  const uploads: Activity[] = props.files.map((f) => ({
    type: 'upload' as const,
    title: `上传了 ${f.original_name}`,
    time: f.created_at,
    color: '#165DFF',
  }))
  const folders: Activity[] = props.directories
    .filter((d) => !d.is_system)
    .map((d) => ({
      type: 'folder' as const,
      title: `创建了文件夹 ${d.name}`,
      time: d.created_at,
      color: '#FF7D00',
    }))
  return [...uploads, ...folders]
    .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
    .slice(0, 8)
})
</script>

<template>
  <div class="widget">
    <h3 class="widget-title">近期活跃轨迹</h3>
    <NTimeline v-if="activities.length">
      <NTimelineItem
        v-for="(act, i) in activities"
        :key="i"
        :type="act.type === 'upload' ? 'info' : 'warning'"
        :color="act.color"
      >
        <template #header>
          <span class="act-title">{{ act.title }}</span>
        </template>
        <span class="act-time">{{ relTime(act.time) }}</span>
      </NTimelineItem>
    </NTimeline>
    <NEmpty v-else description="暂无活动" />
  </div>
</template>

<style scoped>
.widget {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.widget-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  margin: 0 0 14px;
}
.act-title {
  font-size: 12px;
  color: var(--neutral-text-1, #1d2129);
  word-break: break-all;
}
.act-time {
  font-size: 11px;
  color: var(--neutral-text-3, #86909c);
}
</style>
