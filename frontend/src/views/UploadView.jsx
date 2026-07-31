// 上传页：拖拽/多文件 + 客户端预检（类型/大小）+ 登记原图并批量创建任务
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import UploadDropzone from '../components/UploadDropzone'
import { registerImage } from '../api/images'
import { createTask, TASK_TYPES } from '../api/tasks'
import { taskTypeLabel } from '../utils/format'
import { precheckFiles } from '../utils/validate'

const DEFAULT_FORM = {
  taskType: 'restore',
  scale: '2',
  deblur: false,
  denoiseH: '5',
  outputFormat: 'jpeg',
  quality: '90',
}

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

export default function UploadView() {
  const navigate = useNavigate()
  const [entries, setEntries] = useState([]) // { index, file, ok, errors, format, sizeBytes }
  const [previews, setPreviews] = useState({})
  const [form, setForm] = useState(DEFAULT_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [created, setCreated] = useState([])

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

  const validCount = useMemo(() => entries.filter((e) => e.ok).length, [entries])
  const errorCount = entries.length - validCount

  const handleFiles = (files) => {
    const checked = precheckFiles(files)
    setEntries((prev) => {
      const next = prev.filter((e) => e.ok || e.errors.length > 0)
      const base = next.length > 0 ? Math.max(...next.map((e) => e.index)) + 1 : 0
      const merged = [...next]
      checked.forEach((entry, i) => merged.push({ ...entry, index: base + i }))
      return merged
    })
    setSubmitError(null)
    setCreated([])
  }

  const removeEntry = (index) => {
    setEntries((prev) => prev.filter((e) => e.index !== index))
  }

  const handleSubmit = async () => {
    if (submitting || validCount === 0) return
    setSubmitting(true)
    setSubmitError(null)
    const createdIds = []
    try {
      for (const entry of entries) {
        if (!entry.ok) continue
        const image = await registerImage({
          filename: entry.file.name,
          sizeBytes: entry.file.size,
          format: entry.format,
        })
        const task = await createTask({
          imageIds: [image.id],
          taskType: form.taskType,
          params: buildParams(form.taskType, form),
        })
        createdIds.push(task.task_id)
      }
      setCreated(createdIds)
      setEntries([])
      if (createdIds.length > 0) {
        navigate(`/tasks/${createdIds[createdIds.length - 1]}`)
      }
    } catch (err) {
      setSubmitError(err.message || String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  return (
    <div className="page" data-testid="upload-view">
      <div className="page-header">
        <div>
          <h1 className="page-title">上传图片</h1>
          <div className="page-sub">客户端预检（类型/大小）→ 登记原图 → 创建处理任务（后端处理需原图已位于 uploads/）</div>
        </div>
      </div>

      <UploadDropzone onFiles={handleFiles} />

      {submitError && <div className="notice notice-error" data-testid="submit-error">{submitError}</div>}
      {created.length > 0 && (
        <div className="notice notice-success" data-testid="created-notice">
          已创建 {created.length} 个任务：{created.join('、')}（正在打开最后一个任务详情）
        </div>
      )}

      {entries.length > 0 && (
        <div className="card">
          <div className="card-title">
            待提交文件
            <span className="muted">（{validCount} 个有效 / {errorCount} 个有问题）</span>
          </div>
          <div className="file-list" data-testid="file-list">
            {entries.map((entry) => (
              <div className="file-item" key={entry.index} data-testid={`file-item-${entry.index}`} data-ok={entry.ok}>
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
                <label className="field-label" htmlFor="denoise-h">去噪强度（denoise_h）</label>
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
            <div className="muted">黑白照片自动上色（DDColor ONNX / 等价替代模型，无额外参数）</div>
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

        <div className="actions-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={submitting || validCount === 0}
            onClick={handleSubmit}
            data-testid="submit-btn"
          >
            {submitting ? '提交中…' : `创建 ${validCount} 个任务`}
          </button>
          <Link className="btn" to="/">返回工作台</Link>
        </div>
      </div>
    </div>
  )
}
