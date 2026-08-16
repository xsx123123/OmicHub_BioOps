const IMAGE_EXTENSION_BY_TYPE: Record<string, string> = {
  'image/bmp': 'bmp',
  'image/gif': 'gif',
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/svg+xml': 'svg',
  'image/webp': 'webp',
}

function formatTimestamp(timestamp: number): string {
  const date = new Date(timestamp)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getUTCFullYear()}${pad(date.getUTCMonth() + 1)}${pad(date.getUTCDate())}-${pad(date.getUTCHours())}${pad(date.getUTCMinutes())}${pad(date.getUTCSeconds())}`
}

function clipboardImageName(file: File, timestamp: number, index: number): string {
  if (file.name && file.name !== 'image.png') return file.name
  const extension = IMAGE_EXTENSION_BY_TYPE[file.type] || 'png'
  const suffix = index ? `-${index + 1}` : ''
  return `clipboard-image-${formatTimestamp(timestamp)}${suffix}.${extension}`
}

function normalizeClipboardFile(file: File, timestamp: number, index: number): File {
  if (!file.type.startsWith('image/')) return file
  return new File(
    [file],
    clipboardImageName(file, timestamp, index),
    { type: file.type || 'image/png', lastModified: file.lastModified || timestamp },
  )
}

/** Extract real files from a clipboard payload without affecting ordinary text paste. */
export function clipboardAttachmentFiles(clipboardData: DataTransfer | null, timestamp = Date.now()): File[] {
  if (!clipboardData) return []

  const itemFiles = Array.from(clipboardData.items ?? [])
    .filter((item) => item.kind === 'file')
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null)
  const files = itemFiles.length ? itemFiles : Array.from(clipboardData.files ?? [])

  return files.map((file, index) => normalizeClipboardFile(file, timestamp, index))
}
