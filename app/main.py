from pathlib import Path
import json
import sys
import os
import time
from typing import Any, TypeVar

from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from app.schemas import (
    AppSettingsResponse,
    AppSettingsUpdateRequest,
    AssetResponse,
    CharacterDraftApplyRequest,
    CharacterDraftApplyResponse,
    CharacterDraftPatchRequest,
    CharacterDraftPayloadResponse,
    CharacterDraftResponse,
    CharacterCreateRequest,
    CharacterImportResponse,
    CharacterResponse,
    CharacterUpdateRequest,
    ChatAigcActionRequest,
    ChatAigcActionResponse,
    ChatContextStatsResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatSessionSummaryResponse,
    ChatStartResponse,
    GenerationArtifactResponse,
    GenerationEventResponse,
    GenerationJobCreateRequest,
    GenerationJobRerunRequest,
    GenerationJobResponse,
    GenerationTaskResponse,
    HistoryResponse,
    LorebookCreateRequest,
    LorebookResponse,
    LorebookUpdateRequest,
    ModelEndpointCreateRequest,
    ModelEndpointHealthResponse,
    ModelEndpointResponse,
    ModelEndpointUpdateRequest,
    QuotaStatusResponse,
    TrialProxyConfigResponse,
    TrialProxyConfigUpdateRequest,
    TrialProxyHealthResponse,
    TrialConsumeRequest,
    TrialProxyStatusResponse,
    WizardCharacterDraftResponse,
    WizardGenerateRequest,
    WizardGenerateResponse,
)
from app.agent_runtime import ChatRagRuntime, TavilySearchClient, ToolCallRuntime
from app.packaging import CharacterPackageError, CharacterPackageService
from app.quota import DailyQuotaLimiter, QuotaExceededError
from app.repositories import (
    UNSET,
    AssetNotFoundError,
    CharacterDraftNotFoundError,
    DraftVersionConflictError,
    GenerationJobNotFoundError,
    SQLiteAppSettingsRepository,
    CharacterNotFoundError,
    LorebookNotFoundError,
    ModelEndpointNotFoundError,
    SQLiteAssetRepository,
    SQLiteCharacterRepository,
    SQLiteCharacterDraftRepository,
    SQLiteGenerationRepository,
    SQLiteLorebookRepository,
    SQLiteModelEndpointRepository,
    SQLiteSessionRepository,
)
from app.services import (
    AppSettingsService,
    AssetService,
    CharacterDraftService,
    CharacterService,
    ChatService,
    ChatAigcActionPublic,
    ChatContextStats,
    GenerationService,
    GenerationJobStateError,
    InvalidMessageError,
    LorebookService,
    ModelEndpointService,
    RoutingConfigurationError,
    SessionNotFoundError,
    TrialProxyRuntimeConfig,
    TrialService,
    UpstreamModelError,
    WELCOME_MESSAGE,
    WizardService,
)

