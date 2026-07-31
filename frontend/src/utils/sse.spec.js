// SSE 消息解析测试：snapshot/update/done、多 data 行、心跳与空帧
import { describe, expect, it } from 'vitest'
import { decodeEventSourceMessage, parseEventData, parseSSEFrames } from './sse'

const snapshotFrame = 'event: snapshot\ndata: {"task_id":1,"status":"queued","progress":0,"phase":null}\n\n'
const updateFrame = 'event: update\ndata: {"task_id":1,"status":"processing","progress":50,"phase":"infer","seq":3}\n\n'
const doneFrame = 'event: done\ndata: {"task_id":1,"ts":"2026-08-01T10:00:00"}\n\n'

describe('parseSSEFrames', () => {
  it('parses a single event frame', () => {
    const frames = parseSSEFrames(snapshotFrame)
    expect(frames).toHaveLength(1)
    expect(frames[0].event).toBe('snapshot')
    expect(JSON.parse(frames[0].data).task_id).toBe(1)
  })

  it('parses multiple frames separated by blank lines', () => {
    const frames = parseSSEFrames(snapshotFrame + updateFrame + doneFrame)
    expect(frames.map((f) => f.event)).toEqual(['snapshot', 'update', 'done'])
  })

  it('joins multiple data lines with newline', () => {
    const frame = 'event: update\ndata: {"task_id":1}\ndata: {"seq":2}\n\n'
    const [parsed] = parseSSEFrames(frame)
    expect(parsed.data).toBe('{"task_id":1}\n{"seq":2}')
  })

  it('ignores heartbeat comment lines and blank input', () => {
    const frames = parseSSEFrames(': ping\n\n')
    expect(frames).toEqual([])
    expect(parseSSEFrames('')).toEqual([])
    expect(parseSSEFrames(null)).toEqual([])
  })

  it('falls back to message event when event: is missing', () => {
    const [parsed] = parseSSEFrames('data: {"a":1}\n\n')
    expect(parsed.event).toBe('message')
  })
})

describe('parseEventData / decodeEventSourceMessage', () => {
  it('decodes a snapshot message', () => {
    const decoded = decodeEventSourceMessage({ data: snapshotFrame })
    expect(decoded.event).toBe('snapshot')
    expect(decoded.data.status).toBe('queued')
  })

  it('decodes update and done messages', () => {
    expect(decodeEventSourceMessage({ data: updateFrame }).data.progress).toBe(50)
    expect(decodeEventSourceMessage({ data: doneFrame }).event).toBe('done')
  })

  it('returns null for non-JSON or empty payloads', () => {
    expect(decodeEventSourceMessage({ data: 'event: update\ndata: not-json\n\n' }).data).toBeNull()
    expect(decodeEventSourceMessage({ data: ': ping\n\n' })).toBeNull()
    expect(decodeEventSourceMessage(null)).toBeNull()
    expect(decodeEventSourceMessage({})).toBeNull()
  })

  it('ignores trailing/leading whitespace in data lines', () => {
    const decoded = decodeEventSourceMessage({ data: 'event: snapshot\ndata:   {"a":1}  \n\n' })
    expect(decoded.data).toEqual({ a: 1 })
  })
})
