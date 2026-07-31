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

// D7：批量入队（多图同参数，原子创建）与任务重跑（复用原参数，新版本产物）
export function createTasksBatch({ imageIds, taskType, params }) {
  return post('/tasks/batch', { image_ids: imageIds, task_type: taskType, params })
}

export function rerunTask(taskId) {
  return post(`/tasks/${taskId}/rerun`)
}
