"""Readiness checks for /api/health/ready: can this instance reach what it needs to work?"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import chess.engine
from sqlalchemy import text

from .db import session_scope
from .engine import stockfish_path

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 8.0
ENGINE_START_TIMEOUT_SECONDS = 5.0
# The route is public, and each real check starts a process.
STOCKFISH_CACHE_SECONDS = 30.0

_stockfish_lock = threading.Lock()
_stockfish_result: tuple[float, bool] | None = None


def check_database() -> bool:
    with session_scope() as session:
        session.execute(text("SELECT 1"))
    return True


def _start_stockfish() -> bool:
    path = stockfish_path()
    if path is None:
        return False
    engine = chess.engine.SimpleEngine.popen_uci(path, timeout=ENGINE_START_TIMEOUT_SECONDS)
    engine.quit()
    return True


def check_stockfish() -> bool:
    global _stockfish_result
    with _stockfish_lock:
        if _stockfish_result is not None:
            checked_at, passed = _stockfish_result
            if time.monotonic() - checked_at < STOCKFISH_CACHE_SECONDS:
                return passed
        try:
            passed = _start_stockfish()
        except Exception:
            logger.exception("Stockfish did not start")
            passed = False
        _stockfish_result = time.monotonic(), passed
        return passed


async def _run_check(name: str, check) -> str:
    try:
        passed = await asyncio.wait_for(asyncio.to_thread(check), CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.exception("Readiness check %s failed", name)
        return "failed"
    return "ok" if passed else "failed"


async def readiness_checks() -> dict[str, str]:
    database, stockfish = await asyncio.gather(
        _run_check("database", check_database), _run_check("stockfish", check_stockfish)
    )
    return {"database": database, "stockfish": stockfish}
