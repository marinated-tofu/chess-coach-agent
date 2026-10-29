from __future__ import annotations

import chess

from .classification import (
    EXCELLENT_LOSS,
    FALLBACK_BOOK_PLIES,
    MoveContext,
    classify_move,
    classify_win_chance_loss,
    move_accuracy,
    win_percent,
    winning_chances,
)
from .engine import PIECE_VALUES, EngineAnalyzer, PositionEval
from .knowledge import retrieve_notes
from .models import CoachAnalysis, CriticalMoment, MoveRecord
from .pgn import ParsedGame, phase_for_board

__all__ = [
    "ANALYSIS_VERSION",
    "analyze_parsed_game",
    "classify_win_chance_loss",
    "move_accuracy",
    "winning_chances",
]


THEME_PRINCIPLES = {
    "loose_piece": "Loose pieces fall off. Before making a move, scan every undefended piece that your opponent can attack or capture.",
    "missed_tactic": "Forcing moves come first: checks, captures, threats, and only then quiet improving moves.",
    "king_safety": "An exposed king changes the value of every tactic. Finish development and remove back-rank weaknesses before grabbing material.",
    "opening_drift": "In the opening, repeated queen moves and undeveloped minors usually give the opponent free tempos.",
    "endgame_conversion": "In simplified positions, activity and pawn races matter more than one-move material grabs.",
    "time_pressure": "Bank time in quiet positions so critical moments get a real think. Below 10% of your clock, play safe, forcing-move-checked moves.",
}

# Stored in retrieval_notes; sync re-analyzes any stored game whose notes lack the current value.
# v2: every ply evaluated for both sides (MultiPV 2), move labels, accuracy, clocks.
ANALYSIS_VERSION = "lichess-win-chance-v2"


def _pawns(score_cp: int) -> float:
    return score_cp / 100


def _castled(board: chess.Board, color: bool) -> bool:
    king = board.king(color)
    if king is None:
        return False
    return king in ({chess.G1, chess.C1} if color == chess.WHITE else {chess.G8, chess.C8})


def _undefended_attacked_value(board: chess.Board, color: bool) -> int:
    best = 0
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type not in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        if board.attackers(not color, square) and not board.attackers(color, square):
            best = max(best, PIECE_VALUES[piece.piece_type])
    return best


def _king_danger(board: chess.Board, color: bool) -> int:
    king = board.king(color)
    if king is None:
        return 0
    zone = chess.SquareSet(chess.BB_KING_ATTACKS[king] | chess.BB_SQUARES[king])
    return sum(bool(board.attackers(not color, square)) for square in zone)


def _moment_text(
    theme: str,
    judgment: str,
    played: str,
    best: str | None,
    win_percent_loss: float,
) -> tuple[str, str, str, str]:
    best_text = best or "the engine's candidate"
    summary = (
        f"{played} was a {judgment}; {best_text} preserved about "
        f"{win_percent_loss:.1f} more percentage points of winning chances."
    )
    what = {
        "loose_piece": f"{played} left material tactically vulnerable.",
        "missed_tactic": f"{played} missed a forcing resource in the position.",
        "king_safety": f"{played} did not address king safety or back-rank pressure.",
        "opening_drift": (
            f"{played} continued an early queen detour. Repeated queen moves gave away development "
            "tempi and delayed king safety."
        ),
        "endgame_conversion": f"{played} made the conversion harder in a simplified position.",
        "time_pressure": f"{played} was played with less than a tenth of the starting clock left.",
    }.get(theme, f"{played} changed the character of the position.")
    better = {
        "opening_drift": (
            f"Prefer {best_text} and compare developed minor pieces before moving the queen again. "
            "Choose the move that brings you closer to castling."
        ),
        "loose_piece": f"Look at {best_text}, then count attackers and defenders on every rook, bishop, knight, and queen.",
        "time_pressure": (
            f"{best_text} was the move. Spend less time on routine moves earlier so a position "
            "like this one gets a full candidate-move check."
        ),
    }.get(theme, f"Look at {best_text} first and ask what threat it creates or prevents.")
    drill = {
        "opening_drift": (
            "Replay the first ten moves and mark every queen move, developed minor piece, and missed "
            "chance to castle. Find a development move for each unnecessary queen tempo."
        ),
        "loose_piece": (
            "Set the position on a board, identify every attacked and undefended piece, then list checks, "
            "captures, and threats."
        ),
    }.get(theme, "Set the position on a board and list candidate checks, captures, and threats before choosing.")
    return summary, what, better, drill


