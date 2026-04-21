"""asyncpg connection pool and PostgreSQL function execution."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import asyncpg

from src.core.config import get_settings

logger = logging.getLogger(__name__)

_UUID_STR = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _encode_arg(value: Any) -> Any:
    """
    - dict / list (non-uuid[]): JSON text via json.dumps for JSON/JSONB parameters.
      This asyncpg build expects str for those binds (raw dict raises \"expected str, got dict\").
      PostgreSQL parses the text as a jsonb *value* (object/array), not a quoted string.
    - list whose items are all UUID instances or UUID-shaped strings: pass as
      Python list[uuid.UUID] so asyncpg binds uuid[] (not JSON text).
    """
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, list):
        if value and all(
            isinstance(x, uuid.UUID)
            or (isinstance(x, str) and _UUID_STR.fullmatch(x) is not None)
            for x in value
        ):
            return [x if isinstance(x, uuid.UUID) else uuid.UUID(x) for x in value]
        # List of plain strings (e.g. text[] for fn_candidates / fn_candidate_eval filters): bind as array, not JSON text.
        if value and all(isinstance(x, str) for x in value):
            return value
        return json.dumps(value)
    return value


class DatabaseManager:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def init_pool(self) -> asyncpg.Pool:
        if self.pool is not None:
            return self.pool
        try:
            s = get_settings()
            self.pool = await asyncpg.create_pool(
                dsn=s.asyncpg_dsn,
                min_size=s.db_pool_min,
                max_size=s.db_pool_max,
            )
            return self.pool
        except Exception:
            logger.exception("create_pool failed")
            raise

    async def execute_function(
        self, function_name: str, *args: Any
    ) -> list[dict[str, Any]]:
        """
        Call a set-returning SQL function: SELECT * FROM schema.fn($1, ...).
        function_name must be a fixed qualified name (e.g. public.fn_job_description).
        """
        if not self.pool:
            await self.init_pool()
        if self.pool is None:
            raise RuntimeError("DB pool is not initialized.")
        placeholders = ", ".join(f"${i + 1}" for i in range(len(args)))
        query = f"SELECT * FROM {function_name}({placeholders})"
        encoded = tuple(_encode_arg(a) for a in args)
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *encoded)
                return [dict(r) for r in rows]
        except Exception:
            logger.exception("execute_function %s failed", function_name)
            raise

    async def close_pool(self) -> None:
        if self.pool is not None:
            try:
                await self.pool.close()
            except Exception:
                logger.exception("close_pool failed")
            finally:
                self.pool = None


db_manager = DatabaseManager()
