from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .env_bootstrap import load_project_env  # noqa: F401 — loads backend/.env on import

from .agent import ChessCoachAgent, sample_pgn
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    FeedbackRequest,
)
from .monitoring import log_event, monitoring_summary
from .adaptive_api import router as adaptive_router
from .openings_api import router as openings_router
from .endgames_api import router as endgames_router
from .engine_api import router as engine_router
from .bots_api import router as bots_router
from .insights_api import router as insights_router
from .vision_api import router as vision_router
from .auth_api import router as auth_router
from .account_api import router as account_router
from .export_api import router as export_router
from .explorer_api import router as explorer_router
from .repertoire_api import router as repertoire_router
from .study_plan_api import router as study_plan_router
from .today_api import router as today_router
from .library_api import router as library_router
from .puzzles_api import router as puzzles_router
from .accounts import Viewer, require_access
from .db import init_db, session_scope
from .repositories import persist_analyses


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Chess Coach Agent API", version="0.2.0", lifespan=lifespan)
agent = ChessCoachAgent()
app.include_router(adaptive_router)
app.include_router(openings_router)
app.include_router(engine_router)
app.include_router(endgames_router)
app.include_router(bots_router)
app.include_router(insights_router)
app.include_router(vision_router)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(export_router)
app.include_router(explorer_router)
app.include_router(repertoire_router)
app.include_router(study_plan_router)
app.include_router(today_router)
app.include_router(library_router)
app.include_router(puzzles_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/llm/status")
def llm_status() -> dict[str, object]:
    from .llm import _openrouter_model
    from .openrouter_client import model_name, request_timeout

    configured = bool(os.getenv("OPENROUTER_API_KEY"))
    return {
        "configured": configured,
        "model": model_name() if configured else None,
        "timeout_seconds": request_timeout(),
        "pydantic_agent_ready": _openrouter_model() is not None if configured else False,
        "practice_path": "pydantic_agent" if configured else "deterministic_fallback",
    }


@app.get("/api/sample")
def sample() -> dict[str, str]:
    return {"player": "kfctofu", "pgn": sample_pgn()}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest, user_id: Viewer) -> AnalyzeResponse:
    # Pasted games go into the player's library, so a claimed player only takes them from its owner.
    with session_scope() as session:
        require_access(session, request.platform, request.player, user_id)
    log_event("analysis_requested", {"player": request.player, "max_games": request.max_games})
    started = time.perf_counter()
    response = agent.import_pgn_text(request.pgn, player=request.player, max_games=request.max_games)
    if not response.analyses:
        raise HTTPException(422, "No games with moves were found in the pasted PGN.")
    with session_scope() as session:
        persist_analyses(session, request.platform, request.player, response)
    log_event(
        "analysis_timing",
        {"duration_ms": round((time.perf_counter() - started) * 1000, 2), "games": len(response.analyses)},
    )
    return response


@app.post("/api/feedback")
def feedback(request: FeedbackRequest) -> dict[str, str]:
    log_event("moment_feedback", request.model_dump())
    return {"status": "recorded"}


@app.get("/api/monitoring")
def monitoring() -> dict:
    summary = monitoring_summary()
    # This page is public; events carry coach questions and answers, feedback and usernames.
    summary["recent_events"] = [
        {key: event.get(key) for key in ("timestamp", "event_type")}
        for event in summary["recent_events"]
    ]
    return summary


frontend_value = os.getenv("FRONTEND_DIST", "")
frontend_dist = Path(frontend_value) if frontend_value else None
if frontend_dist and (frontend_dist / "index.html").exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        requested = (frontend_dist / full_path).resolve()
        if requested.is_relative_to(frontend_dist.resolve()) and requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend_dist / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def local_frontend() -> RedirectResponse:
        return RedirectResponse("http://127.0.0.1:5173/")
