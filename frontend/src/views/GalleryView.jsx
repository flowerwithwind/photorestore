// D6 对比画廊：按任务类型/状态筛选 + 大图预览（BeforeAfterSlider）+ 下载 + 删除 + 演示模式
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { createTask, TASK_TYPES } from '../api/tasks'
import { deleteImage, imageDownloadUrl, latestOutput, listImages, seedImageFromBase64 } from '../api/images'
import BeforeAfterSlider from '../components/BeforeAfterSlider'
import StatusBadge from '../components/StatusBadge'
import ProgressBar from '../components/ProgressBar'
import { STATUS_ORDER } from '../utils/status'
import { formatBytes, formatDateTime, taskTypeLabel } from '../utils/format'

const PAGE_SIZE = 12
const REFRESH_MS = 5000
const DEMO_IMAGES = ['demo1_sunset.jpg', 'demo2_noisy.jpg', 'demo3_pattern.jpg', 'demo4_lowres.jpg']

function fileToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result || '')
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

export default function GalleryView() {
  const [taskType, setTaskType] = useState('all')
  const [status, setStatus] = useState('all')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [preview, setPreview] = useState(null) // image 对象
  const [deleteTarget, setDeleteTarget] = useState(null) // image id（两段确认）
  const [deleting, setDeleting] = useState(false)
  const [demoState, setDemoState] = useState(null) // {step, total, message} | null
  const mounted = useRef(true)

  const load = useCallback(async () => {
    try {
      const data = await listImages({
        taskType: taskType === 'all' ? undefined : taskType,
        status: status === 'all' ? undefined : status,
        limit: PAGE_SIZE,
        offset,
      })
      if (!mounted.current) return
      setItems(Array.isArray(data.items) ? data.items : [])
      setTotal(Number(data.total) || 0)
      setError(null)
    } catch (err) {
      if (mounted.current) setError(err.message || String(err))
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [taskType, status, offset])

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

  const changeFilter = (nextType, nextStatus) => {
    if (nextType !== taskType) setTaskType(nextType)
    if (nextStatus !== status) setStatus(nextStatus)
    setOffset(0)
  }

  const refresh = useCallback(() => {
    setLoading(true)
    load()
  }, [load])

  const runDemo = useCallback(async () => {
    if (demoState) return
    try {
      for (let i = 0; i < DEMO_IMAGES.length; i += 1) {
        const name = DEMO_IMAGES[i]
        setDemoState({ step: i + 1, total: DEMO_IMAGES.length, message: `加载 ${name} …` })
        const res = await fetch(`/demo/${name}`)
        if (!res.ok) throw new Error(`示例图下载失败: /demo/${name}`)
        const blob = await res.blob()
        const dataBase64 = await fileToBase64(blob)
        const image = await seedImageFromBase64({ filename: name, dataBase64 })
        setDemoState({ step: i + 1, total: DEMO_IMAGES.length, message: `${name} 已登记，创建修复任务（经典保底，无需模型）…` })
        await createTask({
          imageIds: [image.id],
          taskType: 'restore',
          params: { output_format: 'jpeg' },
        })
      }
      setDemoState({ step: DEMO_IMAGES.length, total: DEMO_IMAGES.length, message: '示例任务已全部入队 ✓' })
      changeFilter('all', 'all')
      refresh()
      setTimeout(() => {
        if (mounted.current) setDemoState(null)
      }, 2500)
    } catch (err) {
      if (mounted.current) {
        setDemoState(null)
        setError(err.message || String(err))
      }
    }
  }, [demoState, refresh])

  const confirmDelete = useCallback(
    async (imageId) => {
      if (deleting) return
      setDeleting(true)
      try {
        await deleteImage(imageId)
        if (preview && preview.id === imageId) setPreview(null)
        setDeleteTarget(null)
        refresh()
      } catch (err) {
        setError(err.message || String(err))
      } finally {
        setDeleting(false)
      }
    },
    [deleting, preview, refresh],
  )

  const hasMore = items.length >= PAGE_SIZE
  const totalShown = offset + items.length

  return (
    <div className="page" data-testid="gallery-view">
      <div className="page-header">
        <div>
          <h1 className="page-title">对比画廊</h1>
          <div className="page-sub">图片 · 任务 · 前后对比 · 下载与清理</div>
        </div>
        <div className="actions-row">
          <button type="button" className="btn" onClick={runDemo} disabled={!!demoState} data-testid="demo-btn">
            加载示例图并跑通修复
          </button>
          <button type="button" className="btn" onClick={refresh} data-testid="refresh-btn">
            刷新
          </button>
        </div>
      </div>

      {demoState && (
        <div className="notice notice-info" data-testid="demo-progress">
          {demoState.message}（{demoState.step}/{demoState.total}）
        </div>
      )}

      <div className="card">
        <div className="card-title">
          画廊
          <span className="muted">（共 {total} 张 · 每页 {PAGE_SIZE} 张）</span>
        </div>

        <div className="chip-row" role="group" aria-label="任务类型筛选" data-testid="type-filters">
          <button type="button" className={`chip ${taskType === 'all' ? 'active' : ''}`} onClick={() => changeFilter('all', status)}>
            全部类型
          </button>
          {TASK_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              className={`chip ${taskType === t ? 'active' : ''}`}
              onClick={() => changeFilter(t, status)}
              data-testid={`type-${t}`}
            >
              {taskTypeLabel(t)}
            </button>
          ))}
        </div>
        <div className="chip-row" role="group" aria-label="任务状态筛选" data-testid="status-filters">
          <button type="button" className={`chip ${status === 'all' ? 'active' : ''}`} onClick={() => changeFilter(taskType, 'all')}>
            全部状态
          </button>
          {STATUS_ORDER.map((s) => (
            <button
              key={s}
              type="button"
              className={`chip ${status === s ? 'active' : ''}`}
              onClick={() => changeFilter(taskType, s)}
              data-testid={`filter-${s}`}
            >
              {s}
            </button>
          ))}
        </div>

        {error && <div className="notice notice-error" data-testid="gallery-error">{error}</div>}

        {loading && items.length === 0 ? (
          <div className="empty">加载中…</div>
        ) : items.length === 0 ? (
          <div className="empty" data-testid="gallery-empty">
            {total > 0 ? (
              <span>没有符合当前筛选条件的图片，试试切换类型/状态。</span>
            ) : (
              <span>
                画廊还是空的：去 <Link to="/upload">上传</Link> 图片，或点击右上角“加载示例图”。
              </span>
            )}
          </div>
        ) : (
          <div className="gallery-grid" data-testid="gallery-grid">
            {items.map((image) => {
              const output = latestOutput(image)
              return (
                <div className="gallery-card" key={image.id} data-testid={`gallery-card-${image.id}`}>
                  <button type="button" className="gallery-thumb-wrap" onClick={() => setPreview(image)} data-testid={`preview-btn-${image.id}`}>
                    <img className="gallery-thumb" src={imageDownloadUrl(image.id)} alt={image.filename} loading="lazy" />
                  </button>
                  <div className="gallery-card-body">
                    <div className="gallery-name" title={image.filename}>{image.filename}</div>
                    <div className="muted">{formatBytes(image.size_bytes)} · {image.format} · {formatDateTime(image.created_at)}</div>
                    <div className="gallery-tasks">
                      {image.tasks.length === 0 ? (
                        <span className="muted" data-testid={`no-tasks-${image.id}`}>暂无任务</span>
                      ) : (
                        image.tasks.map((task) => (
                          <div className="gallery-task" key={task.id} data-testid={`task-badge-${task.id}`}>
                            <StatusBadge status={task.status} />
                            <Link to={`/tasks/${task.id}`} className="gallery-task-link">{taskTypeLabel(task.task_type)} #{task.id}</Link>
                            {task.status === 'processing' || task.status === 'queued' ? (
                              <ProgressBar progress={task.progress} phase={task.phase} status={task.status} compact />
                            ) : null}
                          </div>
                        ))
                      )}
                    </div>
                    <div className="gallery-actions">
                      <a className="btn btn-small" href={imageDownloadUrl(image.id)} data-testid={`download-original-${image.id}`}>
                        原图
                      </a>
                      {output ? (
                        <a className="btn btn-small" href={output.download_url} data-testid={`download-result-${image.id}`}>
                          结果
                        </a>
                      ) : (
                        <span className="btn btn-small disabled" data-testid={`download-result-${image.id}`}>结果</span>
                      )}
                      <button type="button" className="btn btn-small btn-danger" onClick={() => setDeleteTarget(image.id)} data-testid={`delete-btn-${image.id}`}>
                        {deleteTarget === image.id ? '确认删除' : '删除'}
                      </button>
                    </div>
                    {deleteTarget === image.id && (
                      <div className="delete-confirm" data-testid={`delete-confirm-${image.id}`}>
                        <span className="muted">删除图片及其全部任务与产物？</span>
                        <button type="button" className="btn btn-small btn-danger" onClick={() => confirmDelete(image.id)} disabled={deleting} data-testid={`confirm-delete-${image.id}`}>
                          确认
                        </button>
                        <button type="button" className="btn btn-small" onClick={() => setDeleteTarget(null)} disabled={deleting}>
                          取消
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <div className="pager">
          <span className="pager-info">显示 1–{totalShown} / 共 {total} 张</span>
          <button type="button" className="btn" disabled={offset === 0} onClick={() => setOffset((v) => Math.max(0, v - PAGE_SIZE))}>
            上一页
          </button>
          <button type="button" className="btn" disabled={!hasMore} onClick={() => setOffset((v) => v + PAGE_SIZE)}>
            下一页
          </button>
        </div>
      </div>

      {preview && (
        <div className="modal-backdrop" data-testid="preview-modal" onClick={() => setPreview(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <div className="modal-title">{preview.filename}</div>
                <div className="muted">{formatBytes(preview.size_bytes)} · {preview.format} · {formatDateTime(preview.created_at)}</div>
              </div>
              <button type="button" className="btn btn-small" onClick={() => setPreview(null)} data-testid="preview-close">
                关闭
              </button>
            </div>
            {latestOutput(preview) ? (
              <BeforeAfterSlider
                beforeUrl={imageDownloadUrl(preview.id)}
                afterUrl={latestOutput(preview).download_url}
              />
            ) : (
              <div className="empty" data-testid="preview-no-output">该图片暂无成功产物，无法对比。</div>
            )}
            <div className="modal-footer actions-row">
              <a className="btn btn-small" href={imageDownloadUrl(preview.id)}>下载原图</a>
              {latestOutput(preview) && (
                <a className="btn btn-small" href={latestOutput(preview).download_url}>下载结果</a>
              )}
              <button type="button" className="btn btn-small btn-danger" onClick={() => setDeleteTarget(preview.id)}>
                {deleteTarget === preview.id ? '确认删除' : '删除图片'}
              </button>
              {deleteTarget === preview.id && (
                <button type="button" className="btn btn-small btn-danger" onClick={() => confirmDelete(preview.id)} disabled={deleting}>
                  确认
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
