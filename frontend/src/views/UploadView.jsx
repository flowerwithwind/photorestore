// 上传页：拖拽/多文件 + 客户端预检（类型/大小）+ 登记原图并批量创建任务
// D7：按任务类型渲染参数面板（修复强度/去模糊、×2/×4、上色提示、输出格式与质量）、
//     批量选择（多图同参数原子入队）、最近任务版本展示与重跑入口（同图多版本产物共存）
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import UploadDropzone from '../components/UploadDropzone'
import StatusBadge from '../components/StatusBadge'
import { uploadImage } from '../api/images'
import { createTasksBatch, listTasks, rerunTask, TASK_TYPES } from '../api/tasks'
import { formatDateTime, shortHash, taskTypeLabel } from '../utils/format'
import { isTerminal } from '../utils/status'
import { precheckFiles } from '../utils/validate'

const DEFAULT_FORM = {
  taskType: 'restore',
  scale: '2',
  deblur: false,
  denoiseH: '5',
  outputFormat: 'jpeg',
  quality: '90',
}

const RECENT_LIMIT = 12

function buildParams(taskType, form) {
  const params = {}
  if (form.outputFormat) params.output_format = form.outputFormat
  if (form.quality) params.quality = Number(form.quality)
  if (taskType === 'restore') {
    if (form.deblur) params.deblur = true
    if (form.denoiseH) params.denoise_h = Number(form.denoiseH)
  }
  if (taskType === 'upscale' && form.scale) params.scale = Number(form.scale)
  return params
}

function paramSummary(taskType, params) {
  const parts = []
  if (taskType === 'restore') {
    parts.push(`去噪强度 ${params.denoise_h ?? 5}`)
    parts.push(params.deblur ? '去模糊开' : '去模糊关')
  }
  if (taskType === 'upscale') parts.push(`×${params.scale ?? 2}`)
  if (taskType === 'colorize') parts.push('自动上色')
  if (params.output_format) parts.push(params.output_format.toUpperCase())
  if (params.quality) parts.push(`质量 ${params.quality}`)
  return parts.join(' · ') || '默认参数'
}