app = FastAPI(title="Prototype Chat Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_local_env_file(root_dir: Path) -> None:
    env_file = root_dir / ".env.local"
    if not env_file.exists():
        return
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        k = key.strip()
        if not k:
            continue
        v = value.strip().strip("'").strip('"')
        if k not in os.environ:
            os.environ[k] = v


def _bootstrap_private_settings(app_settings_service: AppSettingsService) -> None:
    mode_raw = os.getenv("BYOK_MODE", "").strip().lower()
    mode = mode_raw if mode_raw in {"trial", "byok"} else None
    base_url = os.getenv("BYOK_BASE_URL", "").strip() or None
    model = os.getenv("BYOK_MODEL", "").strip() or None
    api_key = os.getenv("BYOK_API_KEY", "").strip() or None

    if mode is None and base_url is None and model is None and api_key is None:
        return

    try:
        app_settings_service.update_settings(
            mode=mode,
            byok_base_url=base_url,
            byok_model=model,
            byok_api_key=api_key,
        )
    except Exception:
        # Keep startup resilient if private runtime settings are partially configured.
        return


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _parse_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _bootstrap_private_model_endpoints(model_endpoint_service: ModelEndpointService) -> None:
    profiles = [
        ("CORE_ENDPOINT", "core-llm", 10),
        ("CHAT_ENDPOINT", "chat-llm", 20),
        ("WIZARD_ENDPOINT", "wizard-llm", 30),
    ]

    try:
        existing = {
            item.name: item
            for item in model_endpoint_service.list_endpoints(include_disabled=True)
        }
    except Exception:
        return

    for env_prefix, default_name, default_priority in profiles:
        provider = os.getenv(f"{env_prefix}_PROVIDER", "").strip().lower()
        base_url = os.getenv(f"{env_prefix}_BASE_URL", "").strip()
        model = os.getenv(f"{env_prefix}_MODEL", "").strip()
        api_key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
        if not provider or not base_url or not model:
            continue

        name = os.getenv(f"{env_prefix}_NAME", "").strip() or default_name
        enabled = _parse_bool_env(f"{env_prefix}_ENABLED", True)
        priority = _parse_int_env(
            f"{env_prefix}_PRIORITY",
            default=default_priority,
            minimum=0,
            maximum=10000,
        )
        is_fallback = _parse_bool_env(f"{env_prefix}_IS_FALLBACK", False)

        try:
            current = existing.get(name)
            if current is None:
                created = model_endpoint_service.create_endpoint(
                    provider=provider,
                    name=name,
                    base_url=base_url,
                    model=model,
                    api_key=api_key or None,
                    enabled=enabled,
                    priority=priority,
                    is_fallback=is_fallback,
                )
                existing[name] = created
            else:
                model_endpoint_service.update_endpoint(
                    current.endpoint_id,
                    provider=provider,
                    base_url=base_url,
                    model=model,
                    api_key=(api_key or UNSET),
                    enabled=enabled,
                    priority=priority,
                    is_fallback=is_fallback,
                )
        except Exception:
            continue


base_dir = Path(__file__).resolve().parent.parent
_load_local_env_file(base_dir)
static_dir = base_dir / "static"
data_dir = base_dir / "data"
assets_dir = data_dir / "assets"
chat_db_path = data_dir / "chat.db"
quota_db_path = data_dir / "quota.db"
static_dir.mkdir(parents=True, exist_ok=True)
data_dir.mkdir(parents=True, exist_ok=True)
assets_dir.mkdir(parents=True, exist_ok=True)

session_repository = SQLiteSessionRepository(chat_db_path)
character_repository = SQLiteCharacterRepository(chat_db_path)
character_draft_repository = SQLiteCharacterDraftRepository(chat_db_path)
lorebook_repository = SQLiteLorebookRepository(chat_db_path)
asset_repository = SQLiteAssetRepository(chat_db_path)
app_settings_repository = SQLiteAppSettingsRepository(chat_db_path)
model_endpoint_repository = SQLiteModelEndpointRepository(chat_db_path)
generation_repository = SQLiteGenerationRepository(chat_db_path)
app_settings_service = AppSettingsService(app_settings_repository)
_bootstrap_private_settings(app_settings_service)
model_endpoint_service = ModelEndpointService(model_endpoint_repository)
_bootstrap_private_model_endpoints(model_endpoint_service)
rag_runtime = ChatRagRuntime(chat_db_path)
search_client = TavilySearchClient()
tool_runtime = ToolCallRuntime(rag_runtime=rag_runtime, search_client=search_client)
wizard_service = WizardService(
    app_settings_service,
    search_client=search_client,
    model_endpoint_service=model_endpoint_service,
)
generation_service = GenerationService(
    generation_repository=generation_repository,
    wizard_service=wizard_service,
    model_endpoint_service=model_endpoint_service,
    app_settings_service=app_settings_service,
)
chat_service = ChatService(
    session_repository,
    character_repository=character_repository,
    lorebook_repository=lorebook_repository,
    app_settings_service=app_settings_service,
    rag_runtime=rag_runtime,
    tool_runtime=tool_runtime,
    model_endpoint_service=model_endpoint_service,
)
character_service = CharacterService(character_repository)
character_draft_service = CharacterDraftService(
    character_repository=character_repository,
    draft_repository=character_draft_repository,
)
lorebook_service = LorebookService(lorebook_repository)
asset_service = AssetService(
    asset_repository,
    asset_dir=assets_dir,
    public_url_prefix="/assets",
)
character_package_service = CharacterPackageService(
    character_repository=character_repository,
    lorebook_repository=lorebook_repository,
    asset_repository=asset_repository,
    asset_dir=assets_dir,
)
trial_service = TrialService(
    quota_limiter=DailyQuotaLimiter(quota_db_path, daily_limit=20),
    app_settings_service=app_settings_service,
)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/")
def index() -> FileResponse:
    index_file = static_dir / "index.html"
    if not index_file.exists():
        return Response(
            content=json.dumps(
                {"status": "ok", "message": "static/index.html not found"},
                ensure_ascii=False,
            ),
            media_type="application/json",
        )
    return FileResponse(index_file)


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


def _source_to_dict(source: Any) -> dict[str, Any]:
    if isinstance(source, dict):
        return dict(source)
    if hasattr(source, "__dict__"):
        return dict(vars(source))
    raise TypeError(f"Unsupported source type for response mapping: {type(source)!r}")


def _to_response(
    response_model: type[ResponseModelT],
    source: Any,
    *,
    extra: dict[str, Any] | None = None,
) -> ResponseModelT:
    payload = _source_to_dict(source)
    if extra:
        payload.update(extra)
    return response_model.model_validate(payload)


def _app_settings_to_response(settings) -> AppSettingsResponse:
    return _to_response(AppSettingsResponse, settings)


def _model_endpoint_to_response(endpoint) -> ModelEndpointResponse:
    return _to_response(ModelEndpointResponse, endpoint)


def _generation_job_to_response(job) -> GenerationJobResponse:
    return _to_response(GenerationJobResponse, job)


def _generation_task_to_response(task) -> GenerationTaskResponse:
    return _to_response(GenerationTaskResponse, task)


def _generation_artifact_to_response(artifact) -> GenerationArtifactResponse:
    return _to_response(GenerationArtifactResponse, artifact)


def _generation_event_to_response(event) -> GenerationEventResponse:
    return _to_response(GenerationEventResponse, event)


def _model_endpoint_health_to_response(health) -> ModelEndpointHealthResponse:
    return _to_response(ModelEndpointHealthResponse, health)


@app.get("/api/settings", response_model=AppSettingsResponse)
def get_app_settings() -> AppSettingsResponse:
    settings = app_settings_service.get_public_settings()
    return _app_settings_to_response(settings)


@app.put("/api/settings", response_model=AppSettingsResponse)
def update_app_settings(payload: AppSettingsUpdateRequest) -> AppSettingsResponse:
    try:
        settings = app_settings_service.update_settings(
            mode=payload.mode,
            byok_base_url=payload.byok_base_url,
            byok_model=payload.byok_model,
            byok_api_key=payload.byok_api_key,
            task_endpoint_bindings=payload.task_endpoint_bindings,
        )
    except RoutingConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _app_settings_to_response(settings)


@app.post("/api/model-endpoints", response_model=ModelEndpointResponse)
def create_model_endpoint(payload: ModelEndpointCreateRequest) -> ModelEndpointResponse:
    try:
        endpoint = model_endpoint_service.create_endpoint(
            provider=payload.provider,
            name=payload.name,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            enabled=payload.enabled,
            priority=payload.priority,
            is_fallback=payload.is_fallback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _model_endpoint_to_response(endpoint)


@app.get("/api/model-endpoints", response_model=list[ModelEndpointResponse])
def list_model_endpoints(
    include_disabled: bool = Query(default=True),
) -> list[ModelEndpointResponse]:
    endpoints = model_endpoint_service.list_endpoints(include_disabled=include_disabled)
    return [_model_endpoint_to_response(item) for item in endpoints]


@app.get(
    "/api/model-endpoints/health",
    response_model=list[ModelEndpointHealthResponse],
)
def list_model_endpoint_health(
    include_disabled: bool = Query(default=False),
    auto_disable_unhealthy: bool = Query(default=False),
) -> list[ModelEndpointHealthResponse]:
    items = model_endpoint_service.list_endpoint_healths(
        include_disabled=include_disabled,
        auto_disable_unhealthy=auto_disable_unhealthy,
    )
    return [_model_endpoint_health_to_response(item) for item in items]


@app.get("/api/model-endpoints/{endpoint_id}", response_model=ModelEndpointResponse)
def get_model_endpoint(endpoint_id: str) -> ModelEndpointResponse:
    try:
        endpoint = model_endpoint_service.get_endpoint(endpoint_id)
    except ModelEndpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _model_endpoint_to_response(endpoint)


@app.put("/api/model-endpoints/{endpoint_id}", response_model=ModelEndpointResponse)
def update_model_endpoint(
    endpoint_id: str,
    payload: ModelEndpointUpdateRequest,
) -> ModelEndpointResponse:
    updates = payload.model_dump(exclude_unset=True)
    try:
        endpoint = model_endpoint_service.update_endpoint(
            endpoint_id,
            provider=updates.get("provider"),
            name=updates.get("name"),
            base_url=updates.get("base_url"),
            model=updates.get("model"),
            api_key=updates["api_key"] if "api_key" in updates else UNSET,
            enabled=updates.get("enabled"),
            priority=updates.get("priority"),
            is_fallback=updates.get("is_fallback"),
        )
    except ModelEndpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _model_endpoint_to_response(endpoint)


@app.delete("/api/model-endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model_endpoint(endpoint_id: str) -> Response:
    try:
        model_endpoint_service.delete_endpoint(endpoint_id)
    except ModelEndpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/api/model-endpoints/{endpoint_id}/health",
    response_model=ModelEndpointHealthResponse,
)
def get_model_endpoint_health(endpoint_id: str) -> ModelEndpointHealthResponse:
    try:
        health = model_endpoint_service.check_endpoint_health(endpoint_id)
    except ModelEndpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _model_endpoint_health_to_response(health)


@app.post("/api/generation/jobs", response_model=GenerationJobResponse)
def create_generation_job(
    payload: GenerationJobCreateRequest,
    background_tasks: BackgroundTasks,
) -> GenerationJobResponse:
    try:
        if payload.run_async:
            job, include_illustration_prompt, include_audio_plan = (
                generation_service.submit_job_async(
                    user_input=payload.user_input,
                    include_illustration_prompt=payload.include_illustration_prompt,
                    include_audio_plan=payload.include_audio_plan,
                )
            )
            background_tasks.add_task(
                generation_service.execute_job,
                job.job_id,
                include_illustration_prompt=include_illustration_prompt,
                include_audio_plan=include_audio_plan,
            )
        else:
            job = generation_service.submit_job(
                user_input=payload.user_input,
                include_illustration_prompt=payload.include_illustration_prompt,
                include_audio_plan=payload.include_audio_plan,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GenerationJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _generation_job_to_response(job)


@app.get("/api/generation/jobs", response_model=list[GenerationJobResponse])
def list_generation_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[GenerationJobResponse]:
    jobs = generation_service.list_jobs(limit=limit, offset=offset)
    return [_generation_job_to_response(item) for item in jobs]


@app.get("/api/generation/jobs/{job_id}", response_model=GenerationJobResponse)
def get_generation_job(job_id: str) -> GenerationJobResponse:
    try:
        job = generation_service.get_job(job_id)
    except GenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _generation_job_to_response(job)


@app.post("/api/generation/jobs/{job_id}/cancel", response_model=GenerationJobResponse)
def cancel_generation_job(job_id: str) -> GenerationJobResponse:
    try:
        job = generation_service.cancel_job(job_id)
    except GenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GenerationJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _generation_job_to_response(job)


@app.post("/api/generation/jobs/{job_id}/rerun", response_model=GenerationJobResponse)
def rerun_generation_job(
    job_id: str,
    payload: GenerationJobRerunRequest,
    background_tasks: BackgroundTasks,
) -> GenerationJobResponse:
    try:
        (
            user_input,
            include_illustration_prompt,
            include_audio_plan,
        ) = generation_service.resolve_rerun_payload(
            job_id,
            user_input=payload.user_input,
            include_illustration_prompt=payload.include_illustration_prompt,
            include_audio_plan=payload.include_audio_plan,
        )

        if payload.run_async:
            job, include_illustration_prompt, include_audio_plan = (
                generation_service.submit_job_async(
                    user_input=user_input,
                    include_illustration_prompt=include_illustration_prompt,
                    include_audio_plan=include_audio_plan,
                )
            )
            background_tasks.add_task(
                generation_service.execute_job,
                job.job_id,
                include_illustration_prompt=include_illustration_prompt,
                include_audio_plan=include_audio_plan,
            )
        else:
            job = generation_service.submit_job(
                user_input=user_input,
                include_illustration_prompt=include_illustration_prompt,
                include_audio_plan=include_audio_plan,
            )
    except GenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GenerationJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _generation_job_to_response(job)


@app.get("/api/generation/jobs/{job_id}/tasks", response_model=list[GenerationTaskResponse])
def list_generation_job_tasks(
    job_id: str,
    status: str | None = None,
    task_type: str | None = None,
    error_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[GenerationTaskResponse]:
    try:
        tasks = generation_service.list_tasks(
            job_id=job_id,
            status=status,
            task_type=task_type,
            error_type=error_type,
            limit=limit,
            offset=offset,
        )
    except GenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_generation_task_to_response(item) for item in tasks]


@app.get(
    "/api/generation/jobs/{job_id}/artifacts",
    response_model=list[GenerationArtifactResponse],
)
def list_generation_job_artifacts(job_id: str) -> list[GenerationArtifactResponse]:
    try:
        artifacts = generation_service.list_artifacts(job_id=job_id)
    except GenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_generation_artifact_to_response(item) for item in artifacts]


@app.get("/api/generation/jobs/{job_id}/events", response_model=list[GenerationEventResponse])
def list_generation_job_events(
    job_id: str,
    event_type: str | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> list[GenerationEventResponse]:
    try:
        events = generation_service.list_events(
            job_id=job_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
    except GenerationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_generation_event_to_response(item) for item in events]


def _character_to_response(character) -> CharacterResponse:
    return _to_response(CharacterResponse, character)


def _lorebook_to_response(lorebook) -> LorebookResponse:
    return _to_response(LorebookResponse, lorebook)


def _session_to_response(session) -> ChatSessionSummaryResponse:
    return _to_response(ChatSessionSummaryResponse, session)


def _chat_context_stats_to_response(stats: ChatContextStats) -> ChatContextStatsResponse:
    return _to_response(ChatContextStatsResponse, stats)


def _chat_action_to_response(action: ChatAigcActionPublic) -> ChatAigcActionResponse:
    return _to_response(ChatAigcActionResponse, action)


def _asset_to_response(asset) -> AssetResponse:
    return _to_response(
        AssetResponse,
        asset,
        extra={"url": asset_service.build_asset_url(asset.stored_filename)},
    )


def _wizard_result_to_response(result) -> WizardGenerateResponse:
    draft = _to_response(WizardCharacterDraftResponse, result.draft)
    return _to_response(
        WizardGenerateResponse,
        result,
        extra={"draft": draft},
    )


def _character_draft_to_response(draft) -> CharacterDraftResponse:
    payload = CharacterDraftPayloadResponse(**draft.payload)
    return CharacterDraftResponse(
        character_id=draft.character_id,
        payload=payload,
        version=draft.version,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _trial_proxy_config_to_response(
    config: TrialProxyRuntimeConfig,
) -> TrialProxyConfigResponse:
    return _to_response(
        TrialProxyConfigResponse,
        config,
        extra={"has_api_key": bool(config.api_key)},
    )


@app.post("/api/characters", response_model=CharacterResponse)
def create_character(payload: CharacterCreateRequest) -> CharacterResponse:
    character = character_service.create_character(
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        first_message=payload.first_message,
        avatar_url=payload.avatar_url,
    )
    return _character_to_response(character)


@app.post("/api/assets", response_model=AssetResponse)
async def upload_asset(file: UploadFile = File(...)) -> AssetResponse:
    try:
        payload = await file.read()
        asset = asset_service.create_asset(
            original_filename=file.filename or "upload.bin",
            content_type=file.content_type,
            data=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _asset_to_response(asset)


@app.get("/api/assets", response_model=list[AssetResponse])
def list_assets(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AssetResponse]:
    assets = asset_service.list_assets(limit=limit, offset=offset)
    return [_asset_to_response(item) for item in assets]


@app.get("/api/assets/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: str) -> AssetResponse:
    try:
        asset = asset_service.get_asset(asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _asset_to_response(asset)


@app.delete("/api/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: str) -> Response:
    try:
        asset_service.delete_asset(asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/wizard/generate-character", response_model=WizardGenerateResponse)
def generate_character(payload: WizardGenerateRequest) -> WizardGenerateResponse:
    try:
        result = wizard_service.generate_character(payload.user_input)
    except RoutingConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UpstreamModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _wizard_result_to_response(result)


@app.get("/api/characters", response_model=list[CharacterResponse])
def list_characters() -> list[CharacterResponse]:
    return [_character_to_response(c) for c in character_service.list_characters()]


@app.get("/api/characters/{character_id}", response_model=CharacterResponse)
def get_character(character_id: str) -> CharacterResponse:
    try:
        character = character_service.get_character(character_id)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _character_to_response(character)


@app.put("/api/characters/{character_id}", response_model=CharacterResponse)
def update_character(character_id: str, payload: CharacterUpdateRequest) -> CharacterResponse:
    updates = payload.model_dump(exclude_unset=True)
    try:
        character = character_service.update_character(
            character_id=character_id,
            name=updates.get("name"),
            description=updates.get("description"),
            system_prompt=updates.get("system_prompt"),
            first_message=updates.get("first_message"),
            avatar_url=updates["avatar_url"] if "avatar_url" in updates else UNSET,
        )
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _character_to_response(character)


@app.delete("/api/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(character_id: str) -> Response:
    try:
        character_service.delete_character(character_id)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/characters/{character_id}/draft", response_model=CharacterDraftResponse)
def get_character_draft(character_id: str) -> CharacterDraftResponse:
    try:
        draft = character_draft_service.get_draft(character_id)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CharacterDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _character_draft_to_response(draft)


@app.put("/api/characters/{character_id}/draft", response_model=CharacterDraftResponse)
def save_character_draft(
    character_id: str,
    payload: CharacterDraftPatchRequest,
) -> CharacterDraftResponse:
    try:
        draft = character_draft_service.save_draft_patch(
            character_id=character_id,
            patch=payload.patch,
            expected_version=payload.expected_version,
        )
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _character_draft_to_response(draft)


@app.post(
    "/api/characters/{character_id}/draft/apply",
    response_model=CharacterDraftApplyResponse,
)
def apply_character_draft(
    character_id: str,
    payload: CharacterDraftApplyRequest,
) -> CharacterDraftApplyResponse:
    try:
        result = character_draft_service.apply_draft(
            character_id=character_id,
            expected_version=payload.expected_version,
            delete_after_apply=payload.delete_after_apply,
        )
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CharacterDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CharacterDraftApplyResponse(
        character=_character_to_response(result.character),
        applied_version=result.applied_version,
    )


@app.delete(
    "/api/characters/{character_id}/draft",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_character_draft(character_id: str) -> Response:
    try:
        character_draft_service.delete_draft(character_id)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/characters/{character_id}/export")
def export_character_package(character_id: str) -> Response:
    try:
        package_bytes, filename = character_package_service.export_character_package(
            character_id
        )
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=package_bytes,
        media_type="application/x-aichat",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/characters/{character_id}/export/image")
def export_character_png_package(character_id: str) -> Response:
    try:
        package_bytes, filename = character_package_service.export_character_png_package(
            character_id
        )
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=package_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/characters/import", response_model=CharacterImportResponse)
def import_character_package(
    package_payload: bytes = Body(..., media_type="application/octet-stream"),
) -> CharacterImportResponse:
    try:
        result = character_package_service.import_character_package(package_payload)
    except CharacterPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CharacterImportResponse(
        character_id=result.character.character_id,
        imported_lorebooks=result.imported_lorebooks,
        package_version=result.package_version,
    )


@app.post("/api/characters/import/image", response_model=CharacterImportResponse)
def import_character_png_package(
    package_payload: bytes = Body(..., media_type="image/png"),
) -> CharacterImportResponse:
    try:
        result = character_package_service.import_character_png_package(package_payload)
    except CharacterPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CharacterImportResponse(
        character_id=result.character.character_id,
        imported_lorebooks=result.imported_lorebooks,
        package_version=result.package_version,
    )


@app.post("/api/lorebooks", response_model=LorebookResponse)
def create_lorebook(payload: LorebookCreateRequest) -> LorebookResponse:
    lorebook = lorebook_service.create_lorebook(
        character_id=payload.character_id,
        keyword=payload.keyword,
        insert_text=payload.insert_text,
        sort_order=payload.sort_order,
        enabled=payload.enabled,
    )
    return _lorebook_to_response(lorebook)


@app.get("/api/lorebooks", response_model=list[LorebookResponse])
def list_lorebooks(
    character_id: str | None = None,
    enabled: bool | None = None,
) -> list[LorebookResponse]:
    lorebooks = lorebook_service.list_lorebooks(
        character_id=character_id,
        enabled=enabled,
    )
    return [_lorebook_to_response(item) for item in lorebooks]


@app.get("/api/lorebooks/{lorebook_id}", response_model=LorebookResponse)
def get_lorebook(lorebook_id: str) -> LorebookResponse:
    try:
        lorebook = lorebook_service.get_lorebook(lorebook_id)
    except LorebookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _lorebook_to_response(lorebook)


@app.put("/api/lorebooks/{lorebook_id}", response_model=LorebookResponse)
def update_lorebook(lorebook_id: str, payload: LorebookUpdateRequest) -> LorebookResponse:
    try:
        lorebook = lorebook_service.update_lorebook(
            lorebook_id=lorebook_id,
            character_id=payload.character_id,
            keyword=payload.keyword,
            insert_text=payload.insert_text,
            sort_order=payload.sort_order,
            enabled=payload.enabled,
        )
    except LorebookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _lorebook_to_response(lorebook)


@app.delete("/api/lorebooks/{lorebook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lorebook(lorebook_id: str) -> Response:
    try:
        lorebook_service.delete_lorebook(lorebook_id)
    except LorebookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/chat/start", response_model=ChatStartResponse)
def start_chat(character_id: str | None = None) -> ChatStartResponse:
    welcome_message = None
    if character_id:
        try:
            character = character_service.get_character(character_id)
        except CharacterNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        welcome_message = (
            character.first_message.strip() if character.first_message else None
        )

    session_id, welcome = chat_service.create_session(
        welcome_message=welcome_message or WELCOME_MESSAGE,
        character_id=character_id,
    )
    return ChatStartResponse(
        session_id=session_id,
        welcome_message=welcome,
        character_id=character_id,
    )


def _prevalidate_chat_request(payload: ChatRequest) -> None:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    try:
        chat_service.get_session_summary(payload.session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chat/message", response_model=ChatResponse)
def send_message(payload: ChatRequest) -> ChatResponse:
    quota_response = None
    _prevalidate_chat_request(payload)
    try:
        if payload.device_id:
            quota_status = trial_service.consume_quota(payload.device_id, amount=1)
            quota_response = QuotaStatusResponse(**quota_status.__dict__)
        reply, history_count = chat_service.add_user_message(
            payload.session_id,
            payload.message,
            device_id=payload.device_id,
        )
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RoutingConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UpstreamModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidMessageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatResponse(
        session_id=payload.session_id,
        reply=reply,
        history_count=history_count,
        quota=quota_response,
    )


@app.post("/api/chat/message/stream")
def stream_message(payload: ChatRequest) -> StreamingResponse:
    quota_response = None
    _prevalidate_chat_request(payload)
    try:
        if payload.device_id:
            quota_status = trial_service.consume_quota(payload.device_id, amount=1)
            quota_response = QuotaStatusResponse(**quota_status.__dict__)

        chunk_iterator, finalize = chat_service.start_user_message_stream(
            payload.session_id,
            payload.message,
            device_id=payload.device_id,
        )
        context_stats = chat_service.get_context_stats(payload.session_id)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RoutingConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UpstreamModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidMessageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def format_event(event: str, data: dict) -> str:
        return (
            f"event: {event}\n"
            f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        )

    def event_generator():
        started = time.perf_counter()
        chunks: list[str] = []
        try:
            yield format_event(
                "context",
                _chat_context_stats_to_response(context_stats).model_dump(mode="json"),
            )
            for chunk in chunk_iterator:
                chunks.append(chunk)
                yield format_event("chunk", {"delta": chunk})

            full_reply = "".join(chunks)
            history_count = finalize(full_reply)
            latest_context_stats = chat_service.get_context_stats(payload.session_id)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            done_payload = {
                "session_id": payload.session_id,
                "reply": full_reply,
                "history_count": history_count,
                "context_stats": _chat_context_stats_to_response(
                    latest_context_stats
                ).model_dump(mode="json"),
                "metrics": {
                    "elapsed_ms": elapsed_ms,
                    "chunk_count": len(chunks),
                    "reply_chars": len(full_reply),
                },
                "quota": (
                    quota_response.model_dump()
                    if quota_response is not None
                    else None
                ),
            }
            yield format_event("done", done_payload)
        except Exception as exc:
            yield format_event("error", {"detail": str(exc)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/chat/history/{session_id}", response_model=HistoryResponse)
def get_history(session_id: str) -> HistoryResponse:
    try:
        history = chat_service.get_history(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HistoryResponse(
        session_id=session_id,
        history=[
            ChatMessage(role=item.role, content=item.content, timestamp=item.timestamp)
            for item in history
        ],
    )


@app.get("/api/chat/session/{session_id}", response_model=ChatSessionSummaryResponse)
def get_chat_session(session_id: str) -> ChatSessionSummaryResponse:
    try:
        session = chat_service.get_session_summary(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _session_to_response(session)


@app.get("/api/chat/sessions", response_model=list[ChatSessionSummaryResponse])
def list_chat_sessions(
    character_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ChatSessionSummaryResponse]:
    sessions = chat_service.list_sessions(
        character_id=character_id,
        limit=limit,
        offset=offset,
    )
    return [_session_to_response(item) for item in sessions]


@app.get("/api/chat/context/{session_id}/stats", response_model=ChatContextStatsResponse)
def get_chat_context_stats(session_id: str) -> ChatContextStatsResponse:
    try:
        stats = chat_service.get_context_stats(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _chat_context_stats_to_response(stats)


@app.post("/api/chat/actions", response_model=ChatAigcActionResponse)
def create_chat_action(payload: ChatAigcActionRequest) -> ChatAigcActionResponse:
    try:
        action = chat_service.run_chat_action(
            session_id=payload.session_id,
            action_type=payload.action_type,
            selected_text=payload.selected_text,
            style=payload.style,
            shot=payload.shot,
            voice=payload.voice,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _chat_action_to_response(action)


@app.get("/api/chat/actions/{session_id}", response_model=list[ChatAigcActionResponse])
def list_chat_actions(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ChatAigcActionResponse]:
    try:
        items = chat_service.list_chat_actions(
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_chat_action_to_response(item) for item in items]


@app.get("/api/trial/quota/{device_id}", response_model=QuotaStatusResponse)
def get_trial_quota(device_id: str) -> QuotaStatusResponse:
    try:
        status = trial_service.get_quota(device_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return QuotaStatusResponse(**status.__dict__)


@app.post("/api/trial/consume", response_model=QuotaStatusResponse)
def consume_trial_quota(payload: TrialConsumeRequest) -> QuotaStatusResponse:
    try:
        status = trial_service.consume_quota(payload.device_id, payload.amount)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return QuotaStatusResponse(**status.__dict__)


@app.get("/api/trial/proxy/status", response_model=TrialProxyStatusResponse)
def get_trial_proxy_status() -> TrialProxyStatusResponse:
    status_obj = trial_service.get_proxy_status()
    return TrialProxyStatusResponse(**status_obj.__dict__)


@app.get("/api/trial/proxy/health", response_model=TrialProxyHealthResponse)
def get_trial_proxy_health() -> TrialProxyHealthResponse:
    health = trial_service.check_proxy_health()
    return TrialProxyHealthResponse(**health.__dict__)


@app.get("/api/trial/proxy/config", response_model=TrialProxyConfigResponse)
def get_trial_proxy_config() -> TrialProxyConfigResponse:
    config = app_settings_service.get_trial_proxy_runtime_config()
    return _trial_proxy_config_to_response(config)


@app.put("/api/trial/proxy/config", response_model=TrialProxyConfigResponse)
def update_trial_proxy_config(
    payload: TrialProxyConfigUpdateRequest,
) -> TrialProxyConfigResponse:
    try:
        trial_service.update_proxy_settings(
            mode=payload.mode,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            timeout_seconds=payload.timeout_seconds,
            system_prompt=payload.system_prompt,
        )
    except RoutingConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    config = app_settings_service.get_trial_proxy_runtime_config()
    return _trial_proxy_config_to_response(config)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
