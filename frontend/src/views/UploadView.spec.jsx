// 上传页 D7 测试：参数面板/批量选择/批量原子入队/最近任务版本与重跑入口
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UploadView from './UploadView'
import { createTasksBatch, listTasks, rerunTask } from '../api/tasks'
import { registerImage } from '../api/images'

vi.mock('../api/images', () => ({
  registerImage: vi.fn().mockResolvedValue({ id: 101 }),
}))

vi.mock('../api/tasks', () => ({
  TASK_TYPES: ['restore', 'upscale', 'colorize'],
  listTasks: vi.fn().mockResolvedValue({
    items: [
      {
        id: 7,
        task_type: 'restore',
        status: 'succeeded',
        progress: 100,
        phase: 'save',
        params: { denoise_h: 5, output_format: 'png' },
        params_hash: 'aabbccdd11223344',
        created_at: '2026-08-01T09:00:00',
        image_ids: [11],
        result: null,
      },
    ],
    total: 1,
  }),
  createTasksBatch: vi.fn().mockResolvedValue({ task_ids: [7], count: 1, status: 'queued' }),
  rerunTask: vi.fn().mockResolvedValue({ task_id: 8, status: 'queued', source_task_id: 7 }),
  createTask: vi.fn(),
  cancelTask: vi.fn(),
  getTaskDetail: vi.fn(),
  taskEventsUrl: vi.fn(),
  outputDownloadUrl: vi.fn(),
}))

function renderUpload() {
  return render(
    <MemoryRouter>
      <UploadView />
    </MemoryRouter>,
  )
}

function makePngFile(name = 'photo.png') {
  const file = new File(['x'], name, { type: 'image/png' })
  Object.defineProperty(file, 'size', { value: 2048 })
  return file
}

describe('UploadView D7', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // jsdom 未实现 object URL，预览缩略图使用桩
    URL.createObjectURL = vi.fn(() => 'blob:mock-preview')
    URL.revokeObjectURL = vi.fn()
  })

  it('renders per-task-type param panel with batch hint', () => {
    renderUpload()
    expect(screen.getByTestId('task-type')).toBeInTheDocument()
    expect(screen.getByTestId('denoise-h')).toBeInTheDocument()
    expect(screen.getByTestId('deblur')).toBeInTheDocument()
    expect(screen.getByTestId('output-format')).toBeInTheDocument()
    expect(screen.getByTestId('quality')).toBeInTheDocument()
    expect(screen.getByTestId('batch-hint')).toBeInTheDocument()
    expect(screen.getByTestId('submit-btn')).toBeDisabled()
  })

  it('switches param panel to upscale ×2/×4 and colorize hint', () => {
    renderUpload()
    fireEvent.change(screen.getByTestId('task-type'), { target: { value: 'upscale' } })
    expect(screen.getByTestId('scale')).toBeInTheDocument()
    expect(screen.queryByTestId('denoise-h')).not.toBeInTheDocument()
    fireEvent.change(screen.getByTestId('task-type'), { target: { value: 'colorize' } })
    expect(screen.getByTestId('colorize-hint')).toBeInTheDocument()
  })

  it('submits selected files via batch API with one shared param set', async () => {
    renderUpload()
    const input = screen.getByTestId('dropzone-input')
    fireEvent.change(input, { target: { files: [makePngFile('a.png'), makePngFile('b.png')] } })
    expect(screen.getByTestId('file-item-0')).toBeInTheDocument()
    expect(screen.getByTestId('file-item-1')).toBeInTheDocument()
    expect(screen.getByTestId('select-all-btn')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('denoise-h'), { target: { value: '8' } })
    fireEvent.click(screen.getByTestId('submit-btn'))

    await waitFor(() => expect(registerImage).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(createTasksBatch).toHaveBeenCalledWith({
        imageIds: [101, 101],
        taskType: 'restore',
        params: { denoise_h: 8, output_format: 'jpeg', quality: 90 },
      }),
    )
    expect(await screen.findByTestId('created-notice')).toBeInTheDocument()
  })

  it('unchecking an entry excludes it from the batch', async () => {
    renderUpload()
    const input = screen.getByTestId('dropzone-input')
    fireEvent.change(input, { target: { files: [makePngFile('a.png'), makePngFile('b.png')] } })
    fireEvent.click(screen.getByTestId('select-0'))
    fireEvent.click(screen.getByTestId('submit-btn'))
    await waitFor(() =>
      expect(createTasksBatch).toHaveBeenCalledWith({
        imageIds: [101],
        taskType: 'restore',
        params: { denoise_h: 5, output_format: 'jpeg', quality: 90 },
      }),
    )
  })

  it('groups recent tasks by image and shows rerun entry for terminal tasks', async () => {
    renderUpload()
    expect(await screen.findByTestId('version-group-11')).toBeInTheDocument()
    expect(screen.getByTestId('recent-task-7')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('rerun-7'))
    await waitFor(() => expect(rerunTask).toHaveBeenCalledWith(7))
    expect(screen.getByTestId('rerun-7')).toBeDisabled() // 重跑中防重复点击
  })

  it('shows empty state when no recent tasks', async () => {
    listTasks.mockResolvedValueOnce({ items: [], total: 0 })
    renderUpload()
    expect(await screen.findByTestId('recent-empty')).toBeInTheDocument()
  })
})
