// 上传预检：类型 + 大小（对齐后端 ALLOWED_EXTENSIONS / MAX_UPLOAD_BYTES=20MB）
export const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'bmp', 'webp', 'tiff', 'tif']
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024

export function extensionOf(filename) {
  if (!filename) return null
  const index = filename.lastIndexOf('.')
  if (index < 0 || index === filename.length - 1) return null
  return filename.slice(index + 1).toLowerCase()
}

export function isAllowedExtension(filename) {
  const ext = extensionOf(filename)
  return ext !== null && ALLOWED_EXTENSIONS.includes(ext)
}

export function precheckFile(file, { maxBytes = MAX_UPLOAD_BYTES } = {}) {
  const errors = []
  const ext = extensionOf(file && file.name)
  if (!isAllowedExtension(file && file.name)) {
    errors.push(`不支持的文件类型${ext ? `：.${ext}` : ''}（支持 jpg/jpeg/png/bmp/webp/tiff/tif）`)
  }
  const size = file && typeof file.size === 'number' ? file.size : 0
  if (size > maxBytes) {
    errors.push(`文件过大：${(size / 1024 / 1024).toFixed(1)} MB（上限 ${Math.round(maxBytes / 1024 / 1024)} MB）`)
  }
  if (file && file.type && !file.type.startsWith('image/')) {
    errors.push(`MIME 类型不匹配：${file.type}`)
  }
  return { ok: errors.length === 0, errors, format: ext, sizeBytes: size }
}

export function precheckFiles(files, options) {
  return Array.from(files || []).map((file, index) => ({
    index,
    file,
    ...precheckFile(file, options),
  }))
}
