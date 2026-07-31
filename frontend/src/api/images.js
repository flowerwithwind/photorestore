// 图片 API（D6 画廊）：列表（含任务摘要/产物）、删除、原图下载、演示种子图片
import { get, post, request } from './http'

export function registerImage({ filename, sizeBytes, format }) {
  return post('/images', { filename, size_bytes: sizeBytes, format })
}

/** D10：真实字节上传（multipart FormData）→ /api/images/upload，返回登记后的 image 对象。 */
export function uploadImage(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request('/images/upload', { method: 'POST', body: formData })
}

export function listImages({ taskType, status, limit = 20, offset = 0 } = {}) {
  return get('/images', { task_type: taskType, status, limit, offset })
}

export function getImage(imageId) {
  return get(`/images/${imageId}`)
}

export function deleteImage(imageId) {
  return request(`/images/${imageId}`, { method: 'DELETE' })
}

export function seedImageFromBase64({ filename, dataBase64 }) {
  return post('/images/seed', { filename, data_base64: dataBase64 })
}

export function imageDownloadUrl(imageId) {
  return `/api/images/${imageId}/download`
}

/** 取一张图片"最新可用产物"（优先 succeeded 任务的第一个输出）。 */
export function latestOutput(image) {
  if (!image || !Array.isArray(image.tasks)) return null
  const succeeded = image.tasks
    .filter((t) => t.status === 'succeeded')
    .sort((a, b) => (b.id || 0) - (a.id || 0))
  if (succeeded.length === 0) return null
  const outputs = succeeded[0].result && Array.isArray(succeeded[0].result.outputs)
    ? succeeded[0].result.outputs
    : []
  return outputs[0] || null
}
