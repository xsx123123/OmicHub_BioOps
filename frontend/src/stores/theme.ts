import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

const THEME_KEY = 'cygnusx-theme'
export type AppTheme = 'dark' | 'light'

export const useThemeStore = defineStore('theme', () => {
  const theme = ref<AppTheme>('dark')
  const hasStoredPreference = ref(false)
  const isDark = computed(() => theme.value === 'dark')

  function applyTheme(next: AppTheme, persist = true) {
    theme.value = next
    document.documentElement.setAttribute('data-theme', next)
    document.documentElement.classList.toggle('dark', next === 'dark')
    if (persist) {
      hasStoredPreference.value = true
      try {
        localStorage.setItem(THEME_KEY, next)
      } catch {
        /* ignore */
      }
    }
  }

  function setTheme(next: AppTheme) {
    applyTheme(next)
  }

  function toggleTheme() {
    applyTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  function initTheme() {
    let next: AppTheme = 'dark'
    let stored = false
    try {
      const saved = localStorage.getItem(THEME_KEY) as AppTheme | null
      if (saved === 'light' || saved === 'dark') {
        next = saved
        stored = true
      }
    } catch {
      /* ignore */
    }
    hasStoredPreference.value = stored
    applyTheme(next, false)
  }

  initTheme()

  return {
    theme,
    isDark,
    hasStoredPreference,
    setTheme,
    toggleTheme,
    initTheme,
  }
})
