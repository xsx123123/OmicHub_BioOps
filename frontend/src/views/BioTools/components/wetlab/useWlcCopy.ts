import { useMessage } from 'naive-ui'

/**
 * 湿实验计算器共享的「一键复制结果」能力。
 * 必须在组件 setup 中调用（内部使用 useMessage）。
 */
export function useWlcCopy() {
  const message = useMessage()

  async function copy(text: string, label = '结果'): Promise<void> {
    const value = (text || '').trim()
    if (!value) {
      message.warning('暂无可复制的内容')
      return
    }
    try {
      await navigator.clipboard.writeText(value)
      message.success(`已复制${label}到剪贴板`)
    } catch {
      message.error('复制失败，请手动选择文本复制')
    }
  }

  return { copy }
}
