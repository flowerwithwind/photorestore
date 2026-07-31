// 存储占用统计：ECharts 环形图（uploads vs outputs），失败时降级为文本
import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { getStorageStats } from '../api/storage'
import { formatBytes } from '../utils/format'

export default function StorageStats() {
  const chartRef = useRef(null)
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getStorageStats()
      .then((data) => {
        if (!cancelled) setStats(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!stats || !chartRef.current) return undefined
    const chart = echarts.init(chartRef.current)
    const uploads = Number((stats.uploads || {}).bytes) || 0
    const outputs = Number((stats.outputs || {}).bytes) || 0
    chart.setOption({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: '#9aa3c7' } },
      series: [
        {
          type: 'pie',
          radius: ['58%', '80%'],
          avoidLabelOverlap: true,
          label: { show: false },
          data: [
            { name: '原图 (uploads)', value: uploads, itemStyle: { color: '#6366f1' } },
            { name: '产物 (outputs)', value: outputs, itemStyle: { color: '#8b5cf6' } },
          ],
        },
      ],
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [stats])

  if (error) {
    return (
      <div className="card">
        <h3 className="card-title">存储占用</h3>
        <div className="muted">统计不可用：{error}</div>
      </div>
    )
  }
  if (!stats) {
    return (
      <div className="card">
        <h3 className="card-title">存储占用</h3>
        <div className="muted">加载中…</div>
      </div>
    )
  }
  return (
    <div className="card">
      <h3 className="card-title">存储占用</h3>
      <div ref={chartRef} style={{ height: 180 }} data-testid="storage-chart" />
      <div className="muted">
        原图 {formatBytes(stats.uploads?.bytes)}（{stats.uploads?.count ?? 0} 张） · 产物{' '}
        {formatBytes(stats.outputs?.bytes)}（{stats.outputs?.count ?? 0} 个）
      </div>
    </div>
  )
}
