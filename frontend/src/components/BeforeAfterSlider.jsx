// D6 对比滑块：分割线拖拽 + 原图/结果/对比模式切换 + 缩放（结果图复用 D4 产物下载链接）
import { useCallback, useRef, useState } from 'react'

const MODES = [
  { key: 'slider', label: '对比' },
  { key: 'before', label: '原图' },
  { key: 'after', label: '结果' },
]
const MIN_ZOOM = 1
const MAX_ZOOM = 3
const ZOOM_STEP = 0.25
const PERCENT_MIN = 2
const PERCENT_MAX = 98

export function clampPercent(value) {
  const numeric = Number(value)
  if (Number.isNaN(numeric)) return 50
  return Math.min(PERCENT_MAX, Math.max(PERCENT_MIN, numeric))
}

export default function BeforeAfterSlider({
  beforeUrl,
  afterUrl,
  beforeLabel = '原图',
  afterLabel = '结果',
  initialPercent = 50,
}) {
  const [mode, setMode] = useState('slider')
  const [percent, setPercent] = useState(() => clampPercent(initialPercent))
  const [zoom, setZoom] = useState(1)
  const [dragging, setDragging] = useState(false)
  const stageRef = useRef(null)

  const updateFromClientX = useCallback((clientX) => {
    const stage = stageRef.current
    if (!stage) return
    const rect = stage.getBoundingClientRect()
    if (!rect || rect.width <= 0) return
    setPercent(clampPercent(((clientX - rect.left) / rect.width) * 100))
  }, [])

  const handlePointerDown = useCallback(
    (event) => {
      event.preventDefault()
      setDragging(true)
      if (event.currentTarget.setPointerCapture) {
        try {
          event.currentTarget.setPointerCapture(event.pointerId)
        } catch {
          /* jsdom 等环境不支持时忽略 */
        }
      }
      updateFromClientX(event.clientX)
    },
    [updateFromClientX],
  )

  const handlePointerMove = useCallback(
    (event) => {
      if (!dragging) return
      updateFromClientX(event.clientX)
    },
    [dragging, updateFromClientX],
  )

  const handlePointerUp = useCallback((event) => {
    setDragging(false)
    if (event.currentTarget.releasePointerCapture) {
      try {
        event.currentTarget.releasePointerCapture(event.pointerId)
      } catch {
        /* ignore */
      }
    }
  }, [])

  const handleKeyDown = useCallback((event) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      setPercent((v) => clampPercent(v - 2))
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      setPercent((v) => clampPercent(v + 2))
    }
  }, [])

  const changeZoom = (next) => setZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next)))

  const dividerStyle = { left: `${percent}%` }
  const zoomStyle = { transform: `scale(${zoom})` }

  return (
    <div className="slider-card" data-testid="before-after-slider">
      <div className="slider-toolbar">
        <div className="slider-modes" role="group" aria-label="对比模式">
          {MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              className={`chip ${mode === m.key ? 'active' : ''}`}
              onClick={() => setMode(m.key)}
              data-testid={`mode-${m.key}`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className="slider-zoom" role="group" aria-label="缩放">
          <button type="button" className="btn btn-small" onClick={() => changeZoom(zoom - ZOOM_STEP)} data-testid="zoom-out">
            −
          </button>
          <span className="zoom-level" data-testid="zoom-level">{Math.round(zoom * 100)}%</span>
          <button type="button" className="btn btn-small" onClick={() => changeZoom(zoom + ZOOM_STEP)} data-testid="zoom-in">
            ＋
          </button>
          <button type="button" className="btn btn-small" onClick={() => setZoom(1)} data-testid="zoom-reset">
            1:1
          </button>
        </div>
      </div>

      <div
        className="slider-stage"
        ref={stageRef}
        data-testid="slider-stage"
        data-percent={Math.round(percent)}
        data-mode={mode}
        data-zoom={zoom}
      >
        {mode === 'before' ? (
          <img className="slider-img" src={beforeUrl} alt={beforeLabel} draggable={false} style={zoomStyle} />
        ) : mode === 'after' ? (
          <img className="slider-img" src={afterUrl} alt={afterLabel} draggable={false} style={zoomStyle} />
        ) : (
          <>
            <img className="slider-img" src={afterUrl} alt={afterLabel} draggable={false} style={zoomStyle} />
            <div
              className="slider-before-layer"
              style={{ clipPath: `inset(0 ${100 - percent}% 0 0)` }}
              data-testid="slider-before-layer"
            >
              <img className="slider-img" src={beforeUrl} alt={beforeLabel} draggable={false} style={zoomStyle} />
            </div>
            <div
              className="slider-divider"
              style={dividerStyle}
              role="slider"
              aria-label="对比分割线"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(percent)}
              tabIndex={0}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
              onKeyDown={handleKeyDown}
              data-testid="slider-divider"
            >
              <span className="slider-handle" aria-hidden="true">⇔</span>
            </div>
          </>
        )}
        <span className="slider-tag tag-before">{beforeLabel}</span>
        <span className="slider-tag tag-after">{afterLabel}</span>
      </div>
    </div>
  )
}
