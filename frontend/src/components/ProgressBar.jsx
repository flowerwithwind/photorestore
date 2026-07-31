// 进度条：0~100 填充 + 阶段标签；终态使用对应配色
import { phaseLabel } from '../utils/format'

export default function ProgressBar({ progress = 0, phase = null, status = null, compact = false }) {
  const value = Math.max(0, Math.min(100, Number(progress) || 0))
  const tone = status === 'succeeded' || status === 'failed' || status === 'cancelled' ? status : ''
  return (
    <div className="progress-wrap" data-testid="progress-bar">
      <div className="progress-track" aria-label={`进度 ${value}%`}>
        <div className={`progress-fill ${tone}`} style={{ width: `${value}%` }} />
      </div>
      {!compact && <span className="progress-text">{phaseLabel(phase)} · {value}%</span>}
    </div>
  )
}
