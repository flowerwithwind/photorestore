// tasks API 扩展测试（D7）：批量入队 / 重跑 的请求契约
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createTasksBatch, rerunTask } from './tasks'

describe('tasks API batch & rerun', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('createTasksBatch posts /tasks/batch with image_ids and params', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ task_ids: [11, 12], count: 2, status: 'queued' }),
    })
    const res = await createTasksBatch({
      imageIds: [3, 4],
      taskType: 'restore',
      params: { denoise_h: 5, output_format: 'png' },
    })
    expect(res.task_ids).toEqual([11, 12])
    const [url, init] = global.fetch.mock.calls[0]
    expect(url).toBe('/api/tasks/batch')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      image_ids: [3, 4],
      task_type: 'restore',
      params: { denoise_h: 5, output_format: 'png' },
    })
  })

  it('rerunTask posts /tasks/{id}/rerun and returns new task id', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ task_id: 9, status: 'queued', source_task_id: 1 }),
    })
    const res = await rerunTask(1)
    expect(res.task_id).toBe(9)
    const [url, init] = global.fetch.mock.calls[0]
    expect(url).toBe('/api/tasks/1/rerun')
    expect(init.method).toBe('POST')
  })

  it('surfaces backend error payload as ApiError', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ error: { code: 'task_not_terminal', message: '任务未结束（非终态），不能重跑', details: { status: 'queued' } } }),
    })
    await expect(rerunTask(1)).rejects.toMatchObject({
      code: 'task_not_terminal',
      status: 409,
    })
  })
})
