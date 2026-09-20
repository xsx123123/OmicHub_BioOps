<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useScheduleStore } from '@/stores/schedule'

const store = useScheduleStore()
const title = ref('')
const startAt = ref('')
const reminderMinutes = ref(0)
const error = ref('')
const selected = computed(() => store.selectedSchedule)

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

async function create() {
  error.value = ''
  if (!title.value || !startAt.value) {
    error.value = '请填写标题和开始时间'
    return
  }
  try {
    await store.createSchedule({
      title: title.value,
      start_at: new Date(startAt.value).toISOString(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      reminder_offsets_minutes: [Number(reminderMinutes.value)],
    })
    title.value = ''
    startAt.value = ''
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '创建失败'
  }
}

async function cancel(id: string) {
  await store.cancelSchedule(id)
}

onMounted(() => store.fetchSchedules())
</script>

<template>
  <div class="schedule-page">
    <header class="page-header">
      <div><h1>日程与提醒</h1><p>管理实验室会议、收样和分析节点提醒。</p></div>
      <button @click="store.fetchSchedules">刷新</button>
    </header>
    <section class="editor card">
      <h2>创建日程</h2>
      <div class="form-grid">
        <label>标题<input v-model="title" placeholder="例如：开组会" /></label>
        <label>开始时间<input v-model="startAt" type="datetime-local" /></label>
        <label>提前提醒<select v-model="reminderMinutes"><option :value="0">准时</option><option :value="5">5 分钟</option><option :value="15">15 分钟</option><option :value="60">1 小时</option></select></label>
        <button class="primary" @click="create">创建</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </section>
    <main class="content-grid">
      <section class="card"><h2>我的日程 <small v-if="store.loading">加载中…</small></h2><div v-if="!store.schedules.length" class="empty">暂无日程</div><ul v-else class="schedule-list"><li v-for="item in store.schedules" :key="item.id" :class="{ active: selected?.id === item.id }" @click="store.fetchDeliveries(item.id)"><div><strong>{{ item.title }}</strong><span>{{ formatDate(item.start_at) }}</span></div><div class="actions"><em>{{ item.status }}</em><button v-if="item.status === 'active'" @click.stop="cancel(item.id)">取消</button></div></li></ul></section>
      <section class="card"><h2>提醒记录</h2><div v-if="!selected" class="empty">选择一个日程查看提醒</div><ul v-else class="delivery-list"><li v-for="delivery in store.deliveries" :key="delivery.id"><div><strong>{{ formatDate(delivery.due_at) }}</strong><span>{{ delivery.status }}</span></div><div><button v-if="delivery.status === 'pending'" @click="store.snoozeReminder(delivery.id, 10)">推迟 10 分钟</button><button v-if="delivery.status !== 'completed'" @click="store.completeReminder(delivery.id)">完成</button></div></li></ul></section>
    </main>
  </div>
</template>

<style scoped>
.schedule-page { padding: 28px; max-width: 1200px; margin: auto; color: var(--text-color, #1f2937); }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
h1, h2 { margin: 0 0 8px; } h1 { font-size: 28px; } h2 { font-size: 18px; } h2 small { font-size: 12px; font-weight: normal; }
.card { background: var(--card-color, #fff); border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; box-shadow: 0 4px 18px #0000000d; }
.form-grid { display: grid; grid-template-columns: 2fr 2fr 1fr auto; gap: 12px; align-items: end; } label { display: grid; gap: 6px; font-size: 13px; } input, select, button { border: 1px solid #d1d5db; border-radius: 7px; padding: 9px 11px; background: inherit; } button { cursor: pointer; } .primary { background: #2563eb; color: white; border-color: #2563eb; }
.content-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; } ul { list-style: none; padding: 0; margin: 0; } li { display: flex; justify-content: space-between; gap: 12px; padding: 13px 0; border-bottom: 1px solid #eef0f2; cursor: pointer; } li.active { color: #2563eb; } li span, li em { display: block; color: #6b7280; font-size: 12px; font-style: normal; margin-top: 4px; } .actions, li > div:last-child { display: flex; gap: 8px; align-items: center; } .empty { color: #9ca3af; padding: 24px 0; } .error { color: #dc2626; } @media (max-width: 800px) { .form-grid, .content-grid { grid-template-columns: 1fr; } }
</style>
