// D6 画廊视图测试：筛选 / 下载链接 / 删除两段确认 / 预览 / 演示模式 / 空态
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GalleryView from './GalleryView'

// 保留真实 imageDownloadUrl / latestOutput，仅替换网络行为
vi.mock('../api/images', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    listImages: vi.fn(),
    deleteImage: vi.fn(),
    seedImageFromBase64: vi.fn(),
  }
})

vi.mock('../api/tasks', () => ({
  TASK_TYPES: ['restore', 'upscale', 'colorize'],
  createTask: vi.fn(),
}))

import { deleteImage, listImages, seedImageFromBase64 } from '../api/images'
import { createTask } from '../api/tasks'

function sampleImage(id, { taskStatus = 'succeeded', taskType = 'restore', outputs = null } = {}) {
  const output =
    outputs === null
      ? [
          {
            filename: `out_${id}.jpeg`,
            download_url: `/api/tasks/${100 + id}/outputs/0/download`,
            format: 'jpeg',
            width: 800,
            height: 600,
            size_bytes: 1024,
          },
        ]
      : outputs
  return {
    id,
    filename: `photo_${id}.png`,
    format: 'png',
    size_bytes: 2048,
    created_at: '2026-08-01T09:00:00',
    tasks: [
      {
        id: 100 + id,
        task_type: taskType,
        status: taskStatus,
        progress: 100,
        phase: 'save',
        params_hash: 'aabbccdd11223344',
        result: outputs === null || outputs.length > 0 ? { model: 'classic-restore', outputs: output } : null,
      },
    ],
  }
}

function renderGallery() {
  return render(
    <MemoryRouter>
      <GalleryView />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  listImages.mockResolvedValue({ items: [], total: 0 })
  deleteImage.mockResolvedValue({ deleted: true, image_id: 1 })
  seedImageFromBase64.mockImplementation(async ({ filename }) => ({ id: Number(filename.replace(/\D/g, '')) || 42 }))
  createTask.mockResolvedValue({ task_id: 900, status: 'queued' })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('GalleryView', () => {
  it('渲染画廊网格：卡片 / 任务徽章 / 原图与结果下载链接', async () => {
    listImages.mockResolvedValue({ items: [sampleImage(1), sampleImage(2)], total: 2 })
    renderGallery()
    expect(await screen.findByTestId('gallery-card-1')).toBeInTheDocument()
    expect(screen.getByTestId('gallery-card-2')).toBeInTheDocument()
    expect(screen.getByTestId('gallery-grid')).toBeInTheDocument()

    // 原图下载链接指向 /api/images/{id}/download
    expect(screen.getByTestId('download-original-1')).toHaveAttribute('href', '/api/images/1/download')
    // 结果下载链接复用 D4 产物下载契约
    expect(screen.getByTestId('download-result-1')).toHaveAttribute('href', '/api/tasks/101/outputs/0/download')
    // 任务徽章 + 详情链接
    const taskBadge = screen.getByTestId('task-badge-101')
    expect(taskBadge).toBeInTheDocument()
    expect(within(taskBadge).getByTestId('status-badge')).toHaveAttribute('data-status', 'succeeded')
    expect(screen.getByRole('link', { name: /修复 #101/ })).toHaveAttribute('href', '/tasks/101')
  })

  it('筛选：点类型/状态 chip 时以对应参数重新请求', async () => {
    listImages.mockResolvedValue({ items: [sampleImage(1)], total: 1 })
    renderGallery()
    await screen.findByTestId('gallery-card-1')
    listImages.mockClear()

    fireEvent.click(screen.getByTestId('type-restore'))
    await waitFor(() => {
      expect(listImages).toHaveBeenCalledWith(
        expect.objectContaining({ taskType: 'restore', limit: 12, offset: 0 }),
      )
    })

    listImages.mockClear()
    fireEvent.click(screen.getByTestId('filter-failed'))
    await waitFor(() => {
      expect(listImages).toHaveBeenCalledWith(
        expect.objectContaining({ taskType: 'restore', status: 'failed', offset: 0 }),
      )
    })
  })

  it('无结果图片时结果下载按钮禁用（不可点链接）', async () => {
    listImages.mockResolvedValue({ items: [sampleImage(1, { outputs: [] })], total: 1 })
    renderGallery()
    await screen.findByTestId('download-result-1')
    expect(screen.getByTestId('download-result-1')).not.toHaveAttribute('href')
  })

  it('删除：两段确认后调用 DELETE 并刷新列表', async () => {
    listImages.mockResolvedValue({ items: [sampleImage(1)], total: 1 })
    renderGallery()
    await screen.findByTestId('gallery-card-1')
    listImages.mockClear()

    fireEvent.click(screen.getByTestId('delete-btn-1'))
    expect(screen.getByTestId('delete-confirm-1')).toBeInTheDocument()
    expect(deleteImage).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('confirm-delete-1'))
    await waitFor(() => expect(deleteImage).toHaveBeenCalledWith(1))
    await waitFor(() => expect(listImages).toHaveBeenCalled())
  })

  it('空态：无图片时展示引导（含上传链接）', async () => {
    listImages.mockResolvedValue({ items: [], total: 0 })
    renderGallery()
    expect(await screen.findByTestId('gallery-empty')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '上传' })).toHaveAttribute('href', '/upload')
  })

  it('预览：有产物时打开对比滑块，无产物时显示空态提示', async () => {
    listImages.mockResolvedValue({ items: [sampleImage(1), sampleImage(2, { outputs: [] })], total: 2 })
    renderGallery()
    fireEvent.click(await screen.findByTestId('preview-btn-1'))
    expect(screen.getByTestId('preview-modal')).toBeInTheDocument()
    expect(screen.getByTestId('slider-stage')).toHaveAttribute('data-mode', 'slider')

    fireEvent.click(screen.getByTestId('preview-close'))
    fireEvent.click(screen.getByTestId('preview-btn-2'))
    expect(screen.getByTestId('preview-no-output')).toBeInTheDocument()
  })

  it('演示模式：依次登记示例图并创建 restore 任务（经典保底）', async () => {
    listImages.mockResolvedValue({ items: [], total: 0 })
    global.fetch = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['fake-demo-image']) })
    renderGallery()

    fireEvent.click(screen.getByTestId('demo-btn'))
    await waitFor(() => expect(seedImageFromBase64).toHaveBeenCalledTimes(4), { timeout: 5000 })
    expect(createTask).toHaveBeenCalledTimes(4)
    // 每张示例图登记后以其返回 id 建 restore 任务（经典保底，无需模型）
    for (let i = 0; i < 4; i += 1) {
      expect(createTask).toHaveBeenNthCalledWith(i + 1, {
        imageIds: [i + 1],
        taskType: 'restore',
        params: { output_format: 'jpeg' },
      })
    }
    const seedCalls = seedImageFromBase64.mock.calls
    for (const [arg] of seedCalls) {
      expect(arg.dataBase64).toBeTruthy()
      expect(arg.filename).toMatch(/^demo\d+_/u)
    }
    // 完成后触发列表刷新
    await waitFor(() => expect(listImages).toHaveBeenCalled())
  })
})
