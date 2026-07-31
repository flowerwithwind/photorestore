// 实时进度状态机测试：SSE 消息合并/终态收尾/断线重连/轮询兜底
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getTaskDetail, taskEventsUrl } from '../api/tasks'
import { mergeSnapshot, useTaskEvents } from './useTaskEvents'

vi.mock('../api/tasks', () => ({
  getTaskDetail: vi.fn(),
  taskEventsUrl: vi.fn((id) => `/api/tasks/${id}/events`),
}))

class FakeEventSource {
  static instances = []
  constructor(url) {
    this.url = url
    this.closed = false
    this.onopen = null
    this.onmessage = null
    this.onerror = null
    FakeEventSource.instances.push(this)
  }
  close() {
    this.closed = true
  }
  static reset() {
    FakeEventSource.instances = []
  }
}

function detail(over = {}) {
  return {
    id: 1,
    task_type: 'restore',
    status: 'queued',
    progress: 0,
    phase: null,
    params: {},
    params_hash: 'aabbccdd',
    error: null,
    result: null,
    image_ids: [7],
    created_at: '2026-08-01T09:00:00',
    started_at: null,
    finished_at: null,
    phase_logs: [],
    ...over,
  }
}

const emitOpen = (es) => es.onopen && es.onopen({})
const emitError = (es) => es.onerror && es.onerror({})
const emitMessage = (es, data) => es.onmessage && es.onmessage({ data })

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })
const frame = (event, payload) => `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`

beforeEach(() => {
  vi.useFakeTimers()
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  getTaskDetail.mockResolvedValue(detail())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.clearAllMocks()
})

describe('mergeSnapshot', () => {
  it('merges snapshots and maps task_id to id, keeping phase_logs', () => {
    const prev = { id: 1, status: 'queued', progress: 0, phase_logs: [{ id: 1 }] }
    const merged = mergeSnapshot(prev, { task_id: 1, status: 'processing', progress: 40 })
    expect(merged.id).toBe(1)
    expect(merged.status).toBe('processing')
    expect(merged.progress).toBe(40)
    expect(merged.phase_logs).toEqual([{ id: 1 }])
  })

  it('returns snapshot as-is when no previous state', () => {
    const snap = { task_id: 2, status: 'queued' }
    expect(mergeSnapshot(null, snap)).toBe(snap)
    expect(mergeSnapshot(undefined, null)).toBeUndefined()
  })
})

describe('useTaskEvents', () => {
  it('opens EventSource after initial detail fetch and applies snapshot/update/done', async () => {
    const { result } = renderHook(() => useTaskEvents(1))
    await flush()

    expect(getTaskDetail).toHaveBeenCalledTimes(1)
    expect(taskEventsUrl).toHaveBeenCalledWith(1)
    expect(FakeEventSource.instances).toHaveLength(1)

    const es = FakeEventSource.instances[0]
    act(() => emitOpen(es))
    expect(result.current.source).toBe('sse')
    expect(result.current.connected).toBe(true)
    expect(result.current.task.id).toBe(1)

    act(() => emitMessage(es, frame('snapshot', { task_id: 1, status: 'queued', progress: 0 })))
    expect(result.current.task.status).toBe('queued')

    act(() => emitMessage(es, frame('update', { task_id: 1, status: 'processing', progress: 45, phase: 'infer', seq: 2 })))
    expect(result.current.task.progress).toBe(45)
    expect(result.current.task.phase).toBe('infer')

    act(() => emitMessage(es, frame('done', { task_id: 1 })))
    await flush()
    expect(es.closed).toBe(true)
    // 终态后补拉一次详情，避免 SSE 与 DB 竞态
    expect(getTaskDetail).toHaveBeenCalledTimes(2)
  })

  it('finalizes on terminal update and stops SSE', async () => {
    const { result } = renderHook(() => useTaskEvents(1))
    await flush()
    const es = FakeEventSource.instances[0]
    act(() => emitOpen(es))
    getTaskDetail.mockClear()
    // 终态后的补拉详情返回一致状态，验证 finalize 合并
    getTaskDetail.mockResolvedValue(detail({ status: 'succeeded', progress: 100, phase: 'save' }))

    act(() => emitMessage(es, frame('update', { task_id: 1, status: 'succeeded', progress: 100, phase: 'save' })))
    await flush()
    expect(es.closed).toBe(true)
    expect(getTaskDetail).toHaveBeenCalledTimes(1)
    expect(result.current.task.status).toBe('succeeded')
  })

  it('reconnects with exponential backoff and resets retries on open', async () => {
    const { result } = renderHook(() => useTaskEvents(1, { maxReconnect: 3 }))
    await flush()
    const es1 = FakeEventSource.instances[0]
    act(() => emitOpen(es1))

    act(() => emitError(es1))
    expect(es1.closed).toBe(true)
    expect(result.current.retries).toBe(1)
    expect(result.current.connected).toBe(false)

    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(FakeEventSource.instances).toHaveLength(2)

    const es2 = FakeEventSource.instances[1]
    act(() => emitOpen(es2))
    expect(result.current.connected).toBe(true)
    expect(result.current.retries).toBe(0)
  })

  it('falls back to polling after reconnect attempts are exhausted', async () => {
    const { result } = renderHook(() => useTaskEvents(1, { maxReconnect: 2, pollIntervalMs: 100 }))
    await flush()

    act(() => emitError(FakeEventSource.instances[0]))
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    act(() => emitError(FakeEventSource.instances[1]))
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    act(() => emitError(FakeEventSource.instances[2]))
    await flush()

    expect(result.current.source).toBe('polling')
    expect(result.current.connected).toBe(false)
    expect(result.current.retries).toBe(2)

    const callsBefore = getTaskDetail.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(250) })
    expect(getTaskDetail.mock.calls.length).toBeGreaterThan(callsBefore)
  })

  it('falls back to polling when EventSource is unavailable', async () => {
    vi.stubGlobal('EventSource', undefined)
    const { result } = renderHook(() => useTaskEvents(1, { pollIntervalMs: 50 }))
    await flush()

    expect(result.current.source).toBe('polling')
    const callsBefore = getTaskDetail.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(120) })
    expect(getTaskDetail.mock.calls.length).toBeGreaterThan(callsBefore)
  })

  it('stays silent when disabled', async () => {
    const { result } = renderHook(() => useTaskEvents(1, { enabled: false }))
    await flush()
    expect(getTaskDetail).not.toHaveBeenCalled()
    expect(FakeEventSource.instances).toHaveLength(0)
    expect(result.current.source).toBe('idle')
  })
})
