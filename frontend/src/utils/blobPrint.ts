/**
 * 通过隐藏 iframe 打印 Blob/Object URL 内容（图片、PDF）。
 * 打印对话框关闭前保留 iframe，最长 60s 后移除。
 */
export function printBlobUrl(url: string): void {
  const frame = document.createElement('iframe')
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden'
  frame.setAttribute('aria-hidden', 'true')
  frame.src = url
  frame.onload = () => {
    try {
      frame.contentWindow?.focus()
      frame.contentWindow?.print()
    } catch {
      frame.remove()
      return
    }
    window.setTimeout(() => frame.remove(), 60_000)
  }
  document.body.appendChild(frame)
}
