import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { schedulesApi, type Delivery, type Schedule } from '@/api/schedules'

export const useScheduleStore = defineStore('schedule', () => {
  const schedules = ref<Schedule[]>([])
  const deliveries = ref<Delivery[]>([])
  const loading = ref(false)
  const selectedScheduleId = ref<string | null>(null)
  const selectedSchedule = computed(() => schedules.value.find((item) => item.id === selectedScheduleId.value) || null)

  async function fetchSchedules() {
    loading.value = true
    try {
      schedules.value = (await schedulesApi.list()).items
    } finally {
      loading.value = false
    }
  }

  async function createSchedule(payload: Parameters<typeof schedulesApi.create>[0]) {
    const schedule = await schedulesApi.create(payload)
    schedules.value.unshift(schedule)
    return schedule
  }

  async function cancelSchedule(id: string) {
    const schedule = await schedulesApi.cancel(id)
    const index = schedules.value.findIndex((item) => item.id === id)
    if (index >= 0) schedules.value[index] = schedule
  }

  async function fetchDeliveries(id: string) {
    selectedScheduleId.value = id
    deliveries.value = await schedulesApi.deliveries(id)
  }

  async function snoozeReminder(id: string, minutes: number) {
    const delivery = await schedulesApi.snooze(id, minutes)
    const index = deliveries.value.findIndex((item) => item.id === id)
    if (index >= 0) deliveries.value[index] = delivery
  }

  async function completeReminder(id: string) {
    const delivery = await schedulesApi.complete(id)
    const index = deliveries.value.findIndex((item) => item.id === id)
    if (index >= 0) deliveries.value[index] = delivery
  }

  return { schedules, deliveries, loading, selectedSchedule, fetchSchedules, createSchedule, cancelSchedule, fetchDeliveries, snoozeReminder, completeReminder }
})
