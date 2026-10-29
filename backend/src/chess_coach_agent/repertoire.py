"""Opening repertoires: a move tree per player and color, seeded from the player's own games,
and a spaced-repetition drill over the player's moves.

Positions are keyed by EPD (FEN without the move counters) so transpositions share a node.
Each row of ``repertoire_moves`` is one edge: the move ``uci`` played from ``parent_fen_epd``.
Only the player's own moves get a review row; opponent moves are context for the drill.

Scheduling is a small SM-2 variant: a correct answer grows the interval (1 day, 3 days, then
interval x ease) and nudges ease up; a wrong one resets the streak, lowers ease and makes
the move due again in ten minutes, so it comes back later in the same session.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

import chess
import chess.engine
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import GameRow, RepertoireMoveRow, RepertoireReviewRow, RepertoireRow
from .engine import stockfish_path

START_EPD = chess.Board().epd()
MAX_SEED_PLY = 12
MIN_SEED_GAMES = 3
OPPONENT_BRANCHES = 3
MIN_SCORE = 0.4
RELEARN_DELAY = timedelta(minutes=10)
FLAGGED = {"inaccuracy": "?!", "mistake": "?", "blunder": "??", "miss": "?"}


class RepertoireError(ValueError):
    pass


def epd_of(fen: str) -> str:
    try:
        return chess.Board(fen).epd()
    except ValueError as exc:
        raise RepertoireError(f"Invalid FEN: {fen}") from exc


def board_from_epd(epd: str) -> chess.Board:
    board = chess.Board()
    board.set_epd(epd)
    return board


def color_bool(color: str) -> bool:
    return chess.WHITE if color == "white" else chess.BLACK


def parse_move(board: chess.Board, move: str) -> chess.Move:
    text = move.strip()
    try:
        parsed = chess.Move.from_uci(text)
        if parsed in board.legal_moves:
            return parsed
    except ValueError:
        pass
    try:
        return board.parse_san(text)
    except ValueError as exc:
        raise RepertoireError(f"{text} is not a legal move here") from exc


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- editing


def add_move(
    session: Session,
    rep: RepertoireRow,
    parent_fen: str,
    move: str,
    comment: str = "",
    mistake_count: int = 0,
) -> tuple[RepertoireMoveRow, bool]:
    """Add one legal move; returns (row, created). Existing edges are returned unchanged."""
    board = board_from_epd(epd_of(parent_fen))
    parsed = parse_move(board, move)
    parent_epd = board.epd()
    existing = session.scalar(
        select(RepertoireMoveRow).where(
            RepertoireMoveRow.repertoire_id == rep.id,
            RepertoireMoveRow.parent_fen_epd == parent_epd,
            RepertoireMoveRow.uci == parsed.uci(),
        )
    )
    if existing:
        if comment and not existing.comment:
            existing.comment = comment
        return existing, False
    san = board.san(parsed)
    board.push(parsed)
    row = RepertoireMoveRow(
        repertoire_id=rep.id,
        parent_fen_epd=parent_epd,
        san=san,
        uci=parsed.uci(),
        fen_after=board.epd(),
        comment=comment,
        mistake_count=mistake_count,
    )
    session.add(row)
    session.flush()
    if board_from_epd(parent_epd).turn == color_bool(rep.color):
        session.add(
            RepertoireReviewRow(move_id=row.id, due_at=_now(), interval_days=0, ease=2.5, streak=0)
        )
    return row, True


def remove_move(session: Session, rep: RepertoireRow, move_id: str) -> int:
    """Delete a move and every move that is only reachable through it. Returns rows removed."""
    moves = _moves(session, rep.id)
    target = next((m for m in moves if m.id == move_id), None)
    if target is None:
        raise RepertoireError("Move not found")
    remaining = [m for m in moves if m.id != move_id]
    reachable = _reachable_ids(remaining)
    doomed = [m for m in moves if m.id == move_id or m.id not in reachable]
    for row in doomed:
        session.delete(row)
    session.flush()
    return len(doomed)


def _moves(session: Session, rep_id: str) -> list[RepertoireMoveRow]:
    return list(
        session.scalars(
            select(RepertoireMoveRow)
            .where(RepertoireMoveRow.repertoire_id == rep_id)
            .order_by(RepertoireMoveRow.created_at, RepertoireMoveRow.id)
        )
    )


def _reachable_ids(moves: Iterable[RepertoireMoveRow]) -> set[str]:
    by_parent: dict[str, list[RepertoireMoveRow]] = defaultdict(list)
    for m in moves:
        by_parent[m.parent_fen_epd].append(m)
    seen_pos = {START_EPD}
    stack = [START_EPD]
    ids: set[str] = set()
    while stack:
        epd = stack.pop()
        for m in by_parent.get(epd, []):
            ids.add(m.id)
            if m.fen_after not in seen_pos:
                seen_pos.add(m.fen_after)
                stack.append(m.fen_after)
    return ids


# --------------------------------------------------------------------------- tree


def build_tree(session: Session, rep: RepertoireRow) -> list[dict[str, Any]]:
    """Nested children from the start position. A transposed position is expanded once."""
    moves = _moves(session, rep.id)
    reviews = (
        {
            r.move_id: r
            for r in session.scalars(
                select(RepertoireReviewRow).where(
                    RepertoireReviewRow.move_id.in_([m.id for m in moves])
                )
            )
        }
        if moves
        else {}
    )
    by_parent: dict[str, list[RepertoireMoveRow]] = defaultdict(list)
    for m in moves:
        by_parent[m.parent_fen_epd].append(m)
    player = color_bool(rep.color)
    expanded: set[str] = set()
    now = _now()

    def node(m: RepertoireMoveRow, ply: int) -> dict[str, Any]:
        review = reviews.get(m.id)
        out = {
            "id": m.id,
            "san": m.san,
            "uci": m.uci,
            "ply": ply,
            "parent_fen": m.parent_fen_epd,
            "fen_after": m.fen_after,
            "comment": m.comment,
            "mistake_count": m.mistake_count,
            "is_player_move": board_from_epd(m.parent_fen_epd).turn == player,
            "due": bool(review and _aware(review.due_at) <= now),
            "streak": review.streak if review else None,
            "transposition": m.fen_after in expanded,
            "children": [],
        }
        if m.fen_after not in expanded:
            expanded.add(m.fen_after)
            out["children"] = [node(c, ply + 1) for c in by_parent.get(m.fen_after, [])]
        return out

    expanded.add(START_EPD)
    return [node(m, 1) for m in by_parent.get(START_EPD, [])]


def count_due(session: Session, rep: RepertoireRow) -> int:
    return len(_due_reviews(session, rep, include_all=False))


def _due_reviews(
    session: Session, rep: RepertoireRow, include_all: bool
) -> list[tuple[RepertoireReviewRow, RepertoireMoveRow]]:
    query = (
        select(RepertoireReviewRow, RepertoireMoveRow)
        .join(RepertoireMoveRow, RepertoireMoveRow.id == RepertoireReviewRow.move_id)
        .where(RepertoireMoveRow.repertoire_id == rep.id)
        .order_by(RepertoireReviewRow.due_at)
    )
    if not include_all:
        query = query.where(RepertoireReviewRow.due_at <= _now())
    reachable = _reachable_ids(_moves(session, rep.id))
    return [(r, m) for r, m in session.execute(query).all() if m.id in reachable]


# --------------------------------------------------------------------------- drill


def _paths(moves: list[RepertoireMoveRow]) -> dict[str, list[RepertoireMoveRow]]:
    """Shortest move sequence from the start position to each position in the tree."""
    by_parent: dict[str, list[RepertoireMoveRow]] = defaultdict(list)
    for m in moves:
        by_parent[m.parent_fen_epd].append(m)
    paths: dict[str, list[RepertoireMoveRow]] = {START_EPD: []}
    queue = [START_EPD]
    while queue:
        epd = queue.pop(0)
        for m in by_parent.get(epd, []):
            if m.fen_after not in paths:
                paths[m.fen_after] = paths[epd] + [m]
                queue.append(m.fen_after)
    return paths


def drill_items(
    session: Session, rep: RepertoireRow, limit: int = 10, include_all: bool = False
) -> list[dict[str, Any]]:
    due = _due_reviews(session, rep, include_all=include_all)
    paths = _paths(_moves(session, rep.id))
    items = []
    for review, move in due[:limit]:
        path = paths.get(move.parent_fen_epd, [])
        board = chess.Board()
        for step in path:
            board.push_uci(step.uci)
        items.append(
            {
                "move_id": move.id,
                "fen": board.fen(),
                "line": [step.san for step in path],
                "line_uci": [step.uci for step in path],
                "last_move": path[-1].uci if path else None,
                "due_at": _aware(review.due_at).isoformat(),
                "streak": review.streak,
            }
        )
    return items


def schedule(review: RepertoireReviewRow, correct: bool, now: datetime | None = None) -> None:
    now = now or _now()
    if correct:
        review.streak += 1
        if review.streak == 1:
            review.interval_days = 1
        elif review.streak == 2:
            review.interval_days = 3
        else:
            review.interval_days = min(
                180, max(review.interval_days + 1, round(review.interval_days * review.ease))
            )
        review.ease = min(3.0, review.ease + 0.1)
        review.due_at = now + timedelta(days=review.interval_days)
        review.last_result = "correct"
    else:
        review.streak = 0
        review.interval_days = 0
        review.ease = max(1.3, review.ease - 0.2)
        review.due_at = now + RELEARN_DELAY
        review.last_result = "wrong"


def answer(session: Session, rep: RepertoireRow, move_id: str, move: str) -> dict[str, Any]:
    target = session.get(RepertoireMoveRow, move_id)
    review = session.get(RepertoireReviewRow, move_id)
    if target is None or target.repertoire_id != rep.id or review is None:
        raise RepertoireError("Drill move not found")
    board = board_from_epd(target.parent_fen_epd)
    try:
        played = parse_move(board, move)
    except RepertoireError:
        played = None
    accepted = {
        m.uci
        for m in session.scalars(
            select(RepertoireMoveRow).where(
                RepertoireMoveRow.repertoire_id == rep.id,
                RepertoireMoveRow.parent_fen_epd == target.parent_fen_epd,
            )
        )
    }
    correct = played is not None and played.uci() in accepted
    schedule(review, correct)
    session.flush()
    return {
        "correct": correct,
        "played_san": board.san(played) if played else None,
        "expected_san": target.san,
        "expected_uci": target.uci,
        "comment": target.comment,
        "next_due_at": _aware(review.due_at).isoformat(),
        "interval_days": review.interval_days,
        "streak": review.streak,
    }


# --------------------------------------------------------------------------- seeding


@dataclass
class _Visit:
    """One game passing through a position: the result and the move it played next."""

    score: float
    move: dict[str, Any] | None


@dataclass
class SeedReport:
    games_used: int = 0
    added: int = 0
    flagged: list[dict[str, Any]] = field(default_factory=list)


def _game_score(result: str) -> float:
    return {"win": 1.0, "draw": 0.5}.get(result, 0.0)


def _engine_best(board: chess.Board, movetime: float = 0.15) -> chess.Move | None:
    path = stockfish_path()
    if not path:
        return None
    try:
        with chess.engine.SimpleEngine.popen_uci(path) as engine:
            result = engine.play(board, chess.engine.Limit(time=movetime))
            return result.move
    except Exception:
        return None


def seed_from_games(session: Session, rep: RepertoireRow, engine_best=_engine_best) -> SeedReport:
    """Walk the player's games in this color and add their most played, best scoring lines.

    Player to move: the most frequent move whose score is at least 40% (else the most
    frequent). If most games that played it had it labeled an inaccuracy or worse, the
    engine's move goes into the repertoire instead, with a comment, and the line stops
    there. Opponent to move: the top three replies seen in at least three games. A branch
    stops at ply 12 or when fewer than three games reach it.
    """
    player = color_bool(rep.color)
    games = session.scalars(
        select(GameRow).where(GameRow.player_id == rep.player_id, GameRow.player_color == rep.color)
    )
    # position -> list of visits; walking every game once keeps this linear in plies.
    visits: dict[str, list[_Visit]] = defaultdict(list)
    report = SeedReport()
    for game in games:
        moves = (game.metadata_json or {}).get("moves") or []
        if not moves:
            continue
        report.games_used += 1
        score = _game_score(game.player_result)
        board = chess.Board()
        for record in moves[:MAX_SEED_PLY]:
            try:
                move = chess.Move.from_uci(record["uci"])
            except (KeyError, ValueError):
                break
            if move not in board.legal_moves:
                break
            visits[board.epd()].append(_Visit(score, record))
            board.push(move)

    def walk(board: chess.Board, ply: int) -> None:
        if ply >= MAX_SEED_PLY:
            return
        here = visits.get(board.epd(), [])
        if len(here) < MIN_SEED_GAMES:
            return
        by_move: dict[str, list[_Visit]] = defaultdict(list)
        for visit in here:
            by_move[visit.move["uci"]].append(visit)
        ranked = sorted(by_move.items(), key=lambda kv: -len(kv[1]))
        if board.turn == player:
            choice = next(
                (
                    (uci, vs)
                    for uci, vs in ranked
                    if len(vs) >= 2 and sum(v.score for v in vs) / len(vs) >= MIN_SCORE
                ),
                ranked[0],
            )
            uci, vs = choice
            labels = Counter(v.move.get("classification") for v in vs)
            bad = sum(n for label, n in labels.items() if label in FLAGGED)
            if bad and bad * 2 >= len(vs):
                played_san = vs[0].move.get("san") or board.san(chess.Move.from_uci(uci))
                best_uci = Counter(
                    v.move.get("best_uci") for v in vs if v.move.get("best_uci")
                ).most_common(1)
                best = chess.Move.from_uci(best_uci[0][0]) if best_uci else engine_best(board)
                if best is not None and best in board.legal_moves and best.uci() != uci:
                    worst = max(
                        (label for label in labels if label in FLAGGED),
                        key=lambda label: list(FLAGGED).index(label),
                    )
                    best_san = board.san(best)
                    comment = (
                        f"You played {played_san}{FLAGGED[worst]} here {bad} "
                        f"time{'s' if bad != 1 else ''}; the engine prefers {best_san}."
                    )
                    row, created = add_move(
                        session, rep, board.fen(), best.uci(), comment=comment, mistake_count=bad
                    )
                    report.added += int(created)
                    report.flagged.append(
                        {
                            "move_id": row.id,
                            "fen": board.fen(),
                            "played_san": played_san,
                            "best_san": best_san,
                            "times": bad,
                        }
                    )
                    return
            _, created = add_move(session, rep, board.fen(), uci)
            report.added += int(created)
            board.push_uci(uci)
            walk(board, ply + 1)
            board.pop()
        else:
            # A reply the player has no answer for is no use in the drill: only branch where
            # enough games continue and there is room left for the player's move.
            if ply + 1 >= MAX_SEED_PLY:
                return
            for uci, vs in ranked[:OPPONENT_BRANCHES]:
                if len(vs) < MIN_SEED_GAMES:
                    continue
                _, created = add_move(session, rep, board.fen(), uci)
                report.added += int(created)
                board.push_uci(uci)
                walk(board, ply + 1)
                board.pop()

    walk(chess.Board(), 0)
    session.flush()
    return report
