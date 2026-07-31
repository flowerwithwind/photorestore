// 磁盘占用统计与一键清理
import { get, post } from './http'

export function getStorageStats() {
  return get('/storage/stats')
}

export function cleanupStorage(body) {
  return post('/storage/cleanup', body)
}
