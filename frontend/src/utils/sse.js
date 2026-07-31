// SSE 消息解析与事件数据解码（对齐 D4 契约：event + data + 空行；注释行 : ping 忽略）
export function parseSSEFrames(text) {
  const frames = []
  const blocks = String(text || '').split(/\r?\n\r?\n/)
  for (const block of blocks) {
    let event = null
    const dataLines = []
    for (const rawLine of block.split(/\r?\n/)) {
      const line = rawLine.trim()
      if (!line || line.startsWith(':')) continue // 心跳注释/空行
      if (line.startsWith('event:')) {
        event = line.slice('event:'.length).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).trim())
      }
    }
    if (event !== null || dataLines.length > 0) {
      frames.push({ event: event || 'message', data: dataLines.join('\n') })
    }
  }
  return frames
}

export function parseEventData(raw) {
  if (raw === null || raw === undefined || raw === '') return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

// 将 EventSource 的 message 事件解码为 { event, data }；未知事件返回 null
export function decodeEventSourceMessage(event) {
  if (!event || typeof event.data !== 'string') return null
  const frames = parseSSEFrames(event.data)
  if (frames.length === 0) return null
  const frame = frames[frames.length - 1]
  return { event: frame.event, data: parseEventData(frame.data) }
}
