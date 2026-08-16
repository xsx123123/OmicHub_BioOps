<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NButton, NIcon, NSpin } from 'naive-ui'
import {
  CheckmarkOutline,
  ChevronForwardOutline,
  RocketOutline,
} from '@vicons/ionicons5'
import { useRouter } from 'vue-router'
import apiClient from '@/api/client'
import type { UserProgress } from '@/types/stats'

const router = useRouter()
const progress = ref<UserProgress | null>(null)
const loading = ref(false)

const steps = computed(() => progress.value?.steps ?? [])
const allDone = computed(
  () => steps.value.length > 0 && steps.value.every((s) => s.done),
)

function stepStatus(done: boolean, number: number): 'completed' | 'current' | 'pending' {
  if (done) return 'completed'
  if (progress.value?.current === number) return 'current'
  return 'pending'
}

function statusClass(s: 'completed' | 'current' | 'pending') {
  return `step-circle step-circle--${s}`
}

function titleClass(s: 'completed' | 'current' | 'pending') {
  return `step-title step-title--${s}`
}

async function fetchProgress() {
  loading.value = true
  try {
    const res = await apiClient.get<UserProgress>('/stats/progress')
    progress.value = res.data
  } catch {
    progress.value = null
  } finally {
    loading.value = false
  }
}

onMounted(fetchProgress)
</script>

<template>
  <section class="quick-start">
    <div class="quick-start-header">
      <h2 class="section-title">快速开始</h2>
      <NButton
        v-if="allDone"
        size="small"
        type="primary"
        ghost
        @click="router.push('/flows')"
      >
        <template #icon>
          <NIcon><RocketOutline /></NIcon>
        </template>
        继续分析
      </NButton>
    </div>
    <NSpin :show="loading">
      <div class="steps-row">
        <div
          v-for="(step, index) in steps"
          :key="step.number"
          class="step-item"
        >
          <span :class="statusClass(stepStatus(step.done, step.number))">
            <NIcon v-if="step.done" :size="14">
              <CheckmarkOutline />
            </NIcon>
            <span v-else>{{ step.number }}</span>
          </span>
          <span :class="titleClass(stepStatus(step.done, step.number))">
            {{ step.title }}
          </span>
          <NIcon
            v-if="index < steps.length - 1"
            :size="16"
            class="step-arrow"
          >
            <ChevronForwardOutline />
          </NIcon>
        </div>
      </div>
    </NSpin>
  </section>
</template>

<style scoped>
.quick-start {
  margin-bottom: 24px;
}

.quick-start-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  line-height: 26px;
  color: var(--neutral-text-1, #1d2129);
  margin: 0;
}

.steps-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-circle {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s ease;
}

.step-circle--completed {
  background: var(--arco-primary, #165dff);
  color: #fff;
}

.step-circle--current {
  background: var(--arco-primary, #165dff);
  color: #fff;
  box-shadow: 0 0 0 4px rgba(22, 93, 255, 0.15);
}

.step-circle--pending {
  background: var(--neutral-border, #e5e6eb);
  color: var(--neutral-text-3, #86909c);
}

.step-title {
  font-size: 14px;
  line-height: 22px;
}

.step-title--completed,
.step-title--current {
  color: var(--arco-primary, #165dff);
  font-weight: 500;
}

.step-title--pending {
  color: var(--neutral-text-3, #86909c);
}

.step-arrow {
  color: var(--neutral-text-4, #c9cdd4);
  margin: 0 4px;
}

@media (max-width: 768px) {
  .steps-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .step-arrow {
    display: none;
  }
}
</style>
