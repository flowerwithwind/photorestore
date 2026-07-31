// 任务 API：入队/详情/列表/取消/SSE 事件流/产物下载（对齐 D4 冻结契约）
import { get, post } from './http'

export const TASK_TYPES = ['restore', 'upscale', 'colorize']

export function listTasks({ status, limit = 20, offset = 0 } = {}) {
  return get('/tasks', { status, limit, offset })
}

export function getTaskDetail(taskId) {
  return get(`/tasks/${taskId}`)
}

export function createTask({ imageIds, taskType, params }) {
  return post('/tasks', { image_ids: imageIds, task_type: taskType, params })
}

export function cancelTask(taskId) {
  return post(`/tasks/${taskId}/cancel`)
}

export function taskEventsUrl(taskId) {
  return `/api/tasks/${taskId}/events`
}

export function outputDownloadUrl(taskId, index) {
  return `/api/tasks/${taskId}/outputs/${index}/download`
}
