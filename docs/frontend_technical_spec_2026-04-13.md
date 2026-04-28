# 前端技术规范（前后端对齐与稳定性）

- 文档版本：v1.0
- 日期：2026-04-13
- 适用范围：`trial1` 基础版（Flet 客户端 + FastAPI 后端）

## 1. 目标
本规范用于约束前端实现，确保：
1. 前后端接口字段与状态码对齐。
2. Flet 运行时兼容（当前基线：`flet==0.83.0`）。
3. 常见交互链路不报错（创建角色、聊天流式输出、导出、AIGC 动作、设置保存）。

## 2. 技术基线
- 前端：Python + Flet（`flet==0.83.0`）
- 后端：FastAPI（`main.py -> app.main:app`）
- 网络：`httpx` 异步请求
- 本地存储：`data/device_id.txt`（当 `Page.client_storage` 不可用时）

## 3. 目录与职责
- 前端入口：`flet_client.py`
- 前端主实现：`clients/flet_client_main.py`
- 后端入口：`main.py`
- 后端路由：`app/main.py`
- 数据目录：`data/`

前端必须以 `clients/flet_client_main.py` 作为唯一主实现，避免并行 UI 文件导致接口漂移。

## 4. Flet 兼容规范（强制）
### 4.1 图标
- 必须使用 `ft.Icons.*`。
- 禁止使用 `ft.icons.*`（在 0.83.0 下可能不存在属性）。

### 4.2 对话框与提示
- `AlertDialog`：使用 `dialog.open = True/False` + `page.update()`。
- `SnackBar`：使用 `page.overlay.append(bar)` + `bar.open = True` + `page.update()`。
- 禁止使用 `page.open(...)` / `page.close(...)`（当前版本 `Page` 无该方法）。

### 4.3 设备标识存储
- 优先：`page.client_storage`（若运行模式支持）。
- 回退：`data/device_id.txt`。
- 禁止直接假设 `page.client_storage` 一定存在。

### 4.4 窗口对象
- 使用 `window = getattr(page, "window", None)` 做空值保护后再写入窗口尺寸。

## 5. 前后端接口契约（当前前端实际依赖）
以下接口为前端必须对齐的最小集合。

### 5.1 设置
1. `GET /api/settings`
- 用途：初始化模式与模型配置。
- 返回：`AppSettingsResponse`

2. `PUT /api/settings`
- 请求：`{ mode, byok_base_url, byok_model, byok_api_key? }`
- 返回：`AppSettingsResponse`

### 5.2 角色生成流水线
1. `POST /api/generation/jobs`
- 请求：`{ user_input, include_illustration_prompt, include_audio_plan, run_async }`
- 返回：`GenerationJobResponse`（含 `job_id`）

2. `GET /api/generation/jobs/{job_id}`
- 用途：轮询 `status`（`completed/failed/cancelled/...`）

3. `GET /api/generation/jobs/{job_id}/artifacts`
- 用途：读取 `bundle / character_card / lorebook / illustration_prompt / audio_plan`

4. `POST /api/generation/jobs/{job_id}/cancel`
- 用途：超时主动中断任务

5. 回退接口：`POST /api/wizard/generate-character`
- 用途：流水线失败时生成基础草案

### 5.3 角色与世界书
1. `GET /api/characters`
2. `POST /api/characters`
3. `POST /api/lorebooks`
4. `GET /api/characters/{character_id}/export`

### 5.4 聊天
1. `POST /api/chat/start?character_id=...`
- 返回：`{ session_id, welcome_message, character_id }`

2. `POST /api/chat/message/stream`
- 请求：`{ session_id, message, device_id? }`
- 返回：SSE（见第 6 节）

3. `GET /api/chat/actions/{session_id}`
4. `POST /api/chat/actions`

## 6. SSE 事件协议（聊天流式）
后端事件（`/api/chat/message/stream`）定义：
1. `event: context`
- data: `ChatContextStatsResponse`

2. `event: chunk`
- data: `{ "delta": "..." }`

3. `event: done`
- data: `{ session_id, reply, history_count, context_stats, metrics, quota }`

4. `event: error`
- data: `{ detail: "..." }`

前端处理规则：
- 仅 `chunk` 追加正文。
- `done` 作为一次请求的完成信号。
- `error` 必须落地为可见错误消息，不得静默吞掉。

## 7. 超时与中断规范
- 前端全局操作超时：`120s`。
- 超时后行为：
1. 停止当前请求（或触发后端 cancel）。
2. 恢复输入控件可编辑状态。
3. 输出清晰提示，且不破坏已有会话内容。

## 8. UI 状态机规范
### 8.1 构建模式（Builder）
- 输入发送后：
1. 禁用输入与发送按钮。
2. 显示“正在生成”占位。
3. 成功后展示草案卡；失败走回退接口。
4. 完成后必须恢复输入可用并聚焦输入框。

### 8.2 角色模式（Role Chat）
- 会话未初始化禁止发送。
- 发送时插入用户消息与 assistant 占位。
- 流式完成后恢复输入可用。

## 9. 错误处理规范
- 非 2xx 统一转为 `ApiError(detail)`。
- 错误展示采用统一 toast，不允许仅打印日志。
- 状态码语义必须前后端一致：
1. `400` 参数/配置错误
2. `404` 资源不存在（角色/会话等）
3. `409` 状态冲突（如任务不可 rerun/cancel）
4. `429` 配额超限
5. `502` 上游模型错误

## 10. 前后端对齐清单（每次改动后执行）
1. 前端调用的每个路径，在 `app/main.py` 中必须存在且语义一致。
2. 前端请求字段名必须匹配 `app/schemas.py`（大小写、可选性、长度约束）。
3. SSE 事件名仅允许 `context/chunk/done/error`。
4. 任何新增字段必须同时更新：
- 后端 `schemas.py`
- 前端解析逻辑
- 本文档接口契约

## 11. 质量门禁（本地）
发布前至少执行：
```powershell
# 后端可启动
python -m uvicorn main:app --host 127.0.0.1 --port 8000

# 前端语法检查
python -m py_compile flet_client.py clients/flet_client_main.py
```

手工回归最小用例：
1. 打开客户端不报错。
2. 生成草案成功/回退均可展示。
3. 角色保存后出现在左侧列表。
4. 聊天流式可持续输出并收尾。
5. 导出角色成功。
6. AIGC 动作可执行并显示结果。

## 12. 变更原则
- 优先保持接口稳定，必要时向后兼容。
- 前端新增能力必须先对齐后端契约，再接入 UI。
- 若运行时兼容与业务功能冲突，先保证“可运行与不报错”。
