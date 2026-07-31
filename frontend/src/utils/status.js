// 任务状态徽章映射（queued/processing/succeeded/failed/cancelled）
export const STATUS_ORDER = ['queued', 'processing', 'succeeded', 'failed', 'cancelled']

export const STATUS_META = {
  queued: { label: '排队中', tone: 'queued' },
  processing: { label: '处理中', tone: 'processing', pulse: true },
  succeeded: { label: '已完成', tone: 'succeeded' },
  failed: { label: '失败', tone: 'failed' },
  cancelled: { label: '已取消', tone: 'cancelled' },
}

export function statusMeta(status) {
  return STATUS_META[status] || { label: status || '未知', tone: 'queued' }
}

export function isTerminal(status) {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

export function isActive(status) {
  return status === 'queued' || status === 'processing'
}
