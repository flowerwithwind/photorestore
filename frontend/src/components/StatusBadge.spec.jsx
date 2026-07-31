// 状态徽章组件测试：五态渲染与 data-status 映射
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import StatusBadge from './StatusBadge'

describe('StatusBadge', () => {
  it.each(['queued', 'processing', 'succeeded', 'failed', 'cancelled'])(
    'renders badge for %s with data-status attribute',
    (status) => {
      render(<StatusBadge status={status} />)
      const badge = screen.getByTestId('status-badge')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveAttribute('data-status', status)
    },
  )

  it('shows the Chinese label mapped from status', () => {
    render(<StatusBadge status="processing" />)
    expect(screen.getByText('处理中')).toBeInTheDocument()
    expect(screen.queryByText('排队中')).not.toBeInTheDocument()
  })

  it('falls back for unknown status', () => {
    render(<StatusBadge status="mystery" />)
    expect(screen.getByTestId('status-badge')).toHaveAttribute('data-status', 'mystery')
  })
})
