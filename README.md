# AI Chat Trial

## 项目定位

本项目是本地运行的 TavernAI 类 AI Chat MVP：

- FastAPI 本地后端
- Flet 桌面客户端
- 手动配置模型 API
- 对话式创建角色草案
- 角色保存、聊天、上下文压缩、世界书与段落级 AIGC
- 角色包导入导出
- Web App 版本：浏览器访问本地后端即可使用

## 快速启动

```powershell
cd <project-root>
D:\MyProjects\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\start_local.ps1
```

也可以使用单进程入口：

```powershell
D:\MyProjects\.venv\Scripts\python.exe run_all_in_one.py
```

## Web App 入口

启动后端后访问：

```text
http://127.0.0.1:8000/
```

Web App 支持：

- 模型 BYOK 配置
- 任务模型端点新增与查看
- 对话式生成角色草案
- 编辑草案并保存角色
- 左侧角色列表
- 角色聊天
- 段落级图片提示词 / 音频方案生成
- 角色 `.aichat` 导出

## 本地私有配置

复制 `.env.local.example` 为 `.env.local`，再填入本地 API 配置。
