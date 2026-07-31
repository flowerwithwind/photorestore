# PhotoRestore 前端（D5 任务工作台）

React + Vite + vitest 实现的任务工作台，对齐后端 D4 冻结 API：

- 上传页：拖拽/多文件 + 客户端预检（类型/大小）+ 登记图片元数据并创建任务
- 任务列表：状态徽章 / 进度条 / 筛选 / 分页 / 自动刷新
- 实时进度：SSE（EventSource snapshot/update/done）+ 断线重连 + 轮询兜底
- 任务详情：阶段时间线（phase_logs）/ 模型名 / 前后尺寸体积 / 下载 / 取消

## 开发

```bash
npm install
npm run dev        # http://localhost:5175，/api 代理到 127.0.0.1:8030
npm test           # vitest run
npm run build      # 产物输出到 dist/
```

后端需先启动（`cd backend && python -m uvicorn app.main:app --port 8030`）。

> 说明：后端冻结接口仅登记图片元数据（POST /api/images），未提供真实文件字节上传端点；
> 前端按契约完成「预检 → 登记 → 建任务」链路，服务端处理要求原图已位于后端 uploads 目录。
