// 模型与设置 API：模型元数据 / 并发数配置（D8 设置页）
import { get, post } from './http'

export function getModels() {
  return get('/models')
}

export function getSettings() {
  return get('/settings')
}

export function saveSettings(body) {
  return post('/settings', body)
}
