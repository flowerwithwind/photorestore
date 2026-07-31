// D6 images API 测试：列表查询参数 / 删除请求契约 / 最新产物选择
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteImage, imageDownloadUrl, latestOutput, listImages, uploadImage } from './images'

function okJson(payload) {
  return { ok: true, status: 200, json: async () => payload }
}

function succeededTask(id, outputs) {
  return { id, status: 'succeeded', result: { model: 'mock', outputs } }
}

beforeEach(() => {
  global.fetch = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('images API', () => {
  it('listImages 把 task_type/status/limit/offset 编码进查询串', async () => {
    global.fetch.mockResolvedValue(okJson({ items: [], total: 0 }))
    await listImages({ taskType: 'restore', status: 'succeeded', limit: 12, offset: 24 })
    const [url] = global.fetch.mock.calls[0]
    expect(url).toBe('/api/images?task_type=restore&status=succeeded&limit=12&offset=24')
  })

  it('listImages 省略未传筛选条件', async () => {
    global.fetch.mockResolvedValue(okJson({ items: [], total: 0 }))
    await listImages({ limit: 20, offset: 0 })
    const [url] = global.fetch.mock.calls[0]
    expect(url).toBe('/api/images?limit=20&offset=0')
  })

  it('deleteImage 发送 DELETE /api/images/{id}', async () => {
    global.fetch.mockResolvedValue(
      okJson({ deleted: true, image_id: 7, deleted_task_ids: [3, 4], removed_files: ['uploads/a.png', 'outputs/b.jpeg'] }),
    )
    const res = await deleteImage(7)
    const [url, init] = global.fetch.mock.calls[0]
    expect(url).toBe('/api/images/7')
    expect(init.method).toBe('DELETE')
    expect(res.deleted).toBe(true)
    expect(res.deleted_task_ids).toEqual([3, 4])
  })

  it('uploadImage 以 FormData POST /api/images/upload 且不设 JSON Content-Type', async () => {
    global.fetch.mockResolvedValue(okJson({ id: 42, filename: 'a.png', size_bytes: 2048 }))
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    const res = await uploadImage(file)
    const [url, init] = global.fetch.mock.calls[0]
    expect(url).toBe('/api/images/upload')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect(init.headers['Content-Type']).toBeUndefined()
    expect(init.body.get('file')).toBe(file)
    expect(res.id).toBe(42)
  })

  it('imageDownloadUrl 生成原图下载链接', () => {
    expect(imageDownloadUrl(9)).toBe('/api/images/9/download')
  })

  it('latestOutput 选择最新 succeeded 任务的第一个产物', () => {
    const image = {
      id: 1,
      tasks: [
        { id: 2, status: 'failed' },
        succeededTask(3, [{ filename: 'old.jpeg', download_url: '/api/tasks/3/outputs/0/download' }]),
        succeededTask(5, [{ filename: 'new.jpeg', download_url: '/api/tasks/5/outputs/0/download' }]),
      ],
    }
    const out = latestOutput(image)
    expect(out.filename).toBe('new.jpeg')
    expect(out.download_url).toBe('/api/tasks/5/outputs/0/download')
  })

  it('latestOutput 无 succeeded 任务或空产物时返回 null', () => {
    expect(latestOutput(null)).toBeNull()
    expect(latestOutput({ id: 1, tasks: [] })).toBeNull()
    expect(latestOutput({ id: 1, tasks: [{ id: 2, status: 'failed' }] })).toBeNull()
    expect(latestOutput({ id: 1, tasks: [succeededTask(2, [])] })).toBeNull()
  })
})
