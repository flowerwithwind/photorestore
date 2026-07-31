// 磁盘占用统计
import { get } from './http'

export function getStorageStats() {
  return get('/storage/stats')
}
