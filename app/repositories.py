from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Protocol
from uuid import uuid4


UNSET = object()


@dataclass(frozen=True)
class StoredMessage:
    role: str
    content: str
    timestamp: datetime


@dataclass(frozen=True)
class StoredCharacter:
    character_id: str
    name: str
    description: str
    system_prompt: str
    first_message: str
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredSessionSummary:
    session_id: str
    character_id: str | None
    created_at: datetime
    last_message_at: datetime | None
    message_count: int
    last_message: str | None


@dataclass(frozen=True)
class StoredLorebook:
    lorebook_id: str
    character_id: str | None
    keyword: str
    insert_text: str
    sort_order: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredAppSettings:
    mode: str
    byok_base_url: str
    byok_model: str
    byok_api_key_encrypted: str | None
    trial_proxy_mode: str
    trial_proxy_base_url: str
    trial_proxy_model: str
    trial_proxy_api_key_encrypted: str | None
    trial_proxy_timeout_seconds: float
    trial_proxy_system_prompt: str
    generation_task_bindings_json: str
    updated_at: datetime


@dataclass(frozen=True)
class StoredAsset:
    asset_id: str
    original_filename: str
    content_type: str
    size_bytes: int
    stored_filename: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredCharacterDraft:
    character_id: str
    payload_json: str
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredModelEndpoint:
    endpoint_id: str
    provider: str
    name: str
    base_url: str
    model: str
    api_key_encrypted: str | None
    enabled: bool
    priority: int
    is_fallback: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredGenerationJob:
    job_id: str
    status: str
    user_input: str
    pipeline_version: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class StoredGenerationTask:
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
    prompt_payload_json: str
    output_payload_json: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class StoredGenerationArtifact:
    artifact_id: str
    job_id: str
    artifact_type: str
    payload_json: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredGenerationEvent:
    event_id: int
    job_id: str
    event_type: str
    payload_json: str
    created_at: datetime


class CharacterNotFoundError(ValueError):
    pass


class LorebookNotFoundError(ValueError):
    pass


class AssetNotFoundError(ValueError):
    pass


class CharacterDraftNotFoundError(ValueError):
    pass


class DraftVersionConflictError(ValueError):
    pass


class ModelEndpointNotFoundError(ValueError):
    pass


class GenerationJobNotFoundError(ValueError):
    pass


class GenerationTaskNotFoundError(ValueError):
    pass


class SessionRepository(Protocol):
    def create_session(
        self,
        session_id: str,
        welcome_message: str,
        character_id: str | None = None,
    ) -> None:
        ...

    def append_message(self, session_id: str, role: str, content: str) -> None:
        ...

    def get_history(self, session_id: str) -> list[StoredMessage]:
        ...

    def count_messages(self, session_id: str) -> int:
        ...

    def session_exists(self, session_id: str) -> bool:
        ...

    def list_sessions(
        self,
        *,
        character_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StoredSessionSummary]:
        ...

    def get_session_summary(self, session_id: str) -> StoredSessionSummary:
        ...

    def clear_character_reference(self, character_id: str) -> None:
        ...


class CharacterRepository(Protocol):
    def create_character(
        self,
        name: str,
        description: str,
        system_prompt: str,
        first_message: str,
        avatar_url: str | None,
    ) -> StoredCharacter:
        ...

    def list_characters(self) -> list[StoredCharacter]:
        ...

    def get_character(self, character_id: str) -> StoredCharacter:
        ...

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
        ...

    def delete_character(self, character_id: str) -> None:
        ...


class AppSettingsRepository(Protocol):
    def get_settings(self) -> StoredAppSettings:
        ...

    def update_settings(
        self,
        *,
        mode: str,
        byok_base_url: str,
        byok_model: str,
        byok_api_key_encrypted: str | None,
        generation_task_bindings_json: str,
    ) -> StoredAppSettings:
        ...

    def update_trial_proxy_settings(
        self,
        *,
        trial_proxy_mode: str,
        trial_proxy_base_url: str,
        trial_proxy_model: str,
        trial_proxy_api_key_encrypted: str | None,
        trial_proxy_timeout_seconds: float,
        trial_proxy_system_prompt: str,
    ) -> StoredAppSettings:
        ...


class AssetRepository(Protocol):
    def create_asset(
        self,
        *,
        asset_id: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        stored_filename: str,
    ) -> StoredAsset:
        ...

    def get_asset(self, asset_id: str) -> StoredAsset:
        ...

    def get_asset_by_stored_filename(self, stored_filename: str) -> StoredAsset:
        ...

    def list_assets(self, *, limit: int = 50, offset: int = 0) -> list[StoredAsset]:
        ...

    def delete_asset(self, asset_id: str) -> None:
        ...


class CharacterDraftRepository(Protocol):
    def get_draft(self, character_id: str) -> StoredCharacterDraft:
        ...

    def save_draft(
        self,
        *,
        character_id: str,
        payload_json: str,
        expected_version: int | None = None,
    ) -> StoredCharacterDraft:
        ...

    def delete_draft(self, character_id: str) -> None:
        ...


class LorebookRepository(Protocol):
    def create_lorebook(
        self,
        *,
        character_id: str | None,
        keyword: str,
        insert_text: str,
        sort_order: int,
        enabled: bool,
    ) -> "StoredLorebook":
        ...

    def list_lorebooks(
        self,
        *,
        character_id: str | None = None,
        enabled: bool | None = None,
    ) -> list["StoredLorebook"]:
        ...

    def get_lorebook(self, lorebook_id: str) -> "StoredLorebook":
        ...

    def update_lorebook(
        self,
        lorebook_id: str,
        *,
        character_id: str | None = None,
        keyword: str | None = None,
        insert_text: str | None = None,
        sort_order: int | None = None,
        enabled: bool | None = None,
    ) -> "StoredLorebook":
        ...

    def delete_lorebook(self, lorebook_id: str) -> None:
        ...

    def find_matching_lorebooks(
        self,
        *,
        message: str,
        character_id: str | None,
        max_items: int = 6,
    ) -> list["StoredLorebook"]:
        ...


