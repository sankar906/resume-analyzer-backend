"""Initialize and verify the asyncpg pool at startup."""

import logging

from src.db.manager import db_manager

logger = logging.getLogger(__name__)


async def init_db() -> None:
    try:
        pool = await db_manager.init_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        logger.info("database ready")
    except Exception:
        logger.exception("database init failed")
        raise
