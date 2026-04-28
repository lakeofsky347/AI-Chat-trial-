from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


class QuotaExceededError(ValueError):
    pass


@dataclass(frozen=True)
class QuotaStatus:
    device_id: str
    quota_date: str
    daily_limit: int
    used: int
    remaining: int
    allowed: bool


class DailyQuotaLimiter:
    def __init__(self, db_path: Path, daily_limit: int = 20) -> None:
        self._db_path = db_path
        self._daily_limit = daily_limit
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def get_status(self, device_id: str) -> QuotaStatus:
        normalized = self._normalize_device_id(device_id)
        quota_date = self._today_utc()

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT used
                FROM daily_quota
                WHERE device_id = ? AND quota_date = ?
                """,
                (normalized, quota_date),
            ).fetchone()

        used = int(row["used"]) if row else 0
        return self._build_status(normalized, quota_date, used)

    def consume(self, device_id: str, amount: int = 1) -> QuotaStatus:
        if amount < 1:
            raise ValueError("amount must be >= 1")

        normalized = self._normalize_device_id(device_id)
        quota_date = self._today_utc()

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT used
                FROM daily_quota
                WHERE device_id = ? AND quota_date = ?
                """,
                (normalized, quota_date),
            ).fetchone()
            current_used = int(row["used"]) if row else 0

            next_used = current_used + amount
            if next_used > self._daily_limit:
                raise QuotaExceededError("Daily trial quota exceeded.")

            if row is None:
                conn.execute(
                    """
                    INSERT INTO daily_quota (device_id, quota_date, used)
                    VALUES (?, ?, ?)
                    """,
                    (normalized, quota_date, next_used),
                )
            else:
                conn.execute(
                    """
                    UPDATE daily_quota
                    SET used = ?
                    WHERE device_id = ? AND quota_date = ?
                    """,
                    (next_used, normalized, quota_date),
                )

        return self._build_status(normalized, quota_date, next_used)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_quota (
                    device_id TEXT NOT NULL,
                    quota_date TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (device_id, quota_date)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _build_status(self, device_id: str, quota_date: str, used: int) -> QuotaStatus:
        remaining = max(0, self._daily_limit - used)
        return QuotaStatus(
            device_id=device_id,
            quota_date=quota_date,
            daily_limit=self._daily_limit,
            used=used,
            remaining=remaining,
            allowed=remaining > 0,
        )

    @staticmethod
    def _normalize_device_id(device_id: str) -> str:
        normalized = device_id.strip()
        if not normalized:
            raise ValueError("device_id is required")
        return normalized

    @staticmethod
    def _today_utc() -> str:
        return datetime.now(timezone.utc).date().isoformat()
