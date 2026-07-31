// 拖拽/多选上传区：接收文件列表回调（预检由调用方完成）
import { useRef, useState } from 'react'

export default function UploadDropzone({ onFiles, accept = 'image/*', multiple = true }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  const handleDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    const files = Array.from(event.dataTransfer ? event.dataTransfer.files : [])
    if (files.length > 0) onFiles(files)
  }

  const handleInput = (event) => {
    const files = Array.from(event.target.files || [])
    if (files.length > 0) onFiles(files)
    event.target.value = '' // 允许重复选择同一文件
  }

  return (
    <div
      className={`dropzone ${dragging ? 'dragging' : ''}`}
      data-testid="upload-dropzone"
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current && inputRef.current.click()}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          inputRef.current && inputRef.current.click()
        }
      }}
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        style={{ display: 'none' }}
        onChange={handleInput}
        data-testid="dropzone-input"
      />
      <div className="dropzone-icon">📁</div>
      <div className="dropzone-title">拖拽图片到此处，或点击选择文件</div>
      <div className="dropzone-hint">支持 jpg / jpeg / png / bmp / webp / tiff · 单文件不超过 20 MB · 可多选</div>
    </div>
  )
}
