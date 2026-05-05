from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.agent_runtime import (
    ChatRagRuntime,
    RagContextBundle,
    TavilySearchClient,
    ToolCallRuntime,
    _merge_summary_locally,
)
from app.quota import DailyQuotaLimiter, QuotaStatus
from app.repositories import (
    UNSET,
    AppSettingsRepository,
    AssetRepository,
    CharacterDraftNotFoundError,
    CharacterDraftRepository,
    CharacterRepository,
    DraftVersionConflictError,
    GenerationRepository,
    LorebookRepository,
    ModelEndpointRepository,
    SessionRepository,
    StoredAsset,
    StoredCharacter,
    StoredCharacterDraft,
    StoredGenerationArtifact,
    StoredGenerationEvent,
    StoredGenerationJob,
    StoredGenerationTask,
    StoredLorebook,
    StoredMessage,
    StoredModelEndpoint,
    StoredSessionSummary,
    StoredStoryCheckpoint,
    StoredStoryEntry,
    StoredStoryFact,
    StoredStoryLorebook,
    StoredStoryProject,
    StoredStorySession,
    StoredStoryAction,
    StoryCheckpointNotFoundError,
    StoryLorebookNotFoundError,
    StoryProjectNotFoundError,
    StoryRepository,
    StorySessionNotFoundError,
)


WELCOME_MESSAGE = (
    "Hello, I am your prototype assistant. "
    "Tell me your goal and I will help you break it into concrete steps."
)

WIZARD_SYSTEM_PROMPT_LIBRARY: dict[str, str] = {
    "character_extraction": (
        "You extract roleplay character cards from user intent. "
        "Return strict JSON only with keys: "
        "name, description, system_prompt, first_message."
    )
}

GENERATION_TASK_TYPES: tuple[str, ...] = (
    "intent_parse",
    "plan_dispatch",
    "character_card_generate",
    "lorebook_generate",
    "story_blueprint_generate",
    "story_lorebook_generate",
    "story_continuity_review",
    "illustration_prompt_generate",
    "audio_plan_generate",
    "result_review",
)


@dataclass(frozen=True)
class Message:
    role: str
    content: str
    timestamp: datetime


@dataclass(frozen=True)
class AppSettingsPublic:
    mode: str
    byok_base_url: str
    byok_model: str
    has_api_key: bool
    task_endpoint_bindings: dict[str, str]
    updated_at: datetime


@dataclass(frozen=True)
class ByokRuntimeConfig:
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class TrialProxyRuntimeConfig:
    mode: str
    enabled: bool
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float
    system_prompt: str


@dataclass(frozen=True)
class TrialProxyPublicStatus:
    mode: str
    enabled: bool
    has_api_key: bool
    base_url: str
    model: str
    timeout_seconds: float


@dataclass(frozen=True)
class TrialProxyHealthCheck:
    mode: str
    enabled: bool
    base_url: str
    health_url: str
    healthy: bool
    status_code: int | None
    latency_ms: float | None
    detail: str


@dataclass(frozen=True)
class ModelEndpointPublic:
    endpoint_id: str
    provider: str
    name: str
    base_url: str
    model: str
    has_api_key: bool
    enabled: bool
    priority: int
    is_fallback: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ModelEndpointRuntime:
    endpoint_id: str
    provider: str
    name: str
    base_url: str
    model: str
    api_key: str
    enabled: bool
    priority: int
    is_fallback: bool


@dataclass(frozen=True)
class ProviderAdapterDescriptor:
    provider: str
    display_name: str
    openai_compatible: bool
    default_base_url: str


@dataclass(frozen=True)
class ModelEndpointHealth:
    endpoint_id: str
    provider: str
    name: str
    healthy: bool
    status_code: int | None
    latency_ms: float | None
    detail: str


@dataclass(frozen=True)
class GenerationJobPublic:
    job_id: str
    status: str
    user_input: str
    pipeline_version: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class GenerationTaskPublic:
    task_id: str
    job_id: str
    task_type: str
    status: str
    provider: str | None
    endpoint_id: str | None
    attempt: int
    error_message: str | None
    error_type: str | None
    duration_ms: int | None
    request_chars: int
    response_chars: int
    prompt_payload: dict[str, object]
    output_payload: dict[str, object]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class GenerationArtifactPublic:
    artifact_id: str
    job_id: str
    artifact_type: str
    payload: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class GenerationEventPublic:
    event_id: int
    job_id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class WizardCharacterDraft:
    name: str
    description: str
    system_prompt: str
    first_message: str


@dataclass(frozen=True)
class WizardGenerationResult:
    draft: WizardCharacterDraft
    route_mode: str
    auto_completed_fields: list[str]
    search_sources: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class CharacterDraftState:
    character_id: str
    payload: dict[str, object]
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CharacterDraftApplyResult:
    character: StoredCharacter
    applied_version: int


@dataclass(frozen=True)
class ChatContextStats:
    session_id: str
    context_char_budget: int
    rag_context_chars: int
    recent_history_chars: int
    recent_message_count: int
    summary_chars: int
    retrieved_count: int
    updated_at: datetime


@dataclass(frozen=True)
class ChatAigcActionPublic:
    action_id: str
    session_id: str
    action_type: str
    selected_text: str
    result: dict[str, object]
    created_at: datetime


class SessionNotFoundError(ValueError):
    pass


class InvalidMessageError(ValueError):
    pass


class RoutingConfigurationError(ValueError):
    pass


class UpstreamModelError(RuntimeError):
    pass


class GenerationJobStateError(ValueError):
    pass


class GenerationJobCancelledError(RuntimeError):
    pass


