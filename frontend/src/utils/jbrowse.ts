/**
 * JBrowse 2 配置工具：把配置里所有 UriLocation.uri 补成绝对 URL。
 *
 * 为什么需要：前端用 blob URL 承载 config（绕过 JWT，详见 pipelines/jbrowse2/README.md），
 * 但 blob URL 是【opaque / 不能作为 base】的 URL。JBrowse 2 加载配置时会用
 *   new URL(uri, configBaseUrl)
 * 解析每个 uri —— 若 uri 是相对路径（如 /tracks/ref/human/hg38.fa）且 base 是 blob:...，
 * 会抛 TypeError: Failed to construct 'URL': Invalid URL，导致参考序列/轨道全部加载失败，
 * 浏览器只显示 Logo（这是「只显示 Logo」问题的真正根因，不是高度塌陷）。
 *
 * 故在把 config 写入 blob 之前，先把所有 uri 补成绝对 URL（带 window.location.origin），
 * 绝对 URL 解析时忽略 base，从而绕开 opaque base 限制。
 */

/** 单个 URI 绝对化：已是绝对 URL（http/https/blob/data/file）则原样返回，否则拼上当前 origin。 */
export function toAbsoluteUri(uri: string): string {
  if (/^(https?:|blob:|data:|file:)/i.test(uri)) return uri
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return uri.startsWith('/') ? `${origin}${uri}` : `${origin}/${uri}`
}

/**
 * 递归遍历配置对象，把【所有】 uri 字段原地绝对化。
 * 覆盖 fastaLocation / faiLocation / gziLocation / 轨道 bigWigLocation / bamLocation /
 * index.location 等 JBrowse 2 配置里一切 UriLocation.uri。
 * 仅改写键名为 'uri' 的字符串字段，其余结构（theme/defaultSession/location 等）不动。
 */
export function absolutizeUris(obj: unknown): void {
  if (!obj || typeof obj !== 'object') return
  if (Array.isArray(obj)) {
    for (const item of obj) absolutizeUris(item)
    return
  }
  const record = obj as Record<string, unknown>
  for (const [k, v] of Object.entries(record)) {
    if (k === 'uri' && typeof v === 'string') {
      record[k] = toAbsoluteUri(v)
    } else if (v && typeof v === 'object') {
      absolutizeUris(v)
    }
  }
}