class ModelEndpointRepository(Protocol):
    def create_endpoint(
        self,
        *,
        provider: str,
        name: str,
        base_url: str,
        model: str,
        api_key_encrypted: str | None,
        enabled: bool,
        priority: int,
        is_fallback: bool,
    ) -> StoredModelEndpoint:
        ...

    def list_endpoints(self, *, include_disabled: bool = True) -> list[StoredModelEndpoint]:
        ...

    def get_endpoint(self, endpoint_id: str) -> StoredModelEndpoint:
        ...

    def update_endpoint(
        self,
        endpoint_id: str,
        *,
        provider: str | None = None,
        name: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key_encrypted: str | None | object = UNSET,
        enabled: bool | None = None,
        priority: int | None = None,
        is_fallback: bool | None = None,
    ) -> StoredModelEndpoint:
        ...

    def delete_endpoint(self, endpoint_id: str) -> None:
        ...


class GenerationRepository(Protocol):
    def create_job(
        self,
        *,
        user_input: str,
        pipeline_version: str,
    ) -> StoredGenerationJob:
        ...

    def get_job(self, job_id: str) -> StoredGenerationJob:
        ...

    def list_jobs(self, *, limit: int = 50, offset: int = 0) -> list[StoredGenerationJob]:
        ...

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error_message: str | None | object = UNSET,
        completed_at: datetime | None | object = UNSET,
    ) -> StoredGenerationJob:
        ...

    def create_task(
        self,
        *,
        job_id: str,
        task_type: str,
        status: str,
        provider: str | None,
        endpoint_id: str | None,
        attempt: int,
        error_type: str | None,
        duration_ms: int | None,
        request_chars: int,
        response_chars: int,
        prompt_payload_json: str,
        output_payload_json: str,
    ) -> StoredGenerationTask:
        ...

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        provider: str | None | object = UNSET,
        endpoint_id: str | None | object = UNSET,
        attempt: int | None = None,
        error_message: str | None | object = UNSET,
        error_type: str | None | object = UNSET,
        duration_ms: int | None | object = UNSET,
        request_chars: int | None = None,
        response_chars: int | None = None,
        prompt_payload_json: str | None = None,
        output_payload_json: str | None = None,
        started_at: datetime | None | object = UNSET,
        completed_at: datetime | None | object = UNSET,
    ) -> StoredGenerationTask:
        ...

    def list_tasks(self, *, job_id: str) -> list[StoredGenerationTask]:
        ...

    def create_artifact(
        self,
        *,
        job_id: str,
        artifact_type: str,
        payload_json: str,
    ) -> StoredGenerationArtifact:
        ...

    def list_artifacts(self, *, job_id: str) -> list[StoredGenerationArtifact]:
        ...

    def append_event(
        self,
        *,
        job_id: str,
        event_type: str,
        payload_json: str,
    ) -> StoredGenerationEvent:
        ...

    def list_events(self, *, job_id: str) -> list[StoredGenerationEvent]:
        ...


class SQLiteSessionRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_session(
        self,
        session_id: str,
        welcome_message: str,
        character_id: str | None = None,
    ) -> None:
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (session_id, created_at, character_id)
                VALUES (?, ?, ?)
                """,
                (session_id, now, character_id),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, "assistant", welcome_message, now),
            )

    def append_message(self, session_id: str, role: str, content: str) -> None:
        timestamp = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, timestamp),
            )

    def get_history(self, session_id: str) -> list[StoredMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, timestamp
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

        return [
            StoredMessage(
                role=row["role"],
                content=row["content"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in rows
        ]

    def count_messages(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(1) AS c FROM chat_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def session_exists(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row is not None

    def list_sessions(
        self,
        *,
        character_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StoredSessionSummary]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        where_clause = ""
        params: list[object] = []
        if character_id is not None:
            where_clause = "WHERE s.character_id = ?"
            params.append(character_id)

        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    s.session_id AS session_id,
                    s.character_id AS character_id,
                    s.created_at AS created_at,
                    MAX(m.timestamp) AS last_message_at,
                    COUNT(m.id) AS message_count,
                    (
                        SELECT m2.content
                        FROM chat_messages m2
                        WHERE m2.session_id = s.session_id
                        ORDER BY m2.id DESC
                        LIMIT 1
                    ) AS last_message
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.session_id
                {where_clause}
                GROUP BY s.session_id, s.character_id, s.created_at
                ORDER BY COALESCE(MAX(m.timestamp), s.created_at) DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()

        return [self._row_to_session_summary(row) for row in rows]

    def get_session_summary(self, session_id: str) -> StoredSessionSummary:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    s.session_id AS session_id,
                    s.character_id AS character_id,
                    s.created_at AS created_at,
                    MAX(m.timestamp) AS last_message_at,
                    COUNT(m.id) AS message_count,
                    (
                        SELECT m2.content
                        FROM chat_messages m2
                        WHERE m2.session_id = s.session_id
                        ORDER BY m2.id DESC
                        LIMIT 1
                    ) AS last_message
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.session_id
                WHERE s.session_id = ?
                GROUP BY s.session_id, s.character_id, s.created_at
                """,
                (session_id,),
            ).fetchone()

        if row is None:
            raise ValueError("Session does not exist.")

        return self._row_to_session_summary(row)

    def clear_character_reference(self, character_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE chat_sessions SET character_id = NULL WHERE character_id = ?",
                (character_id,),
            )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    character_id TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()
            }
            if "character_id" not in columns:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN character_id TEXT")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                ON chat_messages (session_id, id)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_session_summary(row: sqlite3.Row) -> StoredSessionSummary:
        return StoredSessionSummary(
            session_id=row["session_id"],
            character_id=row["character_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_message_at=(
                datetime.fromisoformat(row["last_message_at"])
                if row["last_message_at"] is not None
                else None
            ),
            message_count=int(row["message_count"]),
            last_message=row["last_message"],
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


class SQLiteCharacterRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_character(
        self,
        name: str,
        description: str,
        system_prompt: str,
        first_message: str,
        avatar_url: str | None,
    ) -> StoredCharacter:
        character_id = str(uuid4())
        now = self._utcnow().isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO characters (
                    character_id,
                    name,
                    description,
                    system_prompt,
                    first_message,
                    avatar_url,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    character_id,
                    name,
                    description,
                    system_prompt,
                    first_message,
                    avatar_url,
                    now,
                    now,
                ),
            )

        return self.get_character(character_id)

    def list_characters(self) -> list[StoredCharacter]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    character_id,
                    name,
                    description,
                    system_prompt,
                    first_message,
                    avatar_url,
                    created_at,
                    updated_at
                FROM characters
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [self._row_to_character(row) for row in rows]

    def get_character(self, character_id: str) -> StoredCharacter:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    character_id,
                    name,
                    description,
                    system_prompt,
                    first_message,
                    avatar_url,
                    created_at,
                    updated_at
                FROM characters
                WHERE character_id = ?
                """,
                (character_id,),
            ).fetchone()
        if row is None:
            raise CharacterNotFoundError("Character does not exist.")
        return self._row_to_character(row)

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
        current = self.get_character(character_id)

        updated_name = current.name if name is None else name
        updated_description = current.description if description is None else description
        updated_system_prompt = (
            current.system_prompt if system_prompt is None else system_prompt
        )
        updated_first_message = (
            current.first_message if first_message is None else first_message
        )
        updated_avatar_url = current.avatar_url if avatar_url is UNSET else avatar_url
        updated_at = self._utcnow().isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE characters
                SET
                    name = ?,
                    description = ?,
                    system_prompt = ?,
                    first_message = ?,
                    avatar_url = ?,
                    updated_at = ?
                WHERE character_id = ?
                """,
                (
                    updated_name,
                    updated_description,
                    updated_system_prompt,
                    updated_first_message,
                    updated_avatar_url,
                    updated_at,
                    character_id,
                ),
            )

        return self.get_character(character_id)

    def delete_character(self, character_id: str) -> None:
        self.get_character(character_id)
        with self._connect() as conn:
            has_chat_sessions = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'chat_sessions'
                """
            ).fetchone()
            if has_chat_sessions is not None:
                conn.execute(
                    "UPDATE chat_sessions SET character_id = NULL WHERE character_id = ?",
                    (character_id,),
                )
            has_character_drafts = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'character_drafts'
                """
            ).fetchone()
            if has_character_drafts is not None:
                conn.execute(
                    "DELETE FROM character_drafts WHERE character_id = ?",
                    (character_id,),
                )
            conn.execute(
                "DELETE FROM characters WHERE character_id = ?",
                (character_id,),
            )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS characters (
                    character_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    system_prompt TEXT NOT NULL DEFAULT '',
                    first_message TEXT NOT NULL DEFAULT '',
                    avatar_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_characters_updated_at
                ON characters (updated_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_character(row: sqlite3.Row) -> StoredCharacter:
        return StoredCharacter(
            character_id=row["character_id"],
            name=row["name"],
            description=row["description"],
            system_prompt=row["system_prompt"],
            first_message=row["first_message"],
            avatar_url=row["avatar_url"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


class SQLiteCharacterDraftRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def get_draft(self, character_id: str) -> StoredCharacterDraft:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    character_id,
                    payload_json,
                    version,
                    created_at,
                    updated_at
                FROM character_drafts
                WHERE character_id = ?
                """,
                (character_id,),
            ).fetchone()

        if row is None:
            raise CharacterDraftNotFoundError("Character draft does not exist.")
        return self._row_to_draft(row)

    def save_draft(
        self,
        *,
        character_id: str,
        payload_json: str,
        expected_version: int | None = None,
    ) -> StoredCharacterDraft:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT version
                FROM character_drafts
                WHERE character_id = ?
                """,
                (character_id,),
            ).fetchone()

            now = self._utcnow().isoformat()
            if row is None:
                if expected_version not in {None, 0}:
                    raise DraftVersionConflictError(
                        "Draft version conflict. Draft does not exist yet."
                    )
                conn.execute(
                    """
                    INSERT INTO character_drafts (
                        character_id,
                        payload_json,
                        version,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (character_id, payload_json, 1, now, now),
                )
            else:
                current_version = int(row["version"])
                if (
                    expected_version is not None
                    and expected_version != current_version
                ):
                    raise DraftVersionConflictError(
                        "Draft version conflict. Refresh draft and retry."
                    )
                next_version = current_version + 1
                conn.execute(
                    """
                    UPDATE character_drafts
                    SET
                        payload_json = ?,
                        version = ?,
                        updated_at = ?
                    WHERE character_id = ?
                    """,
                    (payload_json, next_version, now, character_id),
                )

        return self.get_draft(character_id)

    def delete_draft(self, character_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM character_drafts WHERE character_id = ?",
                (character_id,),
            )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS character_drafts (
                    character_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_character_drafts_updated_at
                ON character_drafts (updated_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_draft(row: sqlite3.Row) -> StoredCharacterDraft:
        return StoredCharacterDraft(
            character_id=row["character_id"],
            payload_json=row["payload_json"],
            version=int(row["version"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


class SQLiteLorebookRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_lorebook(
        self,
        *,
        character_id: str | None,
        keyword: str,
        insert_text: str,
        sort_order: int,
        enabled: bool,
    ) -> StoredLorebook:
        lorebook_id = str(uuid4())
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO lorebooks (
                    lorebook_id,
                    character_id,
                    keyword,
                    insert_text,
                    sort_order,
                    enabled,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lorebook_id,
                    character_id,
                    keyword,
                    insert_text,
                    sort_order,
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return self.get_lorebook(lorebook_id)

    def list_lorebooks(
        self,
        *,
        character_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[StoredLorebook]:
        conditions: list[str] = []
        params: list[object] = []

        if character_id is not None:
            conditions.append("character_id = ?")
            params.append(character_id)
        if enabled is not None:
            conditions.append("enabled = ?")
            params.append(1 if enabled else 0)

        where_clause = ""
        if conditions:
            where_clause = f"WHERE {' AND '.join(conditions)}"

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    lorebook_id,
                    character_id,
                    keyword,
                    insert_text,
                    sort_order,
                    enabled,
                    created_at,
                    updated_at
                FROM lorebooks
                {where_clause}
                ORDER BY sort_order ASC, updated_at DESC
                """,
                tuple(params),
            ).fetchall()

        return [self._row_to_lorebook(row) for row in rows]

    def get_lorebook(self, lorebook_id: str) -> StoredLorebook:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    lorebook_id,
                    character_id,
                    keyword,
                    insert_text,
                    sort_order,
                    enabled,
                    created_at,
                    updated_at
                FROM lorebooks
                WHERE lorebook_id = ?
                """,
                (lorebook_id,),
            ).fetchone()

        if row is None:
            raise LorebookNotFoundError("Lorebook does not exist.")
        return self._row_to_lorebook(row)

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
        current = self.get_lorebook(lorebook_id)
        next_character_id = current.character_id if character_id is None else character_id
        next_keyword = current.keyword if keyword is None else keyword
        next_insert_text = current.insert_text if insert_text is None else insert_text
        next_sort_order = current.sort_order if sort_order is None else sort_order
        next_enabled = current.enabled if enabled is None else enabled
        updated_at = self._utcnow().isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE lorebooks
                SET
                    character_id = ?,
                    keyword = ?,
                    insert_text = ?,
                    sort_order = ?,
                    enabled = ?,
                    updated_at = ?
                WHERE lorebook_id = ?
                """,
                (
                    next_character_id,
                    next_keyword,
                    next_insert_text,
                    next_sort_order,
                    1 if next_enabled else 0,
                    updated_at,
                    lorebook_id,
                ),
            )

        return self.get_lorebook(lorebook_id)

    def delete_lorebook(self, lorebook_id: str) -> None:
        self.get_lorebook(lorebook_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM lorebooks WHERE lorebook_id = ?", (lorebook_id,))

    def find_matching_lorebooks(
        self,
        *,
        message: str,
        character_id: str | None,
        max_items: int = 6,
    ) -> list[StoredLorebook]:
        normalized = message.lower()
        candidates = self.list_lorebooks(enabled=True)
        matched: list[StoredLorebook] = []
        for item in candidates:
            if item.character_id is not None and item.character_id != character_id:
                continue
            keyword = item.keyword.strip().lower()
            if not keyword:
                continue
            if keyword in normalized:
                matched.append(item)
            if len(matched) >= max_items:
                break
        return matched

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lorebooks (
                    lorebook_id TEXT PRIMARY KEY,
                    character_id TEXT,
                    keyword TEXT NOT NULL,
                    insert_text TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 100,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lorebooks_lookup
                ON lorebooks (character_id, enabled, sort_order, updated_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_lorebook(row: sqlite3.Row) -> StoredLorebook:
        return StoredLorebook(
            lorebook_id=row["lorebook_id"],
            character_id=row["character_id"],
            keyword=row["keyword"],
            insert_text=row["insert_text"],
            sort_order=int(row["sort_order"]),
            enabled=bool(row["enabled"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


class SQLiteAssetRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_asset(
        self,
        *,
        asset_id: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        stored_filename: str,
    ) -> StoredAsset:
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO assets (
                    asset_id,
                    original_filename,
                    content_type,
                    size_bytes,
                    stored_filename,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    original_filename,
                    content_type,
                    size_bytes,
                    stored_filename,
                    now,
                    now,
                ),
            )
        return self.get_asset(asset_id)

    def get_asset(self, asset_id: str) -> StoredAsset:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    asset_id,
                    original_filename,
                    content_type,
                    size_bytes,
                    stored_filename,
                    created_at,
                    updated_at
                FROM assets
                WHERE asset_id = ?
                """,
                (asset_id,),
            ).fetchone()

        if row is None:
            raise AssetNotFoundError("Asset does not exist.")
        return self._row_to_asset(row)

    def get_asset_by_stored_filename(self, stored_filename: str) -> StoredAsset:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    asset_id,
                    original_filename,
                    content_type,
                    size_bytes,
                    stored_filename,
                    created_at,
                    updated_at
                FROM assets
                WHERE stored_filename = ?
                """,
                (stored_filename,),
            ).fetchone()

        if row is None:
            raise AssetNotFoundError("Asset does not exist.")
        return self._row_to_asset(row)

    def list_assets(self, *, limit: int = 50, offset: int = 0) -> list[StoredAsset]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    asset_id,
                    original_filename,
                    content_type,
                    size_bytes,
                    stored_filename,
                    created_at,
                    updated_at
                FROM assets
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._row_to_asset(row) for row in rows]

    def delete_asset(self, asset_id: str) -> None:
        self.get_asset(asset_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    stored_filename TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assets_updated_at
                ON assets (updated_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_asset(row: sqlite3.Row) -> StoredAsset:
        return StoredAsset(
            asset_id=row["asset_id"],
            original_filename=row["original_filename"],
            content_type=row["content_type"],
            size_bytes=int(row["size_bytes"]),
            stored_filename=row["stored_filename"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


class SQLiteAppSettingsRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._ensure_default_row()

    def get_settings(self) -> StoredAppSettings:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    mode,
                    byok_base_url,
                    byok_model,
                    byok_api_key_encrypted,
                    trial_proxy_mode,
                    trial_proxy_base_url,
                    trial_proxy_model,
                    trial_proxy_api_key_encrypted,
                    trial_proxy_timeout_seconds,
                    trial_proxy_system_prompt,
                    generation_task_bindings_json,
                    updated_at
                FROM app_settings
                WHERE id = 1
                """
            ).fetchone()

        if row is None:
            self._ensure_default_row()
            return self.get_settings()

        return StoredAppSettings(
            mode=row["mode"],
            byok_base_url=row["byok_base_url"],
            byok_model=row["byok_model"],
            byok_api_key_encrypted=row["byok_api_key_encrypted"],
            trial_proxy_mode=row["trial_proxy_mode"],
            trial_proxy_base_url=row["trial_proxy_base_url"],
            trial_proxy_model=row["trial_proxy_model"],
            trial_proxy_api_key_encrypted=row["trial_proxy_api_key_encrypted"],
            trial_proxy_timeout_seconds=float(row["trial_proxy_timeout_seconds"]),
            trial_proxy_system_prompt=row["trial_proxy_system_prompt"],
            generation_task_bindings_json=row["generation_task_bindings_json"] or "{}",
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_settings(
        self,
        *,
        mode: str,
        byok_base_url: str,
        byok_model: str,
        byok_api_key_encrypted: str | None,
        generation_task_bindings_json: str,
    ) -> StoredAppSettings:
        updated_at = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE app_settings
                SET
                    mode = ?,
                    byok_base_url = ?,
                    byok_model = ?,
                    byok_api_key_encrypted = ?,
                    generation_task_bindings_json = ?,
                    updated_at = ?
                WHERE id = 1
                """,
                (
                    mode,
                    byok_base_url,
                    byok_model,
                    byok_api_key_encrypted,
                    generation_task_bindings_json,
                    updated_at,
                ),
            )
        return self.get_settings()

    def update_trial_proxy_settings(
        self,
        *,
        trial_proxy_mode: str,
        trial_proxy_base_url: str,
        trial_proxy_model: str,
        trial_proxy_api_key_encrypted: str | None,
        trial_proxy_timeout_seconds: float,
        trial_proxy_system_prompt: str,
    ) -> StoredAppSettings:
        updated_at = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE app_settings
                SET
                    trial_proxy_mode = ?,
                    trial_proxy_base_url = ?,
                    trial_proxy_model = ?,
                    trial_proxy_api_key_encrypted = ?,
                    trial_proxy_timeout_seconds = ?,
                    trial_proxy_system_prompt = ?,
                    updated_at = ?
                WHERE id = 1
                """,
                (
                    trial_proxy_mode,
                    trial_proxy_base_url,
                    trial_proxy_model,
                    trial_proxy_api_key_encrypted,
                    trial_proxy_timeout_seconds,
                    trial_proxy_system_prompt,
                    updated_at,
                ),
            )
        return self.get_settings()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    mode TEXT NOT NULL DEFAULT 'trial',
                    byok_base_url TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
                    byok_model TEXT NOT NULL DEFAULT 'gpt-4o-mini',
                    byok_api_key_encrypted TEXT,
                    trial_proxy_mode TEXT NOT NULL DEFAULT 'local',
                    trial_proxy_base_url TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
                    trial_proxy_model TEXT NOT NULL DEFAULT 'gpt-4o-mini',
                    trial_proxy_api_key_encrypted TEXT,
                    trial_proxy_timeout_seconds REAL NOT NULL DEFAULT 30,
                    trial_proxy_system_prompt TEXT NOT NULL DEFAULT '',
                    generation_task_bindings_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(app_settings)").fetchall()
            }
            if "trial_proxy_mode" not in columns:
                conn.execute(
                    "ALTER TABLE app_settings ADD COLUMN trial_proxy_mode TEXT NOT NULL DEFAULT 'local'"
                )
            if "trial_proxy_base_url" not in columns:
                conn.execute(
                    "ALTER TABLE app_settings ADD COLUMN trial_proxy_base_url TEXT NOT NULL DEFAULT 'https://api.openai.com/v1'"
                )
            if "trial_proxy_model" not in columns:
                conn.execute(
                    "ALTER TABLE app_settings ADD COLUMN trial_proxy_model TEXT NOT NULL DEFAULT 'gpt-4o-mini'"
                )
            if "trial_proxy_api_key_encrypted" not in columns:
                conn.execute(
                    "ALTER TABLE app_settings ADD COLUMN trial_proxy_api_key_encrypted TEXT"
                )
            if "trial_proxy_timeout_seconds" not in columns:
                conn.execute(
                    "ALTER TABLE app_settings ADD COLUMN trial_proxy_timeout_seconds REAL NOT NULL DEFAULT 30"
                )
            if "trial_proxy_system_prompt" not in columns:
                conn.execute(
                    "ALTER TABLE app_settings ADD COLUMN trial_proxy_system_prompt TEXT NOT NULL DEFAULT ''"
                )
            if "generation_task_bindings_json" not in columns:
                conn.execute(
                    "ALTER TABLE app_settings ADD COLUMN generation_task_bindings_json TEXT NOT NULL DEFAULT '{}'"
                )

    def _ensure_default_row(self) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM app_settings WHERE id = 1").fetchone()
            if row is not None:
                return
            conn.execute(
                """
                INSERT INTO app_settings (
                    id,
                    mode,
                    byok_base_url,
                    byok_model,
                    byok_api_key_encrypted,
                    trial_proxy_mode,
                    trial_proxy_base_url,
                    trial_proxy_model,
                    trial_proxy_api_key_encrypted,
                    trial_proxy_timeout_seconds,
                    trial_proxy_system_prompt,
                    generation_task_bindings_json,
                    updated_at
                ) VALUES (
                    1,
                    'trial',
                    'https://api.openai.com/v1',
                    'gpt-4o-mini',
                    NULL,
                    'local',
                    'https://api.openai.com/v1',
                    'gpt-4o-mini',
                    NULL,
                    30,
                    '',
                    '{}',
                    ?
                )
                """,
                (self._utcnow().isoformat(),),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


class SQLiteModelEndpointRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_endpoint(
        self,
        *,
        provider: str,
        name: str,
        base_url: str,
        model: str,
        api_key_encrypted: str | None,
        enabled: bool,
        priority: int,
        is_fallback: bool,
    ) -> StoredModelEndpoint:
        endpoint_id = str(uuid4())
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_endpoints (
                    endpoint_id,
                    provider,
                    name,
                    base_url,
                    model,
                    api_key_encrypted,
                    enabled,
                    priority,
                    is_fallback,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    endpoint_id,
                    provider,
                    name,
                    base_url,
                    model,
                    api_key_encrypted,
                    1 if enabled else 0,
                    priority,
                    1 if is_fallback else 0,
                    now,
                    now,
                ),
            )
        return self.get_endpoint(endpoint_id)

    def list_endpoints(self, *, include_disabled: bool = True) -> list[StoredModelEndpoint]:
        where_clause = ""
        params: tuple[object, ...] = ()
        if not include_disabled:
            where_clause = "WHERE enabled = 1"

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    endpoint_id,
                    provider,
                    name,
                    base_url,
                    model,
                    api_key_encrypted,
                    enabled,
                    priority,
                    is_fallback,
                    created_at,
                    updated_at
                FROM model_endpoints
                {where_clause}
                ORDER BY priority ASC, updated_at DESC
                """,
                params,
            ).fetchall()
        return [self._row_to_model_endpoint(row) for row in rows]

    def get_endpoint(self, endpoint_id: str) -> StoredModelEndpoint:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    endpoint_id,
                    provider,
                    name,
                    base_url,
                    model,
                    api_key_encrypted,
                    enabled,
                    priority,
                    is_fallback,
                    created_at,
                    updated_at
                FROM model_endpoints
                WHERE endpoint_id = ?
                """,
                (endpoint_id,),
            ).fetchone()
        if row is None:
            raise ModelEndpointNotFoundError("Model endpoint does not exist.")
        return self._row_to_model_endpoint(row)

    def update_endpoint(
        self,
        endpoint_id: str,
        *,
        provider: str | None = None,
        name: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key_encrypted: str | None | object = UNSET,
        enabled: bool | None = None,
        priority: int | None = None,
        is_fallback: bool | None = None,
    ) -> StoredModelEndpoint:
        current = self.get_endpoint(endpoint_id)
        next_provider = current.provider if provider is None else provider
        next_name = current.name if name is None else name
        next_base_url = current.base_url if base_url is None else base_url
        next_model = current.model if model is None else model
        next_api_key_encrypted = (
            current.api_key_encrypted if api_key_encrypted is UNSET else api_key_encrypted
        )
        next_enabled = current.enabled if enabled is None else enabled
        next_priority = current.priority if priority is None else priority
        next_is_fallback = current.is_fallback if is_fallback is None else is_fallback

        updated_at = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE model_endpoints
                SET
                    provider = ?,
                    name = ?,
                    base_url = ?,
                    model = ?,
                    api_key_encrypted = ?,
                    enabled = ?,
                    priority = ?,
                    is_fallback = ?,
                    updated_at = ?
                WHERE endpoint_id = ?
                """,
                (
                    next_provider,
                    next_name,
                    next_base_url,
                    next_model,
                    next_api_key_encrypted,
                    1 if next_enabled else 0,
                    next_priority,
                    1 if next_is_fallback else 0,
                    updated_at,
                    endpoint_id,
                ),
            )

        return self.get_endpoint(endpoint_id)

    def delete_endpoint(self, endpoint_id: str) -> None:
        self.get_endpoint(endpoint_id)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM model_endpoints WHERE endpoint_id = ?",
                (endpoint_id,),
            )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_endpoints (
                    endpoint_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    api_key_encrypted TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 100,
                    is_fallback INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_model_endpoints_priority
                ON model_endpoints (enabled, priority, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_model_endpoints_provider
                ON model_endpoints (provider, updated_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_model_endpoint(row: sqlite3.Row) -> StoredModelEndpoint:
        return StoredModelEndpoint(
            endpoint_id=row["endpoint_id"],
            provider=row["provider"],
            name=row["name"],
            base_url=row["base_url"],
            model=row["model"],
            api_key_encrypted=row["api_key_encrypted"],
            enabled=bool(row["enabled"]),
            priority=int(row["priority"]),
            is_fallback=bool(row["is_fallback"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


class SQLiteGenerationRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_job(
        self,
        *,
        user_input: str,
        pipeline_version: str,
    ) -> StoredGenerationJob:
        job_id = str(uuid4())
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO generation_jobs (
                    job_id,
                    status,
                    user_input,
                    pipeline_version,
                    error_message,
                    created_at,
                    updated_at,
                    completed_at
                ) VALUES (?, 'pending', ?, ?, NULL, ?, ?, NULL)
                """,
                (job_id, user_input, pipeline_version, now, now),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> StoredGenerationJob:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    job_id,
                    status,
                    user_input,
                    pipeline_version,
                    error_message,
                    created_at,
                    updated_at,
                    completed_at
                FROM generation_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise GenerationJobNotFoundError("Generation job does not exist.")
        return self._row_to_generation_job(row)

    def list_jobs(self, *, limit: int = 50, offset: int = 0) -> list[StoredGenerationJob]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    job_id,
                    status,
                    user_input,
                    pipeline_version,
                    error_message,
                    created_at,
                    updated_at,
                    completed_at
                FROM generation_jobs
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._row_to_generation_job(row) for row in rows]

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        error_message: str | None | object = UNSET,
        completed_at: datetime | None | object = UNSET,
    ) -> StoredGenerationJob:
        current = self.get_job(job_id)
        next_status = current.status if status is None else status
        next_error = current.error_message if error_message is UNSET else error_message
        next_completed_at = (
            current.completed_at if completed_at is UNSET else completed_at
        )
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE generation_jobs
                SET
                    status = ?,
                    error_message = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE job_id = ?
                """,
                (
                    next_status,
                    next_error,
                    now,
                    None if next_completed_at is None else next_completed_at.isoformat(),
                    job_id,
                ),
            )
        return self.get_job(job_id)

    def create_task(
        self,
        *,
        job_id: str,
        task_type: str,
        status: str,
        provider: str | None,
        endpoint_id: str | None,
        attempt: int,
        error_type: str | None,
        duration_ms: int | None,
        request_chars: int,
        response_chars: int,
        prompt_payload_json: str,
        output_payload_json: str,
    ) -> StoredGenerationTask:
        self.get_job(job_id)
        task_id = str(uuid4())
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO generation_tasks (
                    task_id,
                    job_id,
                    task_type,
                    status,
                    provider,
                    endpoint_id,
                    attempt,
                    error_message,
                    error_type,
                    duration_ms,
                    request_chars,
                    response_chars,
                    prompt_payload_json,
                    output_payload_json,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    task_id,
                    job_id,
                    task_type,
                    status,
                    provider,
                    endpoint_id,
                    attempt,
                    error_type,
                    duration_ms,
                    request_chars,
                    response_chars,
                    prompt_payload_json,
                    output_payload_json,
                    now,
                    now,
                ),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> StoredGenerationTask:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    task_id,
                    job_id,
                    task_type,
                    status,
                    provider,
                    endpoint_id,
                    attempt,
                    error_message,
                    error_type,
                    duration_ms,
                    request_chars,
                    response_chars,
                    prompt_payload_json,
                    output_payload_json,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at
                FROM generation_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            raise GenerationTaskNotFoundError("Generation task does not exist.")
        return self._row_to_generation_task(row)

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        provider: str | None | object = UNSET,
        endpoint_id: str | None | object = UNSET,
        attempt: int | None = None,
        error_message: str | None | object = UNSET,
        error_type: str | None | object = UNSET,
        duration_ms: int | None | object = UNSET,
        request_chars: int | None = None,
        response_chars: int | None = None,
        prompt_payload_json: str | None = None,
        output_payload_json: str | None = None,
        started_at: datetime | None | object = UNSET,
        completed_at: datetime | None | object = UNSET,
    ) -> StoredGenerationTask:
        current = self.get_task(task_id)
        next_status = current.status if status is None else status
        next_provider = current.provider if provider is UNSET else provider
        next_endpoint_id = current.endpoint_id if endpoint_id is UNSET else endpoint_id
        next_attempt = current.attempt if attempt is None else attempt
        next_error = current.error_message if error_message is UNSET else error_message
        next_error_type = current.error_type if error_type is UNSET else error_type
        next_duration_ms = current.duration_ms if duration_ms is UNSET else duration_ms
        next_request_chars = (
            current.request_chars if request_chars is None else request_chars
        )
        next_response_chars = (
            current.response_chars if response_chars is None else response_chars
        )
        next_prompt = (
            current.prompt_payload_json
            if prompt_payload_json is None
            else prompt_payload_json
        )
        next_output = (
            current.output_payload_json
            if output_payload_json is None
            else output_payload_json
        )
        next_started = current.started_at if started_at is UNSET else started_at
        next_completed = current.completed_at if completed_at is UNSET else completed_at
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE generation_tasks
                SET
                    status = ?,
                    provider = ?,
                    endpoint_id = ?,
                    attempt = ?,
                    error_message = ?,
                    error_type = ?,
                    duration_ms = ?,
                    request_chars = ?,
                    response_chars = ?,
                    prompt_payload_json = ?,
                    output_payload_json = ?,
                    updated_at = ?,
                    started_at = ?,
                    completed_at = ?
                WHERE task_id = ?
                """,
                (
                    next_status,
                    next_provider,
                    next_endpoint_id,
                    next_attempt,
                    next_error,
                    next_error_type,
                    next_duration_ms,
                    next_request_chars,
                    next_response_chars,
                    next_prompt,
                    next_output,
                    now,
                    None if next_started is None else next_started.isoformat(),
                    None if next_completed is None else next_completed.isoformat(),
                    task_id,
                ),
            )
        return self.get_task(task_id)

    def list_tasks(self, *, job_id: str) -> list[StoredGenerationTask]:
        self.get_job(job_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    task_id,
                    job_id,
                    task_type,
                    status,
                    provider,
                    endpoint_id,
                    attempt,
                    error_message,
                    error_type,
                    duration_ms,
                    request_chars,
                    response_chars,
                    prompt_payload_json,
                    output_payload_json,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at
                FROM generation_tasks
                WHERE job_id = ?
                ORDER BY created_at ASC
                """,
                (job_id,),
            ).fetchall()
        return [self._row_to_generation_task(row) for row in rows]

    def create_artifact(
        self,
        *,
        job_id: str,
        artifact_type: str,
        payload_json: str,
    ) -> StoredGenerationArtifact:
        self.get_job(job_id)
        artifact_id = str(uuid4())
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO generation_artifacts (
                    artifact_id,
                    job_id,
                    artifact_type,
                    payload_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, job_id, artifact_type, payload_json, now, now),
            )
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> StoredGenerationArtifact:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    artifact_id,
                    job_id,
                    artifact_type,
                    payload_json,
                    created_at,
                    updated_at
                FROM generation_artifacts
                WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Generation artifact does not exist.")
        return self._row_to_generation_artifact(row)

    def list_artifacts(self, *, job_id: str) -> list[StoredGenerationArtifact]:
        self.get_job(job_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    artifact_id,
                    job_id,
                    artifact_type,
                    payload_json,
                    created_at,
                    updated_at
                FROM generation_artifacts
                WHERE job_id = ?
                ORDER BY created_at ASC
                """,
                (job_id,),
            ).fetchall()
        return [self._row_to_generation_artifact(row) for row in rows]

    def append_event(
        self,
        *,
        job_id: str,
        event_type: str,
        payload_json: str,
    ) -> StoredGenerationEvent:
        self.get_job(job_id)
        now = self._utcnow().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO generation_events (
                    job_id,
                    event_type,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (job_id, event_type, payload_json, now),
            )
            event_id = int(cursor.lastrowid)
        return self.get_event(event_id)

    def get_event(self, event_id: int) -> StoredGenerationEvent:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    event_id,
                    job_id,
                    event_type,
                    payload_json,
                    created_at
                FROM generation_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Generation event does not exist.")
        return self._row_to_generation_event(row)

    def list_events(self, *, job_id: str) -> list[StoredGenerationEvent]:
        self.get_job(job_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    event_id,
                    job_id,
                    event_type,
                    payload_json,
                    created_at
                FROM generation_events
                WHERE job_id = ?
                ORDER BY event_id ASC
                """,
                (job_id,),
            ).fetchall()
        return [self._row_to_generation_event(row) for row in rows]

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    pipeline_version TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_generation_jobs_created_at
                ON generation_jobs (created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_tasks (
                    task_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT,
                    endpoint_id TEXT,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    error_message TEXT,
                    error_type TEXT,
                    duration_ms INTEGER,
                    request_chars INTEGER NOT NULL DEFAULT 0,
                    response_chars INTEGER NOT NULL DEFAULT 0,
                    prompt_payload_json TEXT NOT NULL DEFAULT '{}',
                    output_payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (job_id) REFERENCES generation_jobs(job_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_generation_tasks_job
                ON generation_tasks (job_id, created_at ASC)
                """
            )
            task_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(generation_tasks)").fetchall()
            }
            if "error_type" not in task_columns:
                conn.execute("ALTER TABLE generation_tasks ADD COLUMN error_type TEXT")
            if "duration_ms" not in task_columns:
                conn.execute("ALTER TABLE generation_tasks ADD COLUMN duration_ms INTEGER")
            if "request_chars" not in task_columns:
                conn.execute(
                    "ALTER TABLE generation_tasks ADD COLUMN request_chars INTEGER NOT NULL DEFAULT 0"
                )
            if "response_chars" not in task_columns:
                conn.execute(
                    "ALTER TABLE generation_tasks ADD COLUMN response_chars INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES generation_jobs(job_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_generation_artifacts_job
                ON generation_artifacts (job_id, created_at ASC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES generation_jobs(job_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_generation_events_job
                ON generation_events (job_id, event_id ASC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_generation_job(row: sqlite3.Row) -> StoredGenerationJob:
        return StoredGenerationJob(
            job_id=row["job_id"],
            status=row["status"],
            user_input=row["user_input"],
            pipeline_version=row["pipeline_version"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=(
                None
                if row["completed_at"] is None
                else datetime.fromisoformat(row["completed_at"])
            ),
        )

    @staticmethod
    def _row_to_generation_task(row: sqlite3.Row) -> StoredGenerationTask:
        return StoredGenerationTask(
            task_id=row["task_id"],
            job_id=row["job_id"],
            task_type=row["task_type"],
            status=row["status"],
            provider=row["provider"],
            endpoint_id=row["endpoint_id"],
            attempt=int(row["attempt"]),
            error_message=row["error_message"],
            error_type=row["error_type"],
            duration_ms=(
                None if row["duration_ms"] is None else int(row["duration_ms"])
            ),
            request_chars=int(row["request_chars"]),
            response_chars=int(row["response_chars"]),
            prompt_payload_json=row["prompt_payload_json"],
            output_payload_json=row["output_payload_json"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=(
                None
                if row["started_at"] is None
                else datetime.fromisoformat(row["started_at"])
            ),
            completed_at=(
                None
                if row["completed_at"] is None
                else datetime.fromisoformat(row["completed_at"])
            ),
        )

    @staticmethod
    def _row_to_generation_artifact(row: sqlite3.Row) -> StoredGenerationArtifact:
        return StoredGenerationArtifact(
            artifact_id=row["artifact_id"],
            job_id=row["job_id"],
            artifact_type=row["artifact_type"],
            payload_json=row["payload_json"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_generation_event(row: sqlite3.Row) -> StoredGenerationEvent:
        return StoredGenerationEvent(
            event_id=int(row["event_id"]),
            job_id=row["job_id"],
            event_type=row["event_type"],
            payload_json=row["payload_json"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)
