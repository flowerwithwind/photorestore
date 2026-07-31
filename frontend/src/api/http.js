// API 基础客户端：fetch 封装 + 统一错误处理（对齐后端 {error:{code,message,details}} 契约）
const BASE = '/api'

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'http_error', details = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export function buildUrl(path, query) {
  let url = `${BASE}${path}`
  if (query) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      params.set(key, String(value))
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  }
  return url
}

export async function request(path, { method = 'GET', body, query } = {}) {
  const url = buildUrl(path, query)
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError('网络请求失败：请确认后端服务已启动（127.0.0.1:8030）', { code: 'network_error' })
  }
  if (!res.ok) {
    let payload = null
    try {
      payload = await res.json()
    } catch {
      /* 非 JSON 错误体 */
    }
    const err = payload && payload.error ? payload.error : {}
    throw new ApiError(
      err.message || `请求失败（HTTP ${res.status}）`,
      { status: res.status, code: err.code || 'http_error', details: err.details || null },
    )
  }
  if (res.status === 204) return null
  return res.json()
}

export const get = (path, query) => request(path, { query })
export const post = (path, body) => request(path, { method: 'POST', body })
