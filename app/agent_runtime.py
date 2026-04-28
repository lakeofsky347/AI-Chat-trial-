from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Generic, Protocol, TypeVar
from uuid import uuid4

import httpx


StateT = TypeVar("StateT")


class Runnable(Protocol[StateT]):
    def invoke(self, state: StateT) -> StateT:
        ...


class RunnableLambda(Generic[StateT]):
    def __init__(self, name: str, fn: Callable[[StateT], StateT]) -> None:
        self.name = name
        self._fn = fn

    def invoke(self, state: StateT) -> StateT:
        return self._fn(state)


class RunnableSequence(Generic[StateT]):
    """A lightweight LCEL-style sequential chain for deterministic orchestration."""

    def __init__(self, steps: list[Runnable[StateT]]) -> None:
        self._steps = steps

    def invoke(self, state: StateT) -> StateT:
        current = state
        for step in self._steps:
            current = step.invoke(current)
        return current


@dataclass(frozen=True)
class SessionSummaryState:
    summary_text: str
    last_message_count: int


@dataclass(frozen=True)
class RetrievedMemory:
    content: str
    role: str
    score: float
    created_at: datetime


@dataclass(frozen=True)
class RagContextBundle:
    recent_history: list[Any]
    rag_context: str
    summary_text: str
    retrieved_memories: list[RetrievedMemory]
    context_char_budget: int
    rag_context_chars: int
    recent_history_chars: int
    recent_message_count: int


@dataclass(frozen=True)
class ChatAigcActionRecord:
    action_id: str
    session_id: str
    action_type: str
    selected_text: str
    result_payload: dict[str, Any]
    created_at: datetime


@dataclass
class RagPipelineState:
    session_id: str
    history: list[Any]
    latest_user_message: str
    lore_context: str
    summary_state: SessionSummaryState
    summary_fn: Callable[[str, str], str] | None
    recent_limit: int
    summary_trigger_messages: int
    summary_step_messages: int
    context_char_budget: int
    retrieval_top_k: int
    query_embedding: list[float]
    retrieved: list[RetrievedMemory]
    rag_context: str
    output_recent_history: list[Any]


class BgeEmbeddingClient:
    """BGE embedding client with OpenAI-compatible endpoint support and local fallback."""

    def __init__(self) -> None:
        self._base_url = os.getenv("BGE_EMBEDDING_BASE_URL", "").strip()
        self._model = os.getenv("BGE_EMBEDDING_MODEL", "bge-m3").strip() or "bge-m3"
        self._api_key = os.getenv("BGE_EMBEDDING_API_KEY", "").strip()
        self._timeout = float(os.getenv("BGE_EMBEDDING_TIMEOUT_SECONDS", "20") or "20")
        dim_raw = os.getenv("BGE_EMBEDDING_FALLBACK_DIM", "256").strip()
        try:
            self._fallback_dim = max(64, min(int(dim_raw), 2048))
        except ValueError:
            self._fallback_dim = 256

    def embed_text(self, text: str) -> list[float]:
        normalized = text.strip()
        if not normalized:
            return [0.0] * self._fallback_dim

        if self._base_url:
            endpoint = f"{self._base_url.rstrip('/')}/embeddings"
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            try:
                response = httpx.post(
                    endpoint,
                    headers=headers,
                    json={"model": self._model, "input": normalized},
                    timeout=self._timeout,
                )
                if response.status_code < 400:
                    body = response.json()
                    data = body.get("data")
                    if isinstance(data, list) and data:
                        embedding = data[0].get("embedding")
                        if (
                            isinstance(embedding, list)
                            and embedding
                            and all(isinstance(v, (int, float)) for v in embedding)
                        ):
                            return [float(v) for v in embedding]
            except Exception:
                pass

        return self._fallback_hash_embedding(normalized)

    def _fallback_hash_embedding(self, text: str) -> list[float]:
        vector = [0.0] * self._fallback_dim
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        if not tokens:
            tokens = [text.lower()]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self._fallback_dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[idx] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm <= 1e-9:
            return vector
        return [v / norm for v in vector]


class SQLiteChatMemoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def get_summary(self, session_id: str) -> SessionSummaryState:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT summary_text, last_message_count
                FROM chat_memory_summaries
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return SessionSummaryState(summary_text="", last_message_count=0)
        return SessionSummaryState(
            summary_text=row["summary_text"] or "",
            last_message_count=int(row["last_message_count"] or 0),
        )

    def upsert_summary(
        self,
        *,
        session_id: str,
        summary_text: str,
        last_message_count: int,
    ) -> SessionSummaryState:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_memory_summaries (session_id, summary_text, last_message_count, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    last_message_count = excluded.last_message_count,
                    updated_at = excluded.updated_at
                """,
                (session_id, summary_text, last_message_count, now),
            )
        return SessionSummaryState(summary_text=summary_text, last_message_count=last_message_count)

    def add_memory_chunk(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        embedding: list[float],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_memory_chunks (session_id, role, content, embedding_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, json.dumps(embedding), now),
            )

    def similarity_search(
        self,
        *,
        session_id: str,
        query_embedding: list[float],
        top_k: int,
        scan_limit: int = 300,
    ) -> list[RetrievedMemory]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, embedding_json, created_at
                FROM chat_memory_chunks
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, scan_limit),
            ).fetchall()

        scored: list[RetrievedMemory] = []
        recent_fallback: list[RetrievedMemory] = []
        for row in rows:
            try:
                vector_raw = json.loads(row["embedding_json"])
            except Exception:
                continue
            if not isinstance(vector_raw, list) or not vector_raw:
                continue
            if not all(isinstance(v, (int, float)) for v in vector_raw):
                continue
            vector = [float(v) for v in vector_raw]
            score = _cosine_similarity(query_embedding, vector)
            candidate = RetrievedMemory(
                content=row["content"],
                role=row["role"],
                score=score,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            recent_fallback.append(candidate)
            if score <= 0:
                continue
            scored.append(
                RetrievedMemory(
                    content=candidate.content,
                    role=candidate.role,
                    score=candidate.score,
                    created_at=candidate.created_at,
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        if scored:
            return scored[: max(1, top_k)]
        return recent_fallback[: max(1, top_k)]

    def create_chat_action(
        self,
        *,
        session_id: str,
        action_type: str,
        selected_text: str,
        result_payload: dict[str, Any],
    ) -> ChatAigcActionRecord:
        action_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_aigc_actions (
                    action_id,
                    session_id,
                    action_type,
                    selected_text,
                    result_payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    session_id,
                    action_type,
                    selected_text,
                    json.dumps(result_payload, ensure_ascii=False),
                    now,
                ),
            )
        return ChatAigcActionRecord(
            action_id=action_id,
            session_id=session_id,
            action_type=action_type,
            selected_text=selected_text,
            result_payload=result_payload,
            created_at=datetime.fromisoformat(now),
        )

    def list_chat_actions(
        self,
        *,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatAigcActionRecord]:
        safe_limit = max(1, min(limit, 200))
        safe_offset = max(0, offset)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT action_id, session_id, action_type, selected_text, result_payload_json, created_at
                FROM chat_aigc_actions
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (session_id, safe_limit, safe_offset),
            ).fetchall()
        records: list[ChatAigcActionRecord] = []
        for row in rows:
            try:
                payload = json.loads(row["result_payload_json"])
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            records.append(
                ChatAigcActionRecord(
                    action_id=row["action_id"],
                    session_id=row["session_id"],
                    action_type=row["action_type"],
                    selected_text=row["selected_text"],
                    result_payload=payload,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return records

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_memory_summaries (
                    session_id TEXT PRIMARY KEY,
                    summary_text TEXT NOT NULL,
                    last_message_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_memory_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_memory_chunks_session
                ON chat_memory_chunks (session_id, id DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_aigc_actions (
                    action_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    selected_text TEXT NOT NULL,
                    result_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_aigc_actions_session
                ON chat_aigc_actions (session_id, created_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn


class ChatRagRuntime:
    def __init__(self, db_path: Path) -> None:
        self._store = SQLiteChatMemoryStore(db_path)
        self._embedder = BgeEmbeddingClient()

    def prepare_context(
        self,
        *,
        session_id: str,
        history: list[Any],
        latest_user_message: str,
        lore_context: str,
        summary_fn: Callable[[str, str], str] | None = None,
    ) -> RagContextBundle:
        recent_limit = _read_int_env("CHAT_RECENT_MESSAGE_LIMIT", default=12, min_value=4, max_value=64)
        summary_trigger_messages = _read_int_env(
            "CHAT_SUMMARY_TRIGGER_MESSAGES", default=24, min_value=8, max_value=200
        )
        summary_step_messages = _read_int_env(
            "CHAT_SUMMARY_STEP_MESSAGES", default=10, min_value=4, max_value=80
        )
        context_char_budget = _read_int_env(
            "CHAT_CONTEXT_CHAR_BUDGET", default=14000, min_value=4000, max_value=64000
        )
        retrieval_top_k = _read_int_env("CHAT_RAG_TOP_K", default=4, min_value=1, max_value=10)

        summary_state = self._store.get_summary(session_id)
        query_embedding = self._embedder.embed_text(latest_user_message)

        initial_state = RagPipelineState(
            session_id=session_id,
            history=history,
            latest_user_message=latest_user_message,
            lore_context=lore_context,
            summary_state=summary_state,
            summary_fn=summary_fn,
            recent_limit=recent_limit,
            summary_trigger_messages=summary_trigger_messages,
            summary_step_messages=summary_step_messages,
            context_char_budget=context_char_budget,
            retrieval_top_k=retrieval_top_k,
            query_embedding=query_embedding,
            retrieved=[],
            rag_context="",
            output_recent_history=history,
        )

        chain = RunnableSequence[RagPipelineState](
            [
                RunnableLambda("refresh_summary", self._step_refresh_summary),
                RunnableLambda("retrieve_memory", self._step_retrieve_memory),
                RunnableLambda("assemble_context", self._step_assemble_context),
                RunnableLambda("apply_budget", self._step_apply_budget),
            ]
        )

        result_state = chain.invoke(initial_state)
        recent_chars = sum(len(str(getattr(msg, "content", ""))) for msg in result_state.output_recent_history)
        return RagContextBundle(
            recent_history=result_state.output_recent_history,
            rag_context=result_state.rag_context,
            summary_text=result_state.summary_state.summary_text,
            retrieved_memories=result_state.retrieved,
            context_char_budget=context_char_budget,
            rag_context_chars=len(result_state.rag_context),
            recent_history_chars=recent_chars,
            recent_message_count=len(result_state.output_recent_history),
        )

    def persist_turn(self, *, session_id: str, user_message: str, assistant_message: str) -> None:
        user_text = user_message.strip()
        assistant_text = assistant_message.strip()
        if user_text:
            self._store.add_memory_chunk(
                session_id=session_id,
                role="user",
                content=user_text,
                embedding=self._embedder.embed_text(user_text),
            )
        if assistant_text:
            self._store.add_memory_chunk(
                session_id=session_id,
                role="assistant",
                content=assistant_text,
                embedding=self._embedder.embed_text(assistant_text),
            )

    def recall_memory(self, *, session_id: str, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        embedding = self._embedder.embed_text(query)
        items = self._store.similarity_search(
            session_id=session_id,
            query_embedding=embedding,
            top_k=max(1, min(top_k, 8)),
        )
        return [
            {
                "role": item.role,
                "content": item.content,
                "score": round(item.score, 4),
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]

    def create_chat_action(
        self,
        *,
        session_id: str,
        action_type: str,
        selected_text: str,
        result_payload: dict[str, Any],
    ) -> ChatAigcActionRecord:
        return self._store.create_chat_action(
            session_id=session_id,
            action_type=action_type,
            selected_text=selected_text,
            result_payload=result_payload,
        )

    def list_chat_actions(
        self,
        *,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatAigcActionRecord]:
        return self._store.list_chat_actions(
            session_id=session_id,
            limit=limit,
            offset=offset,
        )

    def _step_refresh_summary(self, state: RagPipelineState) -> RagPipelineState:
        dialogue = [m for m in state.history if getattr(m, "role", "") in {"user", "assistant"}]
        if len(dialogue) < state.summary_trigger_messages:
            return state

        pending_count = len(dialogue) - state.summary_state.last_message_count
        if pending_count < state.summary_step_messages:
            return state

        segment = dialogue[-state.summary_step_messages :]
        segment_text = "\n".join(
            f"{getattr(msg, 'role', 'unknown')}: {getattr(msg, 'content', '')}"
            for msg in segment
        )
        if not segment_text.strip():
            return state

        if state.summary_fn is not None:
            new_summary = state.summary_fn(segment_text, state.summary_state.summary_text)
        else:
            new_summary = _merge_summary_locally(state.summary_state.summary_text, segment_text)

        summary_state = self._store.upsert_summary(
            session_id=state.session_id,
            summary_text=new_summary.strip(),
            last_message_count=len(dialogue),
        )
        state.summary_state = summary_state
        return state

    def _step_retrieve_memory(self, state: RagPipelineState) -> RagPipelineState:
        state.retrieved = self._store.similarity_search(
            session_id=state.session_id,
            query_embedding=state.query_embedding,
            top_k=state.retrieval_top_k,
        )
        return state

    def _step_assemble_context(self, state: RagPipelineState) -> RagPipelineState:
        lines: list[str] = []
        if state.summary_state.summary_text:
            lines.append("Conversation summary:")
            lines.append(state.summary_state.summary_text.strip())

        if state.retrieved:
            lines.append("Relevant long-term memories:")
            for item in state.retrieved:
                lines.append(f"- ({item.role}) {item.content}")

        if state.lore_context.strip():
            lines.append(state.lore_context.strip())

        state.rag_context = "\n\n".join(line for line in lines if line.strip())
        return state

    def _step_apply_budget(self, state: RagPipelineState) -> RagPipelineState:
        budget = max(2000, state.context_char_budget)
        rag_cost = len(state.rag_context)
        remaining = max(800, budget - rag_cost)

        selected: list[Any] = []
        consumed = 0
        for msg in reversed(state.history):
            content = str(getattr(msg, "content", ""))
            role = str(getattr(msg, "role", ""))
            if role not in {"user", "assistant", "system"}:
                continue
            cost = len(content)
            if selected and consumed + cost > remaining:
                break
            selected.append(msg)
            consumed += cost
            if len(selected) >= state.recent_limit:
                break

        state.output_recent_history = list(reversed(selected)) if selected else state.history[-state.recent_limit :]
        return state


class TavilySearchClient:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (api_key or os.getenv("TAVILY_API_KEY", "")).strip()

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        if not self.enabled:
            raise RuntimeError("Tavily is not configured.")
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max(1, min(max_results, 10)),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        response = httpx.post("https://api.tavily.com/search", json=payload, timeout=20.0)
        if response.status_code >= 400:
            raise RuntimeError(f"Tavily HTTP {response.status_code}")
        body = response.json()
        results = body.get("results")
        if not isinstance(results, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in results[: max_results]:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "title": str(item.get("title", "")).strip(),
                    "url": str(item.get("url", "")).strip(),
                    "snippet": str(item.get("content", "")).strip(),
                }
            )
        return normalized


class OpenAIImageClient:
    def __init__(self) -> None:
        self._base_url = os.getenv("IMAGE_BASE_URL", "").strip()
        self._model = os.getenv("IMAGE_MODEL", "").strip()
        self._api_key = os.getenv("IMAGE_API_KEY", "").strip()
        timeout_raw = os.getenv("IMAGE_TIMEOUT_SECONDS", "45").strip()
        try:
            self._timeout = max(5.0, min(float(timeout_raw), 180.0))
        except ValueError:
            self._timeout = 45.0
        self._size = os.getenv("IMAGE_SIZE", "1024x1024").strip() or "1024x1024"
        self._response_format = os.getenv("IMAGE_RESPONSE_FORMAT", "url").strip() or "url"
        self._api_style = os.getenv("IMAGE_API_STYLE", "auto").strip().lower() or "auto"

    @property
    def enabled(self) -> bool:
        return bool(self._base_url and self._model and self._api_key)

    def generate_image(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Image generation is not configured.")

        style = self._api_style
        if style == "dashscope":
            return self._generate_via_dashscope(prompt=prompt)
        if style == "openai":
            return self._generate_via_openai_compatible(
                prompt=prompt,
                negative_prompt=negative_prompt,
            )

        # auto mode: try openai-compatible first, then dashscope fallback for qwen/dashscope.
        try:
            return self._generate_via_openai_compatible(
                prompt=prompt,
                negative_prompt=negative_prompt,
            )
        except RuntimeError as exc:
            message = str(exc).lower()
            if "http 404" not in message and "http 400" not in message:
                raise
            if "dashscope" in self._base_url.lower() or "qwen" in self._model.lower():
                return self._generate_via_dashscope(prompt=prompt)
            raise

    def _generate_via_openai_compatible(
        self,
        *,
        prompt: str,
        negative_prompt: str,
    ) -> dict[str, Any]:
        endpoint = f"{self._base_url.rstrip('/')}/images/generations"
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": self._size,
            "response_format": self._response_format,
        }
        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f"Image request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    err = body.get("error")
                    if isinstance(err, dict):
                        detail = str(err.get("message", "")).strip()
            except Exception:
                pass
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(f"Image upstream HTTP {response.status_code}{suffix}")

        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("Image upstream returned non-JSON response.") from exc

        data = body.get("data")
        if not isinstance(data, list) or not data:
            raise RuntimeError("Image upstream payload has no data.")

        first = data[0]
        if not isinstance(first, dict):
            raise RuntimeError("Image upstream data item is invalid.")

        url = str(first.get("url", "")).strip()
        b64_json = str(first.get("b64_json", "")).strip()
        revised_prompt = str(first.get("revised_prompt", "")).strip()

        result: dict[str, Any] = {
            "provider": "openai_compatible_image",
            "model": self._model,
            "size": self._size,
            "revised_prompt": revised_prompt,
        }
        if url:
            result["image_url"] = url
        if b64_json:
            result["image_b64"] = b64_json
        if not url and not b64_json:
            raise RuntimeError("Image upstream returned no url or b64_json.")
        return result

    def _generate_via_dashscope(self, *, prompt: str) -> dict[str, Any]:
        base = self._normalize_dashscope_base_url(self._base_url)
        create_url = f"{base}/api/v1/services/aigc/text2image/image-synthesis"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        size = self._size.replace("x", "*").replace("X", "*")
        payload = {
            "model": self._model,
            "input": {"prompt": prompt},
            "parameters": {"size": size, "n": 1},
        }
        try:
            create_resp = httpx.post(
                create_url,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f"DashScope image request failed: {exc}") from exc

        if create_resp.status_code >= 400:
            raise RuntimeError(f"DashScope image upstream HTTP {create_resp.status_code}")

        try:
            create_body = create_resp.json()
        except ValueError as exc:
            raise RuntimeError("DashScope image upstream returned non-JSON response.") from exc

        output = create_body.get("output")
        if not isinstance(output, dict):
            raise RuntimeError("DashScope image output is invalid.")

        results = output.get("results")
        if isinstance(results, list) and results:
            return self._normalize_dashscope_result(results)

        task_id = str(output.get("task_id", "")).strip()
        if not task_id:
            raise RuntimeError("DashScope image task_id is missing.")

        poll_url = f"{base}/api/v1/tasks/{task_id}"
        deadline = time.time() + self._timeout
        last_status = ""
        while time.time() < deadline:
            try:
                poll_resp = httpx.get(
                    poll_url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=min(self._timeout, 15.0),
                )
            except httpx.RequestError as exc:
                raise RuntimeError(f"DashScope image polling failed: {exc}") from exc
            if poll_resp.status_code >= 400:
                raise RuntimeError(f"DashScope image poll HTTP {poll_resp.status_code}")
            poll_body = poll_resp.json()
            poll_output = poll_body.get("output")
            if not isinstance(poll_output, dict):
                raise RuntimeError("DashScope image poll output is invalid.")
            status = str(poll_output.get("task_status", "")).strip().upper()
            last_status = status
            if status == "SUCCEEDED":
                results = poll_output.get("results")
                if not isinstance(results, list) or not results:
                    raise RuntimeError("DashScope task succeeded but results are empty.")
                return self._normalize_dashscope_result(results)
            if status in {"FAILED", "CANCELED"}:
                message = str(poll_output.get("message", "")).strip()
                suffix = f": {message}" if message else ""
                raise RuntimeError(f"DashScope image task {status}{suffix}")
            time.sleep(1.0)

        raise RuntimeError(f"DashScope image polling timeout (last_status={last_status or 'UNKNOWN'})")

    def _normalize_dashscope_result(self, results: list[Any]) -> dict[str, Any]:
        first = results[0]
        if not isinstance(first, dict):
            raise RuntimeError("DashScope result item is invalid.")
        url = str(first.get("url", "")).strip()
        if not url:
            raise RuntimeError("DashScope result has no url.")
        return {
            "provider": "dashscope_image",
            "model": self._model,
            "size": self._size,
            "image_url": url,
        }

    @staticmethod
    def _normalize_dashscope_base_url(raw: str) -> str:
        base = raw.strip().rstrip("/")
        suffixes = [
            "/compatible-mode/v1",
            "/compatible-mode",
            "/v1",
        ]
        lower = base.lower()
        for suffix in suffixes:
            if lower.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return base.rstrip("/")


class ToolCallRuntime:
    def __init__(self, *, rag_runtime: ChatRagRuntime, search_client: TavilySearchClient) -> None:
        self._rag_runtime = rag_runtime
        self._search_client = search_client
        self._image_client = OpenAIImageClient()

    @property
    def enabled(self) -> bool:
        raw = os.getenv("CHAT_ENABLE_FUNCTION_CALLING", "1").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @property
    def image_generation_enabled(self) -> bool:
        return self._image_client.enabled

    def openai_tool_specs(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": "recall_memory",
                    "description": "Retrieve relevant long-term conversation memories for this session.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "What memory to retrieve."},
                            "top_k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 3},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "build_image_prompt",
                    "description": "Build an image-generation prompt from a selected paragraph.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "paragraph": {"type": "string"},
                            "style": {"type": "string", "default": "cinematic"},
                            "shot": {"type": "string", "default": "medium shot"},
                        },
                        "required": ["paragraph"],
                    },
                },
            },
        ]

        if self._search_client.enabled:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "description": "Search public web information for non-original characters and references.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "max_results": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
                            },
                            "required": ["query"],
                        },
                    },
                }
            )
        if self._image_client.enabled:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "generate_image",
                        "description": "Generate image from prompt using configured image model.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "prompt": {"type": "string"},
                                "negative_prompt": {"type": "string", "default": ""},
                            },
                            "required": ["prompt"],
                        },
                    },
                }
            )
        return tools

    def execute_tool(
        self,
        *,
        name: str,
        arguments_json: str,
        session_id: str,
    ) -> dict[str, Any]:
        try:
            args = json.loads(arguments_json) if arguments_json.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Tool arguments must be JSON: {exc}") from exc
        if not isinstance(args, dict):
            raise ValueError("Tool arguments must be an object.")

        if name == "search_web":
            query = str(args.get("query", "")).strip()
            if not query:
                raise ValueError("search_web.query is required")
            max_results_raw = args.get("max_results", 4)
            max_results = int(max_results_raw) if isinstance(max_results_raw, (int, float, str)) else 4
            return {"results": self._search_client.search(query, max_results=max_results)}

        if name == "recall_memory":
            query = str(args.get("query", "")).strip()
            if not query:
                raise ValueError("recall_memory.query is required")
            top_k_raw = args.get("top_k", 3)
            top_k = int(top_k_raw) if isinstance(top_k_raw, (int, float, str)) else 3
            memories = self._rag_runtime.recall_memory(session_id=session_id, query=query, top_k=top_k)
            return {"memories": memories}

        if name == "build_image_prompt":
            paragraph = str(args.get("paragraph", "")).strip()
            if not paragraph:
                raise ValueError("build_image_prompt.paragraph is required")
            style = str(args.get("style", "cinematic")).strip() or "cinematic"
            shot = str(args.get("shot", "medium shot")).strip() or "medium shot"
            prompt = (
                f"{style} illustration, {shot}, focus on: {paragraph[:700]}. "
                "high detail, coherent lighting, no watermark"
            )
            negative = "lowres, blurry, watermark, distorted anatomy, bad hands"
            return {"prompt": prompt, "negative_prompt": negative, "style": style, "shot": shot}

        if name == "generate_image":
            prompt = str(args.get("prompt", "")).strip()
            if not prompt:
                raise ValueError("generate_image.prompt is required")
            negative_prompt = str(args.get("negative_prompt", "")).strip()
            return self._image_client.generate_image(
                prompt=prompt,
                negative_prompt=negative_prompt,
            )

        raise ValueError(f"Unknown tool: {name}")


def _merge_summary_locally(previous: str, segment: str) -> str:
    segment_lines = [line.strip() for line in segment.splitlines() if line.strip()]
    key_points: list[str] = []
    for line in segment_lines[-8:]:
        cleaned = re.sub(r"^(user|assistant):\s*", "", line, flags=re.IGNORECASE)
        if cleaned:
            key_points.append(cleaned)
    merged = previous.strip()
    append = "\n".join(f"- {pt[:180]}" for pt in key_points)
    if merged and append:
        return f"{merged}\n{append}"[:5000]
    if append:
        return append[:5000]
    return merged[:5000]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dim = min(len(a), len(b))
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for idx in range(dim):
        av = a[idx]
        bv = b[idx]
        dot += av * bv
        norm_a += av * av
        norm_b += bv * bv
    if norm_a <= 1e-12 or norm_b <= 1e-12:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _read_int_env(name: str, *, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))
