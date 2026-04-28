# 项目进度快照 - 2026-04-28

## 1. 当前定位

项目当前主线已收敛为“本地运行的 TavernAI 类 AI Chat MVP”：

- 本地启动 FastAPI 后端与 Flet 桌面客户端
- 用户手动配置模型接口与 API Key
- 角色创建以自然语言对话为入口，生成可编辑草案
- 草案包含角色设定、系统提示词、开场白、世界书与资产提示词等基础内容
- 支持角色保存、聊天、长期上下文压缩、段落级 AIGC、导入导出
- 网关、Docker、Web 静态前端已从当前主线隔离，不参与本地 MVP 启动

## 2. 当前保留源码结构

```text
trial1/
  app/
    __init__.py
    agent_runtime.py          # RAG/Search/工具调用/段落级 AIGC 支撑
    main.py                   # FastAPI API 路由与服务装配
    packaging.py              # 角色包导入导出
    quota.py                  # 本地试用额度逻辑，后续可继续复用
    repositories.py           # SQLite 持久层
    schemas.py                # Pydantic API Schema
    services.py               # 核心业务逻辑
  clients/
    __init__.py
    flet_client_main.py       # 当前主 Flet 客户端
  docs/
    frontend_technical_spec_2026-04-13.md
    progress_snapshot_2026-04-12.md
    progress_snapshot_2026-04-28.md
  scripts/
    prepare_mvp_release.ps1   # MVP 发布净化脚本
    start_local.ps1           # 本地启动脚本
  .env.local.example          # 本地私有配置模板
  .gitignore
  flet_client.py              # 兼容启动入口
  main.py                     # 后端兼容入口
  README.md
  requirements.txt
  run_all_in_one.py           # 单进程本地启动入口
```

## 3. 当前被隔离或不应提交的内容

- `.env.local`：存在于本地，已被 `.gitignore` 排除；不得提交或打包泄露真实 Key
- `data/`：存在本地运行数据库与设备 ID，已忽略
- `_release_mvp/`：存在净化后的发布工作目录与构建产物，已忽略
- `__pycache__/`、`.pyc`：存在本地编译缓存，已忽略
- `static/`：当前目录为空，旧 Web 静态前端已从 Git 视角删除

## 4. Git 当前状态摘要

当前工作区尚未提交，主要变化方向为：

- 删除或隔离旧网关、Docker、静态 Web 前端、拓扑图、旧文档与旧构建脚本
- 修改本地 MVP 主线文件：`README.md`、`requirements.txt`、`run_all_in_one.py`、`scripts/start_local.ps1`、`app/*`、`clients/flet_client_main.py`
- 新增本地配置模板、Agent Runtime、前端技术规范、最新快照与发布净化脚本

提交前建议先人工确认：

- 网关与 Docker 是否仅保留在历史版本，不进入当前 MVP 分支
- README 是否需要修复编码乱码后再提交
- `_release_mvp/` 是否仅作为本地构建目录，不纳入仓库

## 5. 功能完成状态

### 已具备

- 本地 FastAPI API 服务
- Flet 桌面客户端
- 模型配置入口
- 多任务模型配置基础结构
- Core LLM 与任务模型的服务层抽象
- 角色自然语言生成草案
- 角色草案保存与应用
- 角色列表与角色聊天入口
- 聊天历史持久化
- 长期上下文压缩与 RAG 支撑
- 世界书、角色卡、提示词、资产提示词等结构化生成
- 段落级 AIGC 行为记录与接口闭环
- 角色 `.aichat` 导入导出
- PNG 隐写导入导出接口
- 120 秒无输出保护逻辑
- MVP 发布净化脚本

### 部分完成

- 图片生成接口：后端链路已接入，实际稳定性依赖外部模型配置
- 搜索增强创角：Tavily/搜索工具结构存在，仍需按真实使用场景继续调优
- APK 打包链路：Android SDK、Flutter、JDK 链路曾推进到 Gradle 阶段，但当前未发现最终 `.apk` 文件
- EXE 打包链路：本地 `_release_mvp/dist/AIChatMVP/AIChatMVP.exe` 已存在

### 待完成或待确认

- README 当前存在编码乱码，需要修复后再作为正式仓库说明
- Flet APK 打包需要重新执行一次干净构建并确认产物
- 真实模型接口的端到端稳定性需要按用户手动配置场景再测
- 段落级 AIGC 的移动端长按体验仍需真机测试
- UI 细节还需要基于 MVP 测试反馈继续收敛

## 6. 验证结果

本次快照前执行了以下检查：

- Python 编译检查：通过
- 源码密钥扫描：未在可提交源码中发现 `sk-` 或 `tvly-` 形式密钥
- APK 产物检查：未发现 `.apk`
- EXE 产物检查：发现 `_release_mvp/dist/AIChatMVP/AIChatMVP.exe`
- `.gitignore` 检查：已忽略 `.env.local`、`data/`、`_release_mvp/`、构建产物与缓存

## 7. 当前风险

- README 乱码会影响仓库可读性，提交前应修复
- 当前工作区存在大量删除与新增，提交前需要确认清理范围
- APK 打包不是已完成状态，不能声明 Android MVP 已产出
- 本地 `.env.local` 有真实私有配置，打包前必须继续排除
- `_release_mvp/` 中存在历史构建内容，只能作为本地构建缓存，不应作为源码依据

## 8. 下一步建议

1. 修复 README 编码与内容，保证仓库下载后可直接阅读
2. 确认 Git 删除清单，将当前主线提交为“local MVP cleanup”切点
3. 重新执行 `prepare_mvp_release.ps1` 生成干净发布目录
4. 先完成 Windows EXE 回归测试
5. 再重新执行 APK 打包，并保存 Gradle/Flutter 失败日志或最终 APK 路径
6. 做一轮真实模型配置端到端测试：创角、草案、聊天、段落 AIGC、导出

