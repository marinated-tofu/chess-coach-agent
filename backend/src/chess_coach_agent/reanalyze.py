"""Re-analyze stored games in place with the current ``ANALYSIS_VERSION``.

    python -m chess_coach_agent.reanalyze --username kfctofu --platform chess.com --limit 20

Games are rebuilt from the moves stored in ``games.metadata_json`` (no network), analyzed
again, and written back through ``persist_analyses``, so the game row, its analysis row and
its critical moments are updated, not duplicated. Games already at the current version are
skipped unless ``--force`` is given. Clock times survive only if the stored moves already
have them; games stored before clocks were parsed need a platform sync to get clocks.
Uses ``DATABASE_URL`` like the API.
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import select

from .analysis import ANALYSIS_VERSION, analyze_parsed_game
from .db import init_db, session_scope
from .db_models import AnalysisRow, GameRow, PlayerRow
from .engine import EngineAnalyzer
from .models import AnalyzeResponse, GameMetadata, MoveRecord
from .pgn import parsed_game_from_moves
from .repositories import normalize_username, persist_analyses

_BASE_MOVE_FIELDS = (
    "ply",
    "move_number",
    "color",
    "san",
    "uci",
    "fen_before",
    "fen_after",
    "is_player_move",
    "clock_seconds",
)


def _stale_game_ids(platform: str, username: str, limit: int | None, force: bool) -> list[str]:
    with session_scope() as session:
        player = session.scalar(
            select(PlayerRow).where(
                PlayerRow.platform == platform,
                PlayerRow.username_normalized == normalize_username(username),
            )
        )
        if player is None:
            return []
        rows = session.execute(
            select(GameRow.id, AnalysisRow.retrieval_notes)
            .outerjoin(AnalysisRow, AnalysisRow.game_id == GameRow.id)
            .where(GameRow.player_id == player.id)
            .order_by(GameRow.played_at.desc(), GameRow.created_at.desc())
        ).all()
    ids = [game_id for game_id, notes in rows if force or ANALYSIS_VERSION not in (notes or [])]
    return ids[:limit] if limit is not None else ids


def reanalyze_game(
    game_row_id: str, platform: str, username: str, analyzer: EngineAnalyzer
) -> int:
    """Re-analyze one stored game; returns its ply count (0 if it has no stored moves)."""
    with session_scope() as session:
        game = session.get(GameRow, game_row_id)
        if game is None:
            return 0
        stored = game.metadata_json or {}
        game_payload = dict(stored.get("game", stored))
        game_payload["game_id"] = game.external_game_id
        metadata = GameMetadata.model_validate(game_payload)
        moves = [
            MoveRecord.model_validate({k: v for k, v in item.items() if k in _BASE_MOVE_FIELDS})
            for item in stored.get("moves", [])
        ]
    if not moves:
        return 0
    parsed = parsed_game_from_moves(metadata, moves)
    analysis = analyze_parsed_game(parsed, player=username, analyzer=analyzer)
    with session_scope() as session:
        persist_analyses(session, platform, username, AnalyzeResponse(analyses=[analysis]))
    return len(moves)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", required=True)
    parser.add_argument("--platform", required=True, choices=["chess.com", "lichess", "pgn"])
    parser.add_argument("--limit", type=int, default=None, help="most recent N games only")
    parser.add_argument("--force", action="store_true", help="also redo games at the current version")
    args = parser.parse_args(argv)

    init_db()
    game_ids = _stale_game_ids(args.platform, args.username, args.limit, args.force)
    print(f"{len(game_ids)} game(s) to re-analyze to {ANALYSIS_VERSION}")
    analyzer = EngineAnalyzer()
    started = time.perf_counter()
    done = failed = plies = 0
    try:
        for index, game_id in enumerate(game_ids, start=1):
            game_started = time.perf_counter()
            try:
                game_plies = reanalyze_game(game_id, args.platform, args.username, analyzer)
            except Exception as exc:  # keep going; one bad game must not stop the backfill
                failed += 1
                print(f"[{index}/{len(game_ids)}] {game_id} failed: {exc}")
                continue
            done += 1
            plies += game_plies
            print(
                f"[{index}/{len(game_ids)}] {game_id} {game_plies} plies "
                f"{time.perf_counter() - game_started:.2f}s"
            )
    finally:
        analyzer.close()
    elapsed = time.perf_counter() - started
    per_game = elapsed / done if done else 0.0
    print(
        f"Re-analyzed {done} game(s), {failed} failed, {plies} plies in {elapsed:.1f}s "
        f"({per_game:.2f}s/game)"
    )


if __name__ == "__main__":
    main()
