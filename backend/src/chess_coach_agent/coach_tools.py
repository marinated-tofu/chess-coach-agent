from __future__ import annotations

from typing import Any

import chess
from pydantic_ai import RunContext
from sqlalchemy import select

from .db import session_scope
from .db_models import CriticalMomentRow, GameRow, PlayerRow, TrainingPositionRow
from .engine import EngineAnalyzer
from .repositories import player_profile
from .quiz_copy import (
    candidate_payload,
    fetch_practice_candidates,
    generate_quiz_copy_with_llm,
    rank_moments_with_llm,
)
from .training import build_training_session as create_training_plan
from .training import evaluate_attempt, quiz_panel

def inspect_game(ctx: RunContext[Any], game_id: str) -> dict[str, Any]:
    """Inspect one persisted game and its critical moments by external game ID."""
    ctx.deps.record("inspect_game")
    with session_scope() as session:
        game = session.scalar(select(GameRow).where(GameRow.external_game_id == game_id))
        if game is None:
            return {"error": "Game not found"}
        moments = session.scalars(
            select(CriticalMomentRow)
            .where(CriticalMomentRow.game_id == game.id)
            .order_by(CriticalMomentRow.severity.desc())
        ).all()
        return {
            "game_id": game.external_game_id,
            "players": f"{game.white} vs {game.black}",
            "result": game.player_result,
            "rating": game.player_elo,
            "moments": [
                {
                    "move": item.move_number,
                    "theme": item.theme,
                    "played": item.played_san,
                    "best": item.best_san,
                    "severity": item.severity,
                }
                for item in moments
            ],
        }


def inspect_player_moments(
    ctx: RunContext[Any], theme: str = "", limit: int = 10
) -> list[dict[str, Any]]:
    """Return stored critical moments for the attached player profile."""
    ctx.deps.record("inspect_player_moments")
    if not ctx.deps.platform or not ctx.deps.username:
        return []
    with session_scope() as session:
        moments = fetch_practice_candidates(
            session,
            ctx.deps.platform,
            ctx.deps.username,
            theme or ctx.deps.practice_theme,
            limit=min(max(limit, 1), 20),
        )
        return [candidate_payload(item) for item in moments]


def rank_practice_moments(
    ctx: RunContext[Any], theme: str = "", position_count: int = 5
) -> dict[str, Any]:
    """Rank stored practice moments by player weakness before building a session."""
    ctx.deps.record("rank_practice_moments")
    if not ctx.deps.platform or not ctx.deps.username:
        return {"error": "No persistent player profile is attached"}
    selected_theme = theme or ctx.deps.practice_theme
    count = position_count or ctx.deps.practice_position_count
    with session_scope() as session:
        candidates = fetch_practice_candidates(
            session,
            ctx.deps.platform,
            ctx.deps.username,
            selected_theme,
            limit=20,
        )
        if not candidates:
            return {"error": "Analyze games with engine candidates before ranking practice"}
        ranked, _ = rank_moments_with_llm(
            session,
            ctx.deps.platform,
            ctx.deps.username,
            candidates,
            count,
        )
        ctx.deps.ranked_moment_ids = ranked
        return {"moment_ids": ranked, "count": len(ranked)}


def write_quiz_copy(ctx: RunContext[Any], plan_id: str = "") -> dict[str, Any]:
    """Write grounded quiz prompts and hints for each position in a training plan."""
    ctx.deps.record("write_quiz_copy")
    selected_plan = plan_id or ctx.deps.plan_id
    if not selected_plan:
        return {"error": "No training plan is attached"}
    with session_scope() as session:
        positions = session.scalars(
            select(TrainingPositionRow)
            .where(TrainingPositionRow.plan_id == selected_plan)
            .order_by(TrainingPositionRow.position_order)
        ).all()
        if not positions:
            return {"error": "Training plan has no positions"}
        copies = []
        for position in positions:
            moment = session.get(CriticalMomentRow, position.moment_id) if position.moment_id else None
            explanation = (moment.explanation or {}) if moment else {}
            prompt, hint, _ = generate_quiz_copy_with_llm(
                position.theme,
                position.explanation or explanation.get("what_happened", ""),
                explanation.get("principle", ""),
                position.difficulty,
            )
            position.prompt = prompt
            position.hint = hint
            copies.append({"position_id": position.id, "prompt": prompt, "hint": hint})
        session.flush()
        return {"plan_id": selected_plan, "positions": copies}


