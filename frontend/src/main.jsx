// PhotoRestore 前端入口：路由（工作台/上传/任务详情）
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import DashboardView from './views/DashboardView'
import UploadView from './views/UploadView'
import TaskDetailView from './views/TaskDetailView'
import './styles/base.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardView />} />
          <Route path="/upload" element={<UploadView />} />
          <Route path="/tasks/:taskId" element={<TaskDetailView />} />
          <Route path="*" element={<DashboardView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)
