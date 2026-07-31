// 视图冒烟测试：工作台 / 上传 / 任务详情 三个页面可挂载渲染（API 全部 mock）
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import DashboardView from './DashboardView'
import UploadView from './UploadView'
import TaskDetailView from './TaskDetailView'

// jsdom 无 canvas，ECharts 以 no-op 桩替换（StorageStats 仍可挂载）
vi.mock('echarts', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  })),
}))

vi.mock('../api/storage', () => ({
  getStorageStats: vi.fn().mockResolvedValue({
    uploads: { count: 0, bytes: 0 },
    outputs: { count: 0, bytes: 0 },
  }),
}))

vi.mock('../api/tasks', () => ({
  TASK_TYPES: ['restore', 'upscale', 'colorize'],
  listTasks: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  createTask: vi.fn(),
  cancelTask: vi.fn().mockResolvedValue({}),
  getTaskDetail: vi.fn(),
  taskEventsUrl: vi.fn((id) => `/api/tasks/${id}/events`),
  outputDownloadUrl: vi.fn((id, index) => `/api/tasks/${id}/outputs/${index}/download`),
}))

vi.mock('../hooks/useTaskEvents', () => ({
  useTaskEvents: () => ({
    task: {
      id: 1,
      task_type: 'restore',
      status: 'processing',
      progress: 45,
      phase: 'infer',
      params: { output_format: 'jpeg' },
      params_hash: 'aabbccdd11223344',
      error: null,
      result: {
        model: 'classic-restore',
        outputs: [
          {
            filename: 'img7_paabbccdd_t1.jpeg',
            download_url: '/api/tasks/1/outputs/0/download',
            format: 'jpeg',
            width: 800,
            height: 600,
            size_bytes: 1024,
            input_width: 800,
            input_height: 600,
            input_size_bytes: 2048,
            input_format: 'png',
            model: 'classic-restore',
          },
        ],
      },
      created_at: '2026-08-01T09:00:00',
      started_at: '2026-08-01T09:00:01',
      finished_at: null,
      image_ids: [7],
    },
    phaseLogs: [
      { id: 1, phase: 'decode', started_at: '2026-08-01T09:00:01', finished_at: '2026-08-01T09:00:02', duration_ms: 800 },
    ],
    source: 'sse',
    connected: true,
    retries: 0,
    error: null,
  }),
}))

describe('view smoke tests', () => {
  it('renders dashboard with empty state', async () => {
    render(
      <MemoryRouter>
        <DashboardView />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('dashboard-view')).toBeInTheDocument()
    expect(await screen.findByText(/暂无任务/)).toBeInTheDocument()
  })

  it('renders upload page with dropzone and task params form', () => {
    render(
      <MemoryRouter>
        <UploadView />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('upload-view')).toBeInTheDocument()
    expect(screen.getByTestId('upload-dropzone')).toBeInTheDocument()
    expect(screen.getByTestId('task-type')).toBeInTheDocument()
    expect(screen.getByTestId('submit-btn')).toBeDisabled()
  })

  it('renders task detail with timeline, cancel button and output download link', () => {
    render(
      <MemoryRouter>
        <TaskDetailView />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('task-detail-view')).toBeInTheDocument()
    expect(screen.getByTestId('status-badge')).toHaveAttribute('data-status', 'processing')
    expect(screen.getByTestId('phase-timeline')).toBeInTheDocument()
    expect(screen.getByTestId('cancel-btn')).toBeInTheDocument()
    expect(screen.getByTestId('download-0')).toHaveAttribute('href', '/api/tasks/1/outputs/0/download')
  })
})
