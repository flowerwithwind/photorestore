// 工作台：任务列表（状态徽章/进度条/筛选/分页/自动刷新）+ 存储统计
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { listTasks } from '../api/tasks'
import StatusBadge from '../components/StatusBadge'
import ProgressBar from '../components/ProgressBar'
import StorageStats from '../components/StorageStats'
import { STATUS_ORDER } from '../utils/status'
import { formatDateTime, shortHash, taskTypeLabel } from '../utils/format'

const PAGE_SIZE = 20
const REFRESH_MS = 5000

export default function DashboardView() {
  const [status, setStatus] = useState('all')
  const [items, setItems] = useState([])
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const mounted = useRef(true)

  const load = useCallback(async () => {
    try {
      const data = await listTasks({
        status: status === 'all' ? undefined : status,
        limit: PAGE_SIZE,
        offset,
      })
      if (!mounted.current) return
      setItems(Array.isArray(data.items) ? data.items : [])
      setError(null)
    } catch (err) {
      if (mounted.current) setError(err.message || String(err))
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [status, offset])

  useEffect(() => {
    mounted.current = true
    setLoading(true)
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      mounted.current = false
      clearInterval(timer)
    }
  }, [load])

  const changeStatus = (next) => {
    setStatus(next)
    setOffset(0)
  }

  const hasMore = items.length >= PAGE_SIZE
  const totalShown = offset + items.length

  return (
    <div className="page" data-testid="dashboard-view">
      <div className="page-header">
        <div>
          <h1 className="page-title">任务工作台</h1>
          <div className="page-sub">PhotoRestore 图像处理任务 · 实时状态与产物追踪</div>
        </div>
        <button type="button" className="btn" onClick={() => { setLoading(true); load() }} data-testid="refresh-btn">
          刷新
        </button>
      </div>

      <div className="dashboard-grid">
        <StorageStats />
      </div>

      <div className="card">
        <div className="card-title">
          任务列表
          <span className="muted">（每 {PAGE_SIZE} 条一页 · 自动刷新 {REFRESH_MS / 1000}s）</span>
        </div>

        <div className="chip-row" role="group" aria-label="状态筛选" data-testid="status-filters">
          <button
            type="button"
            className={`chip ${status === 'all' ? 'active' : ''}`}
            onClick={() => changeStatus('all')}
          >
            全部
          </button>
          {STATUS_ORDER.map((s) => (
            <button
              key={s}
              type="button"
              className={`chip ${status === s ? 'active' : ''}`}
              onClick={() => changeStatus(s)}
              data-testid={`filter-${s}`}
            >
              {s}
            </button>
          ))}
        </div>

        {error && <div className="notice notice-error" data-testid="list-error">{error}</div>}

        {loading && items.length === 0 ? (
          <div className="empty">加载中…</div>
        ) : items.length === 0 ? (
          <div className="empty">暂无任务，去 <Link to="/upload">上传</Link> 创建第一个任务</div>
        ) : (
          <table className="table" data-testid="task-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>类型</th>
                <th>状态</th>
                <th>进度</th>
                <th>参数哈希</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((task) => (
                <tr key={task.id} data-testid={`task-row-${task.id}`}>
                  <td>#{task.id}</td>
                  <td>{taskTypeLabel(task.task_type)}</td>
                  <td><StatusBadge status={task.status} /></td>
                  <td><ProgressBar progress={task.progress} phase={task.phase} status={task.status} compact /></td>
                  <td className="muted">{shortHash(task.params_hash)}</td>
                  <td className="muted">{formatDateTime(task.created_at)}</td>
                  <td>
                    <Link className="btn" to={`/tasks/${task.id}`}>详情</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="pager">
          <span className="pager-info">显示 1–{totalShown} 条</span>
          <button type="button" className="btn" disabled={offset === 0} onClick={() => setOffset((v) => Math.max(0, v - PAGE_SIZE))}>
            上一页
          </button>
          <button type="button" className="btn" disabled={!hasMore} onClick={() => setOffset((v) => v + PAGE_SIZE)}>
            下一页
          </button>
        </div>
      </div>
    </div>
  )
}