def _book_ply(moves: list[MoveRecord]) -> int | None:
    """Deepest ply whose position is a named opening line, or None without opening data."""
    try:
        from .openings import classify_moves
    except ImportError:  # opening table not available in this build
        return None
    try:
        match = classify_moves(moves)
    except Exception:
        return None
    return match.book_ply if match else 0


def _evaluate_game(analyzer: EngineAnalyzer, boards: list[chess.Board]) -> list[PositionEval]:
    # Ply n's "after" position is ply n+1's "before", so N plies need N + 1 evaluations.
    return [analyzer.evaluate(board, multipv=2) for board in boards]


def _annotate_moves(
    parsed: ParsedGame, boards: list[chess.Board], evals: list[PositionEval]
) -> list[MoveRecord]:
    """Copy each MoveRecord with engine eval, loss, accuracy and classification filled in."""
    book_ply = _book_ply(parsed.moves)
    fallback_book = book_ply is None
    losses: list[float] = []
    annotated: list[MoveRecord] = []
    for index, record in enumerate(parsed.moves):
        before, after = boards[index], boards[index + 1]
        move = after.peek()
        mover = before.turn
        best_line = evals[index].best
        after_line = evals[index + 1].best
        wc_before = winning_chances(best_line.pov(mover))
        wc_after = winning_chances(after_line.pov(mover))
        loss = max(0.0, wc_before - wc_after)
        second = evals[index].second
        is_engine_best = best_line.move == move
        if fallback_book:
            in_book = record.ply <= FALLBACK_BOOK_PLIES and all(x < EXCELLENT_LOSS for x in [*losses, loss])
        else:
            in_book = record.ply <= (book_ply or 0)
        ctx = MoveContext(
            board_before=before,
            move=move,
            loss=loss,
            wc_before=wc_before,
            wc_after=wc_after,
            is_engine_best=is_engine_best,
            wc_second=winning_chances(second.pov(mover)) if second else None,
            in_book=in_book,
            opponent_loss=losses[-1] if losses else None,
            wc_before_opponent_move=(
                winning_chances(evals[index - 1].best.pov(mover)) if index >= 1 else None
            ),
            previous_move=before.peek() if before.move_stack else None,
        )
        losses.append(loss)
        best_move = best_line.move
        annotated.append(
            record.model_copy(
                update={
                    "eval_cp": after_line.cp,
                    "eval_mate": after_line.mate,
                    "win_pct": round(win_percent(after_line.value), 1),
                    "win_pct_loss": round(loss * 50, 2),
                    "accuracy": round(move_accuracy(loss), 1),
                    "classification": classify_move(ctx),
                    "best_uci": best_move.uci() if best_move else None,
                    "best_san": (
                        before.san(best_move)
                        if best_move is not None and best_move in before.legal_moves
                        else None
                    ),
                }
            )
        )
    return annotated


