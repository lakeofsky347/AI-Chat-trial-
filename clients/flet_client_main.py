from __future__ import annotations

import asyncio
import json
import os
import re
import time
import hmac
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import flet as ft
import httpx

API_BASE = "http://127.0.0.1:8000/api"
OPERATION_TIMEOUT_SECONDS = 120.0
GENERATION_POLL_INTERVAL_SECONDS = 1.2
REQUEST_TIMEOUT = max(5.0, min(180.0, float(os.getenv("CLIENT_REQUEST_TIMEOUT_SECONDS", "125") or "125")))
DEVICE_SIGNING_SECRET = os.getenv("TRIAL_GATEWAY_DEVICE_SIGNING_SECRET", "dev-secret-key")

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F9FAFB",
        "surface": "#FFFFFF",
        "border": "#E5E7EB",
        "text": "#111827",
        "muted": "#6B7280",
        "primary": "#2563EB",
        "assistant": "#FFFFFF",
        "user": "#F3F4F6",
        "sidebar": "#F9FAFB",
        "sidebar_active": "#EFF6FF",
        "success": "#059669",
        "danger": "#DC2626",
    },
    "dark": {
        "bg": "#030712",
        "surface": "#111827",
        "border": "#1F2937",
        "text": "#F9FAFB",
        "muted": "#9CA3AF",
        "primary": "#3B82F6",
        "assistant": "#111827",
        "user": "#1F2937",
        "sidebar": "#030712",
        "sidebar_active": "#1E3A8A",
        "success": "#10B981",
        "danger": "#EF4444",
    },
}

TASK_BINDING_DEFS: list[tuple[str, str]] = [
    ("intent_parse", "意图解析"),
    ("plan_dispatch", "任务分发"),
    ("character_card_generate", "角色卡生成"),
    ("lorebook_generate", "世界书生成"),
    ("story_blueprint_generate", "故事蓝图生成"),
    ("story_lorebook_generate", "故事世界书生成"),
    ("story_continuity_review", "故事连续性审核"),
    ("story_continue", "故事续写"),
    ("illustration_prompt_generate", "插图提示词"),
    ("audio_plan_generate", "音频方案"),
    ("result_review", "结果审核"),
]

class ApiError(Exception):
    pass

class OperationTimeoutError(ApiError):
    pass

