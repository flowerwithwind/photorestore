# PhotoRestore v1.0.0 代码自审报告（Code Review）

> 里程碑 D10 发布前自审：架构、SSE 契约、API 契约、安全性、已知问题与后续建议。
> 审阅基线：D9 提交（943c894）→ D10 提交（本版本）；发布版本 v1.0.0。

## 1. 架构总览

PhotoRestore 是纯本地运行的 AI 影像修复工作台（去噪/去模糊/上色/超分），
前端 React SPA 与后端 FastAPI 同机部署，图像与模型数据均不离开本机。

```text
浏览器 (Vite dev :5175 / nginx :5175)
   │  /api 代理/反代（SSE 关闭缓冲）
   ▼
FastAPI backend (uvicorn :8030)
   ├─ api/          路由层：images / tasks / models / settings / storage / health
   ├─ services/     业务层：任务创建与校验、FIFO 执行器、SSE 事件总线、管线处理器、模型注册表
   ├─ storage/      SQLite 持久化（tasks / images / task_phase_logs）
   ├─ models/       ONNX 模型（realesrgan-x2/x4、ddcolor；缺失时 restore 走经典算法保底）
   └─ data/         SQLite + uploads/ + outputs/ + tmp/（挂载卷持久化）
```

关键设计决策：

- **任务队列与执行器**：`POST /api/tasks` 仅入队（立即返回 `task_id + queued`），
  线程池执行器（默认并发 1，`PHOTORESTORE_CONCURRENCY` 可调）FIFO 消费；
  取消为协作式：检查点抛出 `TaskCancelledError`，DB 状态为最终依据。
- **SSE 事件总线**：进程内存环形缓冲（每任务 200 条），`publish` 永不阻塞执行线程；
  客户端断线重连可补发缓冲事件；任务终态后 `close()` 并推送 `done`。
- **真实管线**：restore 经典算法（OpenCV 去噪 + 维纳滤波去模糊）保底，
  upscale/colorize 依赖 ONNX 模型（缺失时任务明确失败并提示下载脚本）。
- **上传字节链路（D10 修复）**：此前前端"上传"仅登记元数据，无字节端点，
  真实任务必失败 `image_file_missing`；D10 新增 `POST /api/images/upload`
  （multipart），seed 与 upload 共用 `_normalize_and_register` 校验落盘，
  前端 `UploadView` 改为真实字节上传，回归测试覆盖该链路。

## 2. SSE 契约（GET /api/tasks/{id}/events）

事件流为 `text/event-stream`，帧格式：

```text
event: snapshot | update | done
data: {json}
```

| 事件 | 触发 | data 字段 |
|---|---|---|
| snapshot | 连接建立时立即推送一次 | 任务快照 + `seq`（见下） |
| update | 每次状态/进度/阶段变化 | 任务快照 + `seq`（见下） |
| done | 任务进入终态后推送并关闭连接 | 仅 `{task_id, ts}` |

快照字段（snapshot/update 共用，共 10 个）：

| 字段 | 说明 |
|---|---|
| task_id | 任务 ID |
| task_type | restore / upscale / colorize |
| status | queued / processing / succeeded / failed / cancelled |
| progress | 0~100 单调递增 |
| phase | decode / preprocess / infer / postprocess / save |
| params_hash | 参数规范 JSON 的 SHA-256 指纹 |
| error | 失败原因（成功/取消为 null） |
| result | 成功时的结果（含 outputs 产物列表） |
| ts | ISO 时间戳 |
| seq | 事件序号，单调递增（重连续传游标） |

其他约定：15s 无事件时发送 `: ping` 心跳注释行；客户端断开不影响任务执行；
终态后仍可订阅（先 snapshot → 补发缓冲 update → done）；前端另有轮询兜底。

## 3. API 契约

统一错误体：`{"error": {"code", "message", "details"}}`。

