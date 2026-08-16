export function formatMemoryMb(value: number | null | undefined, options?: { ceiling?: boolean }): string {
  if (value == null || !Number.isFinite(value)) return ''

  if (value < 1024) return `${value} MB`

  const gigabytes = options?.ceiling
    ? Math.ceil(value / 1024)
    : Math.round((value / 1024) * 10) / 10
  return `${Number.isInteger(gigabytes) ? gigabytes : gigabytes.toFixed(1)} GB`
}

export function parseMemoryMb(input: string): number | null {
  const normalized = input.trim().toLowerCase().replace(/\s+/g, '')
  if (!normalized) return null

  const matched = normalized.match(/^(\d+(?:\.\d+)?)(gb|g|mb|m)?$/)
  if (!matched) return null

  const value = Number(matched[1])
  if (!Number.isFinite(value)) return null

  return /^(gb|g)$/.test(matched[2] ?? '') ? value * 1024 : value
}
