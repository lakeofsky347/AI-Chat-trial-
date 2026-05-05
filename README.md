# AI Chat Trial

本项目是一个本地运行的 TavernAI 类 AI Chat MVP，当前包含两条主线：

- `Role Play`：角色创建、角色卡保存、长期对话、世界书、上下文压缩、段落级 AIGC、角色包导出。
- `Interactive Fiction`：互动小说项目、故事草案生成、章节大纲、项目世界书、故事续写、事实记忆、检查点与段落级 AIGC。

项目默认本地运行，模型 API 由用户在本地手动配置。真实密钥应写入 `.env.local` 或在应用内配置，不应提交到仓库。

## 技术结构

- 后端：FastAPI + SQLite
- 桌面端：Flet
- Web 端：原生 HTML/CSS/JavaScript
- 模型配置：BYOK + 任务端点绑定
- 数据目录：本地 `data/`，已被 `.gitignore` 排除

## 快速启动

安装依赖：

```powershell
cd <project-root>
D:\MyProjects\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

启动后端和桌面端：

```powershell
.\scripts\start_local.ps1
```

也可以使用单进程入口：

```powershell
D:\MyProjects\.venv\Scripts\python.exe run_all_in_one.py
```

## Web App

启动后端后访问：

```text
http://127.0.0.1:8000/
```

Web 端支持：

- 模型 BYOK 配置
- 任务模型端点与任务绑定
- 角色草案生成、编辑、保存与对话
- 互动小说草案生成、编辑、应用
- Story Workspace：续写、事实、检查点、世界书、段落级 AIGC

## 桌面端

桌面端 Flet 当前支持：

- `角色扮演 / 互动小说` 双模式切换
- 角色创建、编辑、删除、聊天、导出
- 故事项目创建、编辑、删除
- 故事草案生成与应用
- 故事 Workspace、项目世界书、检查点、段落级 AIGC

## 本地私有配置

复制 `.env.local.example` 为 `.env.local`，再填入本地 API 配置：

```powershell
Copy-Item .env.local.example .env.local
```

注意：

- `.env.local` 已被 `.gitignore` 排除。
- `data/` 包含本地数据库、导出文件和运行缓存，不应提交。
- 不要将真实 API Key、浏览器调试 profile、构建产物提交到仓库。
