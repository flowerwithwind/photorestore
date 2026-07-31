// 任务实时进度状态机：SSE（EventSource snapshot/update/done）+ 断线重连 + 轮询兜底
// - SSE 连接成功：source='sse'，事件驱动更新；done 或终态后补拉一次详情再停止
// - SSE 失败/断线：指数退避重连（maxReconnect 次），期间不丢状态
// - 重连耗尽或环境不支持 EventSource：切换 source='polling' 定时轮询详情（含 phase_logs）
import { useCallback, useEffect, useRef, useState } from 'react'
import { getTaskDetail, taskEventsUrl } from '../api/tasks'
import { decodeEventSourceMessage } from '../utils/sse'
import { isTerminal } from '../utils/status'

export const SSE_RECONNECT_BASE_MS = 1000
export const SSE_RECONNECT_MAX_MS = 15000
export const DEFAULT_POLL_INTERVAL_MS = 2500

export function mergeSnapshot(prev, snap) {
  if (!snap) return prev
  if (!prev) return snap
  return {
    ...prev,
    ...snap,
    id: snap.task_id !== undefined && snap.task_id !== null ? snap.task_id : prev.id,
    phase_logs: prev.phase_logs || [],
  }
}

export function useTaskEvents(
  taskId,
  { pollIntervalMs = DEFAULT_POLL_INTERVAL_MS, maxReconnect = 5, enabled = true } = {},
) {
  const [task, setTask] = useState(null)
  const [phaseLogs, setPhaseLogs] = useState([])
  const [source, setSource] = useState('idle') // idle | sse | polling
  const [connected, setConnected] = useState(false)
  const [retries, setRetries] = useState(0)
  const [error, setError] = useState(null)

  const ref = useRef({
    stopped: false,
    es: null,
    pollTimer: null,
    reconnectTimer: null,
    retries: 0,
    maxReconnect,
  })
  ref.current.maxReconnect = maxReconnect
  const taskRef = useRef(null)

  const fetchDetail = useCallback(async (id) => {
    const detail = await getTaskDetail(id)
    taskRef.current = detail
    setTask((prev) => (prev && prev.status === detail.status ? { ...prev, ...detail } : detail))
    setPhaseLogs(detail.phase_logs || [])
    return detail
  }, [])

  const stop = useCallback(() => {
    const r = ref.current
    r.stopped = true
    if (r.es) {
      r.es.close()
      r.es = null
    }
    if (r.pollTimer) {
      clearInterval(r.pollTimer)
      r.pollTimer = null
    }
    if (r.reconnectTimer) {
      clearTimeout(r.reconnectTimer)
      r.reconnectTimer = null
    }
  }, [])

  const finalize = useCallback(
    async (id) => {
      const r = ref.current
      r.stopped = true
      if (r.es) {
        r.es.close()
        r.es = null
      }
      if (r.pollTimer) clearInterval(r.pollTimer)
      if (r.reconnectTimer) clearTimeout(r.reconnectTimer)
      r.pollTimer = null
      r.reconnectTimer = null
      // 终态后补拉一次详情，拿到完整 phase_logs / result
      try {
        await fetchDetail(id)
      } catch (err) {
        setError(err.message || String(err))
      }
    },
    [fetchDetail],
  )

  const startPolling = useCallback(
    (id) => {
      const r = ref.current
      if (r.stopped || r.pollTimer) return
      r.es = null
      setSource('polling')
      setConnected(false)
      const pollOnce = async () => {
        if (r.stopped) return
        try {
          const detail = await fetchDetail(id)
          if (isTerminal(detail.status)) finalize(id)
        } catch (err) {
          if (!r.stopped) setError(err.message || String(err))
        }
      }
      pollOnce()
      r.pollTimer = setInterval(pollOnce, pollIntervalMs)
    },
    [fetchDetail, finalize, pollIntervalMs],
  )

  const openEventSource = useCallback(
    (id) => {
      const r = ref.current
      if (r.stopped) return
      if (typeof EventSource === 'undefined') {
        startPolling(id)
        return
      }
      let es
      try {
        es = new EventSource(taskEventsUrl(id))
      } catch {
        startPolling(id)
        return
      }
      r.es = es
      es.onopen = () => {
        if (r.stopped || r.es !== es) return
        setConnected(true)
        setSource('sse')
        setRetries(0)
        r.retries = 0
      }
      es.onmessage = (event) => {
        if (r.stopped || r.es !== es) return
        const decoded = decodeEventSourceMessage(event)
        if (!decoded || !decoded.data) return
        if (decoded.event === 'done') {
          finalize(id)
          return
        }
        if (decoded.event === 'snapshot' || decoded.event === 'update') {
          const snap = decoded.data
          taskRef.current = mergeSnapshot(taskRef.current, snap)
          setTask(taskRef.current)
          if (isTerminal(snap.status)) finalize(id)
        }
      }
      es.onerror = () => {
        if (r.stopped || r.es !== es) return
        es.close()
        r.es = null
        setConnected(false)
        if (taskRef.current && isTerminal(taskRef.current.status)) {
          finalize(id)
          return
        }
        if (r.retries < r.maxReconnect) {
          const delay = Math.min(SSE_RECONNECT_BASE_MS * 2 ** r.retries, SSE_RECONNECT_MAX_MS)
          r.retries += 1
          setRetries(r.retries)
          r.reconnectTimer = setTimeout(() => openEventSource(id), delay)
        } else {
          startPolling(id)
        }
      }
    },
    [finalize, startPolling],
  )

  useEffect(() => {
    const r = ref.current
    r.stopped = true
    if (r.es) r.es.close()
    if (r.pollTimer) clearInterval(r.pollTimer)
    if (r.reconnectTimer) clearTimeout(r.reconnectTimer)
    r.es = null
    r.pollTimer = null
    r.reconnectTimer = null
    r.retries = 0
    taskRef.current = null
    setTask(null)
    setPhaseLogs([])
    setSource('idle')
    setConnected(false)
    setRetries(0)
    setError(null)

    if (!taskId || !enabled) return undefined

    r.stopped = false
    // 先轮询一次拿到完整详情（含 phase_logs），再尝试 SSE
    ;(async () => {
      try {
        await fetchDetail(taskId)
      } catch (err) {
        if (!r.stopped) setError(err.message || String(err))
      }
      if (!r.stopped) openEventSource(taskId)
    })()

    return () => {
      stop()
    }
  }, [taskId, enabled, fetchDetail, openEventSource, stop])

  return { task, phaseLogs, source, connected, retries, error }
}
