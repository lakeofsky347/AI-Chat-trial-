from datetime import datetime

from pydantic import BaseModel, Field


class ChatStartResponse(BaseModel):
    session_id: str
    welcome_message: str
    character_id: str | None = None


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=2000)
    device_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: datetime


class QuotaStatusResponse(BaseModel):
    device_id: str
    quota_date: str
    daily_limit: int
    used: int
    remaining: int
    allowed: bool


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    history_count: int
    quota: QuotaStatusResponse | None = None


class HistoryResponse(BaseModel):
    session_id: str
    history: list[ChatMessage]


class ChatSessionSummaryResponse(BaseModel):
    session_id: str
    character_id: str | None
    created_at: datetime
    last_message_at: datetime | None
    message_count: int
    last_message: str | None


class ChatContextStatsResponse(BaseModel):
    session_id: str
    context_char_budget: int
    rag_context_chars: int
    recent_history_chars: int
    recent_message_count: int
    summary_chars: int
    retrieved_count: int
    updated_at: datetime


class ChatAigcActionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    action_type: str = Field(..., min_length=1, max_length=40)
    selected_text: str = Field(..., min_length=1, max_length=8000)
    style: str | None = Field(default=None, max_length=120)
    shot: str | None = Field(default=None, max_length=120)
    voice: str | None = Field(default=None, max_length=120)


class ChatAigcActionResponse(BaseModel):
    action_id: str
    session_id: str
    action_type: str
    selected_text: str
    result: dict[str, object]
    created_at: datetime


class TrialConsumeRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    amount: int = Field(default=1, ge=1, le=20)


class TrialProxyStatusResponse(BaseModel):
    mode: str
    enabled: bool
    has_api_key: bool
    base_url: str
    model: str
    timeout_seconds: float


class TrialProxyConfigResponse(BaseModel):
    mode: str
    enabled: bool
    has_api_key: bool
    base_url: str
    model: str
    timeout_seconds: float
    system_prompt: str


class TrialProxyConfigUpdateRequest(BaseModel):
    mode: str | None = Field(default=None)
    base_url: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=4096)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    system_prompt: str | None = Field(default=None, max_length=8000)


class TrialProxyHealthResponse(BaseModel):
    mode: str
    enabled: bool
    base_url: str
    health_url: str
    healthy: bool
    status_code: int | None
    latency_ms: float | None
    detail: str


class AssetResponse(BaseModel):
    asset_id: str
    original_filename: str
    content_type: str
    size_bytes: int
    stored_filename: str
    url: str
    created_at: datetime
    updated_at: datetime


class CharacterCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    system_prompt: str = Field(default="", max_length=8000)
    first_message: str = Field(default="", max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=2048)


class CharacterUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    system_prompt: str | None = Field(default=None, max_length=8000)
    first_message: str | None = Field(default=None, max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=2048)


class CharacterResponse(BaseModel):
    character_id: str
    name: str
    description: str
    system_prompt: str
    first_message: str
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


class CharacterDraftPayloadResponse(BaseModel):
    name: str
    description: str
    system_prompt: str
    first_message: str
    avatar_url: str | None
    advanced: dict[str, object] = Field(default_factory=dict)


class CharacterDraftResponse(BaseModel):
    character_id: str
    payload: CharacterDraftPayloadResponse
    version: int
    created_at: datetime
    updated_at: datetime


class CharacterDraftPatchRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    patch: dict[str, object] = Field(default_factory=dict)


class CharacterDraftApplyRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    delete_after_apply: bool = True


class CharacterDraftApplyResponse(BaseModel):
    character: CharacterResponse
    applied_version: int


class CharacterImportResponse(BaseModel):
    character_id: str
    imported_lorebooks: int
    package_version: int


class AppSettingsResponse(BaseModel):
    mode: str
    byok_base_url: str
    byok_model: str
    has_api_key: bool
    task_endpoint_bindings: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime


class AppSettingsUpdateRequest(BaseModel):
    mode: str | None = Field(default=None)
    byok_base_url: str | None = Field(default=None, max_length=2048)
    byok_model: str | None = Field(default=None, max_length=128)
    byok_api_key: str | None = Field(default=None, max_length=4096)
    task_endpoint_bindings: dict[str, str | None] | None = None


class ModelEndpointCreateRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=80)
    base_url: str = Field(..., min_length=1, max_length=2048)
    model: str = Field(..., min_length=1, max_length=160)
    api_key: str | None = Field(default=None, max_length=4096)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    is_fallback: bool = False


class ModelEndpointUpdateRequest(BaseModel):
    provider: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=160)
    api_key: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    is_fallback: bool | None = None


class ModelEndpointResponse(BaseModel):
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


class ModelEndpointHealthResponse(BaseModel):
    endpoint_id: str
    provider: str
    name: str
    healthy: bool
    status_code: int | None
    latency_ms: float | None
    detail: str


class GenerationJobCreateRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=8000)
    pipeline_type: str = Field(default="roleplay_character", min_length=1, max_length=64)
    apply_mode: str = Field(default="draft_only", min_length=1, max_length=32)
    story_project_id: str | None = Field(default=None, min_length=1, max_length=64)
    story_draft_payload: dict[str, object] | None = None
    include_illustration_prompt: bool = True
    include_audio_plan: bool = False
    run_async: bool = False


