// 任务详情：SSE 实时进度（断线重连 + 轮询兜底）+ 阶段时间线 + 产物下载 + 取消
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { cancelTask, outputDownloadUrl } from '../api/tasks'
import { useTaskEvents } from '../hooks/useTaskEvents'
import StatusBadge from '../components/StatusBadge'
import ProgressBar from '../components/ProgressBar'
import PhaseTimeline from '../components/PhaseTimeline'
import { formatBytes, formatDateTime, taskTypeLabel } from '../utils/format'
import { isActive } from '../utils/status'

function ConnectionBadge({ source, connected, retries }) {
  let text = '未连接'
  let tone = 'queued'
  if (source === 'sse' && connected) {
    text = '实时推送（SSE）'
    tone = 'succeeded'
  } else if (source === 'sse') {
    text = retries > 0 ? `SSE 重连中（${retries} 次）` : 'SSE 连接中…'
    tone = 'processing'
  } else if (source === 'polling') {
    text = '轮询兜底'
    tone = 'queued'
  }
  return <span className={`badge badge-${tone}`} data-testid="conn-badge" data-source={source}>{text}</span>
}

export default function TaskDetailView() {
  const { taskId } = useParams()
  const id = Number(taskId)
  const { task, phaseLogs, source, connected, retries, error } = useTaskEvents(id)
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState(null)

  const handleCancel = async () => {
    if (cancelling || !task || !isActive(task.status)) return
    setCancelling(true)
    setCancelError(null)
    try {
      await cancelTask(task.id)
    } catch (err) {
      setCancelError(err.message || String(err))
    } finally {
      setCancelling(false)
    }
  }

  if (!task) {
    return (
      <div className="page">
        <div className="page-header">
          <div>
            <h1 className="page-title">任务 #{id}</h1>
            <div className="page-sub">加载中…</div>
          </div>
        </div>
        {error && <div className="notice notice-error" data-testid="detail-error">{error}</div>}
      </div>
    )
  }

  const outputs = (task.result && Array.isArray(task.result.outputs)) ? task.result.outputs : []
  const modelName = (task.result && task.result.model) || (outputs[0] && outputs[0].model) || '—'
  const params = task.params && typeof task.params === 'object' && Object.keys(task.params).length > 0
    ? JSON.stringify(task.params, null, 2)
    : '{}（默认参数）'

  return (
    <div className="page" data-testid="task-detail-view">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            任务 #{task.id} <StatusBadge status={task.status} />
          </h1>
          <div className="page-sub">
            {taskTypeLabel(task.task_type)} · <ConnectionBadge source={source} connected={connected} retries={retries} />
          </div>
        </div>
        <div className="actions-row">
          <Link className="btn" to="/">返回工作台</Link>
          {isActive(task.status) && (
            <button
              type="button"
              className="btn btn-danger"
              disabled={cancelling}
              onClick={handleCancel}
              data-testid="cancel-btn"
            >
              {cancelling ? '取消中…' : '取消任务'}
            </button>
          )}
        </div>
      </div>

      {error && <div className="notice notice-error" data-testid="detail-error">{error}</div>}
      {cancelError && <div className="notice notice-error" data-testid="cancel-error">{cancelError}</div>}
      {task.error && (
        <div className="notice notice-error" data-testid="task-error">
          任务失败：{task.error}
        </div>
      )}

      <div className="card">
        <div className="card-title">进度</div>
        <ProgressBar progress={task.progress} phase={task.phase} status={task.status} />
        {source === 'polling' && (
          <div className="muted">SSE 不可用，已切换为轮询模式（详情接口含 phase_logs）</div>
        )}
      </div>

      <div className="detail-grid">
        <div className="card">
          <div className="card-title">任务信息</div>
          <dl className="kv" data-testid="task-kv">
            <dt>任务类型</dt>
            <dd>{taskTypeLabel(task.task_type)}（{task.task_type}）</dd>
            <dt>参数</dt>
            <dd><pre className="params-pre">{params}</pre></dd>
            <dt>参数哈希</dt>
            <dd className="mono">{task.params_hash}</dd>
            <dt>模型</dt>
            <dd>{modelName}</dd>
            <dt>创建时间</dt>
            <dd>{formatDateTime(task.created_at)}</dd>
            <dt>开始时间</dt>
            <dd>{task.started_at ? formatDateTime(task.started_at) : '—'}</dd>
            <dt>完成时间</dt>
            <dd>{task.finished_at ? formatDateTime(task.finished_at) : '—'}</dd>
          </dl>
        </div>

        <div className="card">
          <div className="card-title">阶段时间线</div>
          <PhaseTimeline phaseLogs={phaseLogs} currentPhase={task.phase} status={task.status} />
        </div>
      </div>

      {outputs.length > 0 && (
        <div className="card">
          <div className="card-title">产物（{outputs.length}）</div>
          <div className="output-list" data-testid="output-list">
            {outputs.map((output, index) => (
              <div className="output-item" key={index} data-testid={`output-${index}`}>
                <div className="output-info">
                  <div className="file-name">{output.filename}</div>
                  <div className="muted">
                    模型 {output.model || modelName} · {String(output.format).toUpperCase()} ·{' '}
                    {output.width}×{output.height} · {formatBytes(output.size_bytes)}
                  </div>
                  <div className="muted">
                    原图 {output.input_width}×{output.input_height} ·{' '}
                    {formatBytes(output.input_size_bytes)}（{String(output.input_format).toUpperCase()}）
                  </div>
                </div>
                <a className="btn btn-primary" href={outputDownloadUrl(task.id, index)} data-testid={`download-${index}`}>
                  下载
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
