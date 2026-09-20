const DATA_MANAGEMENT_ONLY_SUFFIXES = new Set([
  '.bam',
  '.cram',
  '.h5ad',
  '.rds',
  '.qs',
  '.zip',
])

export const DATA_MANAGEMENT_UPLOAD_HINT =
  '请前往“文件管理”上传，再在输入框中使用 @ 引用该文件，避免聊天模型直接解析大体积或二进制数据。'

export function requiresDataManagementUpload(filename: string): boolean {
  const normalized = filename.trim().toLowerCase()
  return [...DATA_MANAGEMENT_ONLY_SUFFIXES].some((suffix) => normalized.endsWith(suffix))
}
