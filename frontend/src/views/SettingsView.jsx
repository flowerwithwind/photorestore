// 设置页：模型管理（就绪状态/体积/下载指引）、并发数配置、存储占用与一键清理（D8）
import { useCallback, useEffect, useState } from 'react'
import { getModels, getSettings, saveSettings } from '../api/models'
import { cleanupStorage, getStorageStats } from '../api/storage'
import StorageStats from '../components/StorageStats'
import { formatBytes } from '../utils/format'

export default function SettingsView() {
  const [models, setModels] = useState(null)
  const [modelsError, setModelsError] = useState(null)
  const [settings, setSettings] = useState(null)
  const [concurrency, setConcurrency] = useState('')
  const [settingsNotice, setSettingsNotice] = useState(null)
  const [settingsError, setSettingsError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [stats, setStats] = useState(null)
  const [statsVersion, setStatsVersion] = useState(0)
  const [cleaning, setCleaning] = useState(false)
  const [cleanupResult, setCleanupResult] = useState(null)
  const [cleanupError, setCleanupError] = useState(null)
  const [hintKey, setHintKey] = useState(null)

  const loadStats = useCallback(async () => {
    try {
      const data = await getStorageStats()
      setStats(data)
    } catch (err) {
      setCleanupError(err.message || String(err))
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    getModels()
      .then((data) => {
        if (!cancelled) setModels(data)
      })
      .catch((err) => {
        if (!cancelled) setModelsError(err.message || String(err))
      })
    getSettings()
      .then((data) => {
        if (cancelled) return
        setSettings(data)
        setConcurrency(String(data.worker_concurrency ?? ''))
      })
      .catch((err) => {
        if (!cancelled) setSettingsError(err.message || String(err))
      })
    loadStats()
    return () => {
      cancelled = true
    }
  }, [loadStats])

  const handleSaveConcurrency = async () => {
    const value = Number(concurrency)
    if (!Number.isInteger(value) || value < 1 || value > 64) {
      setSettingsError('并发数需为 1~64 的整数')
      return
    }
    setSaving(true)
    setSettingsError(null)
    setSettingsNotice(null)
    try {
      const data = await saveSettings({ worker_concurrency: value })
      setSettingsNotice(data.note || '已保存到配置，重启后端后生效')
      setSettings((prev) => ({
        ...(prev || {}),
        worker_concurrency: value,
        source: 'db',
        persisted: value,
      }))
    } catch (err) {
      setSettingsError(err.message || String(err))
    } finally {
      setSaving(false)
    }
  }

  const handleCleanup = async () => {
    if (cleaning) return
    const ok = window.confirm('确认一键清理？将删除 uploads/ 与 outputs/ 下的全部文件（原图与产物），任务记录与模型文件不受影响。')
    if (!ok) return
    setCleaning(true)
    setCleanupError(null)
    setCleanupResult(null)
    try {
      const data = await cleanupStorage({ scope: 'all', max_count: 0, dry_run: false })
      setCleanupResult({ count: data.count, freedBytes: data.freed_bytes })
      setStatsVersion((v) => v + 1)
      await loadStats()
    } catch (err) {
      setCleanupError(err.message || String(err))
    } finally {
      setCleaning(false)
    }
  }

  const summary = models?.summary
  const hintItem = hintKey === 'all' ? null : models?.items?.find((item) => item.key === hintKey)
  const hintCommand = hintKey === 'all' ? 'python scripts/download_models.py' : hintItem?.download_hint
  const hintTitle = hintKey === 'all' ? '全部模型' : hintItem?.name

  return (
    <div className="page" data-testid="settings-view">
      <div className="page-header">
        <div>
          <h1 className="page-title">设置</h1>
          <div className="page-sub">模型管理 · 并发配置 · 存储维护</div>
        </div>
      </div>

      <section className="card">
        <div className="card-title">
          模型管理
          <span className="muted">（状态 / 版本文件 / 体积 / 就绪）</span>
        </div>
        {modelsError ? (
          <div className="notice notice-error" data-testid="models-error">{modelsError}</div>
        ) : !models ? (
          <div className="empty">加载中…</div>
        ) : (
          <>
            <div className="chip-row" data-testid="models-summary">
              <span className="chip active">就绪 {summary.ready}/{summary.total}</span>
              <span className="chip">总大小 {formatBytes(summary.total_bytes)}</span>
              <span className="chip mono">{models.models_dir}</span>
              <button
                type="button"
                className="btn"
                onClick={() => setHintKey(hintKey === 'all' ? null : 'all')}
                data-testid="download-all-btn"
              >
                下载全部模型
              </button>
            </div>
            <table className="table" data-testid="models-table">
              <thead>
                <tr>
                  <th>任务类型</th>
                  <th>引擎</th>
                  <th>模型文件</th>
                  <th>体积</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {models.items.map((item) => (
                  <tr key={item.key} data-testid={`model-row-${item.key}`}>
                    <td>
                      {item.name}
                      <div className="muted">{item.key}{item.required ? '（必需）' : '（可选）'}</div>
                    </td>
                    <td className="muted">{item.engine}</td>
                    <td>
                      {item.files.map((file) => (
                        <div key={file.name} className="muted" data-file={file.name} data-exists={file.exists}>
                          {file.exists ? '✓' : '✗'} {file.name}
                          <span className="mono"> {file.exists ? formatBytes(file.size_bytes) : '（缺失）'}</span>
                        </div>
                      ))}
                    </td>
                    <td>{formatBytes(item.total_bytes)}</td>
                    <td>
                      {item.ready ? (
                        <span className="badge badge-succeeded" data-testid={`model-status-${item.key}`} data-ready="true">
                          就绪
                        </span>
                      ) : (
                        <span className="badge badge-failed" data-testid={`model-status-${item.key}`} data-ready="false">
                          缺失{item.required ? '（必需）' : ''}
                        </span>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => setHintKey(hintKey === item.key ? null : item.key)}
                        data-testid={`download-btn-${item.key}`}
                      >
                        下载模型
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {hintKey && (
              <div className="notice notice-info" data-testid="download-hint">
                在仓库根目录执行以下命令下载{hintTitle ?? ''}模型（下载完成后无需重启，缺失模型自动就绪）：
                <pre className="params-pre" data-testid="download-command">{hintCommand}</pre>
              </div>
            )}
          </>
        )}
      </section>

      <section className="card">
        <div className="card-title">并发设置</div>
        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="concurrency-input">并发任务数（1~64）</label>
            <input
              id="concurrency-input"
              className="input"
              type="number"
              min="1"
              max="64"
              value={concurrency}
              onChange={(e) => setConcurrency(e.target.value)}
              data-testid="concurrency-input"
            />
          </div>
          <div className="field">
            <span className="field-label">当前生效</span>
            <div data-testid="concurrency-effective">
              {settings
                ? `${settings.worker_concurrency}（来源：${settings.source === 'db' ? '已保存配置' : '环境变量 PHOTORESTORE_CONCURRENCY'}）`
                : '—'}
            </div>
          </div>
        </div>
        <div className="actions-row">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSaveConcurrency}
            disabled={saving}
            data-testid="save-concurrency-btn"
          >
            {saving ? '保存中…' : '保存并发数'}
          </button>
        </div>
        {settingsError && <div className="notice notice-error" data-testid="settings-error">{settingsError}</div>}
        {settingsNotice && <div className="notice notice-success" data-testid="settings-notice">{settingsNotice}</div>}
        <div className="muted">
          说明：保存后写入配置（settings 表），重启后端后生效；未保存时使用环境变量 PHOTORESTORE_CONCURRENCY（默认 1）。
        </div>
      </section>

      <section className="card">
        <div className="card-title">存储占用与清理</div>
        <div className="dashboard-grid">
          <StorageStats key={statsVersion} />
        </div>
        {stats && (
          <dl className="kv" data-testid="storage-numbers">
            <dt>原图 uploads</dt>
            <dd>{stats.uploads?.count ?? 0} 个 · {formatBytes(stats.uploads?.bytes)}</dd>
            <dt>产物 outputs</dt>
            <dd>{stats.outputs?.count ?? 0} 个 · {formatBytes(stats.outputs?.bytes)}</dd>
            <dt>合计</dt>
            <dd>{stats.total?.count ?? 0} 个 · {formatBytes(stats.total?.bytes)}</dd>
          </dl>
        )}
        <div className="actions-row">
          <button
            type="button"
            className="btn btn-danger"
            onClick={handleCleanup}
            disabled={cleaning}
            data-testid="cleanup-btn"
          >
            {cleaning ? '清理中…' : '一键清理缓存与产物'}
          </button>
        </div>
        {cleanupResult && (
          <div className="notice notice-success" data-testid="cleanup-result">
            已清理 {cleanupResult.count} 个文件，释放 {formatBytes(cleanupResult.freedBytes)}
          </div>
        )}
        {cleanupError && <div className="notice notice-error" data-testid="cleanup-error">{cleanupError}</div>}
        <div className="muted">
          一键清理将删除 uploads/ 与 outputs/ 下的全部文件（含原图与产物），任务记录与模型文件不受影响；删除前需二次确认。
        </div>
      </section>
    </div>
  )
}
