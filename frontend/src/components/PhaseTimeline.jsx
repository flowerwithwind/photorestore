// 阶段时间线：phase_logs（started/finished/duration_ms）+ 当前进行中阶段高亮
import { formatDateTime, formatDuration, phaseLabel } from '../utils/format'

export default function PhaseTimeline({ phaseLogs = [], currentPhase = null, status = null }) {
  if (!phaseLogs || phaseLogs.length === 0) {
    return <div className="empty">暂无阶段日志</div>
  }
  return (
    <div className="timeline" data-testid="phase-timeline">
      {phaseLogs.map((log) => {
        const isActive = log.phase === currentPhase && !log.finished_at
        const isDone = Boolean(log.finished_at)
        const dotClass = isActive ? 'active' : isDone ? 'done' : ''
        return (
          <div className="timeline-item" key={log.id} data-phase={log.phase}>
            <span className="timeline-phase">
              <span className={`timeline-dot ${dotClass}`} />
              {phaseLabel(log.phase)}
            </span>
            <span className="muted">
              {isActive && status !== 'failed' && status !== 'cancelled'
                ? '进行中…'
                : formatDateTime(log.started_at)}
            </span>
            <span className="muted">{isDone ? formatDateTime(log.finished_at) : '—'}</span>
            <span className="muted">{isDone ? formatDuration(log.duration_ms) : '—'}</span>
          </div>
        )
      })}
    </div>
  )
}
