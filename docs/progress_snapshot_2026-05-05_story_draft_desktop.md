# 版本快照：桌面端 Story Draft 主线补齐

日期：2026-05-05
文件：progress_snapshot_2026-05-05_story_draft_desktop.md

## 本轮施工结论

本轮在上一版“桌面端双模式对齐”的基础上，继续补齐桌面端 Flet 的 Story Draft 主线。

当前桌面端已不再只是 Story runtime / workspace 客户端，而是具备：

- 生成互动小说草案
- 编辑故事蓝图字段
- 编辑章节大纲
- 编辑故事世界书草案
- 查看连续性检查结果
- 应用为新故事
- 覆盖当前故事

后端仍复用既有 `/api/generation/jobs`，没有新增 story 专属 apply API。

## 本轮新增能力

### 1. 桌面端 Story Draft 生成入口

修改文件：

- `clients/flet_client_main.py`

新增桌面端控件：

- `story_draft_prompt`
- `story_draft_generate_btn`
- `story_draft_status`
- `story_draft_card`

新增行为：

- 用户在互动小说模式输入自然语言需求
- 点击 `生成故事草案`
- 客户端调用：
  - `POST /api/generation/jobs`
  - `pipeline_type = story_project`
  - `apply_mode = draft_only`
  - `run_async = true`
- 客户端轮询 job 状态
- 完成后读取 artifacts
- 优先读取 `story_bundle`
- 若无 bundle，则从单独 artifacts 拼装：
  - `story_blueprint`
  - `story_lorebook`
  - `story_continuity_review`
  - `illustration_prompt`
  - `audio_plan`

### 2. 桌面端 Story Draft 可编辑表单

新增可编辑字段：

- 草案标题
- 草案前提
- 草案开场
- 草案叙事规则
- 叙事风格
- 主角设定
- 章节大纲（每行一章，至少 3 行）
- 世界书条目（`关键词 | 排序 | 插入文本`，每行一条）
- 插图提示词
- 音频方案
- 连续性检查只读展示

### 3. 桌面端 Story Draft 应用

新增按钮：

- `应用为新故事`
- `覆盖当前故事`

应用逻辑：

- 读取当前编辑后的 Story Draft 表单
- 构造 `story_draft_payload`
- 本地先做最小校验：
  - 标题非空
  - 前提非空
  - 开场非空
  - 章节至少 3 条
  - 世界书至少 1 条有效 entry
- 调用同一主线：
  - `POST /api/generation/jobs`
  - `pipeline_type = story_project`
  - `apply_mode = direct_apply`
  - `story_draft_payload = 当前编辑后的草案`
- `应用为新故事` 不传 `story_project_id`
- `覆盖当前故事` 传当前选中故事的 `story_project_id`
- 应用成功后读取 `story_bundle.apply_result.project_id`
- 重新加载故事列表
- 自动打开落库后的 Story Workspace

### 4. 验证环境恢复

本轮开始时重新检查 Python 环境，当前已恢复：

- `py -0p` 可识别 Python 3.13
- `D:\MyProjects\.venv\Scripts\python.exe --version` 可执行

这解除上一版快照中的 `py_compile` 环境阻塞。

## 验证结果

### 1. 编译检查通过

已执行：

```powershell
D:\MyProjects\.venv\Scripts\python.exe -m py_compile `
  .\trial1\app\main.py `
  .\trial1\app\services.py `
  .\trial1\app\repositories.py `
  .\trial1\app\schemas.py `
  .\trial1\clients\flet_client_main.py
```

结果：通过。

### 2. Story generation smoke 通过

使用 FastAPI `TestClient` 验证：

- `story_project + draft_only` 生成成功
- artifacts 包含：
  - `intent`
  - `dispatch_plan`
  - `story_blueprint`
  - `story_lorebook`
  - `illustration_prompt`
  - `audio_plan`
  - `story_continuity_review`
  - `story_bundle`
- 使用 `story_draft_payload + direct_apply` 落库成功
- 能通过 `GET /api/story/projects/{project_id}` 读取落库项目
- 测试项目已通过 `DELETE /api/story/projects/{project_id}` 清理

Smoke 输出摘要：

```text
draft_job 200 completed
draft_artifacts 200 ['intent', 'dispatch_plan', 'story_blueprint', 'story_lorebook', 'illustration_prompt', 'audio_plan', 'story_continuity_review', 'story_bundle']
apply_job 200 completed
project_get 200 The Enigma of Echoes
cleanup <project_id>
```

## 当前桌面端状态

### Role Play

仍保持：

- 角色草案生成
- 角色保存
- 已保存角色编辑
- 已保存角色删除
- 角色聊天
- 角色导出
- 角色段落级 AIGC

### Interactive Fiction

当前已具备：

- 手动创建故事项目
- 生成故事草案
- 编辑故事草案
- 应用故事草案为新故事
- 覆盖当前故事
- 故事项目编辑
- 故事项目删除
- Story Workspace
- 故事续写
- 故事事实记忆展示
- 检查点展示与回滚
- 项目世界书管理
- Story 段落级 AIGC

## 当前已知限制

- 桌面端 Story Draft 的章节编辑仍是“每行一章”的轻量表单，不是 Web 端那种章节卡片式增删编辑器。
- 桌面端 Story Draft 的世界书编辑采用文本行格式，不是 Web 端条目卡片式编辑器。
- Flet UI 仍需要一次真实桌面启动手测，验证按钮布局、滚动体验和对话工作区高度是否符合预期。
- 当前工作区仍有大量历史删除、新增、修改，尚未形成提交切点。

## 施工方向调整建议

从本轮开始，建议不要继续优先堆新功能。项目已经具备 Role Play 与 Interactive Fiction 的双主线雏形，下一阶段应转入：

### 方向 A：稳定性与回归优先

优先级最高。

建议施工项：

1. 桌面端真实启动手测
2. Web 端完整 E2E 回归
3. 角色主线回归
4. Story Draft → Apply → Workspace → Continue 回归
5. 删除、覆盖、回滚等破坏性操作回归

目标：保证现有功能不会互相破坏。

### 方向 B：提交前清理与可发布形态

优先级次高。

建议施工项：

1. 修复 README 与启动说明
2. 明确保留 / 删除清单
3. 源码密钥扫描
4. 清理旧网关、Docker、APK 相关残留的提交策略
5. 建立一次稳定提交点

目标：让仓库能被干净下载、运行、审查。

### 方向 C：交互体验细化

优先级低于稳定性。

建议施工项：

1. 桌面端 Story Draft 章节卡片化编辑
2. 桌面端 Story Draft 世界书条目卡片化编辑
3. Story continuity review 修复建议
4. Story action 图片结果预览
5. 导出 Story 项目包

目标：提高产品易用性，而不是继续扩张架构。

## 建议下一轮施工包

建议下一轮不要再加大功能面，而是执行：

`本地真实回归 + README/启动链路修复 + 提交前清理`

这是当前项目从开发态进入可评审态的必要步骤。
