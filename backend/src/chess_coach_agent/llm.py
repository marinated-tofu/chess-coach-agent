from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any

import chess
import logfire
from .env_bootstrap import load_project_env  # noqa: F401
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from .annotations import apply_annotations
from .engine import EngineAnalyzer
from .knowledge import retrieve_notes
from .models import CoachAnalysis, CoachAskResponse, CoachPanel, CoachingOutput
from .coach_tools import (
    build_training_session,
    compare_moves,
    evaluate_candidate_move,
    generate_position_quiz,
    inspect_game,
    inspect_player_moments,
    rank_practice_moments,
    write_quiz_copy,
)


from .openrouter_client import (
    OPENROUTER_BASE_URL,
    OPENROUTER_URL,
    complete_with_openrouter,
    model_name,
)
logfire.configure(
    service_name="chess-coach-agent",
    send_to_logfire="if-token-present",
    console=False,
)
logfire.instrument_pydantic_ai()


@dataclass
class CoachDependencies:
    analysis: CoachAnalysis | None = None
    player_id: str | None = None
    platform: str | None = None
    username: str | None = None
    session_id: str | None = None
    panel: CoachPanel | None = None
    plan_id: str | None = None
    practice_theme: str | None = None
    practice_position_count: int = 5
    practice_mode: str = "mixed"
    ranked_moment_ids: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    retrieved_titles: list[str] = field(default_factory=list)

    def record(self, tool_name: str) -> None:
        self.tools_used.append(tool_name)


def _model_name() -> str:
    return model_name()


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    input_rate = float(os.getenv("OPENROUTER_INPUT_COST_PER_MILLION", "0.10"))
    output_rate = float(os.getenv("OPENROUTER_OUTPUT_COST_PER_MILLION", "0.50"))
    return round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 8)