def _read_trial_proxy_runtime_config() -> TrialProxyRuntimeConfig:
    raw_mode = os.getenv("TRIAL_PROXY_MODE", "local")
    mode = raw_mode.strip().lower()
    if mode not in {"local", "upstream"}:
        mode = "local"

    api_key = os.getenv("TRIAL_PROXY_API_KEY", "").strip()
    base_url = os.getenv("TRIAL_PROXY_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv("TRIAL_PROXY_MODEL", "gpt-4o-mini").strip()
    system_prompt = os.getenv("TRIAL_PROXY_SYSTEM_PROMPT", "").strip()

    timeout_raw = os.getenv("TRIAL_PROXY_TIMEOUT_SECONDS", "30")
    try:
        timeout_seconds = float(timeout_raw)
    except (TypeError, ValueError):
        timeout_seconds = 30.0
    if timeout_seconds <= 0:
        timeout_seconds = 30.0

    enabled = mode == "upstream" and bool(api_key)

    return TrialProxyRuntimeConfig(
        mode=mode,
        enabled=enabled,
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        system_prompt=system_prompt,
    )


class ChatService:
    def __init__(
        self,
        session_repository: SessionRepository,
        *,
        character_repository: CharacterRepository | None = None,
        lorebook_repository: LorebookRepository | None = None,
        app_settings_service: "AppSettingsService | None" = None,
        rag_runtime: ChatRagRuntime | None = None,
        tool_runtime: ToolCallRuntime | None = None,
        model_endpoint_service: "ModelEndpointService | None" = None,
    ) -> None:
        self._session_repository = session_repository
        self._character_repository = character_repository
        self._lorebook_repository = lorebook_repository
        self._app_settings_service = app_settings_service
        self._rag_runtime = rag_runtime
        self._tool_runtime = tool_runtime
        self._model_endpoint_service = model_endpoint_service
        self._context_stats_by_session: dict[str, ChatContextStats] = {}

    def create_session(
        self,
        *,
        welcome_message: str = WELCOME_MESSAGE,
        character_id: str | None = None,
    ) -> tuple[str, str]:
        session_id = str(uuid4())
        self._session_repository.create_session(
            session_id=session_id,
            welcome_message=welcome_message,
            character_id=character_id,
        )
        return session_id, welcome_message

    def add_user_message(
        self,
        session_id: str,
        message: str,
        *,
        device_id: str | None = None,
    ) -> tuple[str, int]:
        if not self._session_repository.session_exists(session_id):
            raise SessionNotFoundError("Session does not exist.")

        cleaned = message.strip()
        if not cleaned:
            raise InvalidMessageError("message cannot be empty")

        self._session_repository.append_message(session_id, "user", cleaned)

        history: list[StoredMessage] = self._session_repository.get_history(session_id)
        session_summary = self._session_repository.get_session_summary(session_id)
        system_prompt = self._resolve_system_prompt(session_summary)
        lore_context = self._resolve_lore_context(
            session_summary=session_summary,
            latest_user_message=cleaned,
        )
        context_bundle = self._prepare_rag_context(
            session_id=session_id,
            history=history,
            latest_user_message=cleaned,
            lore_context=lore_context,
        )

        reply = self._generate_reply(
            session_id=session_id,
            message=cleaned,
            history=context_bundle.recent_history,
            system_prompt=system_prompt,
            lore_context=context_bundle.rag_context,
            device_id=device_id,
        )
        self._session_repository.append_message(session_id, "assistant", reply)
        self._persist_turn_memory(
            session_id=session_id,
            user_message=cleaned,
            assistant_message=reply,
        )

        return reply, self._session_repository.count_messages(session_id)

    def start_user_message_stream(
        self,
        session_id: str,
        message: str,
        *,
        device_id: str | None = None,
    ) -> tuple[Iterator[str], Callable[[str], int]]:
        if not self._session_repository.session_exists(session_id):
            raise SessionNotFoundError("Session does not exist.")

        cleaned = message.strip()
        if not cleaned:
            raise InvalidMessageError("message cannot be empty")

        self._session_repository.append_message(session_id, "user", cleaned)

        history: list[StoredMessage] = self._session_repository.get_history(session_id)
        session_summary = self._session_repository.get_session_summary(session_id)
        system_prompt = self._resolve_system_prompt(session_summary)
        lore_context = self._resolve_lore_context(
            session_summary=session_summary,
            latest_user_message=cleaned,
        )
        context_bundle = self._prepare_rag_context(
            session_id=session_id,
            history=history,
            latest_user_message=cleaned,
            lore_context=lore_context,
        )

        chunk_iterator = self._generate_reply_stream(
            session_id=session_id,
            message=cleaned,
            history=context_bundle.recent_history,
            system_prompt=system_prompt,
            lore_context=context_bundle.rag_context,
            device_id=device_id,
        )

        def finalize(full_reply: str) -> int:
            cleaned_reply = full_reply.strip()
            if not cleaned_reply:
                raise UpstreamModelError("Stream response content is empty.")
            self._session_repository.append_message(session_id, "assistant", cleaned_reply)
            self._persist_turn_memory(
                session_id=session_id,
                user_message=cleaned,
                assistant_message=cleaned_reply,
            )
            return self._session_repository.count_messages(session_id)

        return chunk_iterator, finalize

    def get_history(self, session_id: str) -> list[Message]:
        if not self._session_repository.session_exists(session_id):
            raise SessionNotFoundError("Session does not exist.")

        history: list[StoredMessage] = self._session_repository.get_history(session_id)
        return [
            Message(role=item.role, content=item.content, timestamp=item.timestamp)
            for item in history
        ]

    def list_sessions(
        self,
        *,
        character_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StoredSessionSummary]:
        return self._session_repository.list_sessions(
            character_id=character_id,
            limit=limit,
            offset=offset,
        )

    def get_session_summary(self, session_id: str) -> StoredSessionSummary:
        try:
            return self._session_repository.get_session_summary(session_id)
        except ValueError as exc:
            raise SessionNotFoundError(str(exc)) from exc

    def get_context_stats(self, session_id: str) -> ChatContextStats:
        if not self._session_repository.session_exists(session_id):
            raise SessionNotFoundError("Session does not exist.")
        cached = self._context_stats_by_session.get(session_id)
        if cached is not None:
            return cached
        return ChatContextStats(
            session_id=session_id,
            context_char_budget=0,
            rag_context_chars=0,
            recent_history_chars=0,
            recent_message_count=0,
            summary_chars=0,
            retrieved_count=0,
            updated_at=datetime.now(timezone.utc),
        )

    def run_chat_action(
        self,
        *,
        session_id: str,
        action_type: str,
        selected_text: str,
        style: str | None = None,
        shot: str | None = None,
        voice: str | None = None,
    ) -> ChatAigcActionPublic:
        if not self._session_repository.session_exists(session_id):
            raise SessionNotFoundError("Session does not exist.")

        normalized_action = action_type.strip().lower()
        text = selected_text.strip()
        if not text:
            raise ValueError("selected_text cannot be empty")

        if normalized_action in {"image", "image_prompt", "image_generate"}:
            tool_args = {
                "paragraph": text,
                "style": (style or "cinematic").strip() or "cinematic",
                "shot": (shot or "medium shot").strip() or "medium shot",
            }
            if self._tool_runtime is not None and self._tool_runtime.enabled:
                result = self._tool_runtime.execute_tool(
                    name="build_image_prompt",
                    arguments_json=json.dumps(tool_args, ensure_ascii=False),
                    session_id=session_id,
                )
            else:
                prompt = (
                    f"{tool_args['style']} illustration, {tool_args['shot']}, focus on: {text[:700]}. "
                    "high detail, coherent lighting, no watermark"
                )
                result = {
                    "prompt": prompt,
                    "negative_prompt": "lowres, blurry, watermark, distorted anatomy, bad hands",
                    "style": tool_args["style"],
                    "shot": tool_args["shot"],
                }
            if normalized_action in {"image", "image_generate"}:
                generated_result: dict[str, object] | None = None
                image_error: str | None = None
                if self._tool_runtime is not None and self._tool_runtime.image_generation_enabled:
                    try:
                        generated_result = self._tool_runtime.execute_tool(
                            name="generate_image",
                            arguments_json=json.dumps(
                                {
                                    "prompt": str(result.get("prompt", "")),
                                    "negative_prompt": str(result.get("negative_prompt", "")),
                                },
                                ensure_ascii=False,
                            ),
                            session_id=session_id,
                        )
                    except Exception as exc:
                        image_error = str(exc)
                if generated_result is not None:
                    result = {
                        "prompt_payload": result,
                        "image_result": generated_result,
                    }
                    normalized_action = "image_generate"
                else:
                    if image_error:
                        result = {
                            **result,
                            "image_error": image_error,
                        }
                    normalized_action = "image_prompt"
            else:
                normalized_action = "image_prompt"
        elif normalized_action in {"audio", "audio_plan", "tts"}:
            chosen_voice = (voice or "neutral_female").strip() or "neutral_female"
            result = {
                "voice": chosen_voice,
                "script": text[:1600],
                "emotion": "immersive",
                "pace": "medium",
                "format": "mp3",
            }
            normalized_action = "audio_plan"
        else:
            raise ValueError("action_type must be one of: image_prompt, image_generate, audio_plan")

        if self._rag_runtime is not None:
            record = self._rag_runtime.create_chat_action(
                session_id=session_id,
                action_type=normalized_action,
                selected_text=text,
                result_payload=result,
            )
            return ChatAigcActionPublic(
                action_id=record.action_id,
                session_id=record.session_id,
                action_type=record.action_type,
                selected_text=record.selected_text,
                result=record.result_payload,
                created_at=record.created_at,
            )

        return ChatAigcActionPublic(
            action_id=str(uuid4()),
            session_id=session_id,
            action_type=normalized_action,
            selected_text=text,
            result=result,
            created_at=datetime.now(timezone.utc),
        )

    def list_chat_actions(
        self,
        *,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatAigcActionPublic]:
        if not self._session_repository.session_exists(session_id):
            raise SessionNotFoundError("Session does not exist.")

        if self._rag_runtime is None:
            return []

        records = self._rag_runtime.list_chat_actions(
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
        return [
            ChatAigcActionPublic(
                action_id=item.action_id,
                session_id=item.session_id,
                action_type=item.action_type,
                selected_text=item.selected_text,
                result=item.result_payload,
                created_at=item.created_at,
            )
            for item in records
        ]

    def _resolve_system_prompt(self, session_summary: StoredSessionSummary) -> str:
        if not session_summary.character_id or self._character_repository is None:
            return ""
        try:
            character = self._character_repository.get_character(session_summary.character_id)
        except ValueError:
            return ""
        return character.system_prompt.strip()

    def _generate_reply(
        self,
        *,
        session_id: str,
        message: str,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
        device_id: str | None = None,
    ) -> str:
        if self._app_settings_service is not None:
            mode = self._app_settings_service.get_routing_mode()
            if mode == "byok":
                try:
                    return self._generate_byok_reply(
                        session_id=session_id,
                        history=history,
                        system_prompt=system_prompt,
                        lore_context=lore_context,
                    )
                except Exception:
                    # degrade to endpoint/proxy/local to keep app available
                    pass

        endpoint_reply = self._generate_model_endpoint_reply(
            session_id=session_id,
            history=history,
            system_prompt=system_prompt,
            lore_context=lore_context,
        )
        if endpoint_reply is not None:
            return endpoint_reply

        trial_proxy_config = self._resolve_trial_proxy_runtime_config()
        if trial_proxy_config.enabled:
            try:
                return self._generate_trial_proxy_reply(
                    session_id=session_id,
                    history=history,
                    system_prompt=system_prompt,
                    lore_context=lore_context,
                    proxy_config=trial_proxy_config,
                    device_id=device_id,
                )
            except Exception:
                # keep local chat available even when proxy upstream is unavailable
                pass

        return self._generate_trial_reply(
            message,
            lore_context=lore_context,
            history=history,
        )

    def _generate_reply_stream(
        self,
        *,
        session_id: str,
        message: str,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
        device_id: str | None = None,
    ) -> Iterator[str]:
        if self._app_settings_service is not None:
            mode = self._app_settings_service.get_routing_mode()
            if mode == "byok":
                try:
                    return self._generate_byok_reply_stream(
                        session_id=session_id,
                        history=history,
                        system_prompt=system_prompt,
                        lore_context=lore_context,
                    )
                except Exception:
                    # degrade to endpoint/proxy/local to keep app available
                    pass

        endpoint_stream = self._generate_model_endpoint_reply_stream(
            session_id=session_id,
            history=history,
            system_prompt=system_prompt,
            lore_context=lore_context,
        )
        if endpoint_stream is not None:
            return endpoint_stream

        trial_proxy_config = self._resolve_trial_proxy_runtime_config()
        if trial_proxy_config.enabled:
            try:
                return self._generate_trial_proxy_reply_stream(
                    session_id=session_id,
                    history=history,
                    system_prompt=system_prompt,
                    lore_context=lore_context,
                    proxy_config=trial_proxy_config,
                    device_id=device_id,
                )
            except Exception:
                # keep local chat available even when proxy upstream is unavailable
                pass

        local_reply = self._generate_trial_reply(
            message,
            lore_context=lore_context,
            history=history,
        )
        return self._stream_text_chunks(local_reply, chunk_size=24)

    def _resolve_trial_proxy_runtime_config(self) -> TrialProxyRuntimeConfig:
        if self._app_settings_service is None:
            return _read_trial_proxy_runtime_config()

        stored_config = self._app_settings_service.get_trial_proxy_runtime_config()
        if stored_config.enabled or stored_config.mode == "upstream":
            return stored_config

        env_config = _read_trial_proxy_runtime_config()
        if env_config.enabled:
            return env_config
        return stored_config

    def _generate_model_endpoint_reply(
        self,
        *,
        session_id: str,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
    ) -> str | None:
        if self._model_endpoint_service is None:
            return None
        messages = self._build_chat_messages(
            history=history,
            system_prompt=system_prompt,
            lore_context=lore_context,
        )
        if not messages:
            return None

        for endpoint in self._select_chat_endpoint_candidates():
            endpoint_url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
            try:
                if self._tool_runtime is not None and self._tool_runtime.enabled:
                    return self._call_openai_compatible_chat_completion_with_tools(
                        endpoint=endpoint_url,
                        api_key=endpoint.api_key,
                        model=endpoint.model,
                        messages=messages,
                        timeout_seconds=30.0,
                        session_id=session_id,
                    )
                return self._call_openai_compatible_chat_completion(
                    endpoint=endpoint_url,
                    api_key=endpoint.api_key,
                    model=endpoint.model,
                    messages=messages,
                    timeout_seconds=30.0,
                )
            except Exception:
                continue
        return None

    def _generate_model_endpoint_reply_stream(
        self,
        *,
        session_id: str,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
    ) -> Iterator[str] | None:
        reply = self._generate_model_endpoint_reply(
            session_id=session_id,
            history=history,
            system_prompt=system_prompt,
            lore_context=lore_context,
        )
        if reply is None:
            return None
        return self._stream_text_chunks(reply, chunk_size=24)

    def _build_chat_messages(
        self,
        *,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
    ) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = []
        merged_system_prompt = system_prompt.strip()
        if lore_context:
            if merged_system_prompt:
                merged_system_prompt = f"{merged_system_prompt}\n\n{lore_context}"
            else:
                merged_system_prompt = lore_context
        if merged_system_prompt:
            messages.append({"role": "system", "content": merged_system_prompt})

        for item in history:
            if item.role not in {"system", "user", "assistant"}:
                continue
            messages.append({"role": item.role, "content": item.content})
        return messages

    def _select_chat_endpoint_candidates(self) -> list[ModelEndpointRuntime]:
        if self._model_endpoint_service is None:
            return []
        endpoints = self._model_endpoint_service.list_runtime_endpoints()
        if not endpoints:
            return []

        raw_pref = os.getenv(
            "CHAT_ENDPOINT_PROVIDER_PREFERENCE",
            "deepseek,qwen,kimi,openai,openai_compatible",
        ).strip()
        pref = [item.strip().lower() for item in raw_pref.split(",") if item.strip()]
        rank = {provider: idx for idx, provider in enumerate(pref)}

        return sorted(
            endpoints,
            key=lambda item: (
                1 if item.is_fallback else 0,
                rank.get(item.provider.lower(), 999),
                item.priority,
                item.name.lower(),
            ),
        )

    def _generate_trial_reply(
        self,
        message: str,
        *,
        lore_context: str,
        history: list[StoredMessage] | None = None,
    ) -> str:
        text = message.lower()
        memory_queries = [
            "remember",
            "\u4f60\u8fd8\u8bb0\u5f97",
            "\u8bb0\u5f97\u6211",
            "\u6211\u53eb\u4ec0\u4e48",
            "who am i",
            "my name",
        ]
        name_regex = r"(?:\u6211\u53eb|\u53eb\u6211|my name is)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,24})"

        if any(keyword in text for keyword in memory_queries):
            if history:
                for item in reversed(history):
                    if item.role != "user":
                        continue
                    hist_match = re.search(
                        name_regex,
                        item.content,
                        flags=re.IGNORECASE,
                    )
                    if hist_match:
                        remembered_name = hist_match.group(1)
                        return (
                            f"\u6211\u8bb0\u5f97\uff0c\u4f60\u4e4b\u524d\u63d0\u5230\u4f60\u53eb\u201c{remembered_name}\u201d\u3002"
                            "\u6211\u4f1a\u7ee7\u7eed\u6cbf\u7528\u8fd9\u4e2a\u8bbe\u5b9a\u8fdb\u884c\u540e\u7eed\u5bf9\u8bdd\u3002"
                        )
            name_match = re.search(
                name_regex,
                lore_context,
                flags=re.IGNORECASE,
            )
            if name_match:
                remembered_name = name_match.group(1)
                return (
                    f"\u6211\u8bb0\u5f97\uff0c\u4f60\u4e4b\u524d\u63d0\u5230\u4f60\u53eb\u201c{remembered_name}\u201d\u3002"
                    "\u6211\u4f1a\u7ee7\u7eed\u6cbf\u7528\u8fd9\u4e2a\u8bbe\u5b9a\u8fdb\u884c\u540e\u7eed\u5bf9\u8bdd\u3002"
                )

        if any(word in text for word in ["hello", "hi", "hey"]):
            base = (
                "Good start. Let's define a minimal scope first, then split execution into "
                "input, processing, and output."
            )
        elif "?" in message or "\uFF1F" in message:
            base = (
                "Clear question. We should map dependencies, define success criteria, "
                "then choose the smallest implementable slice."
            )
        elif len(message) < 8:
            base = "Please share a bit more detail so I can convert this into concrete tasks."
        else:
            base = (
                "Recorded. Next step: split this request into 1) user input "
                "2) system processing 3) result output."
            )

        if lore_context:
            return (
                f"{base}\n\n"
                "[Context] Loaded memory/lore references for this turn."
            )
        return base

    def _generate_byok_reply(
        self,
        *,
        session_id: str,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
    ) -> str:
        if self._app_settings_service is None:
            raise RoutingConfigurationError("BYOK mode is unavailable.")

        config = self._app_settings_service.get_byok_runtime_config()
        endpoint = f"{config.base_url.rstrip('/')}/chat/completions"

        messages: list[dict[str, object]] = []
        merged_system_prompt = system_prompt.strip()
        if lore_context:
            if merged_system_prompt:
                merged_system_prompt = f"{merged_system_prompt}\n\n{lore_context}"
            else:
                merged_system_prompt = lore_context

        if merged_system_prompt:
            messages.append({"role": "system", "content": merged_system_prompt})

        for item in history:
            if item.role not in {"system", "user", "assistant"}:
                continue
            messages.append({"role": item.role, "content": item.content})

        if not messages:
            raise UpstreamModelError("No message payload to send upstream.")

        if self._tool_runtime is not None and self._tool_runtime.enabled:
            return self._call_openai_compatible_chat_completion_with_tools(
                endpoint=endpoint,
                api_key=config.api_key,
                model=config.model,
                messages=messages,
                timeout_seconds=30.0,
                session_id=session_id,
            )

        return self._call_openai_compatible_chat_completion(
            endpoint=endpoint,
            api_key=config.api_key,
            model=config.model,
            messages=messages,
            timeout_seconds=30.0,
        )

    def _generate_byok_reply_stream(
        self,
        *,
        session_id: str,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
    ) -> Iterator[str]:
        if self._app_settings_service is None:
            raise RoutingConfigurationError("BYOK mode is unavailable.")

        config = self._app_settings_service.get_byok_runtime_config()
        endpoint = f"{config.base_url.rstrip('/')}/chat/completions"

        messages: list[dict[str, object]] = []
        merged_system_prompt = system_prompt.strip()
        if lore_context:
            if merged_system_prompt:
                merged_system_prompt = f"{merged_system_prompt}\n\n{lore_context}"
            else:
                merged_system_prompt = lore_context

        if merged_system_prompt:
            messages.append({"role": "system", "content": merged_system_prompt})

        for item in history:
            if item.role not in {"system", "user", "assistant"}:
                continue
            messages.append({"role": item.role, "content": item.content})

        if not messages:
            raise UpstreamModelError("No message payload to send upstream.")

        return self._call_openai_compatible_chat_completion_stream(
            endpoint=endpoint,
            api_key=config.api_key,
            model=config.model,
            messages=messages,
            timeout_seconds=30.0,
        )

    def _generate_trial_proxy_reply(
        self,
        *,
        session_id: str,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
        proxy_config: TrialProxyRuntimeConfig,
        device_id: str | None,
    ) -> str:
        endpoint = f"{proxy_config.base_url.rstrip('/')}/chat/completions"

        messages: list[dict[str, object]] = []
        merged_system_prompt = system_prompt.strip()
        if proxy_config.system_prompt:
            if merged_system_prompt:
                merged_system_prompt = (
                    f"{proxy_config.system_prompt}\n\n{merged_system_prompt}"
                )
            else:
                merged_system_prompt = proxy_config.system_prompt

        if lore_context:
            if merged_system_prompt:
                merged_system_prompt = f"{merged_system_prompt}\n\n{lore_context}"
            else:
                merged_system_prompt = lore_context

        if merged_system_prompt:
            messages.append({"role": "system", "content": merged_system_prompt})

        for item in history:
            if item.role not in {"system", "user", "assistant"}:
                continue
            messages.append({"role": item.role, "content": item.content})

        if not messages:
            raise UpstreamModelError("No message payload to send upstream.")

        extra_headers = self._build_trial_proxy_extra_headers(
            proxy_config=proxy_config,
            device_id=device_id,
        )

        if self._tool_runtime is not None and self._tool_runtime.enabled:
            return self._call_openai_compatible_chat_completion_with_tools(
                endpoint=endpoint,
                api_key=proxy_config.api_key,
                model=proxy_config.model,
                messages=messages,
                timeout_seconds=proxy_config.timeout_seconds,
                session_id=session_id,
                extra_headers=extra_headers,
            )

        return self._call_openai_compatible_chat_completion(
            endpoint=endpoint,
            api_key=proxy_config.api_key,
            model=proxy_config.model,
            messages=messages,
            timeout_seconds=proxy_config.timeout_seconds,
            extra_headers=extra_headers,
        )

    def _generate_trial_proxy_reply_stream(
        self,
        *,
        session_id: str,
        history: list[StoredMessage],
        system_prompt: str,
        lore_context: str,
        proxy_config: TrialProxyRuntimeConfig,
        device_id: str | None,
    ) -> Iterator[str]:
        endpoint = f"{proxy_config.base_url.rstrip('/')}/chat/completions"

        messages: list[dict[str, object]] = []
        merged_system_prompt = system_prompt.strip()
        if proxy_config.system_prompt:
            if merged_system_prompt:
                merged_system_prompt = (
                    f"{proxy_config.system_prompt}\n\n{merged_system_prompt}"
                )
            else:
                merged_system_prompt = proxy_config.system_prompt

        if lore_context:
            if merged_system_prompt:
                merged_system_prompt = f"{merged_system_prompt}\n\n{lore_context}"
            else:
                merged_system_prompt = lore_context

        if merged_system_prompt:
            messages.append({"role": "system", "content": merged_system_prompt})

        for item in history:
            if item.role not in {"system", "user", "assistant"}:
                continue
            messages.append({"role": item.role, "content": item.content})

        if not messages:
            raise UpstreamModelError("No message payload to send upstream.")

        extra_headers = self._build_trial_proxy_extra_headers(
            proxy_config=proxy_config,
            device_id=device_id,
        )

        return self._call_openai_compatible_chat_completion_stream(
            endpoint=endpoint,
            api_key=proxy_config.api_key,
            model=proxy_config.model,
            messages=messages,
            timeout_seconds=proxy_config.timeout_seconds,
            extra_headers=extra_headers,
        )

    @staticmethod
    def _build_trial_proxy_extra_headers(
        *,
        proxy_config: TrialProxyRuntimeConfig,
        device_id: str | None,
    ) -> dict[str, str]:
        normalized_device_id = (device_id or "").strip()
        if not normalized_device_id:
            return {}

        headers: dict[str, str] = {"x-device-id": normalized_device_id}
        signing_secret = os.getenv("TRIAL_GATEWAY_DEVICE_SIGNING_SECRET", "").strip()
        if not signing_secret:
            return headers

        require_fresh_signature = (
            os.getenv("TRIAL_GATEWAY_REQUIRE_FRESH_SIGNATURE", "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        timestamp: int | None = None
        nonce: str | None = None
        quota_date = datetime.now(timezone.utc).date().isoformat()

        if require_fresh_signature:
            timestamp = int(datetime.now(timezone.utc).timestamp())
            nonce = f"app-{uuid4().hex[:16]}"
            quota_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
            headers["x-device-timestamp"] = str(timestamp)
            headers["x-device-nonce"] = nonce

        signature = ChatService._build_device_signature(
            secret=signing_secret,
            device_id=normalized_device_id,
            quota_date=quota_date,
            timestamp=timestamp,
            nonce=nonce,
        )
        headers["x-device-signature"] = signature
        return headers

    @staticmethod
    def _build_device_signature(
        *,
        secret: str,
        device_id: str,
        quota_date: str,
        timestamp: int | None = None,
        nonce: str | None = None,
    ) -> str:
        if timestamp is None or nonce is None:
            payload = f"{device_id}:{quota_date}".encode("utf-8")
        else:
            payload = f"{device_id}:{quota_date}:{timestamp}:{nonce}".encode("utf-8")
        digest = hashlib.sha256
        return hmac.new(secret.encode("utf-8"), payload, digest).hexdigest()

    @staticmethod
    def _call_openai_compatible_chat_completion(
        *,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list[dict[str, object]],
        timeout_seconds: float,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        request_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            request_headers.update(extra_headers)

        try:
            response = httpx.post(
                endpoint,
                headers=request_headers,
                json={
                    "model": model,
                    "messages": messages,
                },
                timeout=timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise UpstreamModelError(f"Failed to call upstream model: {exc}") from exc

        if response.status_code >= 400:
            raise UpstreamModelError(
                f"Upstream model request failed with HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamModelError("Upstream response is not valid JSON.") from exc

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise UpstreamModelError("Upstream response has no choices.")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise UpstreamModelError("Upstream response choice is invalid.")

        message_obj = first_choice.get("message")
        if not isinstance(message_obj, dict):
            raise UpstreamModelError("Upstream response message is invalid.")

        content = message_obj.get("content")
        if not isinstance(content, str) or not content.strip():
            raise UpstreamModelError("Upstream response content is empty.")

        return content.strip()

    @staticmethod
    def _call_openai_compatible_chat_completion_stream(
        *,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list[dict[str, object]],
        timeout_seconds: float,
        extra_headers: dict[str, str] | None = None,
    ) -> Iterator[str]:
        request_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            request_headers.update(extra_headers)

        try:
            with httpx.stream(
                "POST",
                endpoint,
                headers=request_headers,
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                },
                timeout=timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    raise UpstreamModelError(
                        f"Upstream model request failed with HTTP {response.status_code}."
                    )

                has_chunk = False
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue

                    payload_raw = line[5:].strip()
                    if payload_raw == "[DONE]":
                        break

                    try:
                        payload = json.loads(payload_raw)
                    except json.JSONDecodeError:
                        continue

                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    first = choices[0]
                    if not isinstance(first, dict):
                        continue
                    delta = first.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    content = delta.get("content")
                    if not isinstance(content, str) or not content:
                        continue
                    has_chunk = True
                    yield content

                if not has_chunk:
                    raise UpstreamModelError("Upstream stream returned no content.")
        except httpx.RequestError as exc:
            raise UpstreamModelError(f"Failed to call upstream model: {exc}") from exc

    @staticmethod
    def _stream_text_chunks(text: str, *, chunk_size: int) -> Iterator[str]:
        if chunk_size <= 0:
            chunk_size = 24
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]

    def _prepare_rag_context(
        self,
        *,
        session_id: str,
        history: list[StoredMessage],
        latest_user_message: str,
        lore_context: str,
    ) -> RagContextBundle:
        if self._rag_runtime is None:
            stats = ChatContextStats(
                session_id=session_id,
                context_char_budget=0,
                rag_context_chars=len(lore_context),
                recent_history_chars=sum(len(item.content) for item in history),
                recent_message_count=len(history),
                summary_chars=0,
                retrieved_count=0,
                updated_at=datetime.now(timezone.utc),
            )
            self._context_stats_by_session[session_id] = stats
            return RagContextBundle(
                recent_history=history,
                rag_context=lore_context,
                summary_text="",
                retrieved_memories=[],
                context_char_budget=0,
                rag_context_chars=len(lore_context),
                recent_history_chars=sum(len(item.content) for item in history),
                recent_message_count=len(history),
            )

        bundle = self._rag_runtime.prepare_context(
            session_id=session_id,
            history=history,
            latest_user_message=latest_user_message,
            lore_context=lore_context,
            summary_fn=self._summarize_memory_segment,
        )
        self._context_stats_by_session[session_id] = ChatContextStats(
            session_id=session_id,
            context_char_budget=bundle.context_char_budget,
            rag_context_chars=bundle.rag_context_chars,
            recent_history_chars=bundle.recent_history_chars,
            recent_message_count=bundle.recent_message_count,
            summary_chars=len(bundle.summary_text),
            retrieved_count=len(bundle.retrieved_memories),
            updated_at=datetime.now(timezone.utc),
        )
        return bundle

    def _persist_turn_memory(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        if self._rag_runtime is None:
            return
        try:
            self._rag_runtime.persist_turn(
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
            )
        except Exception:
            # Memory persistence must not break chat availability.
            return

    def _summarize_memory_segment(self, segment_text: str, previous_summary: str) -> str:
        segment = segment_text.strip()
        if not segment:
            return previous_summary

        prompt = (
            "You compress multi-turn roleplay memory.\n"
            "Rules:\n"
            "1) Keep stable facts, relations, commitments, unresolved tasks.\n"
            "2) Remove stylistic repetition.\n"
            "3) Return concise bullet points.\n"
            "4) Max 12 bullets.\n"
        )
        user_content = (
            f"Previous summary:\n{previous_summary or '(empty)'}\n\n"
            f"New segment:\n{segment}\n\n"
            "Return updated summary bullets only."
        )

        messages: list[dict[str, object]] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            if self._app_settings_service is not None:
                mode = self._app_settings_service.get_routing_mode()
                if mode == "byok":
                    config = self._app_settings_service.get_byok_runtime_config()
                    return self._call_openai_compatible_chat_completion(
                        endpoint=f"{config.base_url.rstrip('/')}/chat/completions",
                        api_key=config.api_key,
                        model=config.model,
                        messages=messages,
                        timeout_seconds=20.0,
                    )

            proxy = self._resolve_trial_proxy_runtime_config()
            if proxy.enabled:
                return self._call_openai_compatible_chat_completion(
                    endpoint=f"{proxy.base_url.rstrip('/')}/chat/completions",
                    api_key=proxy.api_key,
                    model=proxy.model,
                    messages=messages,
                    timeout_seconds=min(proxy.timeout_seconds, 20.0),
                )
        except Exception:
            pass

        # Fallback local summarization when no upstream summarizer is available.
        lines = [ln.strip() for ln in segment.splitlines() if ln.strip()]
        compact = []
        for line in lines[-10:]:
            cleaned = line
            if cleaned.lower().startswith("user:"):
                cleaned = cleaned[5:].strip()
            elif cleaned.lower().startswith("assistant:"):
                cleaned = cleaned[10:].strip()
            if cleaned:
                compact.append(f"- {cleaned[:180]}")
        merged = (previous_summary.strip() + "\n" + "\n".join(compact)).strip()
        return merged[:5000]

    def _call_openai_compatible_chat_completion_with_tools(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list[dict[str, object]],
        timeout_seconds: float,
        session_id: str,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        if self._tool_runtime is None or not self._tool_runtime.enabled:
            return self._call_openai_compatible_chat_completion(
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                messages=messages,
                timeout_seconds=timeout_seconds,
                extra_headers=extra_headers,
            )

        request_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            request_headers.update(extra_headers)

        working_messages: list[dict[str, object]] = [dict(item) for item in messages]
        tools = self._tool_runtime.openai_tool_specs()

        for _ in range(3):
            payload = {
                "model": model,
                "messages": working_messages,
                "tools": tools,
                "tool_choice": "auto",
            }
            try:
                response = httpx.post(
                    endpoint,
                    headers=request_headers,
                    json=payload,
                    timeout=timeout_seconds,
                )
            except httpx.RequestError as exc:
                raise UpstreamModelError(f"Failed to call upstream model: {exc}") from exc

            if response.status_code >= 400:
                raise UpstreamModelError(
                    f"Upstream model request failed with HTTP {response.status_code}."
                )

            try:
                body = response.json()
                choice = body["choices"][0]
                message_obj = choice["message"]
                if not isinstance(message_obj, dict):
                    raise TypeError("message must be object")
            except Exception as exc:
                raise UpstreamModelError("Upstream response is invalid for tool call loop.") from exc

            tool_calls = message_obj.get("tool_calls")
            content = message_obj.get("content")

            if isinstance(tool_calls, list) and tool_calls:
                working_messages.append(
                    {
                        "role": "assistant",
                        "content": content if isinstance(content, str) else "",
                        "tool_calls": tool_calls,
                    }
                )
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    call_id = str(tool_call.get("id", "tool-call"))
                    func = tool_call.get("function")
                    if not isinstance(func, dict):
                        continue
                    tool_name = str(func.get("name", "")).strip()
                    args_json = str(func.get("arguments", "")).strip()
                    try:
                        result_payload = self._tool_runtime.execute_tool(
                            name=tool_name,
                            arguments_json=args_json or "{}",
                            session_id=session_id,
                        )
                        result_text = json.dumps(result_payload, ensure_ascii=False)
                    except Exception as exc:
                        result_text = json.dumps(
                            {"error": str(exc), "tool": tool_name},
                            ensure_ascii=False,
                        )

                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result_text,
                        }
                    )
                continue

            if isinstance(content, str) and content.strip():
                return content.strip()

            raise UpstreamModelError("Upstream response content is empty.")

        raise UpstreamModelError("Tool call loop exceeded retry limit.")

    def _resolve_lore_context(
        self,
        *,
        session_summary: StoredSessionSummary,
        latest_user_message: str,
    ) -> str:
        if self._lorebook_repository is None:
            return ""

        matches = self._lorebook_repository.find_matching_lorebooks(
            message=latest_user_message,
            character_id=session_summary.character_id,
            max_items=6,
        )
        if not matches:
            return ""

        lines = ["Lorebook context (highest priority first):"]
        for item in matches:
            lines.append(f"- [{item.keyword}] {item.insert_text}")
        return "\n".join(lines)


class TrialService:
    def __init__(
        self,
        quota_limiter: DailyQuotaLimiter,
        *,
        app_settings_service: "AppSettingsService | None" = None,
    ) -> None:
        self._quota_limiter = quota_limiter
        self._app_settings_service = app_settings_service

    def get_quota(self, device_id: str) -> QuotaStatus:
        return self._quota_limiter.get_status(device_id)

    def consume_quota(self, device_id: str, amount: int = 1) -> QuotaStatus:
        return self._quota_limiter.consume(device_id=device_id, amount=amount)

    def get_proxy_status(self) -> TrialProxyPublicStatus:
        if self._app_settings_service is not None:
            return self._app_settings_service.get_trial_proxy_public_status()
        config = _read_trial_proxy_runtime_config()
        return TrialProxyPublicStatus(
            mode=config.mode,
            enabled=config.enabled,
            has_api_key=bool(config.api_key),
            base_url=config.base_url,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
        )

    def update_proxy_settings(
        self,
        *,
        mode: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        system_prompt: str | None = None,
    ) -> TrialProxyPublicStatus:
        if self._app_settings_service is None:
            raise RoutingConfigurationError(
                "Trial proxy settings are not available in current runtime."
            )
        return self._app_settings_service.update_trial_proxy_settings(
            mode=mode,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            system_prompt=system_prompt,
        )

    def check_proxy_health(self) -> TrialProxyHealthCheck:
        if self._app_settings_service is not None:
            config = self._app_settings_service.get_trial_proxy_runtime_config()
        else:
            config = _read_trial_proxy_runtime_config()

        base_url = config.base_url.strip()
        if not base_url:
            return TrialProxyHealthCheck(
                mode=config.mode,
                enabled=config.enabled,
                base_url=base_url,
                health_url="",
                healthy=False,
                status_code=None,
                latency_ms=None,
                detail="trial proxy base_url is empty",
            )

        health_url = f"{base_url.rstrip('/')}/healthz"
        started = time.perf_counter()
        try:
            response = httpx.get(
                health_url,
                timeout=min(max(config.timeout_seconds, 1.0), 15.0),
            )
        except httpx.RequestError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return TrialProxyHealthCheck(
                mode=config.mode,
                enabled=config.enabled,
                base_url=base_url,
                health_url=health_url,
                healthy=False,
                status_code=None,
                latency_ms=round(elapsed_ms, 2),
                detail=f"proxy health check failed: {exc}",
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        is_healthy = response.status_code < 400
        detail = "ok" if is_healthy else f"proxy returned HTTP {response.status_code}"
        return TrialProxyHealthCheck(
            mode=config.mode,
            enabled=config.enabled,
            base_url=base_url,
            health_url=health_url,
            healthy=is_healthy,
            status_code=response.status_code,
            latency_ms=round(elapsed_ms, 2),
            detail=detail,
        )


class AssetService:
    _DEFAULT_MAX_BYTES = 10 * 1024 * 1024
    _ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
    _CONTENT_TYPE_BY_SUFFIX = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }

    def __init__(
        self,
        asset_repository: AssetRepository,
        *,
        asset_dir: Path,
        public_url_prefix: str = "/assets",
        max_file_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._asset_repository = asset_repository
        self._asset_dir = asset_dir
        self._asset_dir.mkdir(parents=True, exist_ok=True)
        self._public_url_prefix = public_url_prefix.rstrip("/")
        self._max_file_bytes = max_file_bytes

    def create_asset(
        self,
        *,
        original_filename: str,
        content_type: str | None,
        data: bytes,
    ) -> StoredAsset:
        normalized_name = original_filename.strip()
        if not normalized_name:
            raise ValueError("filename cannot be empty")
        if not data:
            raise ValueError("file cannot be empty")
        if len(data) > self._max_file_bytes:
            raise ValueError(
                f"file too large: max {self._max_file_bytes} bytes is allowed."
            )

        suffix = Path(normalized_name).suffix.lower().strip()
        if suffix not in self._ALLOWED_SUFFIXES:
            raise ValueError("unsupported file extension")

        normalized_content_type = (content_type or "").strip().lower()
        expected_content_type = self._CONTENT_TYPE_BY_SUFFIX.get(suffix)
        if not normalized_content_type:
            normalized_content_type = expected_content_type or "application/octet-stream"

        asset_id = str(uuid4())
        stored_filename = f"{asset_id}{suffix}"
        target_path = self._asset_dir / stored_filename

        target_path.write_bytes(data)
        try:
            return self._asset_repository.create_asset(
                asset_id=asset_id,
                original_filename=normalized_name,
                content_type=normalized_content_type,
                size_bytes=len(data),
                stored_filename=stored_filename,
            )
        except Exception:
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def get_asset(self, asset_id: str) -> StoredAsset:
        return self._asset_repository.get_asset(asset_id)

    def list_assets(self, *, limit: int = 50, offset: int = 0) -> list[StoredAsset]:
        return self._asset_repository.list_assets(limit=limit, offset=offset)

    def delete_asset(self, asset_id: str) -> None:
        asset = self._asset_repository.get_asset(asset_id)
        file_path = self._asset_dir / asset.stored_filename
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._asset_repository.delete_asset(asset_id)

    def build_asset_url(self, stored_filename: str) -> str:
        return f"{self._public_url_prefix}/{stored_filename}"


class CharacterService:
    def __init__(self, character_repository: CharacterRepository) -> None:
        self._character_repository = character_repository

    def create_character(
        self,
        *,
        name: str,
        description: str,
        system_prompt: str,
        first_message: str,
        avatar_url: str | None,
    ) -> StoredCharacter:
        return self._character_repository.create_character(
            name=name.strip(),
            description=description.strip(),
            system_prompt=system_prompt.strip(),
            first_message=first_message.strip(),
            avatar_url=avatar_url.strip() if avatar_url else None,
        )

    def list_characters(self) -> list[StoredCharacter]:
        return self._character_repository.list_characters()

    def get_character(self, character_id: str) -> StoredCharacter:
        return self._character_repository.get_character(character_id)

    def update_character(
        self,
        character_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        first_message: str | None = None,
        avatar_url: str | None | object = UNSET,
    ) -> StoredCharacter:
        normalized_avatar_url: str | None | object = UNSET
        if avatar_url is not UNSET:
            if avatar_url is None:
                normalized_avatar_url = None
            elif isinstance(avatar_url, str):
                normalized_avatar_url = avatar_url.strip() or None
            else:
                raise ValueError("avatar_url must be string, null, or omitted")

        return self._character_repository.update_character(
            character_id=character_id,
            name=None if name is None else name.strip(),
            description=None if description is None else description.strip(),
            system_prompt=None if system_prompt is None else system_prompt.strip(),
            first_message=None if first_message is None else first_message.strip(),
            avatar_url=normalized_avatar_url,
        )

    def delete_character(self, character_id: str) -> None:
        self._character_repository.delete_character(character_id)


class CharacterDraftService:
    _MAX_NAME_LEN = 80
    _MAX_DESCRIPTION_LEN = 2000
    _MAX_SYSTEM_PROMPT_LEN = 8000
    _MAX_FIRST_MESSAGE_LEN = 2000
    _MAX_AVATAR_URL_LEN = 2048

    def __init__(
        self,
        *,
        character_repository: CharacterRepository,
        draft_repository: CharacterDraftRepository,
    ) -> None:
        self._character_repository = character_repository
        self._draft_repository = draft_repository

    def get_draft(self, character_id: str) -> CharacterDraftState:
        self._character_repository.get_character(character_id)
        stored = self._draft_repository.get_draft(character_id)
        return self._to_draft_state(stored)

    def save_draft_patch(
        self,
        *,
        character_id: str,
        patch: dict[str, object],
        expected_version: int | None = None,
    ) -> CharacterDraftState:
        character = self._character_repository.get_character(character_id)
        normalized_patch = self._normalize_patch(patch)

        try:
            existing = self._draft_repository.get_draft(character_id)
            base_payload = self._deserialize_payload(existing.payload_json)
        except CharacterDraftNotFoundError:
            base_payload = self._build_payload_from_character(character)

        merged_payload = {**base_payload, **normalized_patch}
        normalized_full_payload = self._normalize_full_payload(merged_payload)

        saved = self._draft_repository.save_draft(
            character_id=character_id,
            payload_json=json.dumps(normalized_full_payload, ensure_ascii=False),
            expected_version=expected_version,
        )
        return self._to_draft_state(saved)

    def apply_draft(
        self,
        *,
        character_id: str,
        expected_version: int | None = None,
        delete_after_apply: bool = True,
    ) -> CharacterDraftApplyResult:
        self._character_repository.get_character(character_id)
        stored = self._draft_repository.get_draft(character_id)
        if expected_version is not None and expected_version != stored.version:
            raise DraftVersionConflictError(
                "Draft version conflict. Refresh draft and retry."
            )

        payload = self._deserialize_payload(stored.payload_json)
        updated_character = self._character_repository.update_character(
            character_id=character_id,
            name=payload["name"],
            description=payload["description"],
            system_prompt=payload["system_prompt"],
            first_message=payload["first_message"],
            avatar_url=payload["avatar_url"],
        )

        if delete_after_apply:
            self._draft_repository.delete_draft(character_id)

        return CharacterDraftApplyResult(
            character=updated_character,
            applied_version=stored.version,
        )

    def delete_draft(self, character_id: str) -> None:
        self._character_repository.get_character(character_id)
        self._draft_repository.delete_draft(character_id)

    def _to_draft_state(self, stored: StoredCharacterDraft) -> CharacterDraftState:
        payload = self._deserialize_payload(stored.payload_json)
        return CharacterDraftState(
            character_id=stored.character_id,
            payload=payload,
            version=stored.version,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )

    def _deserialize_payload(self, payload_json: str) -> dict[str, object]:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Stored draft payload is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Stored draft payload must be an object.")
        return self._normalize_full_payload(payload)

    def _build_payload_from_character(
        self,
        character: StoredCharacter,
    ) -> dict[str, object]:
        return {
            "name": character.name,
            "description": character.description,
            "system_prompt": character.system_prompt,
            "first_message": character.first_message,
            "avatar_url": character.avatar_url,
            "advanced": {},
        }

    def _normalize_patch(self, patch: dict[str, object]) -> dict[str, object]:
        if not isinstance(patch, dict):
            raise ValueError("patch must be an object")

        allowed_fields = {
            "name",
            "description",
            "system_prompt",
            "first_message",
            "avatar_url",
            "advanced",
        }
        unknown_fields = sorted(set(patch.keys()) - allowed_fields)
        if unknown_fields:
            joined = ", ".join(unknown_fields)
            raise ValueError(f"patch contains unsupported fields: {joined}")

        normalized: dict[str, object] = {}
        if "name" in patch:
            normalized["name"] = self._normalize_required_text(
                value=patch["name"],
                field_name="name",
                max_len=self._MAX_NAME_LEN,
            )
        if "description" in patch:
            normalized["description"] = self._normalize_optional_text(
                value=patch["description"],
                field_name="description",
                max_len=self._MAX_DESCRIPTION_LEN,
            )
        if "system_prompt" in patch:
            normalized["system_prompt"] = self._normalize_optional_text(
                value=patch["system_prompt"],
                field_name="system_prompt",
                max_len=self._MAX_SYSTEM_PROMPT_LEN,
            )
        if "first_message" in patch:
            normalized["first_message"] = self._normalize_optional_text(
                value=patch["first_message"],
                field_name="first_message",
                max_len=self._MAX_FIRST_MESSAGE_LEN,
            )
        if "avatar_url" in patch:
            normalized["avatar_url"] = self._normalize_avatar_url(patch["avatar_url"])
        if "advanced" in patch:
            advanced_value = patch["advanced"]
            if advanced_value is None:
                normalized["advanced"] = {}
            elif isinstance(advanced_value, dict):
                normalized["advanced"] = advanced_value
            else:
                raise ValueError("advanced must be an object")
        return normalized

    def _normalize_full_payload(self, payload: dict[str, object]) -> dict[str, object]:
        normalized = {
            "name": self._normalize_required_text(
                value=payload.get("name"),
                field_name="name",
                max_len=self._MAX_NAME_LEN,
            ),
            "description": self._normalize_optional_text(
                value=payload.get("description"),
                field_name="description",
                max_len=self._MAX_DESCRIPTION_LEN,
            ),
            "system_prompt": self._normalize_optional_text(
                value=payload.get("system_prompt"),
                field_name="system_prompt",
                max_len=self._MAX_SYSTEM_PROMPT_LEN,
            ),
            "first_message": self._normalize_optional_text(
                value=payload.get("first_message"),
                field_name="first_message",
                max_len=self._MAX_FIRST_MESSAGE_LEN,
            ),
            "avatar_url": self._normalize_avatar_url(payload.get("avatar_url")),
            "advanced": {},
        }

        advanced_value = payload.get("advanced", {})
        if advanced_value is None:
            normalized["advanced"] = {}
        elif isinstance(advanced_value, dict):
            normalized["advanced"] = advanced_value
        else:
            raise ValueError("advanced must be an object")

        return normalized

    @staticmethod
    def _normalize_required_text(
        *,
        value: object,
        field_name: str,
        max_len: int,
    ) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{field_name} cannot be empty")
        if len(cleaned) > max_len:
            raise ValueError(f"{field_name} exceeds max length {max_len}")
        return cleaned

    @staticmethod
    def _normalize_optional_text(
        *,
        value: object,
        field_name: str,
        max_len: int,
    ) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        cleaned = value.strip()
        if len(cleaned) > max_len:
            raise ValueError(f"{field_name} exceeds max length {max_len}")
        return cleaned

    def _normalize_avatar_url(self, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("avatar_url must be a string or null")
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > self._MAX_AVATAR_URL_LEN:
            raise ValueError(
                f"avatar_url exceeds max length {self._MAX_AVATAR_URL_LEN}"
            )
        return cleaned


class LorebookService:
    def __init__(self, lorebook_repository: LorebookRepository) -> None:
        self._lorebook_repository = lorebook_repository

    def create_lorebook(
        self,
        *,
        character_id: str | None,
        keyword: str,
        insert_text: str,
        sort_order: int,
        enabled: bool,
    ) -> StoredLorebook:
        return self._lorebook_repository.create_lorebook(
            character_id=character_id.strip() if character_id else None,
            keyword=keyword.strip(),
            insert_text=insert_text.strip(),
            sort_order=sort_order,
            enabled=enabled,
        )

    def list_lorebooks(
        self,
        *,
        character_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[StoredLorebook]:
        return self._lorebook_repository.list_lorebooks(
            character_id=character_id,
            enabled=enabled,
        )

    def get_lorebook(self, lorebook_id: str) -> StoredLorebook:
        return self._lorebook_repository.get_lorebook(lorebook_id)

    def update_lorebook(
        self,
        lorebook_id: str,
        *,
        character_id: str | None = None,
        keyword: str | None = None,
        insert_text: str | None = None,
        sort_order: int | None = None,
        enabled: bool | None = None,
    ) -> StoredLorebook:
        normalized_character_id = None
        if character_id is not None:
            normalized_character_id = character_id.strip() or None

        return self._lorebook_repository.update_lorebook(
            lorebook_id=lorebook_id,
            character_id=normalized_character_id,
            keyword=None if keyword is None else keyword.strip(),
            insert_text=None if insert_text is None else insert_text.strip(),
            sort_order=sort_order,
            enabled=enabled,
        )

    def delete_lorebook(self, lorebook_id: str) -> None:
        self._lorebook_repository.delete_lorebook(lorebook_id)


class _WizardDraftSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1, max_length=2000)
    system_prompt: str = Field(..., min_length=1, max_length=8000)
    first_message: str = Field(default="", max_length=2000)


class WizardService:
    def __init__(
        self,
        app_settings_service: "AppSettingsService",
        *,
        search_client: TavilySearchClient | None = None,
        model_endpoint_service: "ModelEndpointService | None" = None,
    ) -> None:
        self._app_settings_service = app_settings_service
        self._search_client = search_client
        self._model_endpoint_service = model_endpoint_service

    def generate_character(self, user_input: str) -> WizardGenerationResult:
        normalized = user_input.strip()
        if not normalized:
            raise ValueError("user_input cannot be empty")

        search_context, search_sources = self._build_search_context(normalized)

        route_mode = self._app_settings_service.get_routing_mode()
        if route_mode == "byok":
            try:
                candidate = self._generate_byok_candidate(
                    normalized,
                    search_context=search_context,
                )
            except Exception:
                candidate = self._generate_model_endpoint_candidate(
                    normalized,
                    search_context=search_context,
                )
                if candidate is not None:
                    route_mode = "model_endpoints"
                else:
                    route_mode = "trial"
                    candidate = self._generate_trial_candidate(
                        normalized,
                        search_context=search_context,
                    )
        else:
            candidate = self._generate_model_endpoint_candidate(
                normalized,
                search_context=search_context,
            )
            if candidate is not None:
                route_mode = "model_endpoints"
            else:
                route_mode = "trial"
                candidate = self._generate_trial_candidate(
                    normalized,
                    search_context=search_context,
                )

        draft, auto_completed_fields = self._normalize_candidate(candidate, normalized)
        return WizardGenerationResult(
            draft=draft,
            route_mode=route_mode,
            auto_completed_fields=auto_completed_fields,
            search_sources=search_sources,
        )

    def _generate_trial_candidate(
        self,
        user_input: str,
        *,
        search_context: str,
    ) -> dict[str, str]:
        text = user_input.strip()
        short_desc = text if len(text) <= 180 else f"{text[:177]}..."
        name = self._infer_name(text)
        extra = ""
        if search_context:
            extra = f" Public references: {search_context[:500]}"

        return {
            "name": name,
            "description": f"Role profile based on user intent: {short_desc}.{extra}",
            "system_prompt": (
                "Stay in character, respond with immersive detail, "
                "and keep continuity across turns."
            ),
            # Leave first_message empty on purpose; normalize step can auto-complete.
            "first_message": "",
        }

    def _generate_byok_candidate(
        self,
        user_input: str,
        *,
        search_context: str,
    ) -> dict[str, str]:
        config = self._app_settings_service.get_byok_runtime_config()
        endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
        system_prompt = WIZARD_SYSTEM_PROMPT_LIBRARY["character_extraction"]

        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Create a roleplay character draft from this requirement:\n"
                        f"{user_input}\n\n"
                        f"Public reference snippets (optional):\n{search_context or '(none)'}\n\n"
                        "Return JSON only."
                    ),
                },
            ],
        }

        try:
            response = httpx.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise UpstreamModelError(f"Failed to call upstream model: {exc}") from exc

        if response.status_code >= 400:
            raise UpstreamModelError(
                f"Upstream model request failed with HTTP {response.status_code}."
            )

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content must be string")
            maybe_json = self._extract_json_payload(content)
            parsed = json.loads(maybe_json)
        except Exception as exc:
            raise UpstreamModelError("Wizard upstream response is invalid.") from exc

        if not isinstance(parsed, dict):
            raise UpstreamModelError("Wizard upstream JSON payload must be an object.")

        return {
            "name": str(parsed.get("name", "")),
            "description": str(parsed.get("description", "")),
            "system_prompt": str(parsed.get("system_prompt", "")),
            "first_message": str(parsed.get("first_message", "")),
        }

    def _generate_model_endpoint_candidate(
        self,
        user_input: str,
        *,
        search_context: str,
    ) -> dict[str, str] | None:
        if self._model_endpoint_service is None:
            return None

        messages: list[dict[str, object]] = [
            {"role": "system", "content": WIZARD_SYSTEM_PROMPT_LIBRARY["character_extraction"]},
            {
                "role": "user",
                "content": (
                    "Create a roleplay character draft from this requirement:\n"
                    f"{user_input}\n\n"
                    f"Public reference snippets (optional):\n{search_context or '(none)'}\n\n"
                    "Return JSON only."
                ),
            },
        ]

        for endpoint in self._select_wizard_endpoint_candidates():
            endpoint_url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
            try:
                content = self._call_openai_compatible_json_text(
                    endpoint=endpoint_url,
                    api_key=endpoint.api_key,
                    model=endpoint.model,
                    messages=messages,
                )
                parsed = json.loads(self._extract_json_payload(content))
                if not isinstance(parsed, dict):
                    continue
                return {
                    "name": str(parsed.get("name", "")),
                    "description": str(parsed.get("description", "")),
                    "system_prompt": str(parsed.get("system_prompt", "")),
                    "first_message": str(parsed.get("first_message", "")),
                }
            except Exception:
                continue
        return None

    def _select_wizard_endpoint_candidates(self) -> list[ModelEndpointRuntime]:
        if self._model_endpoint_service is None:
            return []
        endpoints = self._model_endpoint_service.list_runtime_endpoints()
        if not endpoints:
            return []

        raw_pref = os.getenv(
            "WIZARD_ENDPOINT_PROVIDER_PREFERENCE",
            "kimi,qwen,deepseek,openai,openai_compatible",
        ).strip()
        pref = [item.strip().lower() for item in raw_pref.split(",") if item.strip()]
        rank = {provider: idx for idx, provider in enumerate(pref)}

        return sorted(
            endpoints,
            key=lambda item: (
                1 if item.is_fallback else 0,
                rank.get(item.provider.lower(), 999),
                item.priority,
                item.name.lower(),
            ),
        )

    @staticmethod
    def _call_openai_compatible_json_text(
        *,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list[dict[str, object]],
    ) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = httpx.post(
            endpoint,
            headers=headers,
            json={"model": model, "messages": messages},
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise UpstreamModelError(
                f"Model endpoint request failed with HTTP {response.status_code}."
            )
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise UpstreamModelError("Model endpoint response content is invalid.")
        return content

    def _build_search_context(self, user_input: str) -> tuple[str, list[dict[str, str]]]:
        if self._search_client is None or not self._search_client.enabled:
            return "", []

        # Keep search usage conservative: trigger only when intent likely references known IP/persona.
        trigger_terms = (
            "\u53c2\u8003",
            "\u540c\u4eba",
            "\u57fa\u4e8e",
            "\u50cf",
            "inspired by",
            "based on",
            "from",
        )
        lower = user_input.lower()
        if not any(term in lower for term in trigger_terms):
            return "", []

        try:
            sources = self._search_client.search(user_input, max_results=4)
        except Exception:
            return "", []
        if not sources:
            return "", []

        deduped: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for item in sources:
            url = str(item.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(item)

        snippets: list[str] = []
        compact_sources: list[dict[str, str]] = []
        for idx, item in enumerate(deduped[:4], start=1):
            title = item.get("title", "").strip() or f"source-{idx}"
            url = item.get("url", "").strip()
            snippet = item.get("snippet", "").strip()
            if not snippet:
                continue
            snippets.append(f"[{idx}] {title}: {snippet[:260]}")
            compact_sources.append({
                "title": title,
                "url": url,
                "snippet": snippet[:300],
            })
        return "\n".join(snippets), compact_sources

    def _normalize_candidate(
        self,
        candidate: dict[str, str],
        user_input: str,
    ) -> tuple[WizardCharacterDraft, list[str]]:
        auto_completed_fields: list[str] = []

        if not str(candidate.get("name", "")).strip():
            candidate["name"] = self._infer_name(user_input)
            auto_completed_fields.append("name")

        if not str(candidate.get("description", "")).strip():
            candidate["description"] = f"Role profile based on: {user_input[:160]}"
            auto_completed_fields.append("description")

        if not str(candidate.get("system_prompt", "")).strip():
            candidate["system_prompt"] = (
                "Stay in character and keep responses coherent, concise, and immersive."
            )
            auto_completed_fields.append("system_prompt")

        if not str(candidate.get("first_message", "")).strip():
            name = str(candidate.get("name", "Character")).strip() or "Character"
            candidate["first_message"] = (
                f"Hi, I am {name}. Tell me what scene you want to start with."
            )
            auto_completed_fields.append("first_message")

        try:
            validated = _WizardDraftSchema.model_validate(candidate)
        except ValidationError as exc:
            raise ValueError(f"Invalid wizard draft payload: {exc}") from exc

        draft = WizardCharacterDraft(
            name=validated.name.strip(),
            description=validated.description.strip(),
            system_prompt=validated.system_prompt.strip(),
            first_message=validated.first_message.strip(),
        )
        return draft, auto_completed_fields

    @staticmethod
    def _infer_name(text: str) -> str:
        tokens = [
            token.strip(" ,.!?;:\"'()[]{}")
            for token in text.split()
            if token.strip(" ,.!?;:\"'()[]{}")
        ]
        if not tokens:
            return "New Character"
        max_tokens = 4
        selected = tokens[:max_tokens]
        name = " ".join(selected)
        return name[:80]

    @staticmethod
    def _extract_json_payload(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object in response content.")
        return stripped[start : end + 1]


class AppSettingsService:
    def __init__(self, app_settings_repository: AppSettingsRepository) -> None:
        self._app_settings_repository = app_settings_repository
        self._secret = os.getenv("APP_SETTINGS_SECRET", "dev-only-change-me")

    def get_public_settings(self) -> AppSettingsPublic:
        settings = self._app_settings_repository.get_settings()
        return AppSettingsPublic(
            mode=settings.mode,
            byok_base_url=settings.byok_base_url,
            byok_model=settings.byok_model,
            has_api_key=bool(settings.byok_api_key_encrypted),
            task_endpoint_bindings=self._parse_task_endpoint_bindings(
                settings.generation_task_bindings_json
            ),
            updated_at=settings.updated_at,
        )

    def update_settings(
        self,
        *,
        mode: str | None = None,
        byok_base_url: str | None = None,
        byok_model: str | None = None,
        byok_api_key: str | None = None,
        task_endpoint_bindings: dict[str, str | None] | None = None,
    ) -> AppSettingsPublic:
        current = self._app_settings_repository.get_settings()

        next_mode = (mode or current.mode).strip().lower()
        if next_mode not in {"trial", "byok"}:
            raise ValueError("mode must be one of: trial, byok")

        next_base_url = (
            byok_base_url.strip() if byok_base_url is not None else current.byok_base_url
        )
        next_model = byok_model.strip() if byok_model is not None else current.byok_model

        if byok_api_key is None:
            next_api_key_encrypted = current.byok_api_key_encrypted
        else:
            normalized_key = byok_api_key.strip()
            if normalized_key:
                next_api_key_encrypted = self._encrypt_key(normalized_key)
            else:
                next_api_key_encrypted = None

        if next_mode == "byok" and not next_api_key_encrypted:
            raise RoutingConfigurationError(
                "BYOK mode requires byok_api_key. Configure key before switching mode."
            )

        current_task_bindings = self._parse_task_endpoint_bindings(
            current.generation_task_bindings_json
        )
        next_task_bindings = current_task_bindings
        if task_endpoint_bindings is not None:
            next_task_bindings = self._normalize_task_endpoint_bindings(task_endpoint_bindings)

        updated = self._app_settings_repository.update_settings(
            mode=next_mode,
            byok_base_url=next_base_url,
            byok_model=next_model,
            byok_api_key_encrypted=next_api_key_encrypted,
            generation_task_bindings_json=json.dumps(
                next_task_bindings,
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

        return AppSettingsPublic(
            mode=updated.mode,
            byok_base_url=updated.byok_base_url,
            byok_model=updated.byok_model,
            has_api_key=bool(updated.byok_api_key_encrypted),
            task_endpoint_bindings=self._parse_task_endpoint_bindings(
                updated.generation_task_bindings_json
            ),
            updated_at=updated.updated_at,
        )

    def get_routing_mode(self) -> str:
        return self._app_settings_repository.get_settings().mode

    def get_generation_task_bindings(self) -> dict[str, str]:
        settings = self._app_settings_repository.get_settings()
        return self._parse_task_endpoint_bindings(settings.generation_task_bindings_json)

    def get_byok_runtime_config(self) -> ByokRuntimeConfig:
        settings = self._app_settings_repository.get_settings()
        if settings.mode != "byok":
            raise RoutingConfigurationError("Routing mode is not byok.")
        if not settings.byok_api_key_encrypted:
            raise RoutingConfigurationError("BYOK API key is not configured.")
        api_key = self._decrypt_key(settings.byok_api_key_encrypted)
        if not api_key:
            raise RoutingConfigurationError("BYOK API key is invalid.")
        return ByokRuntimeConfig(
            base_url=settings.byok_base_url,
            model=settings.byok_model,
            api_key=api_key,
        )

    def get_trial_proxy_runtime_config(self) -> TrialProxyRuntimeConfig:
        settings = self._app_settings_repository.get_settings()
        mode = settings.trial_proxy_mode.strip().lower()
        if mode not in {"local", "upstream"}:
            mode = "local"

        api_key = self._decrypt_optional_key(settings.trial_proxy_api_key_encrypted)
        base_url = settings.trial_proxy_base_url.strip()
        model = settings.trial_proxy_model.strip()
        timeout_seconds = settings.trial_proxy_timeout_seconds
        if timeout_seconds <= 0:
            timeout_seconds = 30.0

        enabled = mode == "upstream" and bool(api_key)
        return TrialProxyRuntimeConfig(
            mode=mode,
            enabled=enabled,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            system_prompt=settings.trial_proxy_system_prompt.strip(),
        )

    def get_trial_proxy_public_status(self) -> TrialProxyPublicStatus:
        config = self.get_trial_proxy_runtime_config()
        return TrialProxyPublicStatus(
            mode=config.mode,
            enabled=config.enabled,
            has_api_key=bool(config.api_key),
            base_url=config.base_url,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
        )

    def update_trial_proxy_settings(
        self,
        *,
        mode: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        system_prompt: str | None = None,
    ) -> TrialProxyPublicStatus:
        current = self._app_settings_repository.get_settings()

        next_mode = (
            mode.strip().lower() if mode is not None else current.trial_proxy_mode.strip().lower()
        )
        if next_mode not in {"local", "upstream"}:
            raise ValueError("trial proxy mode must be one of: local, upstream")

        next_base_url = (
            base_url.strip() if base_url is not None else current.trial_proxy_base_url
        )
        next_model = model.strip() if model is not None else current.trial_proxy_model
        next_system_prompt = (
            system_prompt.strip()
            if system_prompt is not None
            else current.trial_proxy_system_prompt
        )

        if timeout_seconds is None:
            next_timeout = current.trial_proxy_timeout_seconds
        else:
            next_timeout = float(timeout_seconds)
        if next_timeout <= 0 or next_timeout > 300:
            raise ValueError("trial proxy timeout_seconds must be within (0, 300].")

        if api_key is None:
            next_api_key_encrypted = current.trial_proxy_api_key_encrypted
        else:
            normalized_key = api_key.strip()
            if normalized_key:
                next_api_key_encrypted = self._encrypt_key(normalized_key)
            else:
                next_api_key_encrypted = None

        self._app_settings_repository.update_trial_proxy_settings(
            trial_proxy_mode=next_mode,
            trial_proxy_base_url=next_base_url,
            trial_proxy_model=next_model,
            trial_proxy_api_key_encrypted=next_api_key_encrypted,
            trial_proxy_timeout_seconds=next_timeout,
            trial_proxy_system_prompt=next_system_prompt,
        )
        return self.get_trial_proxy_public_status()

    def _encrypt_key(self, raw: str) -> str:
        payload = raw.encode("utf-8")
        masked = self._xor_with_secret(payload)
        return base64.urlsafe_b64encode(masked).decode("utf-8")

    def _decrypt_key(self, token: str) -> str:
        try:
            payload = base64.urlsafe_b64decode(token.encode("utf-8"))
        except Exception as exc:
            raise RoutingConfigurationError("Stored BYOK API key is corrupted.") from exc
        raw = self._xor_with_secret(payload)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RoutingConfigurationError("Stored BYOK API key is invalid.") from exc

    def _decrypt_optional_key(self, token: str | None) -> str:
        if not token:
            return ""
        try:
            return self._decrypt_key(token)
        except RoutingConfigurationError:
            return ""

    def _xor_with_secret(self, data: bytes) -> bytes:
        secret_key = hashlib.sha256(self._secret.encode("utf-8")).digest()
        return bytes(data[i] ^ secret_key[i % len(secret_key)] for i in range(len(data)))

    @staticmethod
    def _parse_task_endpoint_bindings(raw_json: str | None) -> dict[str, str]:
        if not raw_json:
            return {}
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        normalized: dict[str, str] = {}
        allowed = set(GENERATION_TASK_TYPES)
        for key, value in payload.items():
            task_type = str(key).strip()
            endpoint_id = str(value).strip() if value is not None else ""
            if task_type in allowed and endpoint_id:
                normalized[task_type] = endpoint_id
        return normalized

    @staticmethod
    def _normalize_task_endpoint_bindings(
        bindings: dict[str, str | None],
    ) -> dict[str, str]:
        allowed = set(GENERATION_TASK_TYPES)
        normalized: dict[str, str] = {}
        for key, value in bindings.items():
            task_type = str(key).strip()
            if task_type not in allowed:
                continue
            endpoint_id = str(value).strip() if value is not None else ""
            if endpoint_id:
                normalized[task_type] = endpoint_id
        return normalized


class ModelEndpointService:
    _SUPPORTED_PROVIDERS: dict[str, ProviderAdapterDescriptor] = {
        "deepseek": ProviderAdapterDescriptor(
            provider="deepseek",
            display_name="DeepSeek",
            openai_compatible=True,
            default_base_url="https://api.deepseek.com/v1",
        ),
        "qwen": ProviderAdapterDescriptor(
            provider="qwen",
            display_name="Qwen",
            openai_compatible=True,
            default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        "kimi": ProviderAdapterDescriptor(
            provider="kimi",
            display_name="Kimi",
            openai_compatible=True,
            default_base_url="https://api.moonshot.cn/v1",
        ),
        "openai": ProviderAdapterDescriptor(
            provider="openai",
            display_name="OpenAI",
            openai_compatible=True,
            default_base_url="https://api.openai.com/v1",
        ),
        "openai_compatible": ProviderAdapterDescriptor(
            provider="openai_compatible",
            display_name="OpenAI Compatible",
            openai_compatible=True,
            default_base_url="",
        ),
    }

    def __init__(self, repository: ModelEndpointRepository) -> None:
        self._repository = repository
        self._secret = os.getenv("APP_SETTINGS_SECRET", "dev-only-change-me")

    def list_supported_providers(self) -> list[ProviderAdapterDescriptor]:
        return list(self._SUPPORTED_PROVIDERS.values())

    def list_endpoints(self, *, include_disabled: bool = True) -> list[ModelEndpointPublic]:
        endpoints = self._repository.list_endpoints(include_disabled=include_disabled)
        return [self._to_public(item) for item in endpoints]

    def get_endpoint(self, endpoint_id: str) -> ModelEndpointPublic:
        endpoint = self._repository.get_endpoint(endpoint_id)
        return self._to_public(endpoint)

    def create_endpoint(
        self,
        *,
        provider: str,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None,
        enabled: bool,
        priority: int,
        is_fallback: bool,
    ) -> ModelEndpointPublic:
        normalized_provider = self._normalize_provider(provider)
        normalized_name = self._normalize_non_empty(name, "name")
        normalized_base_url = self._normalize_non_empty(base_url, "base_url")
        normalized_model = self._normalize_non_empty(model, "model")
        normalized_priority = self._normalize_priority(priority)
        encrypted_key = self._normalize_api_key_for_write(api_key)

        created = self._repository.create_endpoint(
            provider=normalized_provider,
            name=normalized_name,
            base_url=normalized_base_url,
            model=normalized_model,
            api_key_encrypted=encrypted_key,
            enabled=enabled,
            priority=normalized_priority,
            is_fallback=is_fallback,
        )
        return self._to_public(created)

    def update_endpoint(
        self,
        endpoint_id: str,
        *,
        provider: str | None = None,
        name: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None | object = UNSET,
        enabled: bool | None = None,
        priority: int | None = None,
        is_fallback: bool | None = None,
    ) -> ModelEndpointPublic:
        next_provider = (
            None if provider is None else self._normalize_provider(provider)
        )
        next_name = None if name is None else self._normalize_non_empty(name, "name")
        next_base_url = (
            None if base_url is None else self._normalize_non_empty(base_url, "base_url")
        )
        next_model = None if model is None else self._normalize_non_empty(model, "model")
        next_priority = None if priority is None else self._normalize_priority(priority)
        next_api_key = (
            UNSET if api_key is UNSET else self._normalize_api_key_for_write(api_key)
        )

        updated = self._repository.update_endpoint(
            endpoint_id,
            provider=next_provider,
            name=next_name,
            base_url=next_base_url,
            model=next_model,
            api_key_encrypted=next_api_key,
            enabled=enabled,
            priority=next_priority,
            is_fallback=is_fallback,
        )
        return self._to_public(updated)

    def delete_endpoint(self, endpoint_id: str) -> None:
        self._repository.delete_endpoint(endpoint_id)

    def list_runtime_endpoints(
        self,
        *,
        include_disabled: bool = False,
    ) -> list[ModelEndpointRuntime]:
        endpoints = self._repository.list_endpoints(include_disabled=include_disabled)
        result: list[ModelEndpointRuntime] = []
        for item in endpoints:
            result.append(
                ModelEndpointRuntime(
                    endpoint_id=item.endpoint_id,
                    provider=item.provider,
                    name=item.name,
                    base_url=item.base_url,
                    model=item.model,
                    api_key=self._decrypt_optional_key(item.api_key_encrypted),
                    enabled=item.enabled,
                    priority=item.priority,
                    is_fallback=item.is_fallback,
                )
            )
        return result

    def get_runtime_endpoint(self, endpoint_id: str) -> ModelEndpointRuntime:
        item = self._repository.get_endpoint(endpoint_id)
        return ModelEndpointRuntime(
            endpoint_id=item.endpoint_id,
            provider=item.provider,
            name=item.name,
            base_url=item.base_url,
            model=item.model,
            api_key=self._decrypt_optional_key(item.api_key_encrypted),
            enabled=item.enabled,
            priority=item.priority,
            is_fallback=item.is_fallback,
        )

    def build_chat_completion_request(
        self,
        *,
        endpoint_id: str,
        messages: list[dict[str, str]],
        stream: bool = False,
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        endpoint = self.get_runtime_endpoint(endpoint_id)
        provider = self._normalize_provider(endpoint.provider)
        adapter = self._SUPPORTED_PROVIDERS[provider]
        if not adapter.openai_compatible:
            raise ValueError(f"Provider '{provider}' is not openai-compatible.")

        request_url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, object] = {
            "model": endpoint.model,
            "messages": messages,
        }
        if stream:
            payload["stream"] = True

        headers = {"Content-Type": "application/json"}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"

        return request_url, headers, payload

    def check_endpoint_health(self, endpoint_id: str) -> ModelEndpointHealth:
        endpoint = self.get_runtime_endpoint(endpoint_id)
        health_url = f"{endpoint.base_url.rstrip('/')}/models"
        headers: dict[str, str] = {}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"

        started = time.perf_counter()
        try:
            response = httpx.get(
                health_url,
                headers=headers,
                timeout=10.0,
            )
        except httpx.RequestError as exc:
            latency = (time.perf_counter() - started) * 1000.0
            return ModelEndpointHealth(
                endpoint_id=endpoint.endpoint_id,
                provider=endpoint.provider,
                name=endpoint.name,
                healthy=False,
                status_code=None,
                latency_ms=round(latency, 2),
                detail=f"request failed: {exc}",
            )

        latency = (time.perf_counter() - started) * 1000.0
        healthy = 200 <= response.status_code < 300
        detail = (
            "ok"
            if healthy
            else f"HTTP {response.status_code}: {response.text[:120]}"
        )
        return ModelEndpointHealth(
            endpoint_id=endpoint.endpoint_id,
            provider=endpoint.provider,
            name=endpoint.name,
            healthy=healthy,
            status_code=response.status_code,
            latency_ms=round(latency, 2),
            detail=detail,
        )

    def list_endpoint_healths(
        self,
        *,
        include_disabled: bool = False,
        auto_disable_unhealthy: bool = False,
    ) -> list[ModelEndpointHealth]:
        endpoints = self._repository.list_endpoints(include_disabled=include_disabled)
        health_rows: list[ModelEndpointHealth] = []
        for endpoint in endpoints:
            health = self.check_endpoint_health(endpoint.endpoint_id)
            if auto_disable_unhealthy and endpoint.enabled and not health.healthy:
                self._repository.update_endpoint(endpoint.endpoint_id, enabled=False)
                health = replace(
                    health,
                    detail=f"{health.detail}; endpoint disabled by health check",
                )
            health_rows.append(health)
        return health_rows

    def _normalize_provider(self, provider: str) -> str:
        normalized = provider.strip().lower()
        if normalized not in self._SUPPORTED_PROVIDERS:
            providers = ", ".join(sorted(self._SUPPORTED_PROVIDERS.keys()))
            raise ValueError(f"provider must be one of: {providers}")
        return normalized

    @staticmethod
    def _normalize_non_empty(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty")
        return normalized

    @staticmethod
    def _normalize_priority(priority: int) -> int:
        if priority < 0 or priority > 10000:
            raise ValueError("priority must be within [0, 10000]")
        return priority

    def _normalize_api_key_for_write(self, api_key: str | None | object) -> str | None:
        if api_key is None:
            return None
        if api_key is UNSET:
            return None
        if not isinstance(api_key, str):
            raise ValueError("api_key must be string or null")
        normalized = api_key.strip()
        if not normalized:
            return None
        return self._encrypt_key(normalized)

    def _encrypt_key(self, raw: str) -> str:
        payload = raw.encode("utf-8")
        masked = self._xor_with_secret(payload)
        return base64.urlsafe_b64encode(masked).decode("utf-8")

    def _decrypt_optional_key(self, token: str | None) -> str:
        if not token:
            return ""
        try:
            payload = base64.urlsafe_b64decode(token.encode("utf-8"))
            raw = self._xor_with_secret(payload)
            return raw.decode("utf-8")
        except Exception:
            return ""

    def _xor_with_secret(self, data: bytes) -> bytes:
        secret_key = hashlib.sha256(self._secret.encode("utf-8")).digest()
        return bytes(data[i] ^ secret_key[i % len(secret_key)] for i in range(len(data)))

    @staticmethod
    def _to_public(endpoint: StoredModelEndpoint) -> ModelEndpointPublic:
        return ModelEndpointPublic(
            endpoint_id=endpoint.endpoint_id,
            provider=endpoint.provider,
            name=endpoint.name,
            base_url=endpoint.base_url,
            model=endpoint.model,
            has_api_key=bool(endpoint.api_key_encrypted),
            enabled=endpoint.enabled,
            priority=endpoint.priority,
            is_fallback=endpoint.is_fallback,
            created_at=endpoint.created_at,
            updated_at=endpoint.updated_at,
        )


class GenerationService:
    _PIPELINE_VERSION = "v0.2"
    _PIPELINE_ROLEPLAY = "roleplay_character"
    _PIPELINE_STORY = "story_project"
    _APPLY_DRAFT_ONLY = "draft_only"
    _APPLY_DIRECT = "direct_apply"

    def __init__(
        self,
        generation_repository: GenerationRepository,
        wizard_service: WizardService,
        model_endpoint_service: ModelEndpointService,
        app_settings_service: "AppSettingsService | None" = None,
        story_service: "StoryService | None" = None,
    ) -> None:
        self._generation_repository = generation_repository
        self._wizard_service = wizard_service
        self._model_endpoint_service = model_endpoint_service
        self._app_settings_service = app_settings_service
        self._story_service = story_service

    def create_job(
        self,
        *,
        user_input: str,
        pipeline_type: str = _PIPELINE_ROLEPLAY,
        apply_mode: str = _APPLY_DRAFT_ONLY,
        story_project_id: str | None = None,
        story_draft_payload: dict[str, object] | None = None,
    ) -> GenerationJobPublic:
        normalized_input = user_input.strip()
        if not normalized_input:
            raise ValueError("user_input cannot be empty")
        normalized_pipeline = self._normalize_pipeline_type(pipeline_type)
        normalized_apply_mode = self._normalize_apply_mode(apply_mode)
        normalized_story_project_id = self._normalize_story_project_id(
            story_project_id=story_project_id,
            pipeline_type=normalized_pipeline,
            apply_mode=normalized_apply_mode,
        )

        job = self._generation_repository.create_job(
            user_input=normalized_input,
            pipeline_version=self._PIPELINE_VERSION,
        )
        self._append_event(job.job_id, "job_created", {"status": job.status})
        self._append_event(
            job.job_id,
            "job_configured",
            {
                "pipeline_type": normalized_pipeline,
                "apply_mode": normalized_apply_mode,
                "story_project_id": normalized_story_project_id,
                "story_draft_payload_present": story_draft_payload is not None,
            },
        )
        return self.get_job(job.job_id)

    def submit_job(
        self,
        *,
        user_input: str,
        pipeline_type: str = _PIPELINE_ROLEPLAY,
        apply_mode: str = _APPLY_DRAFT_ONLY,
        story_project_id: str | None = None,
        story_draft_payload: dict[str, object] | None = None,
        include_illustration_prompt: bool = True,
        include_audio_plan: bool = False,
    ) -> GenerationJobPublic:
        job = self.create_job(
            user_input=user_input,
            pipeline_type=pipeline_type,
            apply_mode=apply_mode,
            story_project_id=story_project_id,
            story_draft_payload=story_draft_payload,
        )
        return self.execute_job(
            job.job_id,
            pipeline_type=pipeline_type,
            apply_mode=apply_mode,
            story_project_id=story_project_id,
            story_draft_payload=story_draft_payload,
            include_illustration_prompt=include_illustration_prompt,
            include_audio_plan=include_audio_plan,
        )

    def submit_job_async(
        self,
        *,
        user_input: str,
        pipeline_type: str = _PIPELINE_ROLEPLAY,
        apply_mode: str = _APPLY_DRAFT_ONLY,
        story_project_id: str | None = None,
        story_draft_payload: dict[str, object] | None = None,
        include_illustration_prompt: bool = True,
        include_audio_plan: bool = False,
    ) -> tuple[GenerationJobPublic, str, str, str | None, dict[str, object] | None, bool, bool]:
        job = self.create_job(
            user_input=user_input,
            pipeline_type=pipeline_type,
            apply_mode=apply_mode,
            story_project_id=story_project_id,
            story_draft_payload=story_draft_payload,
        )
        return (
            job,
            self._normalize_pipeline_type(pipeline_type),
            self._normalize_apply_mode(apply_mode),
            self._normalize_story_project_id(
                story_project_id=story_project_id,
                pipeline_type=self._normalize_pipeline_type(pipeline_type),
                apply_mode=self._normalize_apply_mode(apply_mode),
            ),
            story_draft_payload,
            include_illustration_prompt,
            include_audio_plan,
        )

    def execute_job(
        self,
        job_id: str,
        *,
        pipeline_type: str = _PIPELINE_ROLEPLAY,
        apply_mode: str = _APPLY_DRAFT_ONLY,
        story_project_id: str | None = None,
        story_draft_payload: dict[str, object] | None = None,
        include_illustration_prompt: bool = True,
        include_audio_plan: bool = False,
    ) -> GenerationJobPublic:
        stored_job = self._generation_repository.get_job(job_id)
        if stored_job.status in {"completed", "failed", "cancelled"}:
            raise GenerationJobStateError(
                f"Cannot execute job in terminal state: {stored_job.status}"
            )
        if stored_job.status == "cancel_requested":
            self._mark_job_cancelled(job_id)
            return self.get_job(job_id)

        self._generation_repository.update_job(
            job_id,
            status="running",
            error_message=None,
            completed_at=None,
        )
        self._append_event(job_id, "job_running", {})

        normalized_input = stored_job.user_input
        normalized_pipeline = self._normalize_pipeline_type(pipeline_type)
        normalized_apply_mode = self._normalize_apply_mode(apply_mode)
        normalized_story_project_id = self._normalize_story_project_id(
            story_project_id=story_project_id,
            pipeline_type=normalized_pipeline,
            apply_mode=normalized_apply_mode,
        )

        try:
            self._assert_job_not_cancel_requested(job_id)
            if story_draft_payload is not None:
                if normalized_pipeline != self._PIPELINE_STORY:
                    raise ValueError("story_draft_payload requires story_project pipeline")
                if normalized_apply_mode != self._APPLY_DIRECT:
                    raise ValueError("story_draft_payload requires direct_apply mode")
                prepared = self._prepare_story_draft_payload(story_draft_payload)
                apply_result = self._apply_story_generation_output(
                    story_project_id=normalized_story_project_id,
                    story_blueprint_output=prepared["story_blueprint"],
                    story_lorebook_output=prepared["story_lorebook"],
                )
                self._create_artifact(job_id, "story_blueprint", prepared["story_blueprint"])
                self._create_artifact(job_id, "story_lorebook", prepared["story_lorebook"])
                if prepared["illustration_prompt"]:
                    self._create_artifact(
                        job_id,
                        "illustration_prompt",
                        prepared["illustration_prompt"],
                    )
                if prepared["audio_plan"]:
                    self._create_artifact(job_id, "audio_plan", prepared["audio_plan"])
                self._create_artifact(
                    job_id,
                    "story_continuity_review",
                    prepared["story_continuity_review"],
                )
                self._create_artifact(
                    job_id,
                    "story_bundle",
                    {
                        "story_blueprint": prepared["story_blueprint"],
                        "story_lorebook": prepared["story_lorebook"],
                        "story_continuity_review": prepared["story_continuity_review"],
                        "illustration_prompt": prepared["illustration_prompt"],
                        "audio_plan": prepared["audio_plan"],
                        "review": {
                            "accepted": True,
                            "missing": [],
                            "source": "prepared_story_draft",
                        },
                        "apply_mode": normalized_apply_mode,
                        "apply_result": apply_result,
                    },
                )
                self._generation_repository.update_job(
                    job_id,
                    status="completed",
                    error_message=None,
                    completed_at=self._utcnow(),
                )
                self._append_event(
                    job_id,
                    "job_completed",
                    {"accepted": True, "source": "prepared_story_draft"},
                )
                return self.get_job(job_id)

            intent_output = self._run_task(
                job_id=job_id,
                task_type="intent_parse",
                prompt_payload={
                    "template": "intent_parse_v1",
                    "pipeline_type": normalized_pipeline,
                    "input": normalized_input,
                },
                executor=lambda task_id: self._build_intent_output(
                    job_id=job_id,
                    task_id=task_id,
                    user_input=normalized_input,
                    pipeline_type=normalized_pipeline,
                ),
            )
            self._assert_job_not_cancel_requested(job_id)

            dispatch_plan = self._run_task(
                job_id=job_id,
                task_type="plan_dispatch",
                prompt_payload={
                    "template": "dispatch_plan_v1",
                    "pipeline_type": normalized_pipeline,
                    "intent": intent_output,
                    "include_illustration_prompt": include_illustration_prompt,
                    "include_audio_plan": include_audio_plan,
                },
                executor=lambda task_id: self._build_dispatch_plan(
                    job_id=job_id,
                    task_id=task_id,
                    intent_output=intent_output,
                    pipeline_type=normalized_pipeline,
                    include_illustration_prompt=include_illustration_prompt,
                    include_audio_plan=include_audio_plan,
                ),
            )
            self._assert_job_not_cancel_requested(job_id)
            if normalized_pipeline == self._PIPELINE_STORY:
                story_blueprint_output = self._run_task(
                    job_id=job_id,
                    task_type="story_blueprint_generate",
                    prompt_payload={
                        "template": "story_blueprint_v1",
                        "intent": intent_output,
                        "dispatch": dispatch_plan,
                    },
                    executor=lambda task_id: self._build_story_blueprint_output(
                        job_id=job_id,
                        task_id=task_id,
                        user_input=normalized_input,
                    ),
                )
                self._assert_job_not_cancel_requested(job_id)

                story_lorebook_output = self._run_task(
                    job_id=job_id,
                    task_type="story_lorebook_generate",
                    prompt_payload={
                        "template": "story_lorebook_v1",
                        "intent": intent_output,
                        "story_blueprint": story_blueprint_output,
                    },
                    executor=lambda task_id: self._build_story_lorebook_output(
                        job_id=job_id,
                        task_id=task_id,
                        user_input=normalized_input,
                        story_blueprint=story_blueprint_output,
                    ),
                )
                self._assert_job_not_cancel_requested(job_id)

                illustration_output: dict[str, object] = {}
                if include_illustration_prompt:
                    illustration_output = self._run_task(
                        job_id=job_id,
                        task_type="illustration_prompt_generate",
                        prompt_payload={
                            "template": "story_illustration_prompt_v1",
                            "intent": intent_output,
                            "story_blueprint": story_blueprint_output,
                            "story_lorebook": story_lorebook_output,
                        },
                        executor=lambda task_id: self._build_story_illustration_prompt_output(
                            job_id=job_id,
                            task_id=task_id,
                            user_input=normalized_input,
                            story_blueprint=story_blueprint_output,
                        ),
                    )
                    self._assert_job_not_cancel_requested(job_id)

                audio_output: dict[str, object] = {}
                if include_audio_plan:
                    audio_output = self._run_task(
                        job_id=job_id,
                        task_type="audio_plan_generate",
                        prompt_payload={
                            "template": "story_audio_plan_v1",
                            "intent": intent_output,
                            "story_blueprint": story_blueprint_output,
                        },
                        executor=lambda _task_id: self._build_story_audio_plan_output(
                            story_blueprint_output
                        ),
                    )
                    self._assert_job_not_cancel_requested(job_id)

                continuity_output = self._run_task(
                    job_id=job_id,
                    task_type="story_continuity_review",
                    prompt_payload={
                        "template": "story_continuity_review_v1",
                        "intent": intent_output,
                        "story_blueprint": story_blueprint_output,
                        "story_lorebook": story_lorebook_output,
                    },
                    executor=lambda task_id: self._build_story_continuity_review_output(
                        job_id=job_id,
                        task_id=task_id,
                        intent_output=intent_output,
                        story_blueprint_output=story_blueprint_output,
                        story_lorebook_output=story_lorebook_output,
                    ),
                )
                self._assert_job_not_cancel_requested(job_id)

                review_output = self._run_task(
                    job_id=job_id,
                    task_type="result_review",
                    prompt_payload={
                        "template": "story_review_v1",
                        "intent": intent_output,
                    },
                    executor=lambda task_id: self._build_story_review_output(
                        job_id=job_id,
                        task_id=task_id,
                        intent_output=intent_output,
                        story_blueprint_output=story_blueprint_output,
                        story_lorebook_output=story_lorebook_output,
                        continuity_output=continuity_output,
                        illustration_output=illustration_output,
                        audio_output=audio_output,
                    ),
                )
                self._assert_job_not_cancel_requested(job_id)

                apply_result: dict[str, object] = {}
                if normalized_apply_mode == self._APPLY_DIRECT:
                    if not bool(continuity_output.get("accepted", False)):
                        raise ValueError(
                            "story_continuity_review rejected direct_apply"
                        )
                    apply_result = self._apply_story_generation_output(
                        story_project_id=normalized_story_project_id,
                        story_blueprint_output=story_blueprint_output,
                        story_lorebook_output=story_lorebook_output,
                    )

                self._create_artifact(job_id, "intent", intent_output)
                self._create_artifact(job_id, "dispatch_plan", dispatch_plan)
                self._create_artifact(job_id, "story_blueprint", story_blueprint_output)
                self._create_artifact(job_id, "story_lorebook", story_lorebook_output)
                if include_illustration_prompt:
                    self._create_artifact(job_id, "illustration_prompt", illustration_output)
                if include_audio_plan:
                    self._create_artifact(job_id, "audio_plan", audio_output)
                self._create_artifact(job_id, "story_continuity_review", continuity_output)

                story_bundle_payload = {
                    "story_blueprint": story_blueprint_output,
                    "story_lorebook": story_lorebook_output,
                    "story_continuity_review": continuity_output,
                    "illustration_prompt": illustration_output,
                    "audio_plan": audio_output,
                    "review": review_output,
                    "apply_mode": normalized_apply_mode,
                    "apply_result": apply_result,
                }
                self._create_artifact(job_id, "story_bundle", story_bundle_payload)
            else:
                character_output = self._run_task(
                    job_id=job_id,
                    task_type="character_card_generate",
                    prompt_payload={
                        "template": "character_card_v1",
                        "intent": intent_output,
                        "dispatch": dispatch_plan,
                    },
                    executor=lambda task_id: self._build_character_card_output(
                        job_id=job_id,
                        task_id=task_id,
                        user_input=normalized_input,
                    ),
                )
                self._assert_job_not_cancel_requested(job_id)

                lorebook_output = self._run_task(
                    job_id=job_id,
                    task_type="lorebook_generate",
                    prompt_payload={
                        "template": "lorebook_v1",
                        "intent": intent_output,
                        "character_name": character_output.get("name"),
                    },
                    executor=lambda task_id: self._build_lorebook_output(
                        job_id=job_id,
                        task_id=task_id,
                        user_input=normalized_input,
                        character_name=str(character_output.get("name", "Character")),
                    ),
                )
                self._assert_job_not_cancel_requested(job_id)

                illustration_output = {}
                if include_illustration_prompt:
                    illustration_output = self._run_task(
                        job_id=job_id,
                        task_type="illustration_prompt_generate",
                        prompt_payload={
                            "template": "illustration_prompt_v1",
                            "intent": intent_output,
                            "character": character_output,
                            "lorebook": lorebook_output,
                        },
                        executor=lambda task_id: self._build_illustration_prompt_output(
                            job_id=job_id,
                            task_id=task_id,
                            user_input=normalized_input,
                            character=character_output,
                        ),
                    )
                    self._assert_job_not_cancel_requested(job_id)

                audio_output = {}
                if include_audio_plan:
                    audio_output = self._run_task(
                        job_id=job_id,
                        task_type="audio_plan_generate",
                        prompt_payload={
                            "template": "audio_plan_v1",
                            "intent": intent_output,
                            "character": character_output,
                        },
                        executor=lambda _task_id: self._build_audio_plan_output(character_output),
                    )
                    self._assert_job_not_cancel_requested(job_id)

                review_output = self._run_task(
                    job_id=job_id,
                    task_type="result_review",
                    prompt_payload={
                        "template": "review_v1",
                        "intent": intent_output,
                    },
                    executor=lambda task_id: self._build_review_output(
                        job_id=job_id,
                        task_id=task_id,
                        intent_output=intent_output,
                        character_output=character_output,
                        lorebook_output=lorebook_output,
                        illustration_output=illustration_output,
                        audio_output=audio_output,
                    ),
                )
                self._assert_job_not_cancel_requested(job_id)

                self._create_artifact(job_id, "intent", intent_output)
                self._create_artifact(job_id, "dispatch_plan", dispatch_plan)
                self._create_artifact(job_id, "character_card", character_output)
                self._create_artifact(job_id, "lorebook", lorebook_output)
                if include_illustration_prompt:
                    self._create_artifact(
                        job_id,
                        "illustration_prompt",
                        illustration_output,
                    )
                if include_audio_plan:
                    self._create_artifact(job_id, "audio_plan", audio_output)

                bundle_payload = {
                    "character_card": character_output,
                    "lorebook": lorebook_output,
                    "illustration_prompt": illustration_output,
                    "audio_plan": audio_output,
                    "review": review_output,
                }
                self._create_artifact(job_id, "bundle", bundle_payload)

            self._generation_repository.update_job(
                job_id,
                status="completed",
                error_message=None,
                completed_at=self._utcnow(),
            )
            self._append_event(job_id, "job_completed", {"accepted": True})
        except GenerationJobCancelledError:
            self._mark_job_cancelled(job_id)
        except Exception as exc:
            self._generation_repository.update_job(
                job_id,
                status="failed",
                error_message=str(exc),
                completed_at=self._utcnow(),
            )
            self._append_event(job_id, "job_failed", {"detail": str(exc)})

        return self.get_job(job_id)

    def cancel_job(self, job_id: str) -> GenerationJobPublic:
        current = self._generation_repository.get_job(job_id)
        if current.status in {"completed", "failed", "cancelled"}:
            raise GenerationJobStateError(
                f"Cannot cancel job in terminal state: {current.status}"
            )
        if current.status == "cancel_requested":
            return self.get_job(job_id)

        self._generation_repository.update_job(
            job_id,
            status="cancel_requested",
            error_message="cancel requested by user",
        )
        self._append_event(job_id, "job_cancel_requested", {})
        latest = self._generation_repository.get_job(job_id)
        if latest.status == "pending":
            self._mark_job_cancelled(job_id)
        return self.get_job(job_id)

    def resolve_rerun_payload(
        self,
        source_job_id: str,
        *,
        user_input: str | None = None,
        pipeline_type: str | None = None,
        apply_mode: str | None = None,
        story_project_id: str | None = None,
        include_illustration_prompt: bool | None = None,
        include_audio_plan: bool | None = None,
    ) -> tuple[str, str, str, str | None, bool, bool]:
        source = self._generation_repository.get_job(source_job_id)
        next_input = source.user_input if user_input is None else user_input.strip()
        if not next_input:
            raise ValueError("user_input cannot be empty")

        source_config = self._resolve_source_job_config(source_job_id)
        next_pipeline_type = self._normalize_pipeline_type(
            source_config.get("pipeline_type", self._PIPELINE_ROLEPLAY)
            if pipeline_type is None
            else pipeline_type
        )
        next_apply_mode = self._normalize_apply_mode(
            source_config.get("apply_mode", self._APPLY_DRAFT_ONLY)
            if apply_mode is None
            else apply_mode
        )
        next_story_project_id = self._normalize_story_project_id(
            story_project_id=(
                source_config.get("story_project_id") if story_project_id is None else story_project_id
            ),
            pipeline_type=next_pipeline_type,
            apply_mode=next_apply_mode,
        )

        if include_illustration_prompt is not None and include_audio_plan is not None:
            return (
                next_input,
                next_pipeline_type,
                next_apply_mode,
                next_story_project_id,
                include_illustration_prompt,
                include_audio_plan,
            )

        tasks = self._generation_repository.list_tasks(job_id=source_job_id)
        inferred_illustration = any(
            task.task_type == "illustration_prompt_generate" for task in tasks
        )
        inferred_audio = any(task.task_type == "audio_plan_generate" for task in tasks)

        return (
            next_input,
            next_pipeline_type,
            next_apply_mode,
            next_story_project_id,
            inferred_illustration if include_illustration_prompt is None else include_illustration_prompt,
            inferred_audio if include_audio_plan is None else include_audio_plan,
        )

    def _normalize_pipeline_type(self, pipeline_type: str) -> str:
        normalized = str(pipeline_type or "").strip().lower()
        if not normalized:
            normalized = self._PIPELINE_ROLEPLAY
        if normalized not in {self._PIPELINE_ROLEPLAY, self._PIPELINE_STORY}:
            raise ValueError(
                "pipeline_type must be one of: roleplay_character, story_project"
            )
        return normalized

    def _normalize_apply_mode(self, apply_mode: str) -> str:
        normalized = str(apply_mode or "").strip().lower()
        if not normalized:
            normalized = self._APPLY_DRAFT_ONLY
        if normalized not in {self._APPLY_DRAFT_ONLY, self._APPLY_DIRECT}:
            raise ValueError("apply_mode must be one of: draft_only, direct_apply")
        return normalized

    def _normalize_story_project_id(
        self,
        *,
        story_project_id: str | None,
        pipeline_type: str,
        apply_mode: str,
    ) -> str | None:
        normalized = None if story_project_id is None else story_project_id.strip()
        if pipeline_type != self._PIPELINE_STORY:
            return None
        if normalized == "":
            normalized = None
        if apply_mode == self._APPLY_DRAFT_ONLY:
            return None
        return normalized

    def _resolve_source_job_config(self, source_job_id: str) -> dict[str, object]:
        events = self._generation_repository.list_events(job_id=source_job_id)
        for event in reversed(events):
            if event.event_type != "job_configured":
                continue
            payload = self._from_json(event.payload_json)
            if payload:
                return payload
        return {}

    def _apply_story_generation_output(
        self,
        *,
        story_project_id: str | None,
        story_blueprint_output: dict[str, object],
        story_lorebook_output: dict[str, object],
    ) -> dict[str, object]:
        if self._story_service is None:
            raise RoutingConfigurationError("Story service is not configured.")

        title = str(story_blueprint_output.get("title", "")).strip()
        premise = str(story_blueprint_output.get("premise", "")).strip()
        opening_scene = str(story_blueprint_output.get("opening_scene", "")).strip()
        system_prompt = str(story_blueprint_output.get("system_prompt", "")).strip()
        if not title or not premise:
            raise ValueError("story blueprint is missing title or premise")

        created = story_project_id is None
        if created:
            project = self._story_service.create_project(
                title=title,
                premise=premise,
                opening_scene=opening_scene,
                system_prompt=system_prompt,
            )
        else:
            project = self._story_service.update_project(
                story_project_id,
                title=title,
                premise=premise,
                opening_scene=opening_scene,
                system_prompt=system_prompt,
            )

        for existing in self._story_service.list_lorebooks(project_id=project.project_id):
            self._story_service.delete_lorebook(existing.lorebook_id)

        created_lorebooks: list[dict[str, object]] = []
        entries_raw = story_lorebook_output.get("entries")
        entries = entries_raw if isinstance(entries_raw, list) else []
        for item in entries:
            if not isinstance(item, dict):
                continue
            lorebook = self._story_service.create_lorebook(
                project_id=project.project_id,
                keyword=str(item.get("keyword", "")).strip(),
                insert_text=str(item.get("insert_text", "")).strip(),
                sort_order=int(item.get("sort_order", 100)),
                enabled=True,
            )
            created_lorebooks.append(
                {
                    "lorebook_id": lorebook.lorebook_id,
                    "keyword": lorebook.keyword,
                    "sort_order": lorebook.sort_order,
                }
            )

        return {
            "project_id": project.project_id,
            "created": created,
            "title": project.title,
            "replaced_lorebook_count": len(created_lorebooks),
            "lorebooks": created_lorebooks,
        }

    def _prepare_story_draft_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        if not isinstance(payload, dict):
            raise ValueError("story_draft_payload must be an object")

        blueprint_raw = payload.get("story_blueprint") or payload.get("blueprint")
        lorebook_raw = payload.get("story_lorebook") or payload.get("lorebook")
        illustration_raw = payload.get("illustration_prompt") or {}
        audio_raw = payload.get("audio_plan") or {}

        if not isinstance(blueprint_raw, dict):
            raise ValueError("story_draft_payload.story_blueprint must be an object")
        if not isinstance(lorebook_raw, dict):
            raise ValueError("story_draft_payload.story_lorebook must be an object")

        story_blueprint = self._validate_story_blueprint_output(blueprint_raw)
        story_lorebook = self._validate_story_lorebook_output(lorebook_raw)

        illustration_prompt: dict[str, object] = {}
        if isinstance(illustration_raw, dict) and str(illustration_raw.get("prompt", "")).strip():
            illustration_prompt = self._validate_illustration_prompt_output(illustration_raw)
        elif isinstance(illustration_raw, str) and illustration_raw.strip():
            illustration_prompt = self._validate_illustration_prompt_output(
                {"prompt": illustration_raw.strip()}
            )

        audio_plan: dict[str, object] = {}
        if isinstance(audio_raw, dict):
            audio_plan = {
                str(key)[:80]: value
                for key, value in audio_raw.items()
                if str(key).strip()
            }
        elif isinstance(audio_raw, str) and audio_raw.strip():
            audio_plan = {
                "voice_style": "narrative",
                "tone": "edited draft",
                "sample_line": audio_raw.strip()[:500],
            }

        continuity = self._build_story_continuity_review_output_local(
            story_blueprint_output=story_blueprint,
            story_lorebook_output=story_lorebook,
        )
        continuity["source"] = "local_validation"
        risks_raw = continuity.get("risks", [])
        risks = risks_raw if isinstance(risks_raw, list) else []
        if "edited_draft_without_model_review" not in risks:
            risks.append("edited_draft_without_model_review")
        continuity["risks"] = risks
        if not bool(continuity.get("accepted", False)):
            raise ValueError("edited story draft failed local continuity validation")

        return {
            "story_blueprint": story_blueprint,
            "story_lorebook": story_lorebook,
            "story_continuity_review": self._validate_story_continuity_review_output(continuity),
            "illustration_prompt": illustration_prompt,
            "audio_plan": audio_plan,
        }

    def get_job(self, job_id: str) -> GenerationJobPublic:
        stored = self._generation_repository.get_job(job_id)
        return self._to_job_public(stored)

    def list_jobs(self, *, limit: int = 50, offset: int = 0) -> list[GenerationJobPublic]:
        rows = self._generation_repository.list_jobs(limit=limit, offset=offset)
        return [self._to_job_public(row) for row in rows]

    def list_tasks(
        self,
        *,
        job_id: str,
        status: str | None = None,
        task_type: str | None = None,
        error_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[GenerationTaskPublic]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        rows = self._generation_repository.list_tasks(job_id=job_id)
        tasks = [self._to_task_public(row) for row in rows]
        if status is not None:
            tasks = [item for item in tasks if item.status == status]
        if task_type is not None:
            tasks = [item for item in tasks if item.task_type == task_type]
        if error_type is not None:
            tasks = [item for item in tasks if item.error_type == error_type]
        return tasks[offset : offset + limit]

    def list_artifacts(self, *, job_id: str) -> list[GenerationArtifactPublic]:
        rows = self._generation_repository.list_artifacts(job_id=job_id)
        return [self._to_artifact_public(row) for row in rows]

    def list_events(
        self,
        *,
        job_id: str,
        event_type: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[GenerationEventPublic]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        rows = self._generation_repository.list_events(job_id=job_id)
        events = [self._to_event_public(row) for row in rows]
        if event_type is not None:
            events = [item for item in events if item.event_type == event_type]
        return events[offset : offset + limit]

    def _assert_job_not_cancel_requested(self, job_id: str) -> None:
        current = self._generation_repository.get_job(job_id)
        if current.status == "cancel_requested":
            raise GenerationJobCancelledError("Job was cancelled by user request.")

    def _mark_job_cancelled(self, job_id: str) -> None:
        self._generation_repository.update_job(
            job_id,
            status="cancelled",
            error_message="cancelled by user",
            completed_at=self._utcnow(),
        )
        self._append_event(job_id, "job_cancelled", {})

    def _run_task(
        self,
        *,
        job_id: str,
        task_type: str,
        prompt_payload: dict[str, object],
        executor: Callable[[str], dict[str, object]],
    ) -> dict[str, object]:
        endpoint_candidates = self._select_endpoint_candidates(task_type)
        endpoint = endpoint_candidates[0] if endpoint_candidates else None
        prompt_payload_json = self._to_json(prompt_payload)
        started_perf = time.perf_counter()
        task = self._generation_repository.create_task(
            job_id=job_id,
            task_type=task_type,
            status="running",
            provider=None if endpoint is None else endpoint.provider,
            endpoint_id=None if endpoint is None else endpoint.endpoint_id,
            attempt=1,
            error_type=None,
            duration_ms=None,
            request_chars=len(prompt_payload_json),
            response_chars=0,
            prompt_payload_json=prompt_payload_json,
            output_payload_json="{}",
        )
        self._generation_repository.update_task(
            task.task_id,
            started_at=self._utcnow(),
        )
        self._append_event(
            job_id,
            "task_started",
            {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "provider": task.provider,
                "endpoint_id": task.endpoint_id,
            },
        )

        try:
            output = executor(task.task_id)
            output_payload_json = self._to_json(output)
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            self._generation_repository.update_task(
                task.task_id,
                status="completed",
                error_type=None,
                duration_ms=duration_ms,
                response_chars=len(output_payload_json),
                output_payload_json=output_payload_json,
                error_message=None,
                completed_at=self._utcnow(),
            )
            self._append_event(
                job_id,
                "task_completed",
                {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                },
            )
            return output
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            self._generation_repository.update_task(
                task.task_id,
                status="failed",
                error_message=str(exc),
                error_type=self._classify_error_type(exc),
                duration_ms=duration_ms,
                completed_at=self._utcnow(),
            )
            self._append_event(
                job_id,
                "task_failed",
                {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "detail": str(exc),
                },
            )
            raise

    def _create_artifact(
        self,
        job_id: str,
        artifact_type: str,
        payload: dict[str, object],
    ) -> None:
        self._generation_repository.create_artifact(
            job_id=job_id,
            artifact_type=artifact_type,
            payload_json=self._to_json(payload),
        )
        self._append_event(
            job_id,
            "artifact_created",
            {"artifact_type": artifact_type},
        )

    def _build_intent_output(
        self,
        *,
        job_id: str,
        task_id: str,
        user_input: str,
        pipeline_type: str,
    ) -> dict[str, object]:
        fallback = lambda: self._build_intent_output_local(
            user_input=user_input,
            pipeline_type=pipeline_type,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a planner for an AI narrative generation pipeline. "
                    "Return strict JSON with keys: summary, requirements, constraints. "
                    "requirements must include booleans: character_card, lorebook, story_blueprint, story_lorebook, illustration_prompt, audio_plan."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this user requirement and decide required tasks.\n"
                    f"Pipeline type: {pipeline_type}\n"
                    f"Requirement: {user_input}\n"
                    "Return JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="intent_parse",
            messages=messages,
            validator=self._validate_intent_output,
            fallback_builder=fallback,
        )

    def _build_intent_output_local(
        self,
        *,
        user_input: str,
        pipeline_type: str,
    ) -> dict[str, object]:
        include_illustration = any(
            token in user_input.lower()
            for token in ["???", "???", "image", "illustration", "???"]
        )
        include_audio = any(
            token in user_input.lower() for token in ["???", "???", "tts", "voice"]
        )
        is_story = pipeline_type == self._PIPELINE_STORY
        return {
            "summary": user_input[:300],
            "requirements": {
                "character_card": not is_story,
                "lorebook": not is_story,
                "story_blueprint": is_story,
                "story_lorebook": is_story,
                "illustration_prompt": include_illustration,
                "audio_plan": include_audio,
            },
            "constraints": [],
        }

    def _validate_intent_output(self, payload: dict[str, object]) -> dict[str, object]:
        summary = str(payload.get("summary", "")).strip()
        if not summary:
            raise ValueError("summary missing")

        requirements_raw = payload.get("requirements")
        requirements_obj = requirements_raw if isinstance(requirements_raw, dict) else {}
        requirements = {
            "character_card": bool(requirements_obj.get("character_card", True)),
            "lorebook": bool(requirements_obj.get("lorebook", True)),
            "story_blueprint": bool(requirements_obj.get("story_blueprint", False)),
            "story_lorebook": bool(requirements_obj.get("story_lorebook", False)),
            "illustration_prompt": bool(requirements_obj.get("illustration_prompt", False)),
            "audio_plan": bool(requirements_obj.get("audio_plan", False)),
        }

        constraints_raw = payload.get("constraints", [])
        constraints: list[str] = []
        if isinstance(constraints_raw, list):
            for item in constraints_raw[:20]:
                text = str(item).strip()
                if text:
                    constraints.append(text[:160])

        return {
            "summary": summary[:500],
            "requirements": requirements,
            "constraints": constraints,
        }

    def _build_dispatch_plan(
        self,
        *,
        job_id: str,
        task_id: str,
        intent_output: dict[str, object],
        pipeline_type: str,
        include_illustration_prompt: bool,
        include_audio_plan: bool,
    ) -> dict[str, object]:
        fallback = lambda: self._build_dispatch_plan_local(
            intent_output=intent_output,
            pipeline_type=pipeline_type,
            include_illustration_prompt=include_illustration_prompt,
            include_audio_plan=include_audio_plan,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You dispatch generation tasks for an AI narrative pipeline. "
                    "Return strict JSON with keys: tasks, strategy. "
                    "tasks is an ordered array of task names from this set: "
                    "character_card_generate, lorebook_generate, story_blueprint_generate, story_lorebook_generate, story_continuity_review, illustration_prompt_generate, audio_plan_generate, result_review."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Pipeline type: {pipeline_type}\n"
                    f"Intent JSON: {self._to_json(intent_output)}\n"
                    f"include_illustration_prompt={include_illustration_prompt}\n"
                    f"include_audio_plan={include_audio_plan}\n"
                    "Return JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="plan_dispatch",
            messages=messages,
            validator=lambda payload: self._validate_dispatch_plan_output(
                payload,
                pipeline_type=pipeline_type,
            ),
            fallback_builder=fallback,
        )

    def _build_dispatch_plan_local(
        self,
        *,
        intent_output: dict[str, object],
        pipeline_type: str,
        include_illustration_prompt: bool,
        include_audio_plan: bool,
    ) -> dict[str, object]:
        requirements = intent_output.get("requirements")
        req_obj = requirements if isinstance(requirements, dict) else {}
        if pipeline_type == self._PIPELINE_STORY:
            tasks = [
                "story_blueprint_generate",
                "story_lorebook_generate",
                "story_continuity_review",
                "result_review",
            ]
            if bool(req_obj.get("illustration_prompt")) or include_illustration_prompt:
                tasks.insert(2, "illustration_prompt_generate")
            if bool(req_obj.get("audio_plan")) or include_audio_plan:
                tasks.insert(3 if "illustration_prompt_generate" in tasks else 2, "audio_plan_generate")
        else:
            tasks = ["character_card_generate", "lorebook_generate", "result_review"]
            if bool(req_obj.get("illustration_prompt")) or include_illustration_prompt:
                tasks.insert(2, "illustration_prompt_generate")
            if bool(req_obj.get("audio_plan")) or include_audio_plan:
                tasks.insert(3, "audio_plan_generate")
        return {"tasks": tasks, "strategy": "parallelizable-after-intent"}

    def _validate_dispatch_plan_output(
        self,
        payload: dict[str, object],
        *,
        pipeline_type: str,
    ) -> dict[str, object]:
        allowed = {
            "character_card_generate",
            "lorebook_generate",
            "story_blueprint_generate",
            "story_lorebook_generate",
            "story_continuity_review",
            "illustration_prompt_generate",
            "audio_plan_generate",
            "result_review",
        }
        tasks_raw = payload.get("tasks")
        tasks: list[str] = []
        if isinstance(tasks_raw, list):
            for item in tasks_raw:
                name = str(item).strip()
                if name in allowed and name not in tasks:
                    tasks.append(name)
        if pipeline_type == self._PIPELINE_STORY:
            if "story_blueprint_generate" not in tasks:
                tasks.insert(0, "story_blueprint_generate")
            if "story_lorebook_generate" not in tasks:
                insert_at = 1 if len(tasks) >= 1 else 0
                tasks.insert(insert_at, "story_lorebook_generate")
            if "story_continuity_review" not in tasks:
                insert_at = len(tasks) if "result_review" not in tasks else max(0, len(tasks) - 1)
                tasks.insert(insert_at, "story_continuity_review")
        else:
            if "character_card_generate" not in tasks:
                tasks.insert(0, "character_card_generate")
            if "lorebook_generate" not in tasks:
                insert_at = 1 if len(tasks) >= 1 else 0
                tasks.insert(insert_at, "lorebook_generate")
        if "result_review" not in tasks:
            tasks.append("result_review")
        strategy = str(payload.get("strategy") or "parallelizable-after-intent").strip()
        if not strategy:
            strategy = "parallelizable-after-intent"
        return {"tasks": tasks, "strategy": strategy[:120]}

    def _build_character_card_output(
        self,
        *,
        job_id: str,
        task_id: str,
        user_input: str,
    ) -> dict[str, object]:
        fallback = lambda: self._build_character_card_output_local(user_input)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a roleplay character card generator. "
                    "Return strict JSON with keys: "
                    "name, description, system_prompt, first_message."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Generate a roleplay character card from this requirement:\n"
                    f"{user_input}\n\n"
                    "Output JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="character_card_generate",
            messages=messages,
            validator=self._validate_character_card_output,
            fallback_builder=fallback,
        )

    def _build_character_card_output_local(self, user_input: str) -> dict[str, object]:
        text = user_input.strip()
        short_desc = text if len(text) <= 180 else f"{text[:177]}..."
        tokens = [
            token.strip(" ,.!?;:\"'()[]{}")
            for token in text.split()
            if token.strip(" ,.!?;:\"'()[]{}")
        ]
        name = "New Character"
        if tokens:
            name = " ".join(tokens[:4])[:80]

        return {
            "name": name,
            "description": f"Role profile based on user intent: {short_desc}",
            "system_prompt": (
                "Stay in character, respond with immersive detail, "
                "and keep continuity across turns."
            ),
            "first_message": (
                f"Hi, I am {name}. Tell me what scene you want to start with."
            ),
            "route_mode": "local_fallback",
            "auto_completed_fields": [],
        }

    def _build_lorebook_output(
        self,
        *,
        job_id: str,
        task_id: str,
        user_input: str,
        character_name: str,
    ) -> dict[str, object]:
        fallback = lambda: self._build_lorebook_output_local(
            user_input=user_input,
            character_name=character_name,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate lorebook entries for roleplay. "
                    "Return strict JSON with key 'entries' as an array. "
                    "Each entry must include keyword, insert_text, sort_order."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Character name: {character_name}\n"
                    f"Requirement: {user_input}\n"
                    "Return 3 to 5 concise lorebook entries in JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="lorebook_generate",
            messages=messages,
            validator=self._validate_lorebook_output,
            fallback_builder=fallback,
        )

    def _build_lorebook_output_local(
        self,
        *,
        user_input: str,
        character_name: str,
    ) -> dict[str, object]:
        keywords = self._extract_keywords(user_input)
        entries = []
        sort_order = 100
        for keyword in keywords[:5]:
            entries.append(
                {
                    "keyword": keyword,
                    "insert_text": (
                        f"{character_name} setting note about '{keyword}'. "
                        "Use this for continuity in roleplay context."
                    ),
                    "sort_order": sort_order,
                }
            )
            sort_order += 10
        if not entries:
            entries.append(
                {
                    "keyword": "baseline",
                    "insert_text": (
                        f"{character_name} baseline world context. "
                        "Maintain consistency across turns."
                    ),
                    "sort_order": 100,
                }
            )
        return {"entries": entries}

    def _build_story_blueprint_output(
        self,
        *,
        job_id: str,
        task_id: str,
        user_input: str,
    ) -> dict[str, object]:
        fallback = lambda: self._build_story_blueprint_output_local(user_input=user_input)
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate an interactive fiction story blueprint. "
                    "Return strict JSON with keys: title, premise, opening_scene, system_prompt, chapters_outline, tone, protagonist_profile."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create a story blueprint from this requirement:\n"
                    f"{user_input}\n\n"
                    "Output JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="story_blueprint_generate",
            messages=messages,
            validator=self._validate_story_blueprint_output,
            fallback_builder=fallback,
        )

    def _build_story_blueprint_output_local(
        self,
        *,
        user_input: str,
    ) -> dict[str, object]:
        text = user_input.strip()
        tokens = [
            token.strip(" ,.!?;:\"'()[]{}")
            for token in text.split()
            if token.strip(" ,.!?;:\"'()[]{}")
        ]
        title = "Untitled Story Project"
        if tokens:
            title = " ".join(tokens[:5])[:120]
        premise = text[:1200] or "An unfolding interactive fiction story."
        opening_scene = (
            f"The story begins in motion: {text[:280]}" if text else "The story begins with a tense, unresolved opening scene."
        )
        return {
            "title": title,
            "premise": premise,
            "opening_scene": opening_scene[:4000],
            "system_prompt": "Narrate with immersive detail, preserve continuity, and let player choices redirect the scene.",
            "chapters_outline": [
                "Chapter 1: Establish the setting, the immediate tension, and the player's role.",
                "Chapter 2: Reveal a complication that deepens the mystery or conflict.",
                "Chapter 3: Force a consequential decision that changes the direction of the story.",
            ],
            "tone": "immersive dramatic fiction",
            "protagonist_profile": text[:600] or "A capable protagonist entering a volatile situation.",
        }

    def _build_story_lorebook_output(
        self,
        *,
        job_id: str,
        task_id: str,
        user_input: str,
        story_blueprint: dict[str, object],
    ) -> dict[str, object]:
        fallback = lambda: self._build_story_lorebook_output_local(
            user_input=user_input,
            story_blueprint=story_blueprint,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate lorebook entries for an interactive fiction project. "
                    "Return strict JSON with key 'entries' as an array. "
                    "Each entry must include keyword, insert_text, sort_order."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Requirement: {user_input}\n"
                    f"Story blueprint JSON: {self._to_json(story_blueprint)}\n"
                    "Return 3 to 6 concise lorebook entries in JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="story_lorebook_generate",
            messages=messages,
            validator=self._validate_story_lorebook_output,
            fallback_builder=fallback,
        )

    def _build_story_lorebook_output_local(
        self,
        *,
        user_input: str,
        story_blueprint: dict[str, object],
    ) -> dict[str, object]:
        title = str(story_blueprint.get("title", "Story")).strip() or "Story"
        keywords = self._extract_keywords(
            f"{user_input} {story_blueprint.get('premise', '')} {story_blueprint.get('opening_scene', '')}"
        )
        entries: list[dict[str, object]] = []
        for idx, keyword in enumerate(keywords[:5]):
            entries.append(
                {
                    "keyword": keyword,
                    "insert_text": f"{title} setting note about '{keyword}'. Keep the story consistent when this appears.",
                    "sort_order": 100 + idx * 10,
                }
            )
        if not entries:
            entries.append(
                {
                    "keyword": "story-baseline",
                    "insert_text": f"{title} baseline world rule. Preserve continuity and recurring tone.",
                    "sort_order": 100,
                }
            )
        return {"entries": entries}

    def _build_story_illustration_prompt_output(
        self,
        *,
        job_id: str,
        task_id: str,
        user_input: str,
        story_blueprint: dict[str, object],
    ) -> dict[str, object]:
        fallback = lambda: self._build_story_illustration_prompt_output_local(
            user_input=user_input,
            story_blueprint=story_blueprint,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a high quality illustration prompt for an interactive fiction story cover or opening scene. "
                    "Return strict JSON with keys: prompt, negative_prompt."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Requirement: {user_input}\n"
                    f"Story blueprint JSON: {self._to_json(story_blueprint)}\n"
                    "Return JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="illustration_prompt_generate",
            messages=messages,
            validator=self._validate_illustration_prompt_output,
            fallback_builder=fallback,
        )

    def _build_story_illustration_prompt_output_local(
        self,
        *,
        user_input: str,
        story_blueprint: dict[str, object],
    ) -> dict[str, object]:
        title = str(story_blueprint.get("title", "Story")).strip() or "Story"
        opening_scene = str(story_blueprint.get("opening_scene", "")).strip()
        prompt = (
            f"Cover or opening-scene illustration for {title}. "
            f"Scene: {opening_scene[:260]}. "
            f"Requirement: {user_input[:180]}. "
            "Cinematic composition, atmospheric lighting, high detail, narrative focus."
        )
        return {
            "prompt": prompt,
            "negative_prompt": "lowres, blurry, distorted anatomy, extra limbs, text watermark, logo",
        }

    def _build_story_audio_plan_output(self, story_blueprint: dict[str, object]) -> dict[str, object]:
        title = str(story_blueprint.get("title", "Story")).strip() or "Story"
        tone = str(story_blueprint.get("tone", "immersive dramatic fiction")).strip() or "immersive dramatic fiction"
        return {
            "voice_style": "narrative_cinematic",
            "tone": tone[:120],
            "sample_line": f"{title}: the scene opens and the world begins to move around the player.",
        }

    def _build_story_continuity_review_output(
        self,
        *,
        job_id: str,
        task_id: str,
        intent_output: dict[str, object],
        story_blueprint_output: dict[str, object],
        story_lorebook_output: dict[str, object],
    ) -> dict[str, object]:
        fallback = lambda: self._build_story_continuity_review_output_local(
            story_blueprint_output=story_blueprint_output,
            story_lorebook_output=story_lorebook_output,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Review story generation outputs for continuity readiness. "
                    "Return strict JSON with keys: accepted, missing, risks."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Intent JSON: {self._to_json(intent_output)}\n"
                    f"Story blueprint JSON: {self._to_json(story_blueprint_output)}\n"
                    f"Story lorebook JSON: {self._to_json(story_lorebook_output)}\n"
                    "Return JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="story_continuity_review",
            messages=messages,
            validator=self._validate_story_continuity_review_output,
            fallback_builder=fallback,
        )

    def _build_story_continuity_review_output_local(
        self,
        *,
        story_blueprint_output: dict[str, object],
        story_lorebook_output: dict[str, object],
    ) -> dict[str, object]:
        missing: list[str] = []
        risks: list[str] = []
        if not story_blueprint_output.get("title"):
            missing.append("story_blueprint.title")
        if not story_blueprint_output.get("opening_scene"):
            missing.append("story_blueprint.opening_scene")
        if not story_lorebook_output.get("entries"):
            missing.append("story_lorebook.entries")
        if len(str(story_blueprint_output.get("premise", "")).strip()) < 40:
            risks.append("premise_too_short")
        return {"accepted": len(missing) == 0, "missing": missing, "risks": risks}

    def _build_illustration_prompt_output(
        self,
        *,
        job_id: str,
        task_id: str,
        user_input: str,
        character: dict[str, object],
    ) -> dict[str, object]:
        fallback = lambda: self._build_illustration_prompt_output_local(
            user_input=user_input,
            character=character,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a high quality illustration prompt for character portrait. "
                    "Return strict JSON with keys: prompt, negative_prompt."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create a prompt for this character requirement.\n"
                    f"Requirement: {user_input}\n"
                    f"Character JSON: {self._to_json(character)}\n"
                    "JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="illustration_prompt_generate",
            messages=messages,
            validator=self._validate_illustration_prompt_output,
            fallback_builder=fallback,
        )

    def _build_illustration_prompt_output_local(
        self,
        *,
        user_input: str,
        character: dict[str, object],
    ) -> dict[str, object]:
        name = str(character.get("name", "Character")).strip() or "Character"
        description = str(character.get("description", "")).strip()
        prompt = (
            f"Portrait illustration of {name}. "
            f"Character profile: {description}. "
            f"Scene requirement: {user_input[:200]}. "
            "Cinematic lighting, clean composition, detailed costume, high quality."
        )
        negative_prompt = (
            "lowres, blurry, distorted anatomy, extra limbs, text watermark, logo"
        )
        return {"prompt": prompt, "negative_prompt": negative_prompt}

    def _build_audio_plan_output(self, character: dict[str, object]) -> dict[str, object]:
        name = str(character.get("name", "Character")).strip() or "Character"
        return {
            "voice_style": "neutral_narrative",
            "tone": "immersive",
            "sample_line": f"Hello, I am {name}. Let's begin the scene.",
        }

    def _build_review_output(
        self,
        *,
        job_id: str,
        task_id: str,
        intent_output: dict[str, object],
        character_output: dict[str, object],
        lorebook_output: dict[str, object],
        illustration_output: dict[str, object],
        audio_output: dict[str, object],
    ) -> dict[str, object]:
        fallback = lambda: self._build_review_output_local(
            intent_output=intent_output,
            character_output=character_output,
            lorebook_output=lorebook_output,
            illustration_output=illustration_output,
            audio_output=audio_output,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You review generation outputs against requirements. "
                    "Return strict JSON with keys: accepted (bool), missing (array of string)."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Intent JSON: {self._to_json(intent_output)}\n"
                    f"Character JSON: {self._to_json(character_output)}\n"
                    f"Lorebook JSON: {self._to_json(lorebook_output)}\n"
                    f"Illustration JSON: {self._to_json(illustration_output)}\n"
                    f"Audio JSON: {self._to_json(audio_output)}\n"
                    "Review and return JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="result_review",
            messages=messages,
            validator=self._validate_review_output,
            fallback_builder=fallback,
        )

    def _build_review_output_local(
        self,
        *,
        intent_output: dict[str, object],
        character_output: dict[str, object],
        lorebook_output: dict[str, object],
        illustration_output: dict[str, object],
        audio_output: dict[str, object],
    ) -> dict[str, object]:
        missing: list[str] = []
        if not character_output.get("name"):
            missing.append("character_card.name")
        if not lorebook_output.get("entries"):
            missing.append("lorebook.entries")
        requirements = intent_output.get("requirements")
        req_obj = requirements if isinstance(requirements, dict) else {}
        if bool(req_obj.get("illustration_prompt")) and not illustration_output:
            missing.append("illustration_prompt")
        if bool(req_obj.get("audio_plan")) and not audio_output:
            missing.append("audio_plan")
        return {
            "accepted": len(missing) == 0,
            "missing": missing,
        }

    def _build_story_review_output(
        self,
        *,
        job_id: str,
        task_id: str,
        intent_output: dict[str, object],
        story_blueprint_output: dict[str, object],
        story_lorebook_output: dict[str, object],
        continuity_output: dict[str, object],
        illustration_output: dict[str, object],
        audio_output: dict[str, object],
    ) -> dict[str, object]:
        fallback = lambda: self._build_story_review_output_local(
            intent_output=intent_output,
            story_blueprint_output=story_blueprint_output,
            story_lorebook_output=story_lorebook_output,
            continuity_output=continuity_output,
            illustration_output=illustration_output,
            audio_output=audio_output,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You review story generation outputs against requirements. "
                    "Return strict JSON with keys: accepted (bool), missing (array of string)."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Intent JSON: {self._to_json(intent_output)}\n"
                    f"Story blueprint JSON: {self._to_json(story_blueprint_output)}\n"
                    f"Story lorebook JSON: {self._to_json(story_lorebook_output)}\n"
                    f"Continuity JSON: {self._to_json(continuity_output)}\n"
                    f"Illustration JSON: {self._to_json(illustration_output)}\n"
                    f"Audio JSON: {self._to_json(audio_output)}\n"
                    "Review and return JSON only."
                ),
            },
        ]
        return self._execute_model_or_fallback(
            job_id=job_id,
            task_id=task_id,
            task_type="result_review",
            messages=messages,
            validator=self._validate_story_review_output,
            fallback_builder=fallback,
        )

    def _build_story_review_output_local(
        self,
        *,
        intent_output: dict[str, object],
        story_blueprint_output: dict[str, object],
        story_lorebook_output: dict[str, object],
        continuity_output: dict[str, object],
        illustration_output: dict[str, object],
        audio_output: dict[str, object],
    ) -> dict[str, object]:
        missing: list[str] = []
        if not story_blueprint_output.get("title"):
            missing.append("story_blueprint.title")
        if not story_lorebook_output.get("entries"):
            missing.append("story_lorebook.entries")
        if not bool(continuity_output.get("accepted", False)):
            missing.extend(str(item) for item in continuity_output.get("missing", []) if str(item).strip())
        requirements = intent_output.get("requirements")
        req_obj = requirements if isinstance(requirements, dict) else {}
        if bool(req_obj.get("illustration_prompt")) and not illustration_output:
            missing.append("illustration_prompt")
        if bool(req_obj.get("audio_plan")) and not audio_output:
            missing.append("audio_plan")
        unique_missing = []
        seen: set[str] = set()
        for item in missing:
            normalized = str(item).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_missing.append(normalized[:120])
        return {"accepted": len(unique_missing) == 0, "missing": unique_missing}

    def _execute_model_or_fallback(
        self,
        *,
        job_id: str,
        task_id: str,
        task_type: str,
        messages: list[dict[str, str]],
        validator: Callable[[dict[str, object]], dict[str, object]],
        fallback_builder: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        endpoints = self._select_endpoint_candidates(task_type)
        if not endpoints:
            self._append_event(
                job_id,
                "task_model_skipped_no_endpoint",
                {"task_id": task_id, "task_type": task_type},
            )
            return fallback_builder()

        failures: list[str] = []
        for attempt_index, endpoint in enumerate(endpoints, start=1):
            self._generation_repository.update_task(
                task_id,
                provider=endpoint.provider,
                endpoint_id=endpoint.endpoint_id,
                attempt=attempt_index,
            )
            self._append_event(
                job_id,
                "task_attempt_started",
                {
                    "task_id": task_id,
                    "task_type": task_type,
                    "attempt": attempt_index,
                    "provider": endpoint.provider,
                    "endpoint_id": endpoint.endpoint_id,
                },
            )

            try:
                output = self._call_endpoint_json(
                    endpoint=endpoint,
                    messages=messages,
                )
                validated = validator(output)
                self._append_event(
                    job_id,
                    "task_attempt_succeeded",
                    {
                        "task_id": task_id,
                        "task_type": task_type,
                        "attempt": attempt_index,
                        "provider": endpoint.provider,
                        "endpoint_id": endpoint.endpoint_id,
                    },
                )
                return validated
            except Exception as exc:
                detail = f"[{endpoint.provider}:{endpoint.endpoint_id}] {exc}"
                failures.append(detail)
                self._generation_repository.update_task(
                    task_id,
                    error_message=detail,
                )
                self._append_event(
                    job_id,
                    "task_attempt_failed",
                    {
                        "task_id": task_id,
                        "task_type": task_type,
                        "attempt": attempt_index,
                        "provider": endpoint.provider,
                        "endpoint_id": endpoint.endpoint_id,
                        "detail": str(exc),
                    },
                )

        self._append_event(
            job_id,
            "task_model_fallback_local",
            {
                "task_id": task_id,
                "task_type": task_type,
                "failures": failures,
            },
        )
        return fallback_builder()

    def _call_endpoint_json(
        self,
        *,
        endpoint: ModelEndpointRuntime,
        messages: list[dict[str, str]],
    ) -> dict[str, object]:
        if not endpoint.api_key:
            raise UpstreamModelError("Endpoint api_key is empty.")

        request_url, headers, payload = self._model_endpoint_service.build_chat_completion_request(
            endpoint_id=endpoint.endpoint_id,
            messages=messages,
            stream=False,
        )
        payload.setdefault("temperature", 0.7)
        payload.setdefault("response_format", {"type": "json_object"})

        try:
            response = httpx.post(
                request_url,
                headers=headers,
                json=payload,
                timeout=45.0,
            )
        except httpx.RequestError as exc:
            raise UpstreamModelError(f"request failed: {exc}") from exc

        if response.status_code >= 400:
            raise UpstreamModelError(f"HTTP {response.status_code}")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content must be a string")
            raw_json = self._extract_json_payload(content)
            parsed = json.loads(raw_json)
            if not isinstance(parsed, dict):
                raise TypeError("payload must be an object")
            return parsed
        except Exception as exc:
            raise UpstreamModelError("invalid response format") from exc

    def _validate_character_card_output(self, payload: dict[str, object]) -> dict[str, object]:
        name = str(payload.get("name", "")).strip()
        description = str(payload.get("description", "")).strip()
        system_prompt = str(payload.get("system_prompt", "")).strip()
        first_message = str(payload.get("first_message", "")).strip()
        if not name:
            raise ValueError("name missing")
        if not description:
            description = f"Role profile for {name}."
        if not system_prompt:
            system_prompt = "Stay in character and keep roleplay continuity."
        if not first_message:
            first_message = f"Hello, I am {name}. Tell me the scene to start."
        return {
            "name": name[:80],
            "description": description[:2000],
            "system_prompt": system_prompt[:8000],
            "first_message": first_message[:2000],
            "route_mode": "model_endpoints",
            "auto_completed_fields": [],
        }

    def _validate_lorebook_output(self, payload: dict[str, object]) -> dict[str, object]:
        entries_raw = payload.get("entries")
        if not isinstance(entries_raw, list) or not entries_raw:
            raise ValueError("entries missing")
        entries: list[dict[str, object]] = []
        for idx, item in enumerate(entries_raw[:8]):
            if not isinstance(item, dict):
                continue
            keyword = str(item.get("keyword", "")).strip()
            insert_text = str(item.get("insert_text", "")).strip()
            sort_order_raw = item.get("sort_order", 100 + idx * 10)
            try:
                sort_order = int(sort_order_raw)
            except (TypeError, ValueError):
                sort_order = 100 + idx * 10
            if not keyword or not insert_text:
                continue
            entries.append(
                {
                    "keyword": keyword[:120],
                    "insert_text": insert_text[:4000],
                    "sort_order": max(0, min(sort_order, 10000)),
                }
            )
        if not entries:
            raise ValueError("entries invalid")
        return {"entries": entries}

    def _validate_story_blueprint_output(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        title = str(payload.get("title", "")).strip()
        premise = str(payload.get("premise", "")).strip()
        opening_scene = str(payload.get("opening_scene", "")).strip()
        system_prompt = str(payload.get("system_prompt", "")).strip()
        tone = str(payload.get("tone", "")).strip()
        protagonist_profile = str(payload.get("protagonist_profile", "")).strip()
        chapters_raw = payload.get("chapters_outline", [])
        if not title:
            raise ValueError("story_blueprint.title missing")
        if not premise:
            raise ValueError("story_blueprint.premise missing")
        if not opening_scene:
            raise ValueError("story_blueprint.opening_scene missing")
        if not system_prompt:
            system_prompt = "Maintain narrative continuity, immersive detail, and clear scene progression."
        if not tone:
            tone = "immersive dramatic fiction"
        if not protagonist_profile:
            protagonist_profile = "A capable protagonist with room to grow under pressure."
        chapters: list[str] = []
        if isinstance(chapters_raw, list):
            for item in chapters_raw[:8]:
                text = str(item).strip()
                if text:
                    chapters.append(text[:240])
        if len(chapters) < 3:
            raise ValueError("story_blueprint.chapters_outline must contain at least 3 items")
        return {
            "title": title[:120],
            "premise": premise[:4000],
            "opening_scene": opening_scene[:4000],
            "system_prompt": system_prompt[:8000],
            "chapters_outline": chapters,
            "tone": tone[:200],
            "protagonist_profile": protagonist_profile[:2000],
        }

    def _validate_story_lorebook_output(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self._validate_lorebook_output(payload)

    def _validate_story_continuity_review_output(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        accepted = bool(payload.get("accepted", False))
        missing_raw = payload.get("missing", [])
        risks_raw = payload.get("risks", [])
        missing = [
            str(item).strip()[:120]
            for item in (missing_raw if isinstance(missing_raw, list) else [])
            if str(item).strip()
        ][:20]
        risks = [
            str(item).strip()[:160]
            for item in (risks_raw if isinstance(risks_raw, list) else [])
            if str(item).strip()
        ][:20]
        return {"accepted": accepted, "missing": missing, "risks": risks}

    def _validate_story_review_output(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self._validate_review_output(payload)

    def _validate_illustration_prompt_output(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        prompt = str(payload.get("prompt", "")).strip()
        negative_prompt = str(payload.get("negative_prompt", "")).strip()
        if not prompt:
            raise ValueError("prompt missing")
        if not negative_prompt:
            negative_prompt = (
                "lowres, blurry, distorted anatomy, extra limbs, text watermark, logo"
            )
        return {
            "prompt": prompt[:4000],
            "negative_prompt": negative_prompt[:2000],
        }

    def _validate_review_output(self, payload: dict[str, object]) -> dict[str, object]:
        accepted = bool(payload.get("accepted", False))
        missing_raw = payload.get("missing", [])
        missing: list[str] = []
        if isinstance(missing_raw, list):
            for item in missing_raw[:20]:
                missing.append(str(item)[:120])
        return {"accepted": accepted, "missing": missing}

    def _select_endpoint_candidates(self, task_type: str) -> list[ModelEndpointRuntime]:
        endpoints = self._model_endpoint_service.list_runtime_endpoints(include_disabled=False)
        if not endpoints:
            return []

        preferred_providers = self._task_provider_preferences(task_type)
        provider_rank = {provider: idx for idx, provider in enumerate(preferred_providers)}
        sorted_candidates = sorted(
            endpoints,
            key=lambda item: (
                1 if item.is_fallback else 0,
                provider_rank.get(item.provider, 999),
                item.priority,
                item.name,
            ),
        )
        if self._app_settings_service is None:
            return sorted_candidates

        bindings = self._app_settings_service.get_generation_task_bindings()
        preferred_endpoint_id = bindings.get(task_type)
        if not preferred_endpoint_id:
            return sorted_candidates

        preferred = next(
            (item for item in sorted_candidates if item.endpoint_id == preferred_endpoint_id),
            None,
        )
        if preferred is None:
            return sorted_candidates

        fallback_candidates = [
            item for item in sorted_candidates if item.endpoint_id != preferred_endpoint_id
        ]
        return [preferred, *fallback_candidates]

    @staticmethod
    def _task_provider_preferences(task_type: str) -> list[str]:
        if task_type == "character_card_generate":
            return ["deepseek", "qwen", "kimi", "openai", "openai_compatible"]
        if task_type == "lorebook_generate":
            return ["qwen", "deepseek", "kimi", "openai", "openai_compatible"]
        if task_type == "story_blueprint_generate":
            return ["deepseek", "kimi", "qwen", "openai", "openai_compatible"]
        if task_type == "story_lorebook_generate":
            return ["qwen", "deepseek", "kimi", "openai", "openai_compatible"]
        if task_type == "story_continuity_review":
            return ["kimi", "deepseek", "qwen", "openai", "openai_compatible"]
        if task_type == "illustration_prompt_generate":
            return ["kimi", "qwen", "deepseek", "openai", "openai_compatible"]
        if task_type == "audio_plan_generate":
            return ["kimi", "qwen", "deepseek", "openai", "openai_compatible"]
        return ["deepseek", "qwen", "kimi", "openai", "openai_compatible"]

    @staticmethod
    def _extract_json_payload(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object in response content.")
        return stripped[start : end + 1]

    def _append_event(
        self,
        job_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        self._generation_repository.append_event(
            job_id=job_id,
            event_type=event_type,
            payload_json=self._to_json(payload),
        )

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        seen: set[str] = set()
        keywords: list[str] = []
        for raw in text.replace("\n", " ").split():
            token = raw.strip(" ,.!?;:\"'()[]{}").lower()
            if len(token) < 3:
                continue
            if token in seen:
                continue
            seen.add(token)
            keywords.append(token)
        return keywords

    @staticmethod
    def _to_json(payload: dict[str, object]) -> str:
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _from_json(raw: str) -> dict[str, object]:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {}

    @staticmethod
    def _to_job_public(job: StoredGenerationJob) -> GenerationJobPublic:
        return GenerationJobPublic(
            job_id=job.job_id,
            status=job.status,
            user_input=job.user_input,
            pipeline_version=job.pipeline_version,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
        )

    def _to_task_public(self, task: StoredGenerationTask) -> GenerationTaskPublic:
        return GenerationTaskPublic(
            task_id=task.task_id,
            job_id=task.job_id,
            task_type=task.task_type,
            status=task.status,
            provider=task.provider,
            endpoint_id=task.endpoint_id,
            attempt=task.attempt,
            error_message=task.error_message,
            error_type=task.error_type,
            duration_ms=task.duration_ms,
            request_chars=task.request_chars,
            response_chars=task.response_chars,
            prompt_payload=self._from_json(task.prompt_payload_json),
            output_payload=self._from_json(task.output_payload_json),
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )

    def _to_artifact_public(
        self,
        artifact: StoredGenerationArtifact,
    ) -> GenerationArtifactPublic:
        return GenerationArtifactPublic(
            artifact_id=artifact.artifact_id,
            job_id=artifact.job_id,
            artifact_type=artifact.artifact_type,
            payload=self._from_json(artifact.payload_json),
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )

    def _to_event_public(self, event: StoredGenerationEvent) -> GenerationEventPublic:
        return GenerationEventPublic(
            event_id=event.event_id,
            job_id=event.job_id,
            event_type=event.event_type,
            payload=self._from_json(event.payload_json),
            created_at=event.created_at,
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _classify_error_type(exc: Exception) -> str:
        if isinstance(exc, GenerationJobCancelledError):
            return "cancelled"
        if isinstance(exc, UpstreamModelError):
            return "upstream_model"
        if isinstance(exc, RoutingConfigurationError):
            return "routing_config"
        if isinstance(exc, ValueError):
            return "validation"
        return "internal"


@dataclass(frozen=True)
class StoryContextStats:
    session_id: str
    context_char_budget: int
    summary_chars: int
    fact_count: int
    lorebook_hit_count: int
    recent_entry_chars: int
    recent_entry_count: int
    checkpoint_count: int
    updated_at: datetime


@dataclass(frozen=True)
class StoryContinueResult:
    session_id: str
    reply: str
    checkpoint_id: str
    entry_count: int
    context_stats: StoryContextStats


@dataclass(frozen=True)
class StoryAigcActionPublic:
    action_id: str
    session_id: str
    action_type: str
    selected_text: str
    result: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class StoryContextBundle:
    messages: list[dict[str, object]]
    stats: StoryContextStats


class StoryService:
    _CONTEXT_CHAR_BUDGET = 12000
    _SUMMARY_MAX_CHARS = 2400
    _CHECKPOINT_SUMMARY_MAX_CHARS = 1200
    _LOREBOOK_TOTAL_MAX_CHARS = 2200
    _FACTS_TOTAL_MAX_CHARS = 1800
    _RECENT_TOTAL_MAX_CHARS = 4200

    def __init__(
        self,
        story_repository: StoryRepository,
        *,
        app_settings_service: "AppSettingsService | None" = None,
        model_endpoint_service: "ModelEndpointService | None" = None,
        tool_runtime: ToolCallRuntime | None = None,
    ) -> None:
        self._story_repository = story_repository
        self._app_settings_service = app_settings_service
        self._model_endpoint_service = model_endpoint_service
        self._tool_runtime = tool_runtime
        self._context_stats_by_session: dict[str, StoryContextStats] = {}

    def create_project(
        self,
        *,
        title: str,
        premise: str,
        opening_scene: str = "",
        system_prompt: str = "",
    ) -> StoredStoryProject:
        return self._story_repository.create_project(
            title=title.strip(),
            premise=premise.strip(),
            opening_scene=opening_scene.strip(),
            system_prompt=system_prompt.strip(),
            status="active",
        )

    def list_projects(self, *, limit: int = 50, offset: int = 0) -> list[StoredStoryProject]:
        return self._story_repository.list_projects(limit=limit, offset=offset)

    def get_project(self, project_id: str) -> StoredStoryProject:
        return self._story_repository.get_project(project_id)

    def update_project(
        self,
        project_id: str,
        *,
        title: str | None = None,
        premise: str | None = None,
        opening_scene: str | None = None,
        system_prompt: str | None = None,
        status: str | None = None,
    ) -> StoredStoryProject:
        return self._story_repository.update_project(
            project_id,
            title=None if title is None else title.strip(),
            premise=None if premise is None else premise.strip(),
            opening_scene=None if opening_scene is None else opening_scene.strip(),
            system_prompt=None if system_prompt is None else system_prompt.strip(),
            status=None if status is None else status.strip(),
        )

    def delete_project(self, project_id: str) -> None:
        sessions = self._story_repository.list_sessions(project_id=project_id, limit=200, offset=0)
        self._story_repository.delete_project(project_id)
        for session in sessions:
            self._context_stats_by_session.pop(session.session_id, None)

    def start_session(self, project_id: str) -> StoredStorySession:
        project = self._story_repository.get_project(project_id)
        session = self._story_repository.create_session(project_id=project_id)
        opening_scene = project.opening_scene.strip()
        if opening_scene:
            entry = self._story_repository.append_entry(
                session_id=session.session_id,
                role="assistant",
                content=opening_scene,
                entry_type="scene",
            )
            facts = self._extract_story_facts([opening_scene])
            self._story_repository.replace_facts(session_id=session.session_id, facts=facts)
            checkpoint = self._story_repository.create_checkpoint(
                session_id=session.session_id,
                title="Opening",
                summary_text=self._build_summary("", opening_scene),
                current_scene=opening_scene,
                facts_json=json.dumps(facts, ensure_ascii=False),
                last_sequence=entry.sequence,
            )
            session = self._story_repository.update_session_state(
                session.session_id,
                current_summary=self._build_summary("", opening_scene),
                current_scene=opening_scene,
                active_checkpoint_id=checkpoint.checkpoint_id,
            )
        self._context_stats_by_session[session.session_id] = self._compute_context_stats(
            session_id=session.session_id
        )
        return session

    def list_sessions(
        self,
        *,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StoredStorySession]:
        return self._story_repository.list_sessions(
            project_id=project_id,
            limit=limit,
            offset=offset,
        )

    def get_session(self, session_id: str) -> StoredStorySession:
        return self._story_repository.get_session(session_id)

    def get_history(self, session_id: str) -> list[StoredStoryEntry]:
        return self._story_repository.get_history(session_id)

    def list_facts(self, session_id: str) -> list[StoredStoryFact]:
        return self._story_repository.list_facts(session_id)

    def list_checkpoints(
        self,
        *,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        ) -> list[StoredStoryCheckpoint]:
        return self._story_repository.list_checkpoints(
            session_id=session_id,
            limit=limit,
            offset=offset,
        )

    def create_lorebook(
        self,
        *,
        project_id: str,
        keyword: str,
        insert_text: str,
        sort_order: int = 100,
        enabled: bool = True,
    ) -> StoredStoryLorebook:
        if not keyword.strip():
            raise ValueError("keyword cannot be empty")
        if not insert_text.strip():
            raise ValueError("insert_text cannot be empty")
        return self._story_repository.create_lorebook(
            project_id=project_id,
            keyword=keyword.strip(),
            insert_text=insert_text.strip(),
            sort_order=sort_order,
            enabled=enabled,
        )

    def list_lorebooks(
        self,
        *,
        project_id: str,
        enabled: bool | None = None,
    ) -> list[StoredStoryLorebook]:
        return self._story_repository.list_lorebooks(project_id=project_id, enabled=enabled)

    def update_lorebook(
        self,
        lorebook_id: str,
        *,
        keyword: str | None = None,
        insert_text: str | None = None,
        sort_order: int | None = None,
        enabled: bool | None = None,
    ) -> StoredStoryLorebook:
        normalized_keyword = None if keyword is None else keyword.strip()
        normalized_insert = None if insert_text is None else insert_text.strip()
        if normalized_keyword is not None and not normalized_keyword:
            raise ValueError("keyword cannot be empty")
        if normalized_insert is not None and not normalized_insert:
            raise ValueError("insert_text cannot be empty")
        return self._story_repository.update_lorebook(
            lorebook_id,
            keyword=normalized_keyword,
            insert_text=normalized_insert,
            sort_order=sort_order,
            enabled=enabled,
        )

    def delete_lorebook(self, lorebook_id: str) -> None:
        self._story_repository.delete_lorebook(lorebook_id)

    def rollback_to_checkpoint(self, *, session_id: str, checkpoint_id: str) -> StoredStorySession:
        session = self._story_repository.rollback_to_checkpoint(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
        )
        self._context_stats_by_session[session_id] = self._compute_context_stats(session_id=session_id)
        return session

    def get_context_stats(self, session_id: str) -> StoryContextStats:
        if session_id in self._context_stats_by_session:
            return self._context_stats_by_session[session_id]
        stats = self._compute_context_stats(session_id=session_id)
        self._context_stats_by_session[session_id] = stats
        return stats

    def continue_story(self, *, session_id: str, message: str) -> StoryContinueResult:
        cleaned = message.strip()
        if not cleaned:
            raise ValueError("message cannot be empty")

        session = self._story_repository.get_session(session_id)
        project = self._story_repository.get_project(session.project_id)
        self._story_repository.append_entry(
            session_id=session_id,
            role="user",
            content=cleaned,
            entry_type="player_input",
        )
        history = self._story_repository.get_history(session_id)
        reply, context_bundle = self._generate_story_reply(
            project=project,
            session=session,
            history=history,
        )
        assistant_entry = self._story_repository.append_entry(
            session_id=session_id,
            role="assistant",
            content=reply,
            entry_type="narrative",
        )

        facts = self._story_repository.list_facts(session_id)
        updated_facts = self._extract_story_facts([cleaned, reply], existing=facts)
        self._story_repository.replace_facts(session_id=session_id, facts=updated_facts)
        updated_summary = self._build_summary(
            session.current_summary,
            f"user: {cleaned}\nassistant: {reply}",
        )
        checkpoint = self._story_repository.create_checkpoint(
            session_id=session_id,
            title=f"Turn {max(1, assistant_entry.sequence // 2)}",
            summary_text=updated_summary,
            current_scene=reply,
            facts_json=json.dumps(updated_facts, ensure_ascii=False),
            last_sequence=assistant_entry.sequence,
        )
        self._story_repository.update_session_state(
            session_id,
            current_summary=updated_summary,
            current_scene=reply,
            active_checkpoint_id=checkpoint.checkpoint_id,
        )
        entry_count = self._story_repository.count_entries(session_id)
        stats = self._compute_context_stats(session_id=session_id)
        self._context_stats_by_session[session_id] = stats
        return StoryContinueResult(
            session_id=session_id,
            reply=reply,
            checkpoint_id=checkpoint.checkpoint_id,
            entry_count=entry_count,
            context_stats=replace(
                stats,
                context_char_budget=context_bundle.stats.context_char_budget,
                lorebook_hit_count=context_bundle.stats.lorebook_hit_count,
                recent_entry_chars=context_bundle.stats.recent_entry_chars,
                recent_entry_count=context_bundle.stats.recent_entry_count,
            ),
        )

    def run_story_action(
        self,
        *,
        session_id: str,
        action_type: str,
        selected_text: str,
        style: str | None = None,
        shot: str | None = None,
        voice: str | None = None,
    ) -> StoryAigcActionPublic:
        session = self._story_repository.get_session(session_id)
        normalized_action = action_type.strip().lower()
        text = selected_text.strip()
        if not text:
            raise ValueError("selected_text cannot be empty")

        last_narrative = next(
            (
                item
                for item in reversed(self._story_repository.get_history(session_id))
                if item.role == "assistant" and item.entry_type == "narrative"
            ),
            None,
        )
        if last_narrative is None or text not in last_narrative.content:
            raise ValueError("Story AIGC only supports text selected from the latest assistant narrative block.")

        if normalized_action in {"image", "image_prompt", "image_generate"}:
            tool_args = {
                "paragraph": text,
                "style": (style or "cinematic").strip() or "cinematic",
                "shot": (shot or "medium shot").strip() or "medium shot",
            }
            if self._tool_runtime is not None and self._tool_runtime.enabled:
                result = self._tool_runtime.execute_tool(
                    name="build_image_prompt",
                    arguments_json=json.dumps(tool_args, ensure_ascii=False),
                    session_id=session_id,
                )
            else:
                result = {
                    "prompt": (
                        f"{tool_args['style']} illustration, {tool_args['shot']}, focus on: {text[:700]}. "
                        "high detail, coherent lighting, no watermark"
                    ),
                    "negative_prompt": "lowres, blurry, watermark, distorted anatomy, bad hands",
                    "style": tool_args["style"],
                    "shot": tool_args["shot"],
                }
            if normalized_action in {"image", "image_generate"}:
                generated_result: dict[str, object] | None = None
                image_error: str | None = None
                if self._tool_runtime is not None and self._tool_runtime.image_generation_enabled:
                    try:
                        generated_result = self._tool_runtime.execute_tool(
                            name="generate_image",
                            arguments_json=json.dumps(
                                {
                                    "prompt": str(result.get("prompt", "")),
                                    "negative_prompt": str(result.get("negative_prompt", "")),
                                },
                                ensure_ascii=False,
                            ),
                            session_id=session_id,
                        )
                    except Exception as exc:
                        image_error = str(exc)
                if generated_result is not None:
                    result = {"prompt_payload": result, "image_result": generated_result}
                    normalized_action = "image_generate"
                else:
                    if image_error:
                        result = {**result, "image_error": image_error}
                    normalized_action = "image_prompt"
            else:
                normalized_action = "image_prompt"
        elif normalized_action in {"audio", "audio_plan", "tts"}:
            chosen_voice = (voice or "neutral_female").strip() or "neutral_female"
            result = {
                "voice": chosen_voice,
                "script": text[:1600],
                "emotion": "immersive",
                "pace": "medium",
                "format": "mp3",
                "project_id": session.project_id,
            }
            normalized_action = "audio_plan"
        else:
            raise ValueError("action_type must be one of: image_prompt, image_generate, audio_plan")

        record = self._story_repository.create_action(
            session_id=session_id,
            action_type=normalized_action,
            selected_text=text,
            result_payload_json=json.dumps(result, ensure_ascii=False),
        )
        return self._to_story_action_public(record)

    def list_story_actions(
        self,
        *,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StoryAigcActionPublic]:
        records = self._story_repository.list_actions(
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
        return [self._to_story_action_public(item) for item in records]

    def _generate_story_reply(
        self,
        *,
        project: StoredStoryProject,
        session: StoredStorySession,
        history: list[StoredStoryEntry],
    ) -> tuple[str, StoryContextBundle]:
        context_bundle = self._build_story_context_bundle(
            project=project,
            session=session,
            history=history,
        )
        if self._app_settings_service is not None:
            mode = self._app_settings_service.get_routing_mode()
            if mode == "byok":
                try:
                    config = self._app_settings_service.get_byok_runtime_config()
                    return ChatService._call_openai_compatible_chat_completion(
                        endpoint=f"{config.base_url.rstrip('/')}/chat/completions",
                        api_key=config.api_key,
                        model=config.model,
                        messages=context_bundle.messages,
                        timeout_seconds=45.0,
                    ), context_bundle
                except Exception:
                    pass

        endpoint_reply = self._generate_story_endpoint_reply(messages=context_bundle.messages)
        if endpoint_reply is not None:
            return endpoint_reply, context_bundle

        return self._generate_story_local_reply(project=project, history=history), context_bundle

    def _generate_story_endpoint_reply(self, *, messages: list[dict[str, object]]) -> str | None:
        if self._model_endpoint_service is None:
            return None
        for endpoint in self._select_story_endpoint_candidates():
            try:
                return ChatService._call_openai_compatible_chat_completion(
                    endpoint=f"{endpoint.base_url.rstrip('/')}/chat/completions",
                    api_key=endpoint.api_key,
                    model=endpoint.model,
                    messages=messages,
                    timeout_seconds=45.0,
                )
            except Exception:
                continue
        return None

    def _select_story_endpoint_candidates(self) -> list[ModelEndpointRuntime]:
        if self._model_endpoint_service is None:
            return []
        endpoints = self._model_endpoint_service.list_runtime_endpoints()
        if not endpoints:
            return []
        preferred_endpoint_id = None
        if self._app_settings_service is not None:
            preferred_endpoint_id = self._app_settings_service.get_generation_task_bindings().get(
                "story_continue"
            )
        ordered = sorted(
            endpoints,
            key=lambda item: (
                1 if item.is_fallback else 0,
                item.priority,
                item.name.lower(),
            ),
        )
        if preferred_endpoint_id is None:
            return ordered
        preferred = next((item for item in ordered if item.endpoint_id == preferred_endpoint_id), None)
        if preferred is None:
            return ordered
        return [preferred, *[item for item in ordered if item.endpoint_id != preferred_endpoint_id]]

    def _build_story_context_bundle(
        self,
        *,
        project: StoredStoryProject,
        session: StoredStorySession,
        history: list[StoredStoryEntry],
    ) -> StoryContextBundle:
        facts = self._story_repository.list_facts(session.session_id)
        checkpoints = self._story_repository.list_checkpoints(session_id=session.session_id, limit=50, offset=0)
        latest_user_message = next((item.content for item in reversed(history) if item.role == "user"), "")
        checkpoint_summary = ""
        if session.active_checkpoint_id:
            try:
                checkpoint = self._story_repository.get_checkpoint(session.active_checkpoint_id)
                checkpoint_summary = checkpoint.summary_text.strip()
            except StoryCheckpointNotFoundError:
                checkpoint_summary = ""
        lorebooks = self._story_repository.find_matching_lorebooks(
            project_id=project.project_id,
            message="\n".join(
                part for part in [latest_user_message, session.current_scene, session.current_summary] if part
            ),
            max_items=6,
        )
        lore_context = self._compose_budgeted_lorebook_context(lorebooks)
        fact_lines = self._compose_budgeted_fact_context(facts)
        recent_history = self._trim_recent_entries(history)
        system_sections = [
            "You are an interactive fiction narrator.",
            "Continue the story in immersive prose and respond directly to the player's latest input.",
            "Advance the scene coherently, preserve continuity, and avoid bullet lists unless explicitly requested.",
            f"Story title: {self._truncate(project.title, 200)}",
            f"Premise: {self._truncate(project.premise, 1500)}",
        ]
        if project.system_prompt.strip():
            system_sections.append(
                f"Additional instruction: {self._truncate(project.system_prompt.strip(), 1200)}"
            )
        if session.current_summary.strip():
            system_sections.append(
                f"Story summary:\n{self._truncate(session.current_summary.strip(), self._SUMMARY_MAX_CHARS)}"
            )
        if checkpoint_summary:
            system_sections.append(
                "Active checkpoint summary:\n"
                f"{self._truncate(checkpoint_summary, self._CHECKPOINT_SUMMARY_MAX_CHARS)}"
            )
        if lore_context:
            system_sections.append(f"Matched story lorebook:\n{lore_context}")
        if fact_lines:
            system_sections.append(f"Established facts:\n{fact_lines}")
        system_prompt = "\n\n".join(section for section in system_sections if section.strip())
        messages: list[dict[str, object]] = [{"role": "system", "content": system_prompt}]
        for item in recent_history:
            if item.role not in {"user", "assistant"}:
                continue
            messages.append({"role": item.role, "content": item.content})
        stats = StoryContextStats(
            session_id=session.session_id,
            context_char_budget=self._CONTEXT_CHAR_BUDGET,
            summary_chars=len(session.current_summary),
            fact_count=len(facts),
            lorebook_hit_count=len(lorebooks),
            recent_entry_chars=sum(len(item.content) for item in recent_history),
            recent_entry_count=len(recent_history),
            checkpoint_count=len(checkpoints),
            updated_at=datetime.now(timezone.utc),
        )
        return StoryContextBundle(messages=messages, stats=stats)

    def _generate_story_local_reply(
        self,
        *,
        project: StoredStoryProject,
        history: list[StoredStoryEntry],
    ) -> str:
        latest_user = next((item.content for item in reversed(history) if item.role == "user"), "")
        scene_seed = project.opening_scene.strip() or project.premise.strip()
        return (
            f"{scene_seed[:600]}\n\n"
            f"你刚刚的行动是：{latest_user[:800]}。\n"
            "场景因此继续推进：周围环境给出了新的反馈，人物关系与局势开始发生细微变化。"
            "接下来你可以继续推动局面，或追问眼前最异常的细节。"
        ).strip()

    def _compute_context_stats(self, *, session_id: str) -> StoryContextStats:
        session = self._story_repository.get_session(session_id)
        history = self._story_repository.get_history(session_id)
        facts = self._story_repository.list_facts(session_id)
        checkpoints = self._story_repository.list_checkpoints(session_id=session_id, limit=100, offset=0)
        lorebooks = self._story_repository.find_matching_lorebooks(
            project_id=session.project_id,
            message="\n".join(
                [
                    session.current_summary,
                    session.current_scene,
                    next((item.content for item in reversed(history) if item.role == "user"), ""),
                ]
            ),
            max_items=6,
        )
        recent_history = self._trim_recent_entries(history)
        recent_chars = sum(len(item.content) for item in recent_history)
        return StoryContextStats(
            session_id=session_id,
            context_char_budget=self._CONTEXT_CHAR_BUDGET,
            summary_chars=len(session.current_summary),
            fact_count=len(facts),
            lorebook_hit_count=len(lorebooks),
            recent_entry_chars=recent_chars,
            recent_entry_count=len(recent_history),
            checkpoint_count=len(checkpoints),
            updated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _build_summary(previous: str, segment: str) -> str:
        merged = _merge_summary_locally(previous, segment)
        if len(merged) <= 4000:
            return merged
        return merged[:1800] + "\n...\n" + merged[-1800:]

    @staticmethod
    def _extract_story_facts(
        snippets: list[str],
        *,
        existing: list[StoredStoryFact] | None = None,
    ) -> list[str]:
        facts: list[str] = []
        seen: set[str] = set()
        if existing:
            for item in existing[-8:]:
                text = item.fact_text.strip()
                if text and text not in seen:
                    seen.add(text)
                    facts.append(text)
        for snippet in snippets:
            raw_lines = re.split(r"[\n。！？!?]+", snippet)
            for raw in raw_lines:
                text = raw.strip()
                if len(text) < 8:
                    continue
                normalized = text[:180]
                if normalized in seen:
                    continue
                seen.add(normalized)
                facts.append(normalized)
                if len(facts) >= 12:
                    return facts[-12:]
        return facts[-12:]

    def _compose_budgeted_lorebook_context(self, lorebooks: list[StoredStoryLorebook]) -> str:
        chunks: list[str] = []
        total = 0
        for item in lorebooks:
            chunk = f"[{item.keyword}] {item.insert_text.strip()}"
            if not chunk.strip():
                continue
            remaining = self._LOREBOOK_TOTAL_MAX_CHARS - total
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                chunk = chunk[:remaining]
            chunks.append(chunk)
            total += len(chunk)
        return "\n".join(chunks)

    def _compose_budgeted_fact_context(self, facts: list[StoredStoryFact]) -> str:
        chunks: list[str] = []
        total = 0
        for item in facts[-12:]:
            chunk = f"- {item.fact_text.strip()}"
            if not chunk.strip():
                continue
            remaining = self._FACTS_TOTAL_MAX_CHARS - total
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                chunk = chunk[:remaining]
            chunks.append(chunk)
            total += len(chunk)
        return "\n".join(chunks)

    def _trim_recent_entries(self, history: list[StoredStoryEntry]) -> list[StoredStoryEntry]:
        recent: list[StoredStoryEntry] = []
        total = 0
        for item in reversed(history):
            if item.role not in {"user", "assistant"}:
                continue
            length = len(item.content)
            if recent and total + length > self._RECENT_TOTAL_MAX_CHARS:
                break
            if not recent and length > self._RECENT_TOTAL_MAX_CHARS:
                truncated = StoredStoryEntry(
                    entry_id=item.entry_id,
                    session_id=item.session_id,
                    role=item.role,
                    content=item.content[-self._RECENT_TOTAL_MAX_CHARS :],
                    entry_type=item.entry_type,
                    sequence=item.sequence,
                    created_at=item.created_at,
                )
                recent.append(truncated)
                break
            recent.append(item)
            total += length
            if len(recent) >= 10:
                break
        recent.reverse()
        return recent

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        cleaned = text.strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit]

    @staticmethod
    def _to_story_action_public(record: StoredStoryAction) -> StoryAigcActionPublic:
        try:
            parsed = json.loads(record.result_payload_json)
            result = parsed if isinstance(parsed, dict) else {}
        except Exception:
            result = {}
        return StoryAigcActionPublic(
            action_id=record.action_id,
            session_id=record.session_id,
            action_type=record.action_type,
            selected_text=record.selected_text,
            result=result,
            created_at=record.created_at,
        )