def compare_moves(
    ctx: RunContext[Any], fen: str, candidate_moves: list[str]
) -> list[dict[str, Any]]:
    """Compare legal candidate moves with Stockfish from a supplied FEN."""
    ctx.deps.record("compare_moves")
    board = chess.Board(fen)
    pov = board.turn
    analyzer = EngineAnalyzer()
    results = []
    try:
        for candidate in candidate_moves[:6]:
            try:
                move = board.parse_san(candidate)
            except ValueError:
                try:
                    move = chess.Move.from_uci(candidate)
                except ValueError:
                    results.append({"move": candidate, "legal": False})
                    continue
            if move not in board.legal_moves:
                results.append({"move": candidate, "legal": False})
                continue
            after = board.copy(stack=False)
            san = after.san(move)
            after.push(move)
            score = analyzer.analyse(after, pov).score_cp
            results.append(
                {"move": san, "legal": True, "evaluation_pawns": score / 100 if score is not None else None}
            )
    finally:
        analyzer.close()
    return sorted(results, key=lambda item: item.get("evaluation_pawns") or -999, reverse=True)


def generate_position_quiz(
    ctx: RunContext[Any], theme: str = "", difficulty: str = "intermediate"
) -> dict[str, Any]:
    """Generate a board quiz from the player's own analyzed critical moments."""
    ctx.deps.record("generate_position_quiz")
    if not ctx.deps.platform or not ctx.deps.username:
        return {"error": "No persistent player profile is attached"}
    with session_scope() as session:
        plan = create_training_plan(session, ctx.deps.platform, ctx.deps.username, theme or None, 5)
        if difficulty in {"beginner", "intermediate", "advanced"}:
            plan.difficulty = difficulty
        panel = quiz_panel(session, plan.id)
        if panel is None:
            return {"error": "Analyze games with engine candidates before creating a quiz"}
        ctx.deps.panel = panel
        return panel.model_dump(mode="json")


def evaluate_candidate_move(
    ctx: RunContext[Any], position_id: str, move: str
) -> dict[str, Any]:
    """Grade a move in a saved training position with legality and Stockfish evidence."""
    ctx.deps.record("evaluate_candidate_move")
    with session_scope() as session:
        panel = evaluate_attempt(session, position_id, move)
        ctx.deps.panel = panel
        return panel.model_dump(mode="json")


def build_training_session(
    ctx: RunContext[Any], player_profile_hint: str = ""
) -> dict[str, Any]:
    """Open the next adaptive quiz from the player's weakness and quiz history."""
    del player_profile_hint
    ctx.deps.record("build_training_session")
    if not ctx.deps.platform or not ctx.deps.username:
        return {"error": "No persistent player profile is attached"}
    with session_scope() as session:
        plan = create_training_plan(
            session,
            ctx.deps.platform,
            ctx.deps.username,
            ctx.deps.practice_theme,
            ctx.deps.practice_position_count,
            ordered_moment_ids=ctx.deps.ranked_moment_ids or None,
            mode=ctx.deps.practice_mode,
        )
        player = session.get(PlayerRow, plan.player_id)
        panel = quiz_panel(session, plan.id)
        if panel is None or player is None:
            return {"error": "Analyze games with engine candidates before starting training"}
        ctx.deps.plan_id = plan.id
        ctx.deps.panel = panel
        return {
            "plan_id": plan.id,
            "panel": panel.model_dump(mode="json"),
            "player": player_profile(session, player).model_dump(mode="json"),
        }