| 端点 | 方法 | 成功 | 主要错误 |
|---|---|---|---|
| /api/health | GET | 200 | - |
| /api/images | GET/POST | 200/201 | 400 unsupported_format |
| /api/images/upload | POST | 201 | 400 unsupported_format / 400 invalid_image / 413 image_too_large |
| /api/images/seed | POST | 201 | 400 invalid_base64 / 413 |
| /api/images/{id} | GET/DELETE | 200 | 404 image_not_found |
| /api/images/{id}/download | GET | 200 | 404 |
| /api/tasks | GET/POST | 200/201 | 404 image_not_found / 422 invalid_params |
| /api/tasks/batch | POST | 201 | 422 / 404（整体失败无残留） |
| /api/tasks/{id} | GET | 200 | 404 task_not_found |
| /api/tasks/{id}/events | GET | 200 SSE | 404 / 503 |
| /api/tasks/{id}/cancel | POST | 200 | 404 / 409 invalid_state_transition |
| /api/tasks/{id}/rerun | POST | 200 | 404 / 409 task_not_terminal |
| /api/tasks/{id}/outputs/{index}/download | GET | 200 | 404 |
| /api/models | GET | 200 | - |
| /api/settings | GET/PUT | 200 | - |
| /api/storage | GET/DELETE | 200 | - |

状态机：`queued → processing → succeeded | failed | cancelled`；终态不可再迁移（409）。

D10 修复记录：单任务创建 `POST /api/tasks` 原先未做参数校验（与 batch 不一致），
现统一走 `validate_task_params`，非法参数返回 422 `invalid_params`（e2e 覆盖）。

## 4. 安全性

- **隐私本地**：无任何外部 API 调用；图像、模型、产物全部落在本机 `data/`、`models/`。
- **上传校验**：扩展名白名单 → 分块限量读取（20MB，超限 413 且不落盘）→
  PIL 内容解码校验 → RGB 规范化落盘；文件名经 `Path.name` 清洗防路径穿越。
- **路径安全**：产物路径来自服务端生成（`task_id/image_id/hash` 拼接），下载按索引定位。
- **CORS**：本地开发放开 `*`（无凭据模式）；生产经 nginx 同源反代。
- **无凭据/无密钥**：单机个人工具，无用户体系与敏感配置。
- **SQL 注入面**：全部经 SQLite 参数化查询。

## 5. 测试与质量基线（v1.0.0）

| 项 | 结果 |
|---|---|
| pytest（含 D10 e2e 集成测试） | 158 passed |
| ruff check | 0 错误 |
| vitest（12 个文件） | 73 passed |
| vite build | exit 0 |

新增测试：`backend/tests/test_upload_api.py`（上传字节链路 7 例）、
`backend/tests/test_e2e_release.py`（发布验收完整链路 + 失败场景 2 例）、
`backend/tests/test_task_sse.py` 断言强化（快照 10 字段 + seq 单调 + done 精简）。
CI（.github/workflows/ci.yml）在 push/PR 时执行 ruff + pytest + vitest + build。

## 6. 已知问题

见 README「已知限制与已知问题」章节（chunk 体积、JS 未分包、act 警告、
starlette/httpx 弃用警告、React Router future flag、模型缺失行为等）。

## 7. 后续建议

1. **构建优化**：按路由分包 + 手动拆分 vendor（react/echarts），主 chunk 降到 500 kB 以下。
2. **多用户/鉴权**：当前为单机单用户；若开放访问需加认证与 SSE 鉴权。
3. **上传体验**：分片/断点续传、并发上传、EXIF 方向归一化。
4. **模型管理**：启动时懒加载校验 + 设置页热下载进度（当前下载为脚本）。
5. **执行器**：并发 >1 时注意 SQLite 写锁与任务隔离；可评估外部队列（Redis）与
   事件总线外置，支撑多实例部署。
6. **端到端**：增加浏览器级 e2e（Playwright）覆盖上传→SSE→画廊真实交互。
7. **发布流水线**：CI 增加 tag 触发构建镜像并推送 registry、自动生成 Release。
8. **可观测性**：结构化日志 + 请求耗时/队列深度指标 + 任务失败告警。