import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type {
  TerminalSession,
  CreateTerminalRequest,
  TerminalImage,
  TerminalResources,
  TerminalRuntimeConfig,
} from '@/types/terminal'
import {
  createTerminalSession,
  listTerminalSessions,
  deleteTerminalSession,
  listTerminalImages,
  getTerminalConfig,
} from '@/api/terminal'

const DEFAULT_MIN_MEMORY_MB = 512
const DEFAULT_MAX_MEMORY_MB = 4096
const DEFAULT_MIN_CPU_CORES = 0.5
const DEFAULT_MAX_CPU_CORES = 4.0

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

export const useTerminalStore = defineStore('terminal', () => {
  const sessions = ref<TerminalSession[]>([])
  const currentSession = ref<TerminalSession | null>(null)
  const images = ref<TerminalImage[]>([])
  const runtimeConfig = ref<TerminalRuntimeConfig | null>(null)
  const selectedImageId = ref<string | null>(null)
  const customMemoryMb = ref<number | null>(null)
  const customCpuCores = ref<number | null>(null)
  const loading = ref(false)

  const enabledImages = computed(() => images.value.filter((img) => img.enabled))
  const selectedImage = computed(() =>
    enabledImages.value.find((img) => img.id === selectedImageId.value),
  )

  const terminalEnabled = computed(() => runtimeConfig.value?.enabled ?? true)
  const maxMemoryMb = computed(() => runtimeConfig.value?.max_resources.memory_mb ?? DEFAULT_MAX_MEMORY_MB)
  const maxCpuCores = computed(() => runtimeConfig.value?.max_resources.cpu_cores ?? DEFAULT_MAX_CPU_CORES)

  const memoryRange = computed(() => {
    const configuredMax = Math.max(DEFAULT_MIN_MEMORY_MB, maxMemoryMb.value)
    return {
      min: DEFAULT_MIN_MEMORY_MB,
      max: configuredMax,
      step: 512,
    }
  })

  const cpuRange = computed(() => {
    const configuredMax = Math.max(DEFAULT_MIN_CPU_CORES, maxCpuCores.value)
    const imageDefault = selectedImage.value?.resources.cpu_cores
    const min = imageDefault ? Math.min(imageDefault, DEFAULT_MIN_CPU_CORES) : DEFAULT_MIN_CPU_CORES
    return {
      min: Math.min(min, configuredMax),
      max: Math.max(min, configuredMax),
      step: 0.5,
    }
  })

  const effectiveMemoryMb = computed(() => {
    const base =
      customMemoryMb.value ??
      selectedImage.value?.resources.memory_mb ??
      runtimeConfig.value?.default_resources.memory_mb ??
      512
    return clampNumber(base, memoryRange.value.min, memoryRange.value.max)
  })

  const effectiveCpuCores = computed(() => {
    const base =
      customCpuCores.value ??
      selectedImage.value?.resources.cpu_cores ??
      runtimeConfig.value?.default_resources.cpu_cores ??
      1.0
    return clampNumber(base, cpuRange.value.min, cpuRange.value.max)
  })

  function resetCustomResources() {
    customMemoryMb.value = null
    customCpuCores.value = null
  }

  watch(selectedImageId, (imageId, previousImageId) => {
    if (previousImageId && imageId !== previousImageId) {
      resetCustomResources()
    }
  })

  async function fetchSessions() {
    try {
      sessions.value = await listTerminalSessions()
    } catch {
      sessions.value = []
    }
  }

  async function fetchImages() {
    try {
      images.value = await listTerminalImages()
      try {
        runtimeConfig.value = await getTerminalConfig()
      } catch {
        runtimeConfig.value = null
      }
      // 默认选中第一个启用镜像，或保持当前选择
      if (!selectedImageId.value || !enabledImages.value.some((img) => img.id === selectedImageId.value)) {
        selectedImageId.value = enabledImages.value[0]?.id ?? null
      }
    } catch {
      images.value = []
      runtimeConfig.value = null
      selectedImageId.value = null
    }
  }

  async function createSession(req?: CreateTerminalRequest) {
    if (!terminalEnabled.value) {
      throw new Error('云端沙盒终端已关闭')
    }

    loading.value = true
    try {
      const request: CreateTerminalRequest = { ...req }
      if (selectedImageId.value) {
        request.image_id = selectedImageId.value
      }
      const resources: Partial<TerminalResources> = {}
      if (customMemoryMb.value != null) {
        resources.memory_mb = clampNumber(
          customMemoryMb.value,
          memoryRange.value.min,
          memoryRange.value.max,
        )
      }
      if (customCpuCores.value != null) {
        resources.cpu_cores = clampNumber(
          customCpuCores.value,
          cpuRange.value.min,
          cpuRange.value.max,
        )
      }
      if (Object.keys(resources).length > 0) {
        request.resources = resources
      }
      const session = await createTerminalSession(request)
      currentSession.value = session
      sessions.value.push(session)
      return session
    } finally {
      loading.value = false
    }
  }

  async function destroySession(sessionId: string) {
    try {
      await deleteTerminalSession(sessionId)
    } finally {
      if (currentSession.value?.session_id === sessionId) {
        currentSession.value = null
      }
      sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
    }
  }

  return {
    sessions,
    currentSession,
    images,
    runtimeConfig,
    selectedImageId,
    customMemoryMb,
    customCpuCores,
    loading,
    enabledImages,
    selectedImage,
    terminalEnabled,
    memoryRange,
    cpuRange,
    effectiveMemoryMb,
    effectiveCpuCores,
    resetCustomResources,
    fetchSessions,
    fetchImages,
    createSession,
    destroySession,
  }
})