def _openrouter_model() -> OpenAIChatModel | None:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    provider = OpenAIProvider(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    settings = OpenAIChatModelSettings(
        timeout=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30")),
        extra_body={"provider": {"sort": "throughput"}},
    )
    return OpenAIChatModel(_model_name(), provider=provider, settings=settings)  # type: ignore[arg-type]


def search_chess_principles(ctx: RunContext[CoachDependencies], query: str) -> list[dict[str, Any]]:
    """Search the evaluated chess knowledge base for principles relevant to the question."""
    ctx.deps.record("search_chess_principles")
    notes = retrieve_notes(query, top_k=3)
    ctx.deps.retrieved_titles.extend(note.title for note in notes)
    return [
        {"title": note.title, "snippet": note.snippet, "retrieval_score": note.score}
        for note in notes
    ]


def inspect_critical_moments(ctx: RunContext[CoachDependencies]) -> list[dict[str, Any]]:
    """Return grounded engine and heuristic facts from the current or stored game."""
    ctx.deps.record("inspect_critical_moments")
    if not ctx.deps.analysis and ctx.deps.platform and ctx.deps.username:
        return inspect_player_moments(ctx)
    if not ctx.deps.analysis:
        return []
    return [
        {
            "move_number": moment.move_number,
            "phase": moment.phase,
            "theme": moment.theme,
            "played_move": moment.played_san,
            "engine_candidate": moment.best_san,
            "evaluation_swing": moment.eval_swing,
            "principle": moment.principle,
        }
        for moment in ctx.deps.analysis.moments[:4]
    ]


def inspect_position(ctx: RunContext[CoachDependencies], fen: str) -> dict[str, Any]:
    """Inspect a legal FEN with Stockfish and list immediate forcing moves."""
    ctx.deps.record("inspect_position")
    try:
        board = chess.Board(fen)
    except ValueError:
        return {"error": "The supplied FEN is invalid."}

    analyzer = EngineAnalyzer()
    try:
        line = analyzer.analyse(board, board.turn)
    finally:
        analyzer.close()
    best_move = board.san(line.best_move) if line.best_move in board.legal_moves else None
    checks = [board.san(move) for move in board.legal_moves if board.gives_check(move)][:8]
    captures = [board.san(move) for move in board.legal_moves if board.is_capture(move)][:8]
    return {
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "best_move": best_move,
        "evaluation_pawns": line.score_cp / 100 if line.score_cp is not None else None,
        "checks": checks,
        "captures": captures,
    }


def build_training_drill(ctx: RunContext[CoachDependencies], theme: str = "") -> dict[str, str]:
    """Build a concrete drill from the dominant weakness in the current game."""
    ctx.deps.record("build_training_drill")
    moment = ctx.deps.analysis.moments[0] if ctx.deps.analysis and ctx.deps.analysis.moments else None
    selected_theme = theme or (moment.theme if moment else "candidate_move_discipline")
    prompt = (
        moment.drill_prompt
        if moment
        else "Solve five positions and write every check, capture, and threat before moving."
    )
    return {"theme": selected_theme, "exercise": prompt}


COACH_INSTRUCTIONS = dedent(
    """
    You are a precise chess improvement coach. Relevant player memory and game positions may
    already be included in the verified context. Use tools only when the question needs evidence
    not already present; do not call tools merely to satisfy a quota.
    Treat engine evaluations, legal moves, and supplied game facts as evidence; never invent a
    variation or claim a move is forced without support. Separate what the player did from the
    reusable lesson. Give one manageable drill. When the user asks to practice, inspect stored moments, rank
    them by weakness, create a training session from stored games, then write quiz prompts and
    hints. Use saved-game tools instead of inventing positions. Return the requested structured coaching object.
    You may add `arrows` and `highlights` for the position on the player's board (the FEN in
    the context). Arrows of kind best, played, or threat must be legal moves in that FEN; illegal
    ones are removed before the player sees them. Use at most 4 arrows and 4 highlights, and
    leave both empty when the answer is not about that position.
    Write for a person, not a program. Never put a FEN string in the answer, evidence,
    principle, or drill: describe positions in words ("after 14...Nf6, with your queen on d1")
    and name moves in SAN. A drill states the task and what to look for; it never gives away
    the move that solves it.
    """
).strip()


def create_coach_agent(
    model: Any = None, instructions: str | None = None
) -> Agent[CoachDependencies, CoachingOutput]:
    selected_model = model if model is not None else _openrouter_model()
    return Agent(
        selected_model,
        deps_type=CoachDependencies,
        output_type=CoachingOutput,
        instructions=instructions or COACH_INSTRUCTIONS,
        tools=[
            search_chess_principles,
            inspect_critical_moments,
            inspect_player_moments,
            inspect_position,
            build_training_drill,
            inspect_game,
            compare_moves,
            rank_practice_moments,
            generate_position_quiz,
            evaluate_candidate_move,
            build_training_session,
            write_quiz_copy,
        ],
        retries=1,
    )


def _coach_prompt(
    question: str, analysis: CoachAnalysis | None, fen: str | None, memory_context: str
) -> str:
    sections = [f"Question:\n{question}"]
    if analysis:
        moments = "\n".join(
            f"- move {moment.move_number}: played {moment.played_san}; candidate "
            f"{moment.best_san or 'unknown'}; theme {moment.theme}; FEN {moment.fen_before}"
            for moment in analysis.moments[:4]
        )
        sections.append(
            f"Selected game: {analysis.game.white} vs {analysis.game.black} "
            f"(game id {analysis.game.game_id}), player result {analysis.game.player_result}\n"
            f"Critical moments:\n{moments or '- none detected'}"
        )
    if fen:
        sections.append(f"Position on the player's board (FEN): {fen}")
    if memory_context:
        sections.append(f"Verified player memory:\n{memory_context}")
    return "\n\n".join(sections)


def _fallback_coaching(
    question: str, analysis: CoachAnalysis | None, fen: str | None = None
) -> CoachingOutput:
    notes = retrieve_notes(question, top_k=1)
    principle = notes[0].snippet if notes else "Start with checks, captures, and threats."
    if analysis and analysis.moments:
        # Prefer the moment on the player's board over the game's first mistake.
        moment = next(
            (m for m in analysis.moments if fen and m.fen_before.split()[:4] == fen.split()[:4]),
            analysis.moments[0],
        )
        return CoachingOutput(
            answer=(
                f"The coach model is unavailable, so here is the engine-backed lesson: around move "
                f"{moment.move_number} you played {moment.played_san}; "
                f"{moment.best_san or 'the engine candidate'} was stronger "
                f"(**{moment.theme.replace('_', ' ')}**)."
            ),
            evidence=[moment.summary],
            recommended_move=moment.best_san,
            principle=moment.principle,
            drill=moment.drill_prompt,
            confidence=0.5,
        )
    return CoachingOutput(
        answer="The coach model is unavailable right now. Open a game so I can point at your own positions.",
        evidence=[principle],
        principle=principle,
        drill="Solve five positions and list every check, capture, and threat before choosing a move.",
        confidence=0.3,
    )


async def ask_coach(
    question: str,
    analysis: CoachAnalysis | None,
    *,
    fen: str | None = None,
    platform: str | None = None,
    username: str | None = None,
    memory_context: str = "",
    message_history: list[dict[str, Any]] | None = None,
    model: Any = None,
    instructions: str | None = None,
) -> CoachAskResponse:
    selected_model = model if model is not None else _openrouter_model()
    if selected_model is None:
        coaching = _fallback_coaching(question, analysis, fen)
        return _annotated(
            CoachAskResponse(
                answer=coaching.answer,
                coaching=coaching,
                used_llm=False,
                fallback_reason="no_api_key",
            ),
            fen,
        )

    deps = CoachDependencies(analysis=analysis, platform=platform, username=username)
    history = ModelMessagesTypeAdapter.validate_python(message_history) if message_history else None
    try:
        with logfire.span("coach_ask", model=_model_name(), has_analysis=analysis is not None):
            result = await asyncio.wait_for(
                create_coach_agent(selected_model, instructions).run(
                    _coach_prompt(question, analysis, fen, memory_context),
                    deps=deps,
                    message_history=history,
                ),
                timeout=float(os.getenv("COACH_TIMEOUT_SECONDS", "60")),
            )
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"[:300]
        logfire.warn("coach_ask_failed", error=reason)
        coaching = _fallback_coaching(question, analysis, fen)
        return _annotated(
            CoachAskResponse(
                answer=coaching.answer, coaching=coaching, used_llm=False, fallback_reason=reason
            ),
            fen,
        )

    response = CoachAskResponse(
        answer=result.output.answer,
        coaching=result.output,
        used_llm=True,
        tools_used=list(dict.fromkeys(deps.tools_used)),
        retrieved_notes=list(dict.fromkeys(deps.retrieved_titles)),
        message_history=ModelMessagesTypeAdapter.dump_python(result.all_messages(), mode="json"),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
    )
    return _annotated(response, fen)


_FEN_RANKS = r"[pnbrqkPNBRQK1-8]{1,8}(?:/[pnbrqkPNBRQK1-8]{1,8}){7}"
_FEN_TAIL = r"(?:\s+[wb](?:\s+(?:-|[KQkq]{1,4}))?(?:\s+(?:-|[a-h][36]))?(?:\s+\d+){0,2})?"
_FEN_BODY = rf"`?(?<![\w/]){_FEN_RANKS}{_FEN_TAIL}`?"
# "(FEN: ...)" asides add nothing once the FEN is gone, so they go entirely.
_FEN_ASIDE_RE = re.compile(rf"\s*[(\[]\s*(?:FEN\b:?\s*)?{_FEN_BODY}\s*[)\]]", re.IGNORECASE)
_FEN_RE = re.compile(rf"(?:\bFEN\b:?\s*)?{_FEN_BODY}", re.IGNORECASE)


def scrub_fen(text: str) -> str:
    """Replace FEN strings in coach prose with plain words; the board already shows the position."""
    if "/" not in text:
        return text
    cleaned = _FEN_ASIDE_RE.sub("", text)
    cleaned = _FEN_RE.sub("this position", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r" +([.,;:])", r"\1", cleaned)


def _scrub_coaching(coaching: CoachingOutput) -> CoachingOutput:
    return coaching.model_copy(
        update={
            "answer": scrub_fen(coaching.answer),
            "evidence": [scrub_fen(item) for item in coaching.evidence],
            "principle": scrub_fen(coaching.principle),
            "drill": scrub_fen(coaching.drill),
        }
    )


def _annotated(response: CoachAskResponse, fen: str | None) -> CoachAskResponse:
    """Keep only board arrows and highlights that python-chess confirms for the FEN, and
    replace any FEN the model wrote into the prose."""
    coaching, dropped = apply_annotations(_scrub_coaching(response.coaching), fen)
    if dropped:
        logfire.info("coach_annotations_dropped", dropped=dropped)
    return response.model_copy(
        update={
            "answer": coaching.answer,
            "coaching": coaching,
            "arrows": coaching.arrows,
            "highlights": coaching.highlights,
            "annotations_dropped": dropped,
        }
    )


__all__ = [
    "OPENROUTER_BASE_URL",
    "OPENROUTER_URL",
    "CoachDependencies",
    "ask_coach",
    "complete_with_openrouter",
    "create_coach_agent",
    "estimate_cost",
    "scrub_fen",
]
