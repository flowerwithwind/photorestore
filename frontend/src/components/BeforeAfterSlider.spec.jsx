// D6 对比滑块组件测试：分割线拖拽 / 模式切换 / 缩放 / 键盘
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'
import BeforeAfterSlider, { clampPercent } from './BeforeAfterSlider'

// jsdom 25 未实现 PointerEvent：补一个基于 MouseEvent 的桩，
// 使 fireEvent.pointerDown/Move 携带 clientX/pointerId（对齐真实浏览器行为）。
class MockPointerEvent extends MouseEvent {
  constructor(type, init = {}) {
    super(type, init)
    this.pointerId = init.pointerId === undefined ? 0 : init.pointerId
    this.isPrimary = init.isPrimary === undefined ? true : init.isPrimary
  }
}

beforeAll(() => {
  window.PointerEvent = MockPointerEvent
})

function mockStageRect(element) {
  // jsdom 无布局：伪造一个 200px 宽的可拖拽区域
  element.getBoundingClientRect = () => ({
    left: 0,
    top: 0,
    right: 200,
    bottom: 150,
    width: 200,
    height: 150,
    x: 0,
    y: 0,
  })
}

function renderSlider(props = {}) {
  render(
    <BeforeAfterSlider
      beforeUrl="/api/images/1/download"
      afterUrl="/api/tasks/9/outputs/0/download"
      {...props}
    />,
  )
  return screen.getByTestId('slider-stage')
}

describe('BeforeAfterSlider', () => {
  it('默认对比模式：渲染原图与结果图两层及分割线', () => {
    const stage = renderSlider()
    expect(stage).toHaveAttribute('data-mode', 'slider')
    expect(screen.getByTestId('slider-divider')).toBeInTheDocument()
    expect(screen.getByTestId('slider-before-layer')).toBeInTheDocument()
    expect(stage).toHaveAttribute('data-percent', '50')
  })

  it('拖拽分割线按 clientX 更新百分比并夹紧', () => {
    const stage = renderSlider()
    mockStageRect(stage)
    const divider = screen.getByTestId('slider-divider')
    fireEvent.pointerDown(divider, { pointerId: 1, clientX: 100 })
    fireEvent.pointerMove(divider, { pointerId: 1, clientX: 150 })
    expect(stage).toHaveAttribute('data-percent', '75')
    // 拖出边界时夹紧到 98
    fireEvent.pointerMove(divider, { pointerId: 1, clientX: 9999 })
    expect(stage).toHaveAttribute('data-percent', '98')
  })

  it('方向键微调分割线', () => {
    const stage = renderSlider()
    const divider = screen.getByTestId('slider-divider')
    fireEvent.keyDown(divider, { key: 'ArrowRight' })
    expect(stage).toHaveAttribute('data-percent', '52')
    fireEvent.keyDown(divider, { key: 'ArrowLeft' })
    fireEvent.keyDown(divider, { key: 'ArrowLeft' })
    expect(stage).toHaveAttribute('data-percent', '48')
  })

  it('模式切换：原图 / 结果 / 对比', () => {
    const stage = renderSlider()
    fireEvent.click(screen.getByTestId('mode-before'))
    expect(stage).toHaveAttribute('data-mode', 'before')
    expect(screen.queryByTestId('slider-divider')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('mode-after'))
    expect(stage).toHaveAttribute('data-mode', 'after')

    fireEvent.click(screen.getByTestId('mode-slider'))
    expect(stage).toHaveAttribute('data-mode', 'slider')
    expect(screen.getByTestId('slider-divider')).toBeInTheDocument()
  })

  it('缩放：放大 / 缩小 / 复位', () => {
    const stage = renderSlider()
    fireEvent.click(screen.getByTestId('zoom-in'))
    expect(stage).toHaveAttribute('data-zoom', '1.25')
    expect(screen.getByTestId('zoom-level')).toHaveTextContent('125%')
    fireEvent.click(screen.getByTestId('zoom-in'))
    expect(stage).toHaveAttribute('data-zoom', '1.5')
    fireEvent.click(screen.getByTestId('zoom-out'))
    expect(stage).toHaveAttribute('data-zoom', '1.25')
    fireEvent.click(screen.getByTestId('zoom-reset'))
    expect(stage).toHaveAttribute('data-zoom', '1')
  })

  it('clampPercent 边界', () => {
    expect(clampPercent(-10)).toBe(2)
    expect(clampPercent(200)).toBe(98)
    expect(clampPercent(Number.NaN)).toBe(50)
    expect(clampPercent(33)).toBe(33)
  })
})