class GenerationJobRerunRequest(BaseModel):
    user_input: str | None = Field(default=None, min_length=1, max_length=8000)
    pipeline_type: str | None = Field(default=None, min_length=1, max_length=64)
    apply_mode: str | None = Field(default=None, min_length=1, max_length=32)
    story_project_id: str | None = Field(default=None, min_length=1, max_length=64)
    story_draft_payload: dict[str, object] | None = None
    include_illustration_prompt: bool | None = None
    include_audio_plan: bool | None = None
    run_async: bool = False


class GenerationJobResponse(BaseModel):
    job_id: str
    status: str
    user_input: str
    pipeline_version: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class GenerationTaskResponse(BaseModel):
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


class GenerationArtifactResponse(BaseModel):
    artifact_id: str
    job_id: str
    artifact_type: str
    payload: dict[str, object]
    created_at: datetime
    updated_at: datetime


class GenerationEventResponse(BaseModel):
    event_id: int
    job_id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime


class WizardGenerateRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=4000)


class WizardCharacterDraftResponse(BaseModel):
    name: str
    description: str
    system_prompt: str
    first_message: str


class WizardGenerateResponse(BaseModel):
    draft: WizardCharacterDraftResponse
    route_mode: str
    auto_completed_fields: list[str]
    search_sources: list[dict[str, str]] = Field(default_factory=list)


class LorebookCreateRequest(BaseModel):
    character_id: str | None = Field(default=None, min_length=1, max_length=64)
    keyword: str = Field(..., min_length=1, max_length=120)
    insert_text: str = Field(..., min_length=1, max_length=4000)
    sort_order: int = Field(default=100, ge=0, le=10000)
    enabled: bool = True


class LorebookUpdateRequest(BaseModel):
    character_id: str | None = Field(default=None, min_length=1, max_length=64)
    keyword: str | None = Field(default=None, min_length=1, max_length=120)
    insert_text: str | None = Field(default=None, min_length=1, max_length=4000)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None


class LorebookResponse(BaseModel):
    lorebook_id: str
    character_id: str | None
    keyword: str
    insert_text: str
    sort_order: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class StoryProjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    premise: str = Field(..., min_length=1, max_length=8000)
    opening_scene: str = Field(default="", max_length=8000)
    system_prompt: str = Field(default="", max_length=8000)


class StoryProjectUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    premise: str | None = Field(default=None, min_length=1, max_length=8000)
    opening_scene: str | None = Field(default=None, max_length=8000)
    system_prompt: str | None = Field(default=None, max_length=8000)
    status: str | None = Field(default=None, min_length=1, max_length=32)


class StoryProjectResponse(BaseModel):
    project_id: str
    title: str
    premise: str
    opening_scene: str
    system_prompt: str
    status: str
    created_at: datetime
    updated_at: datetime


class StorySessionResponse(BaseModel):
    session_id: str
    project_id: str
    current_summary: str
    current_scene: str
    active_checkpoint_id: str | None
    created_at: datetime
    updated_at: datetime


class StoryEntryResponse(BaseModel):
    entry_id: str
    session_id: str
    role: str
    content: str
    entry_type: str
    sequence: int
    created_at: datetime


class StoryHistoryResponse(BaseModel):
    session_id: str
    history: list[StoryEntryResponse]


class StoryFactResponse(BaseModel):
    fact_id: str
    session_id: str
    fact_text: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class StoryCheckpointResponse(BaseModel):
    checkpoint_id: str
    session_id: str
    title: str
    summary_text: str
    current_scene: str
    facts: list[str] = Field(default_factory=list)
    last_sequence: int
    created_at: datetime


class StoryLorebookCreateRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)
    insert_text: str = Field(..., min_length=1, max_length=12000)
    sort_order: int = Field(default=100, ge=0, le=10000)
    enabled: bool = True


class StoryLorebookUpdateRequest(BaseModel):
    keyword: str | None = Field(default=None, min_length=1, max_length=200)
    insert_text: str | None = Field(default=None, min_length=1, max_length=12000)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None


class StoryLorebookResponse(BaseModel):
    lorebook_id: str
    project_id: str
    keyword: str
    insert_text: str
    sort_order: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class StoryContinueRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=4000)


class StoryContextStatsResponse(BaseModel):
    session_id: str
    context_char_budget: int
    summary_chars: int
    fact_count: int
    lorebook_hit_count: int
    recent_entry_chars: int
    recent_entry_count: int
    checkpoint_count: int
    updated_at: datetime


class StoryContinueResponse(BaseModel):
    session_id: str
    reply: str
    checkpoint_id: str
    entry_count: int
    context_stats: StoryContextStatsResponse


class StoryAigcActionRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    action_type: str = Field(..., min_length=1, max_length=40)
    selected_text: str = Field(..., min_length=1, max_length=8000)
    style: str | None = Field(default=None, max_length=120)
    shot: str | None = Field(default=None, max_length=120)
    voice: str | None = Field(default=None, max_length=120)


class StoryAigcActionResponse(BaseModel):
    action_id: str
    session_id: str
    action_type: str
    selected_text: str
    result: dict[str, object]
    created_at: datetime
