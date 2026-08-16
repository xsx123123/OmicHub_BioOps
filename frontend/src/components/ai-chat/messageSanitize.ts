/** 助手正文渲染前的清理工具。
 *
 * 模型偶发会把「工具调用」以文本形式写进正文（tool_use / tool_call / function_call /
 * invoke 等标签形态，含带命名空间前缀的变体）。真实工具调用走 function-calling 通道、
 * 由 ToolCallEntry 卡片渲染；这类文本形态的伪调用标记对用户没有任何信息量，还会显示成
 * 突兀的原始代码，统一在渲染前剔除。
 */

// 伪调用标签名（可带命名空间前缀，如 Claude 风格的 antml:invoke）。
const TAG_NAME = '(?:[a-z0-9]+:)?(?:tool_use|tool_call|function_calls|function_call|invoke)'

// 完整的「开标签 + 内容 + 闭标签」块；\1 回引确保闭合标签与开标签同名。
const FAKE_TOOL_CALL_BLOCK_PATTERN = new RegExp(
  '<(' + TAG_NAME + ')\\b[^>]*>[\\s\\S]*?<\\/\\1\\s*>',
  'gi',
)

// 兜底：未闭合 / 残留的单个开闭标签。
const FAKE_TOOL_CALL_TAG_PATTERN = new RegExp('<\\/?' + TAG_NAME + '\\b[^>]*>', 'gi')

/** 剔除文本形态的伪工具调用标记；纯函数，便于单测。 */
export function stripFakeToolCallMarkup(source: string): string {
  if (!source) return source
  let out = source.replace(FAKE_TOOL_CALL_BLOCK_PATTERN, '')
  out = out.replace(FAKE_TOOL_CALL_TAG_PATTERN, '')
  return out.replace(/\n{3,}/g, '\n\n').trim()
}
