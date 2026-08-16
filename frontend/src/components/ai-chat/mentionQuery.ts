export function readActiveMentionQuery(
  textBeforeCaret: string,
  committedLabels: readonly string[] = [],
): string | null {
  const match = textBeforeCaret.match(/(?:^|[\s\n])@([^@\n]*)$/)
  if (!match) return null

  const query = match[1].trimStart()
  const isCommitted = committedLabels.some((label) => {
    if (!label) return false
    return query === label || query.startsWith(`${label} `)
  })

  return isCommitted ? null : query
}
