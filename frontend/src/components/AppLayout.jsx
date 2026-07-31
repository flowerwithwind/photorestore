// 画廊主题应用外壳：顶栏（品牌/导航/明暗切换）+ 内容区
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

const THEME_KEY = 'photorestore-theme'

export default function AppLayout() {
  const [isDark, setIsDark] = useState(true)

  useEffect(() => {
    let saved = null
    try {
      saved = localStorage.getItem(THEME_KEY)
    } catch {
      /* ignore */
    }
    if (saved === 'light') setIsDark(false)
  }, [])

  useEffect(() => {
    document.documentElement.classList.toggle('light', !isDark)
    try {
      localStorage.setItem(THEME_KEY, isDark ? 'dark' : 'light')
    } catch {
      /* ignore */
    }
  }, [isDark])

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="logo">🖼</div>
          <div className="brand-text">
            <span className="brand-name">PhotoRestore</span>
            <span className="brand-sub">影像修复工作台 · v1.0.0-dev</span>
          </div>
        </div>
        <div className="topbar-right">
          <nav className="nav">
            <NavLink to="/" end className="nav-link">
              工作台
            </NavLink>
            <NavLink to="/upload" className="nav-link">
              上传
            </NavLink>
            <NavLink to="/settings" className="nav-link">
              设置
            </NavLink>
            <NavLink to="/gallery" className="nav-link">
              画廊
            </NavLink>
          </nav>
          <button
            type="button"
            className="theme-btn"
            title={isDark ? '切换到亮色' : '切换到暗色'}
            onClick={() => setIsDark((v) => !v)}
          >
            {isDark ? '☀️' : '🌙'}
          </button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
