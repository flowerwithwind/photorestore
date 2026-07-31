// 格式化工具：字节数 / 耗时 / 时间 / 阶段与任务类型标签
export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return '—'
  const value = Number(bytes)
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB']
  let size = value / 1024
  let unit = units[0]
  for (let i = 1; i < units.length && size >= 1024; i += 1) {
    size /= 1024
    unit = units[i]
  }
  return `${size >= 100 ? Math.round(size) : size.toFixed(1)} ${unit}`
}

export function formatDuration(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '—'
  const value = Number(ms)
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(1)} s`
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export const PHASE_LABELS = {
  decode: '解码',
  preprocess: '预处理',
  infer: '推理',
  postprocess: '后处理',
  save: '保存',
}

export function phaseLabel(phase) {
  if (!phase) return '—'
  return PHASE_LABELS[phase] || phase
}

export const TASK_TYPE_LABELS = {
  restore: '修复',
  upscale: '超分',
  colorize: '上色',
}

export function taskTypeLabel(type) {
  return TASK_TYPE_LABELS[type] || type || '—'
}

export function shortHash(hash) {
  if (!hash) return '—'
  return hash.length > 8 ? hash.slice(0, 8) : hash
}
