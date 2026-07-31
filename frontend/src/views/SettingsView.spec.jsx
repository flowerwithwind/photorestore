// 设置页冒烟测试：模型表格 / 下载指引 / 并发保存 / 一键清理（API 与 ECharts 全部 mock，D8）
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { cleanupStorage } from '../api/storage'
import { saveSettings } from '../api/models'
import SettingsView from './SettingsView'

vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
}))

vi.mock('../api/models', () => ({
  getModels: vi.fn().mockResolvedValue({
    models_dir: '/repo/models',
    items: [
      {
        key: 'restore',
        name: '去噪去模糊',
        engine: 'classic+realesrgan',
        required: false,
        files: [{ name: 'realesrgan-x4.onnx', exists: true, size_bytes: 2048 }],
        total_bytes: 2048,
        missing: [],
        ready: true,
        download_hint: 'python scripts/download_models.py --only restore',
      },
      {
        key: 'upscale',
        name: '超分辨率',
        engine: 'realesrgan',
        required: true,
        files: [
          { name: 'realesrgan-x2.onnx', exists: false, size_bytes: 0 },
          { name: 'realesrgan-x4.onnx', exists: true, size_bytes: 2048 },
        ],
        total_bytes: 2048,
        missing: ['realesrgan-x2.onnx'],
        ready: false,
        download_hint: 'python scripts/download_models.py --only upscale',
      },
    ],
    summary: { total: 2, ready: 1, missing: 1, total_bytes: 4096 },
  }),
  getSettings: vi.fn().mockResolvedValue({
    worker_concurrency: 2,
    source: 'env',
    persisted: null,
    max_upload_bytes: 20971520,
  }),
  saveSettings: vi.fn().mockResolvedValue({
    worker_concurrency: 4,
    saved: true,
    note: '已保存到配置，重启后端后生效',
  }),
}))

vi.mock('../api/storage', () => ({
  getStorageStats: vi.fn().mockResolvedValue({
    uploads: { count: 3, bytes: 300 },
    outputs: { count: 1, bytes: 100 },
    total: { count: 4, bytes: 400 },
  }),
  cleanupStorage: vi.fn().mockResolvedValue({
    dry_run: false,
    scope: 'all',
    count: 4,
    freed_bytes: 400,
    deleted: [],
  }),
}))

describe('SettingsView', () => {
  it('renders model table with ready/missing badges', async () => {
    render(<SettingsView />)
    expect(screen.getByTestId('settings-view')).toBeInTheDocument()
    expect(await screen.findByTestId('model-row-restore')).toBeInTheDocument()
    expect(screen.getByTestId('model-row-upscale')).toBeInTheDocument()
    expect(screen.getByTestId('model-status-restore')).toHaveAttribute('data-ready', 'true')
    expect(screen.getByTestId('model-status-upscale')).toHaveAttribute('data-ready', 'false')
    expect(screen.getByTestId('models-summary')).toHaveTextContent('就绪 1/2')
  })

  it('shows download hint with the documented command', async () => {
    render(<SettingsView />)
    fireEvent.click(await screen.findByTestId('download-btn-upscale'))
    expect(screen.getByTestId('download-hint')).toBeInTheDocument()
    expect(screen.getByTestId('download-command')).toHaveTextContent('python scripts/download_models.py --only upscale')
  })

  it('saves concurrency and shows success notice', async () => {
    render(<SettingsView />)
    const input = await screen.findByTestId('concurrency-input')
    expect(input).toHaveValue(2)
    fireEvent.change(input, { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('save-concurrency-btn'))
    expect(await screen.findByTestId('settings-notice')).toBeInTheDocument()
    expect(saveSettings).toHaveBeenCalledWith({ worker_concurrency: 4 })
  })

  it('cleans storage after confirmation and shows result', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<SettingsView />)
    fireEvent.click(await screen.findByTestId('cleanup-btn'))
    expect(cleanupStorage).toHaveBeenCalledWith({ scope: 'all', max_count: 0, dry_run: false })
    expect(await screen.findByTestId('cleanup-result')).toHaveTextContent('已清理 4 个文件')
  })
})
