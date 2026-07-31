// 状态徽章映射与状态分类测试
import { describe, expect, it } from 'vitest'
import { STATUS_META, STATUS_ORDER, isActive, isTerminal, statusMeta } from './status'

describe('statusMeta / STATUS_META', () => {
  it('maps all five task statuses with Chinese labels', () => {
    expect(statusMeta('queued').label).toBe('排队中')
    expect(statusMeta('processing').label).toBe('处理中')
    expect(statusMeta('succeeded').label).toBe('已完成')
    expect(statusMeta('failed').label).toBe('失败')
    expect(statusMeta('cancelled').label).toBe('已取消')
  })

  it('covers exactly the five statuses in STATUS_ORDER', () => {
    expect(STATUS_ORDER).toEqual(['queued', 'processing', 'succeeded', 'failed', 'cancelled'])
    for (const status of STATUS_ORDER) {
      expect(STATUS_META[status]).toBeDefined()
      expect(STATUS_META[status].tone).toBe(status)
    }
  })

  it('falls back for unknown status', () => {
    expect(statusMeta(undefined).label).toBe('未知')
    expect(statusMeta('weird').label).toBe('weird')
  })
})

describe('isTerminal / isActive', () => {
  it('classifies terminal statuses', () => {
    expect(isTerminal('succeeded')).toBe(true)
    expect(isTerminal('failed')).toBe(true)
    expect(isTerminal('cancelled')).toBe(true)
    expect(isTerminal('queued')).toBe(false)
    expect(isTerminal('processing')).toBe(false)
  })

  it('classifies active (cancellable) statuses', () => {
    expect(isActive('queued')).toBe(true)
    expect(isActive('processing')).toBe(true)
    expect(isActive('succeeded')).toBe(false)
    expect(isActive('failed')).toBe(false)
    expect(isActive('cancelled')).toBe(false)
  })
})