def _extract_error_message(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail
    except Exception:
        pass
    text = (resp.text or "").strip()
    return text if text else f"HTTP {resp.status_code}"

def _extract_filename(disposition: str | None, default_name: str) -> str:
    if not disposition:
        return default_name
    matched = re.search(r'filename="?([^";]+)"?', disposition)
    if not matched:
        return default_name
    name = matched.group(1).strip()
    return name or default_name

async def _api_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.request(
            method=method,
            url=f"{API_BASE}{path}",
            json=payload,
            params=params,
            headers=headers,
        )
    if resp.status_code >= 400:
        raise ApiError(_extract_error_message(resp))
    return resp

async def _api_request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    resp = await _api_request(method, path, payload=payload, params=params, headers=headers)
    return resp.json()

def main(page: ft.Page) -> None:
    page.title = "AI Roleplay"
    page.padding = 0
    page.spacing = 0
    project_root = Path(__file__).resolve().parent.parent
    
    # [规范 4.4 强制] 窗口对象空值保护
    window = getattr(page, "window", None)
    if window is not None:
        window.width = 1360
        window.height = 880
        window.min_width = 1020
        window.min_height = 700

    # [规范 4.3 强制] 设备标识存储回退策略
    device_id_path = project_root / "data" / "device_id.txt"

    def get_or_create_device_id() -> str:
        storage = getattr(page, "client_storage", None)
        if storage is not None:
            try:
                cached = storage.get("device_id")
                if cached:
                    return str(cached)
                new_id = str(uuid.uuid4())
                storage.set("device_id", new_id)
                return new_id
            except Exception:
                pass

        try:
            device_id_path.parent.mkdir(parents=True, exist_ok=True)
            if device_id_path.exists():
                cached_file_id = device_id_path.read_text(encoding="utf-8").strip()
                if cached_file_id:
                    return cached_file_id
            new_id = str(uuid.uuid4())
            device_id_path.write_text(new_id, encoding="utf-8")
            return new_id
        except OSError:
            return str(uuid.uuid4())

    device_id = get_or_create_device_id()

    def get_auth_headers() -> dict[str, str]:
        quota_date = datetime.now(timezone.utc).date().isoformat()
        payload = f"{device_id}:{quota_date}".encode("utf-8")
        secret = DEVICE_SIGNING_SECRET.encode("utf-8")
        signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return {
            "x-device-id": device_id,
            "x-device-signature": signature
        }

    # API Wrappers with Auth injected
    async def api_get(path: str, params: dict[str, Any] | None = None) -> Any:
        return await _api_request_json("GET", path, params=params, headers=get_auth_headers())

    async def api_put(path: str, payload: dict[str, Any]) -> Any:
        return await _api_request_json("PUT", path, payload=payload, headers=get_auth_headers())

    async def api_delete(path: str, params: dict[str, Any] | None = None) -> None:
        await _api_request("DELETE", path, params=params, headers=get_auth_headers())

    async def api_post(path: str, payload: dict[str, Any], params: dict[str, Any] | None = None) -> Any:
        return await _api_request_json("POST", path, payload=payload, params=params, headers=get_auth_headers())

    async def api_export_character(character_id: str) -> tuple[bytes, str]:
        resp = await _api_request("GET", f"/characters/{character_id}/export", headers=get_auth_headers())
        filename = _extract_filename(resp.headers.get("content-disposition"), f"{character_id}.aichat")
        return resp.content, filename

    state: dict[str, Any] = {
        "is_dark": False,
        "active_mode": "roleplay",
        "characters":[],
        "selected_character": None,
        "editing_character_id": None,
        "selected_session_id": None,
        "builder_notes": [],
        "builder_messages":[],
        "role_messages": [],
        "role_actions":[],
        "draft_lorebook_entries":[],
        "action_scope": "roleplay",
        "stories": [],
        "selected_story": None,
        "editing_story_id": None,
        "story_session_id": None,
        "story_session": None,
        "story_messages": [],
        "story_facts": [],
        "story_checkpoints": [],
        "story_lorebooks": [],
        "editing_story_lorebook_id": None,
        "story_actions": [],
        "story_context_stats": None,
        "story_draft_payload": None,
        "settings": {
            "mode": "trial",
            "byok_base_url": "",
            "byok_model": "",
            "has_api_key": False,
        },
        "model_endpoints": [],
        "selected_endpoint_id": None,
        "endpoint_health_by_id": {},
        "task_endpoint_bindings": {},
    }

    export_dir = project_root / "data" / "exports"

    def c(key: str) -> str:
        return PALETTES["dark" if state["is_dark"] else "light"][key]

    # [规范 4.2 强制] 弹窗与 Toast 标准
    def show_toast(message: str, *, error: bool = False) -> None:
        bar = ft.SnackBar(
            content=ft.Text(message, color="#FFFFFF"),
            bgcolor=c("danger") if error else "#111827",
        )
        page.overlay.append(bar)
        bar.open = True
        page.update()

    def format_action_result(result: dict[str, Any]) -> str:
        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception:
            return str(result)

    # ---- controls ----
    sidebar_title = ft.Text("AI Roleplay", size=20, weight=ft.FontWeight.W_700)
    sidebar_subtitle = ft.Text("双模式桌面端", size=12)
    roleplay_mode_btn = ft.ElevatedButton(content=ft.Text("角色扮演"))
    story_mode_btn = ft.TextButton(content=ft.Text("互动小说"))

    create_new_btn = ft.ElevatedButton(
        content=ft.Text("+ 新建角色", weight=ft.FontWeight.W_600),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=16), padding=16),
    )
    nav_section_title = ft.Text("我的角色", size=13, weight=ft.FontWeight.W_600)
    character_list = ft.ListView(expand=True, spacing=8, padding=2)

    header_title = ft.Text("角色创建向导", size=24, weight=ft.FontWeight.W_700)
    header_subtitle = ft.Text("用自然语言描述角色，系统自动生成草案", size=14)
    mode_badge = ft.Text("草案模式：LOCAL", size=12, weight=ft.FontWeight.W_600)

    theme_label = ft.Text("浅色", size=12, weight=ft.FontWeight.W_600)
    theme_switch = ft.Switch(value=False)
    settings_btn = ft.TextButton(content=ft.Text("模型设置"))
    edit_btn = ft.TextButton(content=ft.Text("编辑"), visible=False)
    delete_btn = ft.TextButton(content=ft.Text("删除"), visible=False)
    export_btn = ft.ElevatedButton(
        content=ft.Text("导出角色"), visible=False,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=12),
    )
    back_to_builder_btn = ft.TextButton(content=ft.Text("返回创建"), visible=False)

    builder_chat = ft.ListView(expand=True, spacing=16, auto_scroll=True)
    builder_input = ft.TextField(hint_text="例如：创建一个冷静、专业的反派角色", expand=True, border_radius=24, content_padding=20)
    
    # [规范 4.1 强制] 使用大写 ft.Icons
    builder_send_btn = ft.IconButton(
        icon=ft.Icons.ARROW_UPWARD, icon_color="#FFFFFF", bgcolor=c("primary")
    )
    
    draft_source = ft.Text("草案来源：未生成", size=12, weight=ft.FontWeight.W_700)
    draft_route_note = ft.Text("提示：当前还没有生成草案。", size=12)
    draft_name = ft.TextField(label="角色名称", border_radius=12)
    draft_desc = ft.TextField(label="角色简介", multiline=True, min_lines=2, max_lines=4, border_radius=12)
    draft_first = ft.TextField(label="开场白", multiline=True, min_lines=2, max_lines=4, border_radius=12)
    draft_system = ft.TextField(label="系统设定", multiline=True, min_lines=4, max_lines=8, border_radius=12)
    draft_lorebook = ft.TextField(label="世界书（草案）", multiline=True, min_lines=4, max_lines=8, border_radius=12)
    draft_illustration = ft.TextField(label="人物插图提示词（草案）", multiline=True, min_lines=2, max_lines=4, border_radius=12)
    draft_audio = ft.TextField(label="音频方案（草案）", multiline=True, min_lines=2, max_lines=4, border_radius=12)
    save_role_btn = ft.ElevatedButton(
        content=ft.Text("保存并开始对话"),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=16), padding=16),
    )

    draft_card = ft.Container(
        visible=False, border_radius=20, padding=24,
        content=ft.Column(
            spacing=12,
            controls=[
                ft.Text("草案结果（可编辑）", weight=ft.FontWeight.W_700, size=16),
                draft_source, draft_route_note, draft_name, draft_desc,
                draft_first, draft_system, draft_lorebook, draft_illustration,
                draft_audio, save_role_btn,
            ],
        ),
    )

    builder_view = ft.Column(
        expand=True, scroll=ft.ScrollMode.AUTO, spacing=16,
        controls=[
            ft.Container(height=360, border_radius=20, padding=16, content=builder_chat),
            ft.Row([builder_input, builder_send_btn], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            draft_card,
        ],
    )

    detail_name = ft.Text("", size=20, weight=ft.FontWeight.W_800)
    detail_desc = ft.Text("", size=13)
    detail_first = ft.Text("", size=14, selectable=True)

    role_chat = ft.ListView(expand=True, spacing=16, auto_scroll=True)
    role_input = ft.TextField(hint_text="发送消息...", expand=True, border_radius=24, content_padding=20)
    role_send_btn = ft.IconButton(
        icon=ft.Icons.ARROW_UPWARD, icon_color="#FFFFFF", bgcolor=c("primary")
    )
    action_history_title = ft.Text("对话内 AIGC 动作历史", weight=ft.FontWeight.W_700, size=12)
    action_history_list = ft.ListView(height=180, spacing=8, auto_scroll=True)

    role_view = ft.Column(
        visible=False, expand=True, scroll=ft.ScrollMode.AUTO, spacing=16,
        controls=[
            ft.Container(
                border_radius=20, padding=20,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        detail_name, detail_desc,
                        ft.Text("开场白", weight=ft.FontWeight.W_600, size=12),
                        detail_first,
                    ],
                ),
            ),
            ft.Container(
                height=580, border_radius=20, padding=20,
                content=ft.Column(
                    expand=True, spacing=12,
                    controls=[
                        ft.Text("角色对话", weight=ft.FontWeight.W_700),
                        role_chat,
                        ft.Row([role_input, role_send_btn], spacing=12),
                        ft.Divider(height=16, color=ft.Colors.TRANSPARENT),
                        action_history_title,
                        action_history_list,
                    ],
                ),
            ),
        ],
    )

    story_title = ft.TextField(label="故事标题", border_radius=12)
    story_premise = ft.TextField(label="故事设定 / 核心前提", multiline=True, min_lines=4, max_lines=8, border_radius=12)
    story_opening = ft.TextField(label="开场场景", multiline=True, min_lines=3, max_lines=6, border_radius=12)
    story_system = ft.TextField(label="叙事规则（可选）", multiline=True, min_lines=3, max_lines=6, border_radius=12)
    save_story_btn = ft.ElevatedButton(
        content=ft.Text("保存故事项目"),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=16), padding=16),
    )
    story_draft_prompt = ft.TextField(
        label="一句话生成故事草案",
        hint_text="例如：写一个赛博雨夜里的侦探互动小说，主角要追查失踪仿生人",
        multiline=True,
        min_lines=2,
        max_lines=5,
        border_radius=12,
    )
    story_draft_generate_btn = ft.ElevatedButton(
        content=ft.Text("生成故事草案"),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=16), padding=16),
    )
    story_draft_status = ft.Text("草案状态：未生成", size=12, weight=ft.FontWeight.W_700)
    story_draft_title = ft.TextField(label="草案标题", border_radius=12)
    story_draft_premise = ft.TextField(label="草案前提", multiline=True, min_lines=3, max_lines=6, border_radius=12)
    story_draft_opening = ft.TextField(label="草案开场", multiline=True, min_lines=3, max_lines=6, border_radius=12)
    story_draft_system = ft.TextField(label="草案叙事规则", multiline=True, min_lines=3, max_lines=6, border_radius=12)
    story_draft_tone = ft.TextField(label="叙事风格", border_radius=12)
    story_draft_protagonist = ft.TextField(label="主角设定", multiline=True, min_lines=2, max_lines=4, border_radius=12)
    story_draft_chapters = ft.TextField(
        label="章节大纲（每行一章，至少 3 行）",
        multiline=True,
        min_lines=4,
        max_lines=8,
        border_radius=12,
    )
    story_draft_lorebook = ft.TextField(
        label="世界书条目（格式：关键词 | 排序 | 插入文本，每行一条）",
        multiline=True,
        min_lines=4,
        max_lines=8,
        border_radius=12,
    )
    story_draft_illustration = ft.TextField(label="插图提示词", multiline=True, min_lines=2, max_lines=4, border_radius=12)
    story_draft_audio = ft.TextField(label="音频方案", multiline=True, min_lines=2, max_lines=4, border_radius=12)
    story_draft_review = ft.TextField(label="连续性检查", multiline=True, min_lines=2, max_lines=5, read_only=True, border_radius=12)
    story_draft_apply_new_btn = ft.ElevatedButton(
        content=ft.Text("应用为新故事"),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=16), padding=16),
    )
    story_draft_apply_current_btn = ft.TextButton(content=ft.Text("覆盖当前故事"))
    story_draft_card = ft.Container(
        visible=False,
        border_radius=20,
        padding=24,
        content=ft.Column(
            spacing=12,
            controls=[
                ft.Text("故事草案（可编辑后应用）", weight=ft.FontWeight.W_700, size=16),
                story_draft_status,
                story_draft_title,
                story_draft_premise,
                story_draft_opening,
                story_draft_system,
                ft.Row([story_draft_tone, story_draft_protagonist], spacing=12),
                story_draft_chapters,
                story_draft_lorebook,
                story_draft_illustration,
                story_draft_audio,
                story_draft_review,
                ft.Row([story_draft_apply_new_btn, story_draft_apply_current_btn], spacing=12),
            ],
        ),
    )

    story_builder_view = ft.Column(
        visible=False, expand=True, scroll=ft.ScrollMode.AUTO, spacing=16,
        controls=[
            ft.Container(
                border_radius=20, padding=24,
                content=ft.Column(
                    spacing=12,
                    controls=[
                        ft.Text("AI 故事草案生成", weight=ft.FontWeight.W_700, size=16),
                        ft.Text("输入自然语言需求，系统会生成故事蓝图、章节大纲、项目世界书和连续性检查。", size=12),
                        story_draft_prompt,
                        story_draft_generate_btn,
                    ],
                ),
            ),
            story_draft_card,
            ft.Container(
                border_radius=20, padding=24,
                content=ft.Column(
                    spacing=12,
                    controls=[
                        ft.Text("互动小说项目", weight=ft.FontWeight.W_700, size=16),
                        ft.Text("填写故事基础信息后保存到左侧故事栏。打开故事后可续写、管理世界书并触发段落级 AIGC。", size=12),
                        story_title,
                        story_premise,
                        story_opening,
                        story_system,
                        save_story_btn,
                    ],
                ),
            )
        ],
    )

    story_detail_title = ft.Text("", size=20, weight=ft.FontWeight.W_800)
    story_detail_premise = ft.Text("", size=13, selectable=True)
    story_summary = ft.Text("暂无摘要", size=13, selectable=True)
    story_scene = ft.Text("暂无当前场景", size=13, selectable=True)
    story_context_stats_text = ft.Text("上下文状态：未加载", size=12)

    story_chat = ft.ListView(expand=True, spacing=16, auto_scroll=True)
    story_input = ft.TextField(hint_text="输入你的选择、行动或下一段要求...", expand=True, border_radius=24, content_padding=20)
    story_send_btn = ft.IconButton(
        icon=ft.Icons.ARROW_UPWARD, icon_color="#FFFFFF", bgcolor=c("primary")
    )

    story_facts_list = ft.ListView(height=140, spacing=8, padding=2)
    story_checkpoints_list = ft.ListView(height=150, spacing=8, padding=2)
    story_actions_list = ft.ListView(height=180, spacing=8, padding=2, auto_scroll=True)

    story_lore_keyword = ft.TextField(label="触发词", border_radius=12)
    story_lore_text = ft.TextField(label="插入文本", multiline=True, min_lines=3, max_lines=6, border_radius=12)
    story_lore_order = ft.TextField(label="排序", value="100", border_radius=12)
    story_lore_enabled = ft.Switch(label="启用", value=True)
    story_lore_save_btn = ft.ElevatedButton(
        content=ft.Text("保存世界书条目"),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=12),
    )
    story_lore_clear_btn = ft.TextButton(content=ft.Text("清空表单"))
    story_lorebook_list = ft.ListView(height=220, spacing=8, padding=2)

    story_view = ft.Column(
        visible=False, expand=True, scroll=ft.ScrollMode.AUTO, spacing=16,
        controls=[
            ft.Container(
                border_radius=20, padding=20,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        story_detail_title,
                        story_detail_premise,
                        ft.Text("当前摘要", weight=ft.FontWeight.W_600, size=12),
                        story_summary,
                        ft.Text("当前场景", weight=ft.FontWeight.W_600, size=12),
                        story_scene,
                        story_context_stats_text,
                    ],
                ),
            ),
            ft.Container(
                height=620, border_radius=20, padding=20,
                content=ft.Column(
                    expand=True, spacing=12,
                    controls=[
                        ft.Text("互动小说续写", weight=ft.FontWeight.W_700),
                        story_chat,
                        ft.Row([story_input, story_send_btn], spacing=12),
                    ],
                ),
            ),
            ft.Row(
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(
                        expand=True, border_radius=20, padding=18,
                        content=ft.Column(
                            spacing=10,
                            controls=[
                                ft.Text("事实记忆", weight=ft.FontWeight.W_700),
                                story_facts_list,
                                ft.Divider(height=14, color=ft.Colors.TRANSPARENT),
                                ft.Text("检查点", weight=ft.FontWeight.W_700),
                                story_checkpoints_list,
                            ],
                        ),
                    ),
                    ft.Container(
                        expand=True, border_radius=20, padding=18,
                        content=ft.Column(
                            spacing=10,
                            controls=[
                                ft.Text("段落级 AIGC 动作历史", weight=ft.FontWeight.W_700),
                                story_actions_list,
                            ],
                        ),
                    ),
                ],
            ),
            ft.Container(
                border_radius=20, padding=18,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("项目世界书", weight=ft.FontWeight.W_700),
                        ft.Row([story_lore_keyword, story_lore_order], spacing=12),
                        story_lore_text,
                        ft.Row([story_lore_enabled, story_lore_save_btn, story_lore_clear_btn], spacing=12),
                        story_lorebook_list,
                    ],
                ),
            ),
        ],
    )

    sidebar = ft.Container(
        width=300, padding=24,
        content=ft.Column(
            expand=True, spacing=20,
            controls=[
                ft.Column([sidebar_title, sidebar_subtitle], spacing=4),
                ft.Row([roleplay_mode_btn, story_mode_btn], spacing=8),
                create_new_btn,
                nav_section_title,
                character_list,
            ],
        ),
    )

    header_right = ft.Row(
        spacing=12,
        controls=[theme_label, theme_switch, settings_btn, back_to_builder_btn, edit_btn, delete_btn, export_btn],
    )

    main_content = ft.Container(
        expand=True, padding=ft.padding.only(left=32, right=32, top=24, bottom=24),
        border_radius=ft.border_radius.only(top_left=32, bottom_left=32),
        content=ft.Column(
            expand=True, scroll=ft.ScrollMode.AUTO, spacing=16,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Column([header_title, header_subtitle, mode_badge], spacing=4),
                        header_right,
                    ],
                ),
                builder_view,
                role_view,
                story_builder_view,
                story_view,
            ],
        ),
    )

    page.add(ft.Row([sidebar, main_content], expand=True, spacing=0))

    # ---- dialogs ----
    byok_enable = ft.Switch(label="启用模型直连/草案 (BYOK)", value=False)
    byok_base = ft.TextField(label="API Base URL", hint_text="例如 https://api.openai.com/v1", border_radius=12)
    byok_model = ft.TextField(label="模型名", hint_text="例如 gpt-4o-mini", border_radius=12)
    byok_key = ft.TextField(label="API Key", password=True, can_reveal_password=True, border_radius=12)
    endpoint_status = ft.Text("任务模型端点：0", size=12, weight=ft.FontWeight.W_700)
    endpoint_health_status = ft.Text("健康状态：未检测", size=12)
    endpoint_selected_hint = ft.Text("未选择端点（将创建新端点）", size=12)
    endpoint_list = ft.ListView(height=180, spacing=8, padding=2)
    endpoint_health_list = ft.ListView(height=120, spacing=6, padding=2)
    endpoint_provider = ft.Dropdown(
        label="Provider",
        border_radius=12,
        options=[
            ft.dropdown.Option("deepseek", "deepseek"),
            ft.dropdown.Option("qwen", "qwen"),
            ft.dropdown.Option("kimi", "kimi"),
            ft.dropdown.Option("openai", "openai"),
            ft.dropdown.Option("openai_compatible", "openai_compatible"),
        ],
    )
    endpoint_name = ft.TextField(label="端点名称", hint_text="例如 core-llm / chat-llm", border_radius=12)
    endpoint_base = ft.TextField(label="Base URL", hint_text="例如 https://api.openai.com/v1", border_radius=12)
    endpoint_model = ft.TextField(label="模型名", hint_text="例如 deepseek-chat", border_radius=12)
    endpoint_api_key = ft.TextField(
        label="端点 API Key",
        password=True,
        can_reveal_password=True,
        border_radius=12,
    )
    endpoint_priority = ft.TextField(label="优先级（越小越优先）", value="100", border_radius=12)
    endpoint_enabled = ft.Switch(label="启用", value=True)
    endpoint_is_fallback = ft.Switch(label="回退端点", value=False)
    endpoint_refresh_btn = ft.TextButton(content=ft.Text("刷新端点"))
    endpoint_health_btn = ft.TextButton(content=ft.Text("检测健康"))
    endpoint_new_btn = ft.TextButton(content=ft.Text("新建端点"))
    endpoint_delete_btn = ft.TextButton(content=ft.Text("删除端点"))
    endpoint_save_btn = ft.ElevatedButton(
        content=ft.Text("保存端点"),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
    )
    task_binding_controls: dict[str, ft.Dropdown] = {}
    task_binding_column = ft.Column(spacing=8)
    for task_type, label in TASK_BINDING_DEFS:
        control = ft.Dropdown(
            label=f"{label} ({task_type})",
            border_radius=12,
            options=[ft.dropdown.Option("", "自动")],
        )
        task_binding_controls[task_type] = control
        task_binding_column.controls.append(control)

    settings_dialog = ft.AlertDialog(
        modal=True, title=ft.Text("环境与模型设置", weight=ft.FontWeight.W_700),
        content=ft.Container(
            width=760,
            content=ft.Column(
                tight=True, spacing=12,
                controls=[
                    ft.Text("通用模型模式（BYOK）", weight=ft.FontWeight.W_700),
                    byok_enable, byok_base, byok_model, byok_key,
                    ft.Divider(height=16),
                    ft.Text("任务模型端点（Generation Pipeline）", weight=ft.FontWeight.W_700),
                    endpoint_status,
                    endpoint_health_status,
                    endpoint_selected_hint,
                    ft.Container(
                        height=180,
                        border_radius=12,
                        padding=8,
                        content=endpoint_list,
                    ),
                    ft.Row(
                        [endpoint_refresh_btn, endpoint_health_btn, endpoint_new_btn, endpoint_delete_btn],
                        spacing=8,
                    ),
                    ft.Container(
                        height=120,
                        border_radius=12,
                        padding=8,
                        content=endpoint_health_list,
                    ),
                    endpoint_provider,
                    endpoint_name,
                    endpoint_base,
                    endpoint_model,
                    endpoint_api_key,
                    endpoint_priority,
                    ft.Row([endpoint_enabled, endpoint_is_fallback], spacing=12),
                    endpoint_save_btn,
                    ft.Divider(height=16),
                    ft.Text("任务 -> 端点绑定（留空即自动路由）", weight=ft.FontWeight.W_700),
                    task_binding_column,
                    ft.Text("说明：关闭后系统将走试用网关配额，并回退至本地提取草案。", size=12, color=c("muted")),
                ],
            ),
        ),
        actions=[
            ft.TextButton(
                content=ft.Text("取消"),
                on_click=lambda e: (setattr(settings_dialog, "open", False), page.update()),
            ),
            ft.ElevatedButton(
                content=ft.Text("保存"),
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                on_click=lambda e: page.run_task(on_save_settings_click)
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(settings_dialog)

    action_type = ft.Dropdown(
        label="动作类型", value="image_prompt", border_radius=12,
        options=[
            ft.dropdown.Option("image_prompt", "生成配图提示词"),
            ft.dropdown.Option("image_generate", "直接生成配图"),
            ft.dropdown.Option("audio_plan", "生成语音方案"),
        ],
    )
    action_selected_text = ft.TextField(label="选中段落", multiline=True, min_lines=3, max_lines=6, border_radius=12)
    action_style = ft.TextField(label="画面风格（可选）", value="cinematic", border_radius=12)
    action_shot = ft.TextField(label="镜头（可选）", value="medium shot", border_radius=12)
    action_voice = ft.TextField(label="音色（可选）", value="neutral_female", border_radius=12)
    action_result = ft.TextField(label="执行结果", multiline=True, min_lines=4, max_lines=8, read_only=True, border_radius=12)

    action_dialog = ft.AlertDialog(
        modal=True, title=ft.Text("段落 AIGC 增强", weight=ft.FontWeight.W_700),
        content=ft.Container(
            width=620,
            content=ft.Column(
                tight=True, spacing=12,
                controls=[
                    action_type, action_selected_text, action_style, action_shot, action_voice, action_result,
                ],
            ),
        ),
        actions=[
            ft.TextButton(
                content=ft.Text("关闭"),
                on_click=lambda e: (setattr(action_dialog, "open", False), page.update()),
            ),
            ft.ElevatedButton(
                content=ft.Text("执行生成"), 
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                on_click=lambda e: page.run_task(on_execute_action)
            )
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(action_dialog)

    # ---- render helpers ----
    def split_paragraphs(content: str) -> list[str]:
        normalized = content.replace("\r\n", "\n").strip()
        if not normalized: return []
        blocks =[segment.strip() for segment in re.split(r"\n{2,}", normalized) if segment.strip()]
        if blocks: return blocks[:20]
        lines =[line.strip() for line in normalized.split("\n") if line.strip()]
        return lines[:20]

    def make_bubble(role: str, content: str, *, allow_action: bool = False, action_scope: str = "roleplay") -> ft.Container:
        is_user = role == "user"
        bubble_color = c("user") if is_user else c("assistant")
        label = "你" if is_user else "助手"

        header_controls: list[ft.Control] =[ft.Text(label, size=11, color=c("muted"), weight=ft.FontWeight.W_600)]
        if allow_action and content.strip() and content.strip() not in {"思考中...", "正在启动角色会话..."}:
            if action_scope == "story":
                header_controls.append(ft.Text("可对最新叙事段落生成图片/音频方案", size=10, color=c("muted")))
            else:
                header_controls.append(
                    ft.TextButton("整条AIGC", height=24, on_click=lambda _e, txt=content, scope=action_scope: page.run_task(open_action_dialog, txt, scope))
                )

        paragraph_controls: list[ft.Control] =[]
        paragraphs = split_paragraphs(content)
        if not paragraphs: paragraphs = [content]

        for idx, paragraph in enumerate(paragraphs):
            paragraph_text = paragraph.strip()
            text_control = ft.Text(paragraph_text, size=15, color=c("text"), selectable=True)

            if allow_action and paragraph_text and paragraph_text not in {"思考中...", "正在启动角色会话..."}:
                interactive_block = ft.Container(
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=12, bgcolor=c("bg"), border=ft.border.all(1, c("border")),
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text("右键/长按本段落触发 AIGC", size=10, color=c("muted")),
                            text_control,
                            *(
                                [
                                    ft.Row(
                                        spacing=8,
                                        controls=[
                                            ft.TextButton("图片提示词", on_click=lambda _e, txt=paragraph_text: page.run_task(open_action_dialog, txt, "story", "image_prompt")),
                                            ft.TextButton("直接生图", on_click=lambda _e, txt=paragraph_text: page.run_task(open_action_dialog, txt, "story", "image_generate")),
                                            ft.TextButton("音频方案", on_click=lambda _e, txt=paragraph_text: page.run_task(open_action_dialog, txt, "story", "audio_plan")),
                                        ],
                                    )
                                ]
                                if action_scope == "story"
                                else []
                            ),
                        ],
                    ),
                )
                paragraph_controls.append(
                    ft.GestureDetector(
                        content=interactive_block,
                        on_secondary_tap=lambda _e, txt=paragraph_text, scope=action_scope: page.run_task(open_action_dialog, txt, scope),
                        on_long_press=lambda _e, txt=paragraph_text, scope=action_scope: page.run_task(open_action_dialog, txt, scope),
                    )
                )
            else:
                paragraph_controls.append(text_control)

            if idx < len(paragraphs) - 1:
                paragraph_controls.append(ft.Divider(height=12, color=ft.Colors.TRANSPARENT))

        body = ft.Container(
            bgcolor=bubble_color, border=ft.border.all(1, c("border")) if not is_user else None,
            border_radius=20, padding=16, width=760,
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=header_controls),
                    *paragraph_controls,
                ],
            ),
        )

        return ft.Container(
            padding=ft.padding.symmetric(vertical=4),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
                controls=[body],
            ),
        )

    def render_builder_messages() -> None:
        builder_chat.controls.clear()
        for role, text in state["builder_messages"]:
            builder_chat.controls.append(make_bubble(role, text, allow_action=False))

    def render_role_messages() -> None:
        role_chat.controls.clear()
        for role, text in state["role_messages"]:
            role_chat.controls.append(make_bubble(role, text, allow_action=True))

    def render_story_messages() -> None:
        story_chat.controls.clear()
        messages = state.get("story_messages", [])
        rows = messages if isinstance(messages, list) else []
        latest_assistant_idx = next(
            (idx for idx in range(len(rows) - 1, -1, -1) if rows[idx][0] == "assistant" and str(rows[idx][1]).strip()),
            -1,
        )
        for idx, (role, text) in enumerate(rows):
            story_chat.controls.append(
                make_bubble(role, text, allow_action=(role == "assistant" and idx == latest_assistant_idx), action_scope="story")
            )

    def render_action_history() -> None:
        action_history_list.controls.clear()
        items = state.get("role_actions")
        if not isinstance(items, list) or not items:
            action_history_list.controls.append(ft.Text("暂无动作结果。可在消息气泡点击 AIGC 生成。", size=12, color=c("muted")))
            return

        for item in reversed(items[-20:]):
            if not isinstance(item, dict): continue
            action_name = str(item.get("action_type") or "action")
            selected_text = str(item.get("selected_text") or "")
            result_obj = item.get("result")
            result_text = format_action_result(result_obj if isinstance(result_obj, dict) else {})
            action_history_list.controls.append(
                ft.Container(
                    border=ft.border.all(1, c("border")), border_radius=16, bgcolor=c("surface"), padding=14,
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text(f"动作: {action_name}", size=13, weight=ft.FontWeight.W_700, color=c("text")),
                            ft.Text(f"原文: {selected_text[:140]}", size=12, color=c("muted")),
                            ft.Text(result_text[:600], size=13, color=c("text"), selectable=True),
                        ],
                    ),
                )
            )

    def render_story_action_history() -> None:
        story_actions_list.controls.clear()
        items = state.get("story_actions")
        if not isinstance(items, list) or not items:
            story_actions_list.controls.append(ft.Text("暂无故事动作结果。可在助手叙事段落触发 AIGC。", size=12, color=c("muted")))
            return

        for item in reversed(items[-20:]):
            if not isinstance(item, dict):
                continue
            action_name = str(item.get("action_type") or "action")
            selected_text = str(item.get("selected_text") or "")
            result_obj = item.get("result")
            result_text = format_action_result(result_obj if isinstance(result_obj, dict) else {})
            story_actions_list.controls.append(
                ft.Container(
                    border=ft.border.all(1, c("border")), border_radius=16, bgcolor=c("surface"), padding=14,
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text(f"动作: {action_name}", size=13, weight=ft.FontWeight.W_700, color=c("text")),
                            ft.Text(f"原文: {selected_text[:140]}", size=12, color=c("muted")),
                            ft.Text(result_text[:600], size=13, color=c("text"), selectable=True),
                        ],
                    ),
                )
            )

    def render_story_memory_panels() -> None:
        story_facts_list.controls.clear()
        facts = state.get("story_facts")
        fact_rows = facts if isinstance(facts, list) else []
        if not fact_rows:
            story_facts_list.controls.append(ft.Text("暂无事实记忆。续写后会自动积累。", size=12, color=c("muted")))
        for item in fact_rows[:30]:
            if not isinstance(item, dict):
                continue
            story_facts_list.controls.append(
                ft.Text(str(item.get("fact_text") or ""), size=12, color=c("text"), selectable=True)
            )

        story_checkpoints_list.controls.clear()
        checkpoints = state.get("story_checkpoints")
        checkpoint_rows = checkpoints if isinstance(checkpoints, list) else []
        if not checkpoint_rows:
            story_checkpoints_list.controls.append(ft.Text("暂无检查点。续写后会自动生成。", size=12, color=c("muted")))
        for item in reversed(checkpoint_rows[-12:]):
            if not isinstance(item, dict):
                continue
            checkpoint_id = str(item.get("checkpoint_id") or "")
            title = str(item.get("title") or "检查点")
            summary = str(item.get("summary_text") or "")[:120]
            story_checkpoints_list.controls.append(
                ft.Container(
                    border=ft.border.all(1, c("border")), border_radius=14, padding=10, bgcolor=c("surface"),
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text(title, size=12, weight=ft.FontWeight.W_700, color=c("text")),
                            ft.Text(summary, size=11, color=c("muted"), max_lines=3),
                            ft.TextButton("回滚到此检查点", on_click=lambda _e, cid=checkpoint_id: page.run_task(on_rollback_story_checkpoint, cid)),
                        ],
                    ),
                )
            )

    def clear_story_lorebook_form() -> None:
        state["editing_story_lorebook_id"] = None
        story_lore_keyword.value = ""
        story_lore_text.value = ""
        story_lore_order.value = "100"
        story_lore_enabled.value = True
        story_lore_save_btn.content = ft.Text("保存世界书条目")

    def set_story_lorebook_form(item: dict[str, Any]) -> None:
        state["editing_story_lorebook_id"] = str(item.get("lorebook_id") or "") or None
        story_lore_keyword.value = str(item.get("keyword") or "")
        story_lore_text.value = str(item.get("insert_text") or "")
        story_lore_order.value = str(item.get("sort_order", 100))
        story_lore_enabled.value = bool(item.get("enabled", True))
        story_lore_save_btn.content = ft.Text("保存修改")
        page.update()

    def render_story_lorebooks() -> None:
        story_lorebook_list.controls.clear()
        items = state.get("story_lorebooks")
        rows = items if isinstance(items, list) else []
        if not rows:
            story_lorebook_list.controls.append(ft.Text("暂无世界书条目。", size=12, color=c("muted")))
            return
        for item in rows:
            if not isinstance(item, dict):
                continue
            lorebook_id = str(item.get("lorebook_id") or "")
            story_lorebook_list.controls.append(
                ft.Container(
                    border=ft.border.all(1, c("border")), border_radius=14, padding=12, bgcolor=c("surface"),
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text(f"{item.get('keyword') or '未命名触发词'} · sort={item.get('sort_order', 100)}", size=13, weight=ft.FontWeight.W_700, color=c("text")),
                            ft.Text(str(item.get("insert_text") or "")[:240], size=12, color=c("muted"), selectable=True),
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.TextButton("编辑", on_click=lambda _e, x=item: set_story_lorebook_form(x)),
                                    ft.TextButton("删除", on_click=lambda _e, lid=lorebook_id: page.run_task(on_delete_story_lorebook, lid)),
                                ],
                            ),
                        ],
                    ),
                )
            )

    def render_character_list() -> None:
        character_list.controls.clear()
        if state.get("active_mode") == "story":
            nav_section_title.value = "我的故事"
            create_new_btn.content = ft.Text("+ 新建故事", weight=ft.FontWeight.W_600)
            selected = state.get("selected_story")
            selected_id = selected.get("project_id") if isinstance(selected, dict) else None

            if not state.get("stories"):
                character_list.controls.append(ft.Text("暂无故事。点击上方新建。", size=12, color=c("muted")))
                return

            for item in state.get("stories", []):
                if not isinstance(item, dict):
                    continue
                pid = item.get("project_id")
                if not pid:
                    continue
                is_selected = pid == selected_id
                tile = ft.Container(
                    bgcolor=c("sidebar_active") if is_selected else "transparent",
                    border_radius=16, padding=12, ink=True,
                    on_click=lambda _e, x=item: page.run_task(select_story, x),
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text(item.get("title") or "未命名故事", size=15, color=c("primary") if is_selected else c("text"), weight=ft.FontWeight.W_600),
                            ft.Text((item.get("premise") or "无设定")[:45], size=12, color=c("muted"), max_lines=2),
                        ],
                    ),
                )
                character_list.controls.append(tile)
            return

        nav_section_title.value = "我的角色"
        create_new_btn.content = ft.Text("+ 新建角色", weight=ft.FontWeight.W_600)
        selected = state.get("selected_character")
        selected_id = selected.get("character_id") if isinstance(selected, dict) else None

        if not state.get("characters"):
            character_list.controls.append(ft.Text("暂无角色。点击上方新建。", size=12, color=c("muted")))
            return

        for item in state["characters"]:
            cid = item.get("character_id")
            if not cid: continue
            is_selected = cid == selected_id
            tile = ft.Container(
                bgcolor=c("sidebar_active") if is_selected else "transparent",
                border_radius=16, padding=12, ink=True,
                on_click=lambda _e, x=item: page.run_task(select_character, x),
                content=ft.Column(
                    spacing=4,
                    controls=[
                        ft.Text(item.get("name") or "未命名角色", size=15, color=c("primary") if is_selected else c("text"), weight=ft.FontWeight.W_600),
                        ft.Text((item.get("description") or "无描述")[:45], size=12, color=c("muted"), max_lines=2),
                    ],
                ),
            )
            character_list.controls.append(tile)

    def set_endpoint_form(endpoint: dict[str, Any] | None) -> None:
        allowed_providers = {"deepseek", "qwen", "kimi", "openai", "openai_compatible"}
        if endpoint is None:
            state["selected_endpoint_id"] = None
            endpoint_provider.value = "deepseek"
            endpoint_name.value = ""
            endpoint_base.value = ""
            endpoint_model.value = ""
            endpoint_api_key.value = ""
            endpoint_api_key.hint_text = "例如 sk-..."
            endpoint_priority.value = "100"
            endpoint_enabled.value = True
            endpoint_is_fallback.value = False
            endpoint_selected_hint.value = "未选择端点（将创建新端点）"
            endpoint_delete_btn.disabled = True
            return

        endpoint_id = str(endpoint.get("endpoint_id") or "").strip()
        state["selected_endpoint_id"] = endpoint_id or None
        provider_value = str(endpoint.get("provider") or "").strip().lower() or "deepseek"
        if provider_value not in allowed_providers:
            provider_value = "openai_compatible"
        endpoint_provider.value = provider_value
        endpoint_name.value = str(endpoint.get("name") or "")
        endpoint_base.value = str(endpoint.get("base_url") or "")
        endpoint_model.value = str(endpoint.get("model") or "")
        endpoint_api_key.value = ""
        endpoint_api_key.hint_text = (
            "已保存密钥（留空保持不变）"
            if bool(endpoint.get("has_api_key"))
            else "例如 sk-..."
        )
        endpoint_priority.value = str(endpoint.get("priority", 100))
        endpoint_enabled.value = bool(endpoint.get("enabled", True))
        endpoint_is_fallback.value = bool(endpoint.get("is_fallback", False))
        endpoint_selected_hint.value = f"当前端点：{endpoint_name.value} ({endpoint_id[:8]}...)"
        endpoint_delete_btn.disabled = False

    def render_model_endpoint_list() -> None:
        endpoint_list.controls.clear()
        items = state.get("model_endpoints")
        rows = items if isinstance(items, list) else []
        selected_id = state.get("selected_endpoint_id")
        health_by_id = state.get("endpoint_health_by_id")
        health_map = health_by_id if isinstance(health_by_id, dict) else {}
        endpoint_status.value = f"任务模型端点：{len(rows)}"

        if not rows:
            endpoint_list.controls.append(ft.Text("暂无端点，请先新建。", size=12, color=c("muted")))
            return

        for item in rows:
            if not isinstance(item, dict):
                continue
            endpoint_id = str(item.get("endpoint_id") or "")
            if not endpoint_id:
                continue
            is_selected = endpoint_id == selected_id
            title = f"{item.get('name') or 'unnamed'} · {item.get('provider') or '-'}"
            subtitle = f"{item.get('model') or '-'} | priority={item.get('priority', '-')}"
            if not bool(item.get("enabled", True)):
                subtitle = f"[disabled] {subtitle}"
            if bool(item.get("is_fallback", False)):
                subtitle = f"[fallback] {subtitle}"
            health = health_map.get(endpoint_id) if isinstance(health_map.get(endpoint_id), dict) else None
            health_text = "health: unknown"
            if isinstance(health, dict):
                if health.get("healthy") is True:
                    health_text = "health: ok"
                elif health.get("healthy") is False:
                    status_code = health.get("status_code")
                    health_text = f"health: fail ({status_code if status_code is not None else '-'})"
            subtitle = f"{subtitle} | {health_text}"

            endpoint_list.controls.append(
                ft.Container(
                    bgcolor=c("sidebar_active") if is_selected else c("surface"),
                    border=ft.border.all(1, c("border")),
                    border_radius=12,
                    padding=10,
                    ink=True,
                    on_click=lambda _e, x=item: on_select_endpoint(x),
                    content=ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(title, size=13, color=c("text"), weight=ft.FontWeight.W_600),
                            ft.Text(subtitle, size=11, color=c("muted")),
                        ],
                    ),
                )
            )

    def render_endpoint_health_list() -> None:
        endpoint_health_list.controls.clear()
        health_by_id = state.get("endpoint_health_by_id")
        health_map = health_by_id if isinstance(health_by_id, dict) else {}
        rows = state.get("model_endpoints")
        endpoints = rows if isinstance(rows, list) else []
        if not endpoints:
            endpoint_health_status.value = "健康状态：暂无端点"
            endpoint_health_list.controls.append(ft.Text("暂无端点可检测。", size=12, color=c("muted")))
            return

        ok = 0
        fail = 0
        unknown = 0
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                continue
            endpoint_id = str(endpoint.get("endpoint_id") or "")
            if not endpoint_id:
                continue
            name = str(endpoint.get("name") or endpoint_id[:8])
            provider = str(endpoint.get("provider") or "-")
            health = health_map.get(endpoint_id) if isinstance(health_map.get(endpoint_id), dict) else None
            if isinstance(health, dict):
                if health.get("healthy") is True:
                    ok += 1
                    status_text = "OK"
                else:
                    fail += 1
                    status_code = health.get("status_code")
                    status_text = f"FAIL ({status_code if status_code is not None else '-'})"
                detail = str(health.get("detail") or "")
            else:
                unknown += 1
                status_text = "UNKNOWN"
                detail = "尚未检测"
            endpoint_health_list.controls.append(
                ft.Container(
                    border=ft.border.all(1, c("border")),
                    border_radius=10,
                    padding=8,
                    content=ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(f"{name} · {provider} · {status_text}", size=12, color=c("text"), weight=ft.FontWeight.W_600),
                            ft.Text(detail[:140], size=11, color=c("muted")),
                        ],
                    ),
                )
            )

        endpoint_health_status.value = f"健康状态：OK {ok} / FAIL {fail} / UNKNOWN {unknown}"

    def refresh_task_binding_options() -> None:
        rows = state.get("model_endpoints")
        endpoints = rows if isinstance(rows, list) else []
        options = [ft.dropdown.Option("", "自动")]
        for item in endpoints:
            if not isinstance(item, dict):
                continue
            endpoint_id = str(item.get("endpoint_id") or "").strip()
            if not endpoint_id:
                continue
            provider = str(item.get("provider") or "")
            name = str(item.get("name") or endpoint_id[:8])
            model = str(item.get("model") or "")
            options.append(
                ft.dropdown.Option(endpoint_id, f"{name} · {provider} · {model}")
            )

        bindings = state.get("task_endpoint_bindings")
        binding_map = bindings if isinstance(bindings, dict) else {}
        for task_type, control in task_binding_controls.items():
            current = str(binding_map.get(task_type) or "")
            control.options = list(options)
            option_values = {str(opt.key or "") for opt in options}
            control.value = current if current in option_values else ""

    async def load_model_endpoint_health(*, include_disabled: bool = True) -> None:
        params = {"include_disabled": include_disabled}
        items = await api_get("/model-endpoints/health", params=params)
        health_map: dict[str, dict[str, Any]] = {}
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                endpoint_id = str(item.get("endpoint_id") or "").strip()
                if endpoint_id:
                    health_map[endpoint_id] = item
        state["endpoint_health_by_id"] = health_map
        render_endpoint_health_list()

    def on_select_endpoint(endpoint: dict[str, Any]) -> None:
        set_endpoint_form(endpoint)
        render_model_endpoint_list()
        page.update()

    def collect_endpoint_payload(*, for_update: bool) -> dict[str, Any]:
        provider = str(endpoint_provider.value or "").strip().lower()
        name = str(endpoint_name.value or "").strip()
        base_url = str(endpoint_base.value or "").strip()
        model = str(endpoint_model.value or "").strip()
        api_key = str(endpoint_api_key.value or "").strip()
        priority_raw = str(endpoint_priority.value or "").strip()
        if not provider or not name or not base_url or not model:
            raise ValueError("请完整填写 Provider / 端点名称 / Base URL / 模型名")

        try:
            priority = int(priority_raw)
        except ValueError as exc:
            raise ValueError("优先级必须是整数") from exc

        payload: dict[str, Any] = {
            "provider": provider,
            "name": name,
            "base_url": base_url,
            "model": model,
            "enabled": bool(endpoint_enabled.value),
            "priority": priority,
            "is_fallback": bool(endpoint_is_fallback.value),
        }
        if api_key:
            payload["api_key"] = api_key
        elif not for_update:
            payload["api_key"] = None
        return payload

    async def load_model_endpoints(*, select_first: bool = False) -> None:
        items = await api_get("/model-endpoints", params={"include_disabled": True})
        state["model_endpoints"] = items if isinstance(items, list) else []
        rows = state["model_endpoints"] if isinstance(state["model_endpoints"], list) else []
        selected_id = state.get("selected_endpoint_id")

        matched = None
        if selected_id:
            matched = next(
                (x for x in rows if isinstance(x, dict) and x.get("endpoint_id") == selected_id),
                None,
            )
        if matched is not None:
            set_endpoint_form(matched)
        elif select_first and rows:
            first = rows[0]
            if isinstance(first, dict):
                set_endpoint_form(first)
        elif not rows:
            set_endpoint_form(None)

        refresh_task_binding_options()
        render_model_endpoint_list()
        render_endpoint_health_list()

    async def on_refresh_endpoint_click(e: ft.ControlEvent | None = None) -> None:
        try:
            await load_model_endpoints(select_first=False)
            await load_model_endpoint_health(include_disabled=True)
            render_model_endpoint_list()
            refresh_task_binding_options()
            render_endpoint_health_list()
            page.update()
            show_toast("任务模型端点已刷新")
        except ApiError as exc:
            show_toast(f"刷新端点失败：{exc}", error=True)

    async def on_health_endpoint_click(e: ft.ControlEvent | None = None) -> None:
        try:
            await load_model_endpoint_health(include_disabled=True)
            render_model_endpoint_list()
            render_endpoint_health_list()
            page.update()
            show_toast("端点健康检测完成")
        except ApiError as exc:
            show_toast(f"健康检测失败：{exc}", error=True)

    def on_new_endpoint_click(e: ft.ControlEvent | None = None) -> None:
        set_endpoint_form(None)
        render_model_endpoint_list()
        page.update()

    async def on_save_endpoint_click(e: ft.ControlEvent | None = None) -> None:
        endpoint_id = state.get("selected_endpoint_id")
        is_update = isinstance(endpoint_id, str) and bool(endpoint_id)
        try:
            payload = collect_endpoint_payload(for_update=is_update)
        except ValueError as exc:
            show_toast(str(exc), error=True)
            return

        try:
            if is_update:
                await api_put(f"/model-endpoints/{endpoint_id}", payload)
                show_toast("任务模型端点已更新")
            else:
                created = await api_post("/model-endpoints", payload)
                created_id = str(created.get("endpoint_id") or "").strip() if isinstance(created, dict) else ""
                state["selected_endpoint_id"] = created_id or None
                show_toast("任务模型端点已创建")

            await load_model_endpoints(select_first=False)
            await load_model_endpoint_health(include_disabled=True)
            render_model_endpoint_list()
            render_endpoint_health_list()
            page.update()
        except ApiError as exc:
            show_toast(f"保存端点失败：{exc}", error=True)

    async def on_delete_endpoint_click(e: ft.ControlEvent | None = None) -> None:
        endpoint_id = state.get("selected_endpoint_id")
        if not isinstance(endpoint_id, str) or not endpoint_id:
            show_toast("请先选择要删除的端点", error=True)
            return

        try:
            await api_delete(f"/model-endpoints/{endpoint_id}")
            state["selected_endpoint_id"] = None
            set_endpoint_form(None)
            await load_model_endpoints(select_first=False)
            await load_model_endpoint_health(include_disabled=True)
            render_model_endpoint_list()
            render_endpoint_health_list()
            page.update()
            show_toast("任务模型端点已删除")
        except ApiError as exc:
            show_toast(f"删除端点失败：{exc}", error=True)

    def apply_input_style(control: ft.TextField) -> None:
        control.bgcolor = c("surface")
        control.border_color = c("border")
        control.focused_border_color = c("primary")
        control.cursor_color = c("primary")
        control.text_style = ft.TextStyle(color=c("text"), size=15, weight=ft.FontWeight.W_500)
        control.hint_style = ft.TextStyle(color=c("muted"), size=14, weight=ft.FontWeight.W_400)
        control.label_style = ft.TextStyle(color=c("muted"), size=13, weight=ft.FontWeight.W_600)

    def apply_dropdown_style(control: ft.Dropdown) -> None:
        control.bgcolor = c("surface")
        control.border_color = c("border")
        control.focused_border_color = c("primary")
        control.text_style = ft.TextStyle(color=c("text"), size=14, weight=ft.FontWeight.W_500)
        control.label_style = ft.TextStyle(color=c("muted"), size=13, weight=ft.FontWeight.W_600)

    def apply_theme() -> None:
        page.theme_mode = ft.ThemeMode.DARK if state["is_dark"] else ft.ThemeMode.LIGHT
        page.bgcolor = c("bg")
        sidebar.bgcolor = c("sidebar")
        main_content.bgcolor = c("surface")

        sidebar_title.color = c("text")
        sidebar_subtitle.color = c("muted")
        nav_section_title.color = c("muted")
        header_title.color = c("text")
        header_subtitle.color = c("muted")
        mode_badge.color = c("muted")
        theme_label.color = c("muted")
        theme_label.value = "深色" if state["is_dark"] else "浅色"

        create_new_btn.style = ft.ButtonStyle(bgcolor=c("primary"), color="#FFFFFF", shape=ft.RoundedRectangleBorder(radius=16), padding=16)
        roleplay_mode_btn.style = ft.ButtonStyle(
            bgcolor=c("primary") if state.get("active_mode") == "roleplay" else c("surface"),
            color="#FFFFFF" if state.get("active_mode") == "roleplay" else c("text"),
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=10,
        )
        story_mode_btn.style = ft.ButtonStyle(
            bgcolor=c("primary") if state.get("active_mode") == "story" else c("surface"),
            color="#FFFFFF" if state.get("active_mode") == "story" else c("text"),
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=10,
        )
        export_btn.style = ft.ButtonStyle(bgcolor=c("sidebar") if state["is_dark"] else "#111827", color="#FFFFFF", shape=ft.RoundedRectangleBorder(radius=12), padding=12)
        edit_btn.style = ft.ButtonStyle(color=c("text"))
        delete_btn.style = ft.ButtonStyle(color=c("danger"))
        builder_send_btn.bgcolor = c("primary")
        role_send_btn.bgcolor = c("primary")
        story_send_btn.bgcolor = c("primary")
        save_role_btn.style = ft.ButtonStyle(bgcolor=c("success"), color="#FFFFFF", shape=ft.RoundedRectangleBorder(radius=16), padding=16)
        save_story_btn.style = ft.ButtonStyle(bgcolor=c("success"), color="#FFFFFF", shape=ft.RoundedRectangleBorder(radius=16), padding=16)
        story_draft_generate_btn.style = ft.ButtonStyle(bgcolor=c("primary"), color="#FFFFFF", shape=ft.RoundedRectangleBorder(radius=16), padding=16)
        story_draft_apply_new_btn.style = ft.ButtonStyle(bgcolor=c("success"), color="#FFFFFF", shape=ft.RoundedRectangleBorder(radius=16), padding=16)
        story_draft_apply_current_btn.style = ft.ButtonStyle(color=c("text"), shape=ft.RoundedRectangleBorder(radius=16), padding=16)
        story_lore_save_btn.style = ft.ButtonStyle(bgcolor=c("primary"), color="#FFFFFF", shape=ft.RoundedRectangleBorder(radius=12), padding=12)

        for card in (
            builder_view.controls[0],
            draft_card,
            role_view.controls[0],
            role_view.controls[1],
            story_builder_view.controls[0],
            story_builder_view.controls[1],
            story_builder_view.controls[2],
            story_view.controls[0],
            story_view.controls[1],
            story_view.controls[2].controls[0],
            story_view.controls[2].controls[1],
            story_view.controls[3],
        ):
            if isinstance(card, ft.Container):
                card.bgcolor = c("bg")
                card.border = ft.border.all(1, c("border"))

        for tf in (
            builder_input,
            role_input,
            story_input,
            story_draft_prompt,
            story_draft_title,
            story_draft_premise,
            story_draft_opening,
            story_draft_system,
            story_draft_tone,
            story_draft_protagonist,
            story_draft_chapters,
            story_draft_lorebook,
            story_draft_illustration,
            story_draft_audio,
            story_draft_review,
            draft_name,
            draft_desc,
            draft_first,
            draft_system,
            draft_lorebook,
            draft_illustration,
            draft_audio,
            story_title,
            story_premise,
            story_opening,
            story_system,
            story_lore_keyword,
            story_lore_text,
            story_lore_order,
            byok_base,
            byok_model,
            byok_key,
            endpoint_name,
            endpoint_base,
            endpoint_model,
            endpoint_api_key,
            endpoint_priority,
            action_selected_text,
            action_style,
            action_shot,
            action_voice,
            action_result,
        ):
            apply_input_style(tf)
        for dd in (endpoint_provider, action_type, *task_binding_controls.values()):
            apply_dropdown_style(dd)

        draft_source.color = c("muted")
        draft_route_note.color = c("text")
        action_history_title.color = c("muted")
        story_detail_title.color = c("text")
        story_detail_premise.color = c("muted")
        story_summary.color = c("text")
        story_scene.color = c("text")
        story_context_stats_text.color = c("muted")
        story_draft_status.color = c("muted")
        endpoint_status.color = c("muted")
        endpoint_health_status.color = c("muted")
        endpoint_selected_hint.color = c("text")
        endpoint_save_btn.style = ft.ButtonStyle(
            bgcolor=c("primary"),
            color="#FFFFFF",
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=12,
        )

        settings_dialog.bgcolor = c("surface")
        action_dialog.bgcolor = c("surface")

        render_builder_messages()
        render_role_messages()
        render_story_messages()
        render_action_history()
        render_story_action_history()
        render_story_memory_panels()
        render_story_lorebooks()
        render_character_list()
        page.update()

    # ---- logic ----
    def set_builder_view() -> None:
        state["active_mode"] = "roleplay"
        state["selected_character"] = None
        state["selected_session_id"] = None
        state["editing_character_id"] = None
        state["role_actions"] = []
        state["builder_notes"] =[]
        state["builder_messages"] =[("assistant", "你好，我是向导。我会通过对话帮你创建角色。\n先告诉我：你想创建怎样的一个人物？")]

        draft_card.visible = False
        reset_draft_fields()
        save_role_btn.content = ft.Text("保存并开始对话")

        header_title.value = "角色创建向导"
        header_subtitle.value = "用自然语言描述角色，系统自动生成完整体系草案"
        sidebar_title.value = "AI Roleplay"
        export_btn.visible = False
        edit_btn.visible = False
        delete_btn.visible = False
        back_to_builder_btn.visible = False
        builder_view.visible = True
        role_view.visible = False
        story_builder_view.visible = False
        story_view.visible = False

        render_builder_messages()
        render_action_history()
        render_character_list()
        page.update()

    def set_role_view(character: dict[str, Any]) -> None:
        state["active_mode"] = "roleplay"
        state["selected_character"] = character
        state["role_actions"] =[]

        header_title.value = character.get("name") or "角色详情"
        header_subtitle.value = "进入角色后可聊天、导出，并在消息中执行 AIGC"
        sidebar_title.value = "AI Roleplay"
        export_btn.visible = True
        edit_btn.visible = True
        delete_btn.visible = True
        back_to_builder_btn.visible = True
        builder_view.visible = False
        role_view.visible = True
        story_builder_view.visible = False
        story_view.visible = False

        detail_name.value = character.get("name") or "未命名角色"
        detail_desc.value = character.get("description") or "无角色简介"
        detail_first.value = character.get("first_message") or "无开场白"

        render_character_list()
        render_role_messages()
        render_action_history()
        page.update()

    def reset_story_fields() -> None:
        story_title.value = ""
        story_premise.value = ""
        story_opening.value = ""
        story_system.value = ""
        state["editing_story_id"] = None

    def set_story_builder_view(project: dict[str, Any] | None = None) -> None:
        state["active_mode"] = "story"
        sidebar_title.value = "Interactive Fiction"
        header_title.value = "互动小说创建台"
        header_subtitle.value = "创建或编辑故事项目，打开后进行长期上下文续写"
        mode_badge.value = "故事模式：LOCAL"
        export_btn.visible = False
        edit_btn.visible = isinstance(project, dict)
        delete_btn.visible = isinstance(project, dict)
        back_to_builder_btn.visible = False
        builder_view.visible = False
        role_view.visible = False
        story_builder_view.visible = True
        story_view.visible = False

        if isinstance(project, dict):
            state["selected_story"] = project
            state["editing_story_id"] = project.get("project_id")
            story_title.value = str(project.get("title") or "")
            story_premise.value = str(project.get("premise") or "")
            story_opening.value = str(project.get("opening_scene") or "")
            story_system.value = str(project.get("system_prompt") or "")
            save_story_btn.content = ft.Text("保存故事修改")
            story_draft_apply_current_btn.disabled = False
        else:
            state["selected_story"] = None
            state["story_session_id"] = None
            state["story_session"] = None
            reset_story_fields()
            clear_story_lorebook_form()
            save_story_btn.content = ft.Text("保存故事项目")
            story_draft_apply_current_btn.disabled = True

        render_character_list()
        page.update()

    def set_story_view(project: dict[str, Any]) -> None:
        state["active_mode"] = "story"
        state["selected_story"] = project
        state["editing_story_id"] = None
        sidebar_title.value = "Interactive Fiction"
        header_title.value = project.get("title") or "互动小说"
        header_subtitle.value = "续写故事、管理项目世界书，并对助手叙事段落触发 AIGC"
        mode_badge.value = "故事模式：WORKSPACE"
        export_btn.visible = False
        edit_btn.visible = True
        delete_btn.visible = True
        back_to_builder_btn.visible = True
        builder_view.visible = False
        role_view.visible = False
        story_builder_view.visible = False
        story_view.visible = True

        story_detail_title.value = project.get("title") or "未命名故事"
        story_detail_premise.value = project.get("premise") or "无故事设定"
        render_character_list()
        page.update()

    def clear_builder_pending_message() -> None:
        pending = ("assistant", "正在生成角色草案，请稍候...")
        if state["builder_messages"] and state["builder_messages"][-1] == pending:
            state["builder_messages"].pop()

    def reset_draft_fields() -> None:
        draft_source.value = "草案来源：未生成"
        draft_route_note.value = "提示：当前还没有生成草案。"
        draft_name.value = ""
        draft_desc.value = ""
        draft_first.value = ""
        draft_system.value = ""
        draft_lorebook.value = ""
        draft_illustration.value = ""
        draft_audio.value = ""
        state["draft_lorebook_entries"] =[]

    async def load_settings() -> None:
        data = await api_get("/settings")
        mode = str(data.get("mode") or "trial")
        state["settings"]["mode"] = mode
        state["settings"]["byok_base_url"] = str(data.get("byok_base_url") or "")
        state["settings"]["byok_model"] = str(data.get("byok_model") or "")
        state["settings"]["has_api_key"] = bool(data.get("has_api_key"))
        bindings_raw = data.get("task_endpoint_bindings")
        state["task_endpoint_bindings"] = (
            bindings_raw if isinstance(bindings_raw, dict) else {}
        )

        byok_enable.value = mode == "byok"
        byok_base.value = state["settings"]["byok_base_url"]
        byok_model.value = state["settings"]["byok_model"]
        
        # [规范优化] 记住密码提示，避免频繁输入
        byok_key.value = ""
        byok_key.hint_text = "已安全保存 (留空以保持)" if state["settings"]["has_api_key"] else "例如 sk-..."

        mode_badge.value = "模式：MODEL" if mode == "byok" else "模式：LOCAL (Trial)"
        draft_route_note.value = "提示：当前配置为模型草案模式。" if mode == "byok" else "提示：当前为本地草案模式，可在“模型设置”切换。"
        refresh_task_binding_options()

    async def save_settings() -> None:
        task_endpoint_bindings: dict[str, str | None] = {}
        for task_type, control in task_binding_controls.items():
            endpoint_id = str(control.value or "").strip()
            task_endpoint_bindings[task_type] = endpoint_id or None

        payload: dict[str, Any] = {
            "mode": "byok" if byok_enable.value else "trial",
            "byok_base_url": (byok_base.value or "").strip(),
            "byok_model": (byok_model.value or "").strip(),
            "task_endpoint_bindings": task_endpoint_bindings,
        }
        if (byok_key.value or "").strip():
            payload["byok_api_key"] = byok_key.value.strip()

        await api_put("/settings", payload)
        await load_settings()
        show_toast("模型设置已保存")

    async def reload_characters(select_latest: bool = False) -> None:
        items = await api_get("/characters")
        state["characters"] = items if isinstance(items, list) else[]

        if select_latest and state["characters"]:
            await select_character(state["characters"][-1])
            return

        selected = state.get("selected_character")
        selected_id = selected.get("character_id") if isinstance(selected, dict) else None
        if selected_id:
            matched = next((x for x in state["characters"] if x.get("character_id") == selected_id), None)
            if matched:
                state["selected_character"] = matched
                render_character_list()
                return

        render_character_list()
        page.update()

    async def reload_stories(select_latest: bool = False) -> None:
        items = await api_get("/story/projects")
        state["stories"] = items if isinstance(items, list) else []

        if select_latest and state["stories"]:
            await select_story(state["stories"][-1])
            return

        selected = state.get("selected_story")
        selected_id = selected.get("project_id") if isinstance(selected, dict) else None
        if selected_id:
            matched = next((x for x in state["stories"] if isinstance(x, dict) and x.get("project_id") == selected_id), None)
            if matched:
                state["selected_story"] = matched
                render_character_list()
                return

        render_character_list()
        page.update()

    async def initialize() -> None:
        set_endpoint_form(None)
        try:
            await load_settings()
            await reload_characters(select_latest=False)
            await reload_stories(select_latest=False)
        except ApiError as exc:
            show_toast(f"初始化失败：{exc}", error=True)
        set_builder_view()
        apply_theme()

    def _render_lorebook(entries: list[dict[str, Any]]) -> str:
        lines: list[str] =[]
        for idx, item in enumerate(entries[:8], start=1):
            keyword = str(item.get("keyword") or "").strip()
            insert_text = str(item.get("insert_text") or "").strip()
            if keyword and insert_text:
                lines.append(f"{idx}. [{keyword}] {insert_text}")
        return "\n".join(lines) if lines else "（暂无世界书条目）"

    async def _run_generation_job(job_payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        job = await api_post("/generation/jobs", job_payload)
        job_id = str(job.get("job_id") or "").strip()
        if not job_id: raise ApiError("生成任务未返回 job_id")

        started = time.monotonic()
        while True:
            if time.monotonic() - started >= OPERATION_TIMEOUT_SECONDS:
                try: await api_post(f"/generation/jobs/{job_id}/cancel", {})
                except ApiError: pass
                raise OperationTimeoutError("超过120秒未完成生成，已自动中断。")

            job_state = await api_get(f"/generation/jobs/{job_id}")
            job_status = str(job_state.get("status") or "")
            if job_status == "completed": break
            if job_status in {"failed", "cancelled"}:
                raise ApiError(str(job_state.get("error_message") or f"generation job {job_status}"))
            await asyncio.sleep(GENERATION_POLL_INTERVAL_SECONDS)

        artifacts = await api_get(f"/generation/jobs/{job_id}/artifacts")
        artifact_map = {str(item.get("artifact_type") or ""): item.get("payload", {}) for item in artifacts if isinstance(item, dict)}
        return artifact_map, job_id

    async def _generate_full_bundle(prompt: str) -> tuple[dict[str, Any], str]:
        artifact_map, job_id = await _run_generation_job({
            "user_input": prompt,
            "include_illustration_prompt": True,
            "include_audio_plan": True,
            "run_async": True,
        })
        
        bundle = artifact_map.get("bundle")
        if not isinstance(bundle, dict):
            bundle = {
                "character_card": artifact_map.get("character_card", {}),
                "lorebook": artifact_map.get("lorebook", {}),
                "illustration_prompt": artifact_map.get("illustration_prompt", {}),
                "audio_plan": artifact_map.get("audio_plan", {}),
            }
        return bundle, job_id

    def format_story_lorebook_lines(entries: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for idx, item in enumerate(entries[:12]):
            if not isinstance(item, dict):
                continue
            keyword = str(item.get("keyword") or "").strip()
            insert_text = str(item.get("insert_text") or "").strip()
            if not keyword or not insert_text:
                continue
            sort_order = item.get("sort_order", 100 + idx * 10)
            lines.append(f"{keyword} | {sort_order} | {insert_text}")
        return "\n".join(lines)

    def parse_story_lorebook_lines(raw: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for idx, line in enumerate(raw.splitlines()):
            text = line.strip()
            if not text:
                continue
            parts = [part.strip() for part in text.split("|", 2)]
            if len(parts) == 3:
                keyword, order_raw, insert_text = parts
            elif len(parts) == 2:
                keyword, insert_text = parts
                order_raw = str(100 + idx * 10)
            else:
                keyword = text[:40]
                insert_text = text
                order_raw = str(100 + idx * 10)
            if not keyword or not insert_text:
                continue
            try:
                sort_order = int(order_raw)
            except ValueError:
                sort_order = 100 + idx * 10
            entries.append({
                "keyword": keyword[:120],
                "insert_text": insert_text[:4000],
                "sort_order": max(0, min(sort_order, 10000)),
            })
        return entries[:8]

    def read_story_draft_payload() -> dict[str, Any]:
        chapters = [line.strip() for line in (story_draft_chapters.value or "").splitlines() if line.strip()]
        lorebook_entries = parse_story_lorebook_lines(story_draft_lorebook.value or "")
        return {
            "story_blueprint": {
                "title": (story_draft_title.value or "").strip(),
                "premise": (story_draft_premise.value or "").strip(),
                "opening_scene": (story_draft_opening.value or "").strip(),
                "system_prompt": (story_draft_system.value or "").strip(),
                "chapters_outline": chapters[:8],
                "tone": (story_draft_tone.value or "").strip() or "immersive dramatic fiction",
                "protagonist_profile": (story_draft_protagonist.value or "").strip() or "A capable protagonist with room to grow under pressure.",
            },
            "story_lorebook": {"entries": lorebook_entries},
            "illustration_prompt": {"prompt": (story_draft_illustration.value or "").strip()} if (story_draft_illustration.value or "").strip() else {},
            "audio_plan": {"plan": (story_draft_audio.value or "").strip()} if (story_draft_audio.value or "").strip() else {},
        }

    def validate_story_draft_payload(payload: dict[str, Any]) -> str | None:
        blueprint = payload.get("story_blueprint") if isinstance(payload.get("story_blueprint"), dict) else {}
        lorebook = payload.get("story_lorebook") if isinstance(payload.get("story_lorebook"), dict) else {}
        if not str(blueprint.get("title") or "").strip():
            return "故事标题不能为空"
        if not str(blueprint.get("premise") or "").strip():
            return "故事前提不能为空"
        if not str(blueprint.get("opening_scene") or "").strip():
            return "开场场景不能为空"
        chapters = blueprint.get("chapters_outline")
        if not isinstance(chapters, list) or len([x for x in chapters if str(x).strip()]) < 3:
            return "章节大纲至少需要 3 行"
        entries = lorebook.get("entries")
        if not isinstance(entries, list) or not entries:
            return "至少需要 1 条有效故事世界书条目"
        return None

    def populate_story_draft(bundle: dict[str, Any]) -> None:
        blueprint = bundle.get("story_blueprint") if isinstance(bundle.get("story_blueprint"), dict) else {}
        lorebook = bundle.get("story_lorebook") if isinstance(bundle.get("story_lorebook"), dict) else {}
        continuity = bundle.get("story_continuity_review") if isinstance(bundle.get("story_continuity_review"), dict) else {}
        illustration = bundle.get("illustration_prompt") if isinstance(bundle.get("illustration_prompt"), dict) else {}
        audio = bundle.get("audio_plan") if isinstance(bundle.get("audio_plan"), dict) else {}

        story_draft_title.value = str(blueprint.get("title") or "")
        story_draft_premise.value = str(blueprint.get("premise") or "")
        story_draft_opening.value = str(blueprint.get("opening_scene") or "")
        story_draft_system.value = str(blueprint.get("system_prompt") or "")
        story_draft_tone.value = str(blueprint.get("tone") or "")
        story_draft_protagonist.value = str(blueprint.get("protagonist_profile") or "")
        chapters = blueprint.get("chapters_outline")
        story_draft_chapters.value = "\n".join(str(item).strip() for item in chapters if str(item).strip()) if isinstance(chapters, list) else ""
        entries = lorebook.get("entries")
        story_draft_lorebook.value = format_story_lorebook_lines(entries if isinstance(entries, list) else [])
        story_draft_illustration.value = str(illustration.get("prompt") or format_action_result(illustration) if illustration else "")
        story_draft_audio.value = str(audio.get("plan") or format_action_result(audio) if audio else "")
        story_draft_review.value = format_action_result(continuity if continuity else {})
        state["story_draft_payload"] = read_story_draft_payload()
        story_draft_card.visible = True
        story_draft_status.value = "草案状态：已生成，可编辑后应用"

    # [规范 8.1 强制] 禁用与恢复输入框机制
    async def on_builder_send(e: ft.ControlEvent | None = None) -> None:
        text = (builder_input.value or "").strip()
        if not text: return

        builder_input.value = ""
        builder_input.disabled = True
        builder_send_btn.disabled = True
        state["builder_notes"].append(text)
        state["builder_messages"].append(("user", text))
        state["builder_messages"].append(("assistant", "正在生成角色草案，请稍候..."))
        render_builder_messages()
        page.update()

        prompt = "\n".join(state["builder_notes"][-6:])

        try:
            bundle, job_id = await _generate_full_bundle(prompt)
            character = bundle.get("character_card") if isinstance(bundle.get("character_card"), dict) else {}
            lore_payload = bundle.get("lorebook") if isinstance(bundle.get("lorebook"), dict) else {}

            draft_name.value = str(character.get("name") or "")
            draft_desc.value = str(character.get("description") or "")
            draft_first.value = str(character.get("first_message") or "")
            draft_system.value = str(character.get("system_prompt") or "")

            normalized_entries =[]
            for idx, item in enumerate((lore_payload.get("entries") or [])[:8]):
                if isinstance(item, dict) and item.get("keyword") and item.get("insert_text"):
                    sort_order_raw = item.get("sort_order", 100 + idx * 10)
                    try:
                        sort_order = int(sort_order_raw)
                    except (TypeError, ValueError):
                        sort_order = 100 + idx * 10
                    normalized_entries.append({
                        "keyword": str(item.get("keyword")).strip(),
                        "insert_text": str(item.get("insert_text")).strip(),
                        "sort_order": sort_order,
                    })
            
            state["draft_lorebook_entries"] = normalized_entries
            draft_lorebook.value = _render_lorebook(normalized_entries)
            draft_illustration.value = format_action_result(bundle.get("illustration_prompt", {}))
            draft_audio.value = format_action_result(bundle.get("audio_plan", {}))
            draft_card.visible = True

            source_text = "模型生成(多节点)" if str(character.get("route_mode")) in {"model_endpoints", "byok"} else "任务编排生成"
            draft_source.value = f"草案来源：{source_text}"
            mode_badge.value = "草案模式：PIPELINE"
            clear_builder_pending_message()
            state["builder_messages"].append(("assistant", f"完整草案已生成，来源：{source_text}。可编辑后保存。"))
        except (OperationTimeoutError, ApiError) as exc:
            # Fallback
            try:
                payload = await api_post("/wizard/generate-character", {"user_input": prompt})
                draft = payload.get("draft", {})
                draft_name.value = str(draft.get("name") or "")
                draft_desc.value = str(draft.get("description") or "")
                draft_first.value = str(draft.get("first_message") or "")
                draft_system.value = str(draft.get("system_prompt") or "")
                draft_lorebook.value = "（本次为基础草案，未生成世界书）"
                draft_illustration.value = "（本次为基础草案，未生成插图提示词）"
                draft_audio.value = "（本次为基础草案，未生成音频方案）"
                state["draft_lorebook_entries"] =[]
                draft_card.visible = True
                source_text = "模型输出(BYOK)" if str(payload.get("route_mode")) == "byok" else "本地草案(trial)"
                draft_source.value = f"草案来源：{source_text}"
                clear_builder_pending_message()
                state["builder_messages"].append(("assistant", f"已回退基础草案。原因：{exc}"))
            except ApiError as inner:
                clear_builder_pending_message()
                state["builder_messages"].append(("assistant", f"生成失败：{inner}"))
                show_toast(f"生成失败：{inner}", error=True)

        builder_input.disabled = False
        builder_send_btn.disabled = False
        builder_input.focus()
        render_builder_messages()
        apply_theme()

    async def on_save_role(e: ft.ControlEvent | None = None) -> None:
        name = (draft_name.value or "").strip()
        if not name:
            show_toast("请先生成并填写角色名称", error=True)
            return

        payload = {
            "name": name,
            "description": (draft_desc.value or "").strip(),
            "first_message": (draft_first.value or "").strip(),
            "system_prompt": (draft_system.value or "").strip(),
        }
        try:
            editing_id = state.get("editing_character_id")
            if editing_id:
                updated = await api_put(f"/characters/{editing_id}", payload)
                show_toast("角色修改已保存")
                state["editing_character_id"] = None
                await reload_characters(select_latest=False)
                await select_character(updated if isinstance(updated, dict) else payload)
                return

            created = await api_post("/characters", payload)
            character_id = str(created.get("character_id") or "")
            created_lore = 0
            if character_id:
                for item in state.get("draft_lorebook_entries",[]):
                    if isinstance(item, dict) and item.get("keyword") and item.get("insert_text"):
                        await api_post("/lorebooks", {
                            "character_id": character_id, "keyword": item["keyword"],
                            "insert_text": item["insert_text"], "sort_order": int(item.get("sort_order", 100)),
                            "enabled": True,
                        })
                        created_lore += 1
            show_toast(f"角色创建成功，挂载世界书 {created_lore} 条")
            await reload_characters(select_latest=True)
        except ApiError as exc:
            show_toast(f"保存失败：{exc}", error=True)

    async def select_character(character: dict[str, Any]) -> None:
        set_role_view(character)
        state["role_messages"] =[("assistant", "正在启动角色会话...")]
        state["role_actions"] =[]
        render_role_messages()
        render_action_history()
        page.update()

        char_id = character.get("character_id")
        try:
            session = await api_post("/chat/start", payload={}, params={"character_id": char_id})
            session_id = session.get("session_id")
            state["selected_session_id"] = session_id
            welcome = str(session.get("welcome_message") or "你好，很高兴见到你。")
            state["role_messages"] = [("assistant", welcome)]
            
            try:
                loaded_actions = await api_get(f"/chat/actions/{session_id}")
                state["role_actions"] = loaded_actions if isinstance(loaded_actions, list) else[]
            except ApiError:
                pass
            render_role_messages()
            render_action_history()
            page.update()
        except ApiError as exc:
            state["role_messages"] = [("assistant", f"会话启动失败：{exc}")]
            render_role_messages()
            page.update()

    # [规范 6 & 8.2 强制] SSE 协议与流式恢复
    async def on_role_send(e: ft.ControlEvent | None = None) -> None:
        text = (role_input.value or "").strip()
        if not text: return

        session_id = state.get("selected_session_id")
        if not session_id:
            show_toast("当前角色会话未初始化", error=True)
            return

        role_input.value = ""
        role_input.disabled = True
        role_send_btn.disabled = True
        state["role_messages"].append(("user", text))
        
        ai_idx = len(state["role_messages"])
        state["role_messages"].append(("assistant", ""))
        render_role_messages()
        page.update()

        payload = {"session_id": session_id, "message": text}
        # 如果是 trial 模式，加上 device_id 触发后端的计费额度扣减
        if state["settings"]["mode"] == "trial":
            payload["device_id"] = device_id
            
        headers = get_auth_headers()

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                async with client.stream("POST", f"{API_BASE}/chat/message/stream", json=payload, headers=headers) as resp:
                    if resp.status_code == 429:
                        state["role_messages"][ai_idx] = ("assistant", "⚠️ 免费额度已耗尽，请在设置中切换模型。")
                    elif resp.status_code >= 400:
                        state["role_messages"][ai_idx] = ("assistant", f"⚠️ 请求异常: {resp.status_code}")
                    else:
                        current_text = ""
                        current_event = None
                        async for line in resp.aiter_lines():
                            if not line.strip(): continue
                            
                            if line.startswith("event:"):
                                current_event = line.replace("event:", "").strip()
                            elif line.startswith("data:"):
                                data_str = line.replace("data:", "").strip()
                                try:
                                    data = json.loads(data_str)
                                    if current_event == "chunk":
                                        current_text += data.get("delta", "")
                                        state["role_messages"][ai_idx] = ("assistant", current_text)
                                        render_role_messages() 
                                    elif current_event == "done":
                                        pass
                                    # [规范 6 强制] error 不得静默，落地并展示
                                    elif current_event == "error":
                                        err_detail = data.get("detail", "未知流式错误")
                                        state["role_messages"][ai_idx] = ("assistant", f"⚠️ 服务端错误: {err_detail}")
                                        render_role_messages()
                                        show_toast(f"流式生成报错: {err_detail}", error=True)
                                except Exception:
                                    pass
        except Exception as exc:
            state["role_messages"][ai_idx] = ("assistant", f"⚠️ 网络连接中断: {exc}")
            show_toast(f"网络连接中断: {exc}", error=True)

        role_input.disabled = False
        role_send_btn.disabled = False
        role_input.focus()
        render_role_messages()
        page.update()

    async def on_export_role(e: ft.ControlEvent | None = None) -> None:
        selected = state.get("selected_character")
        if not isinstance(selected, dict):
            show_toast("请先选择角色", error=True)
            return

        char_id = selected.get("character_id")
        try:
            package_bytes, filename = await api_export_character(char_id)
            export_dir.mkdir(parents=True, exist_ok=True)
            target = export_dir / filename
            target.write_bytes(package_bytes)
            show_toast(f"已导出：{target}")
        except Exception as exc:
            show_toast(f"导出失败：{exc}", error=True)

    def on_edit_selected(e: ft.ControlEvent | None = None) -> None:
        if state.get("active_mode") == "story":
            selected_story = state.get("selected_story")
            if isinstance(selected_story, dict):
                set_story_builder_view(selected_story)
            else:
                show_toast("请先选择故事", error=True)
            return

        selected_character = state.get("selected_character")
        if not isinstance(selected_character, dict):
            show_toast("请先选择角色", error=True)
            return

        state["active_mode"] = "roleplay"
        state["editing_character_id"] = selected_character.get("character_id")
        state["builder_notes"] = []
        state["builder_messages"] = [("assistant", "正在编辑已保存角色。修改草案字段后点击保存。")]
        draft_name.value = str(selected_character.get("name") or "")
        draft_desc.value = str(selected_character.get("description") or "")
        draft_first.value = str(selected_character.get("first_message") or "")
        draft_system.value = str(selected_character.get("system_prompt") or "")
        draft_lorebook.value = "角色世界书编辑暂未并入本表单；本轮保留已有角色世界书数据。"
        draft_illustration.value = ""
        draft_audio.value = ""
        draft_source.value = "草案来源：已保存角色"
        draft_route_note.value = "提示：当前为编辑模式，保存会覆盖角色基础字段。"
        save_role_btn.content = ft.Text("保存角色修改")
        draft_card.visible = True

        header_title.value = "编辑角色"
        header_subtitle.value = "修改角色基础字段，保存后返回角色对话"
        export_btn.visible = False
        edit_btn.visible = False
        delete_btn.visible = True
        back_to_builder_btn.visible = True
        builder_view.visible = True
        role_view.visible = False
        story_builder_view.visible = False
        story_view.visible = False
        render_builder_messages()
        render_character_list()
        page.update()
        apply_theme()

    async def on_delete_selected(e: ft.ControlEvent | None = None) -> None:
        if state.get("active_mode") == "story":
            selected_story = state.get("selected_story")
            if not isinstance(selected_story, dict):
                show_toast("请先选择故事", error=True)
                return
            project_id = str(selected_story.get("project_id") or "")
            if not project_id:
                show_toast("故事 ID 缺失", error=True)
                return
            try:
                await api_delete(f"/story/projects/{project_id}")
                state["selected_story"] = None
                state["story_session_id"] = None
                state["story_session"] = None
                state["story_messages"] = []
                state["story_facts"] = []
                state["story_checkpoints"] = []
                state["story_lorebooks"] = []
                state["story_actions"] = []
                await reload_stories(select_latest=False)
                set_story_builder_view(None)
                show_toast("故事已删除")
            except ApiError as exc:
                show_toast(f"删除故事失败：{exc}", error=True)
            return

        selected_character = state.get("selected_character")
        if not isinstance(selected_character, dict):
            show_toast("请先选择角色", error=True)
            return
        character_id = str(selected_character.get("character_id") or state.get("editing_character_id") or "")
        if not character_id:
            show_toast("角色 ID 缺失", error=True)
            return
        try:
            await api_delete(f"/characters/{character_id}")
            state["selected_character"] = None
            state["selected_session_id"] = None
            state["editing_character_id"] = None
            state["role_messages"] = []
            state["role_actions"] = []
            await reload_characters(select_latest=False)
            set_builder_view()
            show_toast("角色已删除")
        except ApiError as exc:
            show_toast(f"删除角色失败：{exc}", error=True)

    async def on_save_story(e: ft.ControlEvent | None = None) -> None:
        title = (story_title.value or "").strip()
        premise = (story_premise.value or "").strip()
        if not title or not premise:
            show_toast("请填写故事标题和核心设定", error=True)
            return

        payload = {
            "title": title,
            "premise": premise,
            "opening_scene": (story_opening.value or "").strip(),
            "system_prompt": (story_system.value or "").strip(),
        }
        try:
            editing_id = state.get("editing_story_id")
            if editing_id:
                project = await api_put(f"/story/projects/{editing_id}", payload)
                show_toast("故事修改已保存")
            else:
                project = await api_post("/story/projects", payload)
                show_toast("故事项目已创建")
            state["editing_story_id"] = None
            await reload_stories(select_latest=False)
            await select_story(project if isinstance(project, dict) else payload)
        except ApiError as exc:
            show_toast(f"保存故事失败：{exc}", error=True)

    async def on_generate_story_draft(e: ft.ControlEvent | None = None) -> None:
        prompt = (story_draft_prompt.value or "").strip()
        if not prompt:
            show_toast("请先输入故事草案需求", error=True)
            return

        story_draft_prompt.disabled = True
        story_draft_generate_btn.disabled = True
        story_draft_status.value = "草案状态：正在生成..."
        page.update()

        try:
            artifact_map, job_id = await _run_generation_job({
                "user_input": prompt,
                "pipeline_type": "story_project",
                "apply_mode": "draft_only",
                "include_illustration_prompt": True,
                "include_audio_plan": True,
                "run_async": True,
            })
            bundle = artifact_map.get("story_bundle")
            if not isinstance(bundle, dict):
                bundle = {
                    "story_blueprint": artifact_map.get("story_blueprint", {}),
                    "story_lorebook": artifact_map.get("story_lorebook", {}),
                    "story_continuity_review": artifact_map.get("story_continuity_review", {}),
                    "illustration_prompt": artifact_map.get("illustration_prompt", {}),
                    "audio_plan": artifact_map.get("audio_plan", {}),
                }
            populate_story_draft(bundle)
            story_draft_status.value = f"草案状态：已生成（job {job_id[:8]}），可编辑后应用"
            show_toast("故事草案已生成")
        except (OperationTimeoutError, ApiError) as exc:
            story_draft_status.value = f"草案状态：生成失败 - {exc}"
            show_toast(f"故事草案生成失败：{exc}", error=True)
        finally:
            story_draft_prompt.disabled = False
            story_draft_generate_btn.disabled = False
            page.update()
            apply_theme()

    async def apply_story_draft(mode: str) -> None:
        story_draft_payload = read_story_draft_payload()
        validation_error = validate_story_draft_payload(story_draft_payload)
        if validation_error:
            show_toast(validation_error, error=True)
            return

        selected_story = state.get("selected_story")
        target_project_id = None
        if mode == "current":
            if not isinstance(selected_story, dict) or not selected_story.get("project_id"):
                show_toast("覆盖当前故事前，请先选择一个故事项目", error=True)
                return
            target_project_id = str(selected_story.get("project_id"))

        story_draft_apply_new_btn.disabled = True
        story_draft_apply_current_btn.disabled = True
        story_draft_status.value = "草案状态：正在应用到故事项目..."
        page.update()

        try:
            job_payload: dict[str, Any] = {
                "user_input": (story_draft_prompt.value or story_draft_title.value or "apply story draft").strip(),
                "pipeline_type": "story_project",
                "apply_mode": "direct_apply",
                "story_draft_payload": story_draft_payload,
                "include_illustration_prompt": bool((story_draft_illustration.value or "").strip()),
                "include_audio_plan": bool((story_draft_audio.value or "").strip()),
                "run_async": True,
            }
            if target_project_id:
                job_payload["story_project_id"] = target_project_id

            artifact_map, job_id = await _run_generation_job(job_payload)
            story_bundle = artifact_map.get("story_bundle")
            apply_result = story_bundle.get("apply_result") if isinstance(story_bundle, dict) else None
            project_id = str(apply_result.get("project_id") or "") if isinstance(apply_result, dict) else ""
            if not project_id:
                raise ApiError("应用完成但未返回 story project id")

            await reload_stories(select_latest=False)
            project = await api_get(f"/story/projects/{project_id}")
            story_draft_status.value = f"草案状态：已应用（job {job_id[:8]}）"
            show_toast("故事草案已应用")
            await select_story(project if isinstance(project, dict) else {"project_id": project_id})
        except (OperationTimeoutError, ApiError) as exc:
            story_draft_status.value = f"草案状态：应用失败 - {exc}"
            show_toast(f"故事草案应用失败：{exc}", error=True)
        finally:
            story_draft_apply_new_btn.disabled = False
            story_draft_apply_current_btn.disabled = False
            page.update()
            apply_theme()

    async def on_apply_story_draft_new(e: ft.ControlEvent | None = None) -> None:
        await apply_story_draft("new")

    async def on_apply_story_draft_current(e: ft.ControlEvent | None = None) -> None:
        await apply_story_draft("current")

    async def ensure_story_session(project_id: str) -> dict[str, Any]:
        sessions = await api_get("/story/sessions", params={"project_id": project_id, "limit": 1, "offset": 0})
        if isinstance(sessions, list) and sessions:
            return sessions[0]
        created = await api_post(f"/story/projects/{project_id}/sessions", {})
        if not isinstance(created, dict):
            raise ApiError("故事会话创建失败")
        return created

    async def reload_story_lorebooks(project_id: str) -> None:
        items = await api_get(f"/story/projects/{project_id}/lorebooks")
        state["story_lorebooks"] = items if isinstance(items, list) else []
        render_story_lorebooks()

    async def refresh_story_workspace() -> None:
        session_id = str(state.get("story_session_id") or "")
        selected_story = state.get("selected_story")
        if not session_id or not isinstance(selected_story, dict):
            return

        try:
            session = await api_get(f"/story/sessions/{session_id}")
            history_payload = await api_get(f"/story/history/{session_id}")
            facts = await api_get(f"/story/facts/{session_id}")
            checkpoints = await api_get(f"/story/sessions/{session_id}/checkpoints")
            actions = await api_get(f"/story/actions/{session_id}")
            try:
                stats = await api_get(f"/story/context/{session_id}/stats")
            except ApiError:
                stats = None

            state["story_session"] = session if isinstance(session, dict) else None
            history_items = history_payload.get("history") if isinstance(history_payload, dict) else []
            messages: list[tuple[str, str]] = []
            for item in history_items if isinstance(history_items, list) else []:
                if not isinstance(item, dict):
                    continue
                raw_role = str(item.get("role") or "")
                role = "user" if raw_role in {"user", "player"} else "assistant"
                content = str(item.get("content") or "")
                if content:
                    messages.append((role, content))
            state["story_messages"] = messages or [("assistant", str(selected_story.get("opening_scene") or "故事会话已启动。"))]
            state["story_facts"] = facts if isinstance(facts, list) else []
            state["story_checkpoints"] = checkpoints if isinstance(checkpoints, list) else []
            state["story_actions"] = actions if isinstance(actions, list) else []
            state["story_context_stats"] = stats if isinstance(stats, dict) else None
            await reload_story_lorebooks(str(selected_story.get("project_id") or ""))

            session_obj = state.get("story_session")
            story_summary.value = str(session_obj.get("current_summary") or "暂无摘要") if isinstance(session_obj, dict) else "暂无摘要"
            story_scene.value = str(session_obj.get("current_scene") or "暂无当前场景") if isinstance(session_obj, dict) else "暂无当前场景"
            if isinstance(stats, dict):
                story_context_stats_text.value = (
                    f"上下文预算 {stats.get('context_char_budget')} 字符 · "
                    f"事实 {stats.get('fact_count')} · "
                    f"世界书命中 {stats.get('lorebook_hit_count')} · "
                    f"近期条目 {stats.get('recent_entry_count')} · "
                    f"检查点 {stats.get('checkpoint_count')}"
                )
            else:
                story_context_stats_text.value = "上下文状态：未加载"

            render_story_messages()
            render_story_memory_panels()
            render_story_action_history()
            page.update()
            apply_theme()
        except ApiError as exc:
            show_toast(f"刷新故事工作区失败：{exc}", error=True)

    async def select_story(project: dict[str, Any]) -> None:
        set_story_view(project)
        project_id = str(project.get("project_id") or "")
        if not project_id:
            show_toast("故事 ID 缺失", error=True)
            return

        state["story_messages"] = [("assistant", "正在打开故事会话...")]
        render_story_messages()
        page.update()

        try:
            session = await ensure_story_session(project_id)
            state["story_session_id"] = session.get("session_id")
            state["story_session"] = session
            await refresh_story_workspace()
        except ApiError as exc:
            state["story_messages"] = [("assistant", f"故事会话启动失败：{exc}")]
            render_story_messages()
            page.update()

    async def on_story_send(e: ft.ControlEvent | None = None) -> None:
        text = (story_input.value or "").strip()
        if not text:
            return
        session_id = state.get("story_session_id")
        if not session_id:
            show_toast("当前故事会话未初始化", error=True)
            return

        story_input.value = ""
        story_input.disabled = True
        story_send_btn.disabled = True
        state["story_messages"].append(("user", text))
        state["story_messages"].append(("assistant", "思考中..."))
        render_story_messages()
        page.update()

        try:
            await api_post("/story/message", {"session_id": session_id, "message": text})
            await refresh_story_workspace()
        except ApiError as exc:
            if state["story_messages"] and state["story_messages"][-1] == ("assistant", "思考中..."):
                state["story_messages"].pop()
            state["story_messages"].append(("assistant", f"续写失败：{exc}"))
            render_story_messages()
            show_toast(f"续写失败：{exc}", error=True)
        finally:
            story_input.disabled = False
            story_send_btn.disabled = False
            story_input.focus()
            page.update()

    async def on_save_story_lorebook(e: ft.ControlEvent | None = None) -> None:
        selected_story = state.get("selected_story")
        if not isinstance(selected_story, dict):
            show_toast("请先打开一个故事项目", error=True)
            return
        project_id = str(selected_story.get("project_id") or "")
        keyword = (story_lore_keyword.value or "").strip()
        insert_text = (story_lore_text.value or "").strip()
        if not keyword or not insert_text:
            show_toast("请填写世界书触发词和插入文本", error=True)
            return
        try:
            sort_order = int((story_lore_order.value or "100").strip())
        except ValueError:
            sort_order = 100
        payload = {
            "keyword": keyword,
            "insert_text": insert_text,
            "sort_order": sort_order,
            "enabled": bool(story_lore_enabled.value),
        }
        try:
            editing_id = state.get("editing_story_lorebook_id")
            if editing_id:
                await api_put(f"/story/lorebooks/{editing_id}", payload)
                show_toast("故事世界书已更新")
            else:
                await api_post(f"/story/projects/{project_id}/lorebooks", payload)
                show_toast("故事世界书已新增")
            clear_story_lorebook_form()
            await reload_story_lorebooks(project_id)
            page.update()
        except ApiError as exc:
            show_toast(f"保存故事世界书失败：{exc}", error=True)

    async def on_delete_story_lorebook(lorebook_id: str) -> None:
        selected_story = state.get("selected_story")
        if not lorebook_id or not isinstance(selected_story, dict):
            show_toast("世界书条目或故事项目缺失", error=True)
            return
        try:
            await api_delete(f"/story/lorebooks/{lorebook_id}")
            await reload_story_lorebooks(str(selected_story.get("project_id") or ""))
            show_toast("故事世界书已删除")
            page.update()
        except ApiError as exc:
            show_toast(f"删除故事世界书失败：{exc}", error=True)

    async def on_rollback_story_checkpoint(checkpoint_id: str) -> None:
        session_id = str(state.get("story_session_id") or "")
        if not session_id or not checkpoint_id:
            show_toast("会话或检查点缺失", error=True)
            return
        try:
            await api_post(f"/story/sessions/{session_id}/rollback/{checkpoint_id}", {})
            await refresh_story_workspace()
            show_toast("已回滚到检查点")
        except ApiError as exc:
            show_toast(f"回滚失败：{exc}", error=True)

    async def on_open_settings(e: ft.ControlEvent | None = None) -> None:
        try:
            await load_settings()
            await load_model_endpoints(select_first=False)
            await load_model_endpoint_health(include_disabled=True)
            render_model_endpoint_list()
            refresh_task_binding_options()
            render_endpoint_health_list()
            settings_dialog.open = True
            page.update()
            apply_theme()
        except ApiError as exc:
            show_toast(f"读取设置失败：{exc}", error=True)

    async def on_save_settings_click(e: ft.ControlEvent | None = None) -> None:
        try:
            await save_settings()
            settings_dialog.open = False
            page.update()
            apply_theme()
        except ApiError as exc:
            show_toast(f"保存设置失败：{exc}", error=True)

    async def open_action_dialog(text: str, scope: str = "roleplay", default_action: str = "image_prompt") -> None:
        if scope == "story":
            if not state.get("story_session_id"):
                show_toast("当前故事会话未初始化", error=True)
                return
        elif not state.get("selected_session_id"):
            show_toast("当前角色会话未初始化", error=True)
            return

        state["action_scope"] = scope
        action_dialog.title = ft.Text("故事段落 AIGC 增强" if scope == "story" else "段落 AIGC 增强", weight=ft.FontWeight.W_700)
        action_type.value = default_action if default_action in {"image_prompt", "image_generate", "audio_plan"} else "image_prompt"
        action_selected_text.value = (text or "").strip()
        action_result.value = ""
        action_dialog.open = True
        page.update()
        apply_theme()

    async def on_execute_action(e: ft.ControlEvent | None = None) -> None:
        scope = str(state.get("action_scope") or "roleplay")
        session_id = state.get("story_session_id") if scope == "story" else state.get("selected_session_id")
        selected = (action_selected_text.value or "").strip()
        if not selected:
            show_toast("请先填写段落内容", error=True)
            return

        payload = {
            "session_id": session_id,
            "action_type": action_type.value or "image_prompt",
            "selected_text": selected,
            "style": (action_style.value or "").strip() or None,
            "shot": (action_shot.value or "").strip() or None,
            "voice": (action_voice.value or "").strip() or None,
        }

        try:
            endpoint = "/story/actions" if scope == "story" else "/chat/actions"
            created = await api_post(endpoint, payload)
            if isinstance(created, dict):
                if scope == "story":
                    state.setdefault("story_actions", []).append(created)
                else:
                    state.setdefault("role_actions",[]).append(created)
                result_obj = created.get("result")
                action_result.value = format_action_result(result_obj if isinstance(result_obj, dict) else {})
            render_action_history()
            render_story_action_history()
            page.update()
            show_toast("AIGC 动作执行完成")
        except ApiError as exc:
            show_toast(f"AIGC 动作执行失败：{exc}", error=True)

    def on_theme_change(e: ft.ControlEvent) -> None:
        state["is_dark"] = bool(theme_switch.value)
        apply_theme()

    def on_create_new(e: ft.ControlEvent | None = None) -> None:
        if state.get("active_mode") == "story":
            set_story_builder_view(None)
        else:
            set_builder_view()

    def on_back_to_builder(e: ft.ControlEvent | None = None) -> None:
        if state.get("active_mode") == "story":
            set_story_builder_view(None)
        else:
            set_builder_view()

    def switch_to_roleplay(e: ft.ControlEvent | None = None) -> None:
        state["active_mode"] = "roleplay"
        set_builder_view()
        apply_theme()

    def switch_to_story(e: ft.ControlEvent | None = None) -> None:
        state["active_mode"] = "story"
        set_story_builder_view(None)
        apply_theme()

    # Event Bindings
    roleplay_mode_btn.on_click = switch_to_roleplay
    story_mode_btn.on_click = switch_to_story
    create_new_btn.on_click = on_create_new
    builder_send_btn.on_click = lambda e: page.run_task(on_builder_send)
    builder_input.on_submit = lambda e: page.run_task(on_builder_send)
    save_role_btn.on_click = lambda e: page.run_task(on_save_role)

    role_send_btn.on_click = lambda e: page.run_task(on_role_send)
    role_input.on_submit = lambda e: page.run_task(on_role_send)
    story_send_btn.on_click = lambda e: page.run_task(on_story_send)
    story_input.on_submit = lambda e: page.run_task(on_story_send)
    save_story_btn.on_click = lambda e: page.run_task(on_save_story)
    story_draft_generate_btn.on_click = lambda e: page.run_task(on_generate_story_draft)
    story_draft_apply_new_btn.on_click = lambda e: page.run_task(on_apply_story_draft_new)
    story_draft_apply_current_btn.on_click = lambda e: page.run_task(on_apply_story_draft_current)
    story_lore_save_btn.on_click = lambda e: page.run_task(on_save_story_lorebook)
    story_lore_clear_btn.on_click = lambda e: (clear_story_lorebook_form(), page.update())

    export_btn.on_click = lambda e: page.run_task(on_export_role)
    edit_btn.on_click = on_edit_selected
    delete_btn.on_click = lambda e: page.run_task(on_delete_selected)
    back_to_builder_btn.on_click = on_back_to_builder

    theme_switch.on_change = on_theme_change
    settings_btn.on_click = lambda e: page.run_task(on_open_settings)
    endpoint_refresh_btn.on_click = lambda e: page.run_task(on_refresh_endpoint_click)
    endpoint_health_btn.on_click = lambda e: page.run_task(on_health_endpoint_click)
    endpoint_new_btn.on_click = on_new_endpoint_click
    endpoint_save_btn.on_click = lambda e: page.run_task(on_save_endpoint_click)
    endpoint_delete_btn.on_click = lambda e: page.run_task(on_delete_endpoint_click)

    settings_dialog.actions[0].on_click = lambda e: (setattr(settings_dialog, "open", False), page.update())
    settings_dialog.actions[1].on_click = lambda e: page.run_task(on_save_settings_click)

    action_dialog.actions[0].on_click = lambda e: (setattr(action_dialog, "open", False), page.update())
    action_dialog.actions[1].on_click = lambda e: page.run_task(on_execute_action)

    page.run_task(initialize)

if __name__ == "__main__":
    ft.app(target=main)
