from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .db_models import TrainingPlanRow
from .llm import CoachDependencies, _openrouter_model, create_coach_agent
from .quiz_copy import apply_llm_quiz_copy, fetch_practice_candidates, rank_moments_with_llm
from .training import apply_default_quiz_copy, build_due_session, build_training_session

logger = logging.getLogger(__name__)


PRACTICE_AGENT_PROMPT = (
    "Build my next practice session from stored mistakes in my game history. "
    "Inspect my stored critical moments, rank them by my recurring weaknesses, "
    "create the training session, then write grounded quiz prompts and hints "
    "for each position. Do not invent positions or moves."
)


@dataclass
class PracticeAgentResult:
    plan: TrainingPlanRow
    used_llm: bool
    fallback: bool
    tools_used: list[str]
    duration_ms: int


async def run_practice_agent(
    session: Session,
    platform: str,
    username: str,
    theme: str | None = None,
    position_count: int = 5,
    moment_id: str | None = None,
    mode: str = "mixed",
) -> PracticeAgentResult:
    started = time.perf_counter()
    deps = CoachDependencies(
        platform=platform,
        username=username,
        practice_theme=theme,
        practice_position_count=position_count,
        practice_mode=mode,
    )
    if moment_id:
        plan = build_training_session(
            session,
            platform,
            username,
            theme,
            position_count,
            moment_id,
            mode=mode,
        )
        apply_default_quiz_copy(session, plan.id)
        return PracticeAgentResult(
            plan=plan,
            used_llm=False,
            fallback=True,
            tools_used=[],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    if mode == "due":
        plan = build_due_session(session, platform, username, position_count)
        if plan is not None:
            return PracticeAgentResult(
                plan=plan,
                used_llm=False,
                fallback=True,
                tools_used=[],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        mode = "mixed"

    # Puzzle-only sessions have nothing from the player's games to rank.
    if mode != "puzzles" and os.getenv("OPENROUTER_API_KEY") and _openrouter_model() is not None:
        try:
            agent = create_coach_agent()
            await agent.run(PRACTICE_AGENT_PROMPT, deps=deps)
            plan_id = deps.plan_id
            if plan_id is None and deps.panel is not None:
                plan_id = getattr(deps.panel, "training_session_id", None)
            if plan_id is None:
                raise RuntimeError("Practice agent did not create a training session")
            plan = session.get(TrainingPlanRow, plan_id)
            if plan is None:
                raise RuntimeError("Training plan missing after agent run")
            if "write_quiz_copy" not in deps.tools_used:
                apply_llm_quiz_copy(session, plan.id)
            return PracticeAgentResult(
                plan=plan,
                used_llm=True,
                fallback=False,
                tools_used=list(deps.tools_used),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception:
            logger.exception("Practice agent failed; using deterministic fallback")

    candidates = fetch_practice_candidates(session, platform, username, theme, limit=20)
    ranked, rank_used_llm = rank_moments_with_llm(
        session, platform, username, candidates, position_count
    )
    plan = build_training_session(
        session,
        platform,
        username,
        theme,
        position_count,
        moment_id,
        ordered_moment_ids=ranked or None,
        mode=mode,
    )
    if os.getenv("OPENROUTER_API_KEY"):
        quiz_used_llm = apply_llm_quiz_copy(session, plan.id)
    else:
        apply_default_quiz_copy(session, plan.id)
        quiz_used_llm = False
    return PracticeAgentResult(
        plan=plan,
        used_llm=rank_used_llm or quiz_used_llm,
        fallback=True,
        tools_used=[],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
