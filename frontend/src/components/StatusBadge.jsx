// 状态徽章：queued/processing/succeeded/failed/cancelled 映射与脉冲动画
import { statusMeta } from '../utils/status'

export default function StatusBadge({ status }) {
  const meta = statusMeta(status)
  return (
    <span className={`badge badge-${meta.tone}`} data-testid="status-badge" data-status={status}>
      <span className="badge-dot" />
      {meta.label}
    </span>
  )
}
