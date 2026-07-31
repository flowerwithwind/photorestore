// 上传预检测试：类型（扩展名/MIME）与大小
import { describe, expect, it } from 'vitest'
import {
  ALLOWED_EXTENSIONS,
  MAX_UPLOAD_BYTES,
  extensionOf,
  isAllowedExtension,
  precheckFile,
  precheckFiles,
} from './validate'

function fakeFile(name, { size = 1024, type = '' } = {}) {
  return { name, size, type }
}

describe('extensionOf / isAllowedExtension', () => {
  it('accepts all allowed image extensions', () => {
    expect(ALLOWED_EXTENSIONS).toEqual(['jpg', 'jpeg', 'png', 'bmp', 'webp', 'tiff', 'tif'])
    for (const ext of ALLOWED_EXTENSIONS) {
      expect(isAllowedExtension(`photo.${ext}`)).toBe(true)
      expect(isAllowedExtension(`photo.${ext.toUpperCase()}`)).toBe(true)
    }
  })

  it('rejects unsupported or missing extensions', () => {
    expect(isAllowedExtension('photo.txt')).toBe(false)
    expect(isAllowedExtension('photo')).toBe(false)
    expect(isAllowedExtension('')).toBe(false)
    expect(isAllowedExtension(null)).toBe(false)
  })
})

describe('precheckFile', () => {
  it('passes a valid image file', () => {
    const result = precheckFile(fakeFile('a.png', { size: 2048, type: 'image/png' }))
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
    expect(result.format).toBe('png')
    expect(result.sizeBytes).toBe(2048)
  })

  it('rejects unsupported type with a clear error', () => {
    const result = precheckFile(fakeFile('a.txt', { type: 'text/plain' }))
    expect(result.ok).toBe(false)
    expect(result.errors.join('')).toContain('不支持的文件类型')
  })

  it('rejects oversized files (limit 20 MB)', () => {
    const over = precheckFile(fakeFile('a.png', { size: MAX_UPLOAD_BYTES + 1 }))
    expect(over.ok).toBe(false)
    expect(over.errors.join('')).toContain('文件过大')
    const atLimit = precheckFile(fakeFile('a.png', { size: MAX_UPLOAD_BYTES }))
    expect(atLimit.ok).toBe(true)
  })

  it('rejects MIME type mismatch', () => {
    const result = precheckFile(fakeFile('a.png', { type: 'application/octet-stream' }))
    expect(result.ok).toBe(false)
    expect(result.errors.join('')).toContain('MIME 类型不匹配')
  })
})

describe('precheckFiles', () => {
  it('checks every file and keeps index/size metadata', () => {
    const files = [
      fakeFile('ok.jpg', { size: 100, type: 'image/jpeg' }),
      fakeFile('bad.exe', { size: 50, type: 'application/x-msdownload' }),
      fakeFile('huge.png', { size: MAX_UPLOAD_BYTES + 10, type: 'image/png' }),
    ]
    const results = precheckFiles(files)
    expect(results).toHaveLength(3)
    expect(results[0].ok).toBe(true)
    expect(results[1].ok).toBe(false)
    expect(results[2].ok).toBe(false)
    expect(results.map((r) => r.index)).toEqual([0, 1, 2])
    expect(results[0].file).toBe(files[0])
  })

  it('handles empty / non-array input', () => {
    expect(precheckFiles([])).toEqual([])
    expect(precheckFiles(null)).toEqual([])
  })
})