export default function UploadView() {
  const navigate = useNavigate()
  const [entries, setEntries] = useState([]) // { index, file, ok, errors, format, sizeBytes, selected }
  const [previews, setPreviews] = useState({})
  const [form, setForm] = useState(DEFAULT_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [created, setCreated] = useState([])
  const [recent, setRecent] = useState([])
  const [rerunningId, setRerunningId] = useState(null)
  const [rerunError, setRerunError] = useState(null)

  const loadRecent = useCallback(async () => {
    try {
      const data = await listTasks({ limit: RECENT_LIMIT })
      setRecent(Array.isArray(data.items) ? data.items : [])
    } catch {
      // 最近任务/版本列表加载失败不影响上传主流程
    }
  }, [])

  useEffect(() => {
    loadRecent()
  }, [loadRecent])

  useEffect(() => {
    const urls = {}
    for (const entry of entries) {
      if (entry.ok && entry.file) urls[entry.index] = URL.createObjectURL(entry.file)
    }
    setPreviews((prev) => ({ ...prev, ...urls }))
    return () => {
      for (const url of Object.values(urls)) URL.revokeObjectURL(url)
    }
  }, [entries])

  const okEntries = useMemo(() => entries.filter((e) => e.ok), [entries])
  const validCount = okEntries.length
  const errorCount = entries.length - validCount
  const selectedCount = useMemo(
    () => okEntries.filter((e) => e.selected !== false).length,
    [okEntries],
  )
  const allSelected = validCount > 0 && selectedCount === validCount

  const handleFiles = (files) => {
    const checked = precheckFiles(files)
    setEntries((prev) => {
      const next = prev.filter((e) => e.ok || e.errors.length > 0)
      const base = next.length > 0 ? Math.max(...next.map((e) => e.index)) + 1 : 0
      const merged = [...next]
      checked.forEach((entry, i) => merged.push({ ...entry, index: base + i, selected: true }))
      return merged
    })
    setSubmitError(null)
    setCreated([])
  }

  const removeEntry = (index) => {
    setEntries((prev) => prev.filter((e) => e.index !== index))
  }

  const toggleEntry = (index) => {
    setEntries((prev) =>
      prev.map((e) => (e.index === index ? { ...e, selected: !(e.selected !== false) } : e)),
    )
  }

  const toggleAll = () => {
    const next = !allSelected
    setEntries((prev) => prev.map((e) => (e.ok ? { ...e, selected: next } : e)))
  }

  const handleSubmit = async () => {
    if (submitting || selectedCount === 0) return
    const selected = okEntries.filter((e) => e.selected !== false)
    setSubmitting(true)
    setSubmitError(null)
    try {
      const imageIds = []
      for (const entry of selected) {
        const image = await uploadImage(entry.file)
        imageIds.push(image.id)
      }
      // D7：多图同参数一次性批量入队（后端先全量校验，任一失败整体失败无残留）
      const res = await createTasksBatch({
        imageIds,
        taskType: form.taskType,
        params: buildParams(form.taskType, form),
      })
      const taskIds = Array.isArray(res.task_ids) ? res.task_ids : []
      setCreated(taskIds)
      setEntries([])
      loadRecent()
      if (taskIds.length > 0) {
        navigate(`/tasks/${taskIds[taskIds.length - 1]}`)
      }
    } catch (err) {
      setSubmitError(err.message || String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRerun = async (task) => {
    if (rerunningId !== null) return
    setRerunningId(task.id)
    setRerunError(null)
    try {
      const res = await rerunTask(task.id)
      // 重跑生成新 task_id（同 params_hash），打开新版本详情
      navigate(`/tasks/${res.task_id}`)
    } catch (err) {
      setRerunError(err.message || String(err))
      setRerunningId(null)
    }
  }

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  // 按图像分组最近任务 → 展示“同图多参数/多次处理”的版本列表
  const versionGroups = useMemo(() => {
    const groups = []
    const byImage = new Map()
    for (const task of recent) {
      for (const imageId of task.image_ids || []) {
        if (!byImage.has(imageId)) {
          const group = { imageId, tasks: [] }
          byImage.set(imageId, group)
          groups.push(group)
        }
        byImage.get(imageId).tasks.push(task)
      }
    }
    return groups
  }, [recent])

  return (
    <div className="page" data-testid="upload-view">
      <div className="page-header">
        <div>
          <h1 className="page-title">上传图片</h1>
          <div className="page-sub">客户端预检（类型/大小）→ 登记原图 → 批量创建处理任务（后端处理需原图已位于 uploads/）</div>
        </div>
      </div>

      <UploadDropzone onFiles={handleFiles} />

      {submitError && <div className="notice notice-error" data-testid="submit-error">{submitError}</div>}
      {created.length > 0 && (
        <div className="notice notice-success" data-testid="created-notice">
          已批量创建 {created.length} 个任务：{created.join('、')}（正在打开最后一个任务详情）
        </div>
      )}

      {entries.length > 0 && (
        <div className="card">
          <div className="card-title">
            待提交文件
            <span className="muted">（{validCount} 个有效 / {errorCount} 个有问题 · 已选 {selectedCount} 个）</span>
            {validCount > 0 && (
              <button type="button" className="chip" onClick={toggleAll} data-testid="select-all-btn">
                {allSelected ? '取消全选' : '全选'}
              </button>
            )}
          </div>
          <div className="file-list" data-testid="file-list">
            {entries.map((entry) => (
              <div className="file-item" key={entry.index} data-testid={`file-item-${entry.index}`} data-ok={entry.ok}>
                {entry.ok && (
                  <label className="checkbox-field">
                    <input
                      type="checkbox"
                      checked={entry.selected !== false}
                      onChange={() => toggleEntry(entry.index)}
                      data-testid={`select-${entry.index}`}
                      aria-label={`选择 ${entry.file.name}`}
                    />
                  </label>
                )}
                {previews[entry.index] && (
                  <img className="file-thumb" src={previews[entry.index]} alt={entry.file.name} />
                )}
                <div className="file-info">
                  <div className="file-name">{entry.file.name}</div>
                  <div className="muted">
                    {entry.format} · {(entry.sizeBytes / 1024).toFixed(1)} KB
                    {entry.ok ? ' · 通过预检' : ` · ${entry.errors.join('；')}`}
                  </div>
                </div>
                <button type="button" className="btn" onClick={() => removeEntry(entry.index)}>移除</button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-title">任务参数</div>
        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="task-type">任务类型</label>
            <select id="task-type" className="select" value={form.taskType} onChange={(e) => setField('taskType', e.target.value)} data-testid="task-type">
              {TASK_TYPES.map((t) => (
                <option key={t} value={t}>{taskTypeLabel(t)}（{t}）</option>
              ))}
            </select>
          </div>

          {form.taskType === 'restore' && (
            <>
              <div className="field">
                <label className="field-label" htmlFor="denoise-h">修复强度（denoise_h）</label>
                <select id="denoise-h" className="select" value={form.denoiseH} onChange={(e) => setField('denoiseH', e.target.value)} data-testid="denoise-h">
                  <option value="3">弱（3）</option>
                  <option value="5">中（5）</option>
                  <option value="8">强（8）</option>
                </select>
              </div>
              <label className="checkbox-field">
                <input type="checkbox" checked={form.deblur} onChange={(e) => setField('deblur', e.target.checked)} data-testid="deblur" />
                同时去模糊（Wiener deconvolution）
              </label>
            </>
          )}

          {form.taskType === 'upscale' && (
            <div className="field">
              <label className="field-label" htmlFor="scale">放大倍数</label>
              <select id="scale" className="select" value={form.scale} onChange={(e) => setField('scale', e.target.value)} data-testid="scale">
                <option value="2">×2</option>
                <option value="4">×4</option>
              </select>
            </div>
          )}

          {form.taskType === 'colorize' && (
            <div className="field">
              <label className="field-label" htmlFor="colorize-hint">上色开关</label>
              <div className="muted" id="colorize-hint" data-testid="colorize-hint">
                黑白照片自动上色（DDColor ONNX / 等价替代模型，无需额外参数）
              </div>
            </div>
          )}

          <div className="field">
            <label className="field-label" htmlFor="output-format">输出格式</label>
            <select id="output-format" className="select" value={form.outputFormat} onChange={(e) => setField('outputFormat', e.target.value)} data-testid="output-format">
              <option value="jpeg">JPEG</option>
              <option value="png">PNG</option>
              <option value="webp">WebP</option>
            </select>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="quality">输出质量</label>
            <select id="quality" className="select" value={form.quality} onChange={(e) => setField('quality', e.target.value)} data-testid="quality">
              <option value="80">80（体积优先）</option>
              <option value="90">90（推荐）</option>
              <option value="95">95（质量优先）</option>
            </select>
          </div>
        </div>

        <div className="muted" data-testid="batch-hint" style={{ marginTop: 8 }}>
          批量入队：选中的 {selectedCount} 张图片将使用同一参数一次性创建任务（原子提交，任一校验失败则整体不创建）；同一图片多次处理会生成多版本产物，互不覆盖。
        </div>

        <div className="actions-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={submitting || selectedCount === 0}
            onClick={handleSubmit}
            data-testid="submit-btn"
          >
            {submitting ? '提交中…' : `批量创建 ${selectedCount} 个任务`}
          </button>
          <Link className="btn" to="/">返回工作台</Link>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          最近任务与版本（重跑入口）
          <span className="muted">（同图不同参数 / 多次处理 → 多版本产物共存，互不覆盖）</span>
        </div>
        {rerunError && <div className="notice notice-error" data-testid="rerun-error">{rerunError}</div>}
        {versionGroups.length === 0 ? (
          <div className="empty" data-testid="recent-empty">暂无历史任务，提交后此处展示版本与重跑入口</div>
        ) : (
          versionGroups.map((group) => (
            <div key={group.imageId} className="version-group" data-testid={`version-group-${group.imageId}`}>
              <div className="muted" style={{ margin: '10px 0 6px', fontWeight: 600 }}>
                图像 #{group.imageId} · {group.tasks.length} 个版本
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>任务</th>
                    <th>类型</th>
                    <th>参数</th>
                    <th>哈希</th>
                    <th>状态</th>
                    <th>创建时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {group.tasks.map((task) => (
                    <tr key={task.id} data-testid={`recent-task-${task.id}`}>
                      <td>#{task.id}</td>
                      <td>{taskTypeLabel(task.task_type)}</td>
                      <td className="muted">{paramSummary(task.task_type, task.params || {})}</td>
                      <td className="muted">{shortHash(task.params_hash)}</td>
                      <td><StatusBadge status={task.status} /></td>
                      <td className="muted">{formatDateTime(task.created_at)}</td>
                      <td>
                        <Link className="btn" to={`/tasks/${task.id}`}>详情</Link>{' '}
                        {isTerminal(task.status) ? (
                          <button
                            type="button"
                            className="btn"
                            disabled={rerunningId !== null}
                            onClick={() => handleRerun(task)}
                            data-testid={`rerun-${task.id}`}
                          >
                            {rerunningId === task.id ? '重跑中…' : '重跑'}
                          </button>
                        ) : (
                          <span className="muted">进行中</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
