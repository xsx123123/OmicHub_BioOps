import { ref } from 'vue'

let cachedText: string | null = null

export function useAgreementText() {
  const text = ref('')
  const loading = ref(false)
  const error = ref('')

  async function fetchText() {
    if (cachedText) {
      text.value = cachedText
      return
    }
    loading.value = true
    error.value = ''
    try {
      const res = await fetch('/docs/platform-agreement.md')
      if (!res.ok) {
        throw new Error(`加载协议失败: ${res.status}`)
      }
      const markdown = await res.text()
      cachedText = markdown
      text.value = markdown
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载协议失败'
    } finally {
      loading.value = false
    }
  }

  return {
    text,
    loading,
    error,
    fetchText,
  }
}
