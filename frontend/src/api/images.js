// 图片元数据 API：上传即登记（后端仅登记元数据，不接收文件字节）
import { post } from './http'

export function registerImage({ filename, sizeBytes, format }) {
  return post('/images', { filename, size_bytes: sizeBytes, format })
}