def analyze_parsed_game(
    parsed: ParsedGame,
    player: str = "kfctofu",
    max_moments: int | None = None,
    analyzer: EngineAnalyzer | None = None,
) -> CoachAnalysis:
    """Evaluate every ply of the game for both sides, label each move, and turn the
    player's engine-significant errors into critical moments.

    Pass ``analyzer`` to reuse one Stockfish process across games (it is left open);
    otherwise one is started and closed for this game.
    """
    own_analyzer = analyzer is None
    engine = analyzer or EngineAnalyzer()
    player_color = chess.WHITE if parsed.metadata.player_color == "white" else chess.BLACK
    boards = [parsed.game.board()]
    for move in parsed.game.mainline_moves():
        board = boards[-1].copy()
        board.push(move)
        boards.append(board)
    boards = boards[: len(parsed.moves) + 1]
    try:
        evals = _evaluate_game(engine, boards)
    finally:
        if own_analyzer:
            engine.close()
    moves = _annotate_moves(parsed, boards, evals)

    moments: list[CriticalMoment] = []
    queen_moves = 0
    for index, move_record in enumerate(moves):
        before, after = boards[index], boards[index + 1]
        if before.turn != player_color:
            continue
        move = after.peek()
        moving_piece = before.piece_at(move.from_square)
        if moving_piece and moving_piece.piece_type == chess.QUEEN:
            queen_moves += 1

        before_line, after_line = evals[index].best, evals[index + 1].best
        before_cp, after_cp = before_line.pov(player_color), after_line.pov(player_color)
        chance_loss = max(0.0, winning_chances(before_cp) - winning_chances(after_cp))
        judgment = classify_win_chance_loss(chance_loss)
        if before_line.move == move or judgment is None:
            continue

        theme = "missed_tactic"
        loose_before = _undefended_attacked_value(before, player_color)
        loose_after = _undefended_attacked_value(after, player_color)
        if move_record.time_pressure and judgment in ("mistake", "blunder"):
            theme = "time_pressure"
        elif loose_after >= 300 and loose_after > loose_before:
            theme = "loose_piece"
        elif (
            after.fullmove_number <= 12
            and moving_piece
            and moving_piece.piece_type == chess.QUEEN
        ):
            if queen_moves >= 2:
                theme = "opening_drift"
        elif (
            before.fullmove_number >= 10
            and not _castled(after, player_color)
            and _king_danger(after, player_color) > _king_danger(before, player_color)
        ):
            theme = "king_safety"
        elif phase_for_board(after) == "endgame":
            theme = "endgame_conversion"

        fen_best = None
        if before_line.move in before.legal_moves:
            best_board = before.copy(stack=False)
            best_board.push(before_line.move)
            fen_best = best_board.fen()
        win_percent_loss = chance_loss * 50
        played_san = move_record.san
        best_san = move_record.best_san
        summary, what, better, drill = _moment_text(
            theme, judgment, played_san, best_san, win_percent_loss
        )
        moments.append(
            CriticalMoment(
                id=f"{parsed.game_id}-{move_record.ply}",
                game_id=parsed.game_id,
                ply=move_record.ply,
                move_number=move_record.move_number,
                phase=phase_for_board(before),  # type: ignore[arg-type]
                theme=theme,
                played_san=played_san,
                best_san=best_san,
                fen_before=before.fen(),
                fen_after=after.fen(),
                fen_best=fen_best,
                eval_before=_pawns(before_cp),
                eval_after=_pawns(after_cp),
                eval_swing=(before_cp - after_cp) / 100,
                severity=round(win_percent_loss, 2),
                judgment=judgment,
                win_probability_loss=round(win_percent_loss, 2),
                move_accuracy=round(move_accuracy(chance_loss), 1),
                trainable=judgment in ("mistake", "blunder"),
                summary=summary,
                what_happened=what,
                better_plan=better,
                principle=THEME_PRINCIPLES.get(theme, THEME_PRINCIPLES["missed_tactic"]),
                drill_prompt=drill,
            )
        )

    moments = sorted(moments, key=lambda m: m.ply)
    if max_moments is not None:
        moments = sorted(moments, key=lambda m: m.severity, reverse=True)[:max_moments]
        moments.sort(key=lambda m: m.ply)
    themes = ", ".join(sorted({m.theme.replace("_", " ") for m in moments}))
    notes = retrieve_notes(themes, top_k=3)
    trainable_count = sum(moment.trainable for moment in moments)
    training_plan = (
        [
            f"Replay the {trainable_count} mistake/blunder positions without moving pieces, then write three candidate moves.",
            "For each loss, mark whether the mistake was tactical, positional, or time-management related.",
            "Do a daily five-position drill from your own games before playing new blitz games.",
        ]
        if moments
        else [
            "No move crossed the inaccuracy threshold in this game.",
            "Review the opening and endgame plans without manufacturing a tactical drill.",
        ]
    )
    return CoachAnalysis(
        game=parsed.metadata,
        moves=moves,
        moments=moments,
        summary=f"Found {len(moments)} coachable moments. Main themes: {themes or 'candidate move discipline'}.",
        training_plan=training_plan,
        retrieval_notes=[ANALYSIS_VERSION, *[f"{n.title}: {n.snippet}" for n in notes]],
    )
