"""Annotated PGN export of a reviewed game.

Writes the same kind of file Lichess and Chess.com hand out after a review:
[%eval]/[%clk] commands, NAGs from the move classification, a short
"Mistake. Nf3 was best." comment and the engine's move as a variation.
"""

from __future__ import annotations

import re

import chess
import chess.engine
import chess.pgn

from .models import CoachAnalysis, CriticalMoment, MoveRecord

ANNOTATOR = "Chess Coach Agent"

NAGS: dict[str, int] = {
    "brilliant": chess.pgn.NAG_BRILLIANT_MOVE,  # !!
    "great": chess.pgn.NAG_GOOD_MOVE,  # !
    "inaccuracy": chess.pgn.NAG_DUBIOUS_MOVE,  # ?!
    "mistake": chess.pgn.NAG_MISTAKE,  # ?
    "miss": chess.pgn.NAG_MISTAKE,  # ?
    "blunder": chess.pgn.NAG_BLUNDER,  # ??
}

LABELS: dict[str, str] = {
    "brilliant": "Brilliant move",
    "great": "Great move",
    "inaccuracy": "Inaccuracy",
    "mistake": "Mistake",
    "miss": "Missed win",
    "blunder": "Blunder",
}

# Only bad moves get "X was best." (as Lichess does).
NEEDS_BEST = {"inaccuracy", "mistake", "miss", "blunder"}


def _opening_label(analysis: CoachAnalysis) -> dict | None:
    try:
        from .openings import label_game
    except ImportError:  # pragma: no cover - openings module optional
        return None
    try:
        return label_game(analysis.moves)
    except Exception:  # noqa: BLE001 - opening data is a nicety, never fatal
        return None


def _score(move: MoveRecord) -> chess.engine.PovScore | None:
    if move.eval_mate is not None:
        if move.eval_mate == 0:
            return None  # checkmate on the board, nothing to evaluate
        return chess.engine.PovScore(chess.engine.Mate(move.eval_mate), chess.WHITE)
    if move.eval_cp is not None:
        return chess.engine.PovScore(chess.engine.Cp(move.eval_cp), chess.WHITE)
    return None


def _join(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _move_comment(move: MoveRecord, moment: CriticalMoment | None) -> str:
    label = LABELS.get(move.classification or "")
    best = move.best_san or (moment.best_san if moment else None)
    head = ""
    if label:
        head = f"{label}."
        if move.classification in NEEDS_BEST and best and best != move.san:
            head += f" {best} was best."
    elif moment is not None:
        head = f"{moment.judgment.capitalize()}."
        if best and best != move.san:
            head += f" {best} was best."
    coach = _join(moment.what_happened, moment.better_plan) if moment else ""
    return _join(head, coach)


def _best_move(board: chess.Board, move: MoveRecord, moment: CriticalMoment | None):
    candidates = [move.best_uci, move.best_san, moment.best_san if moment else None]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            if candidate == move.best_uci:
                parsed = chess.Move.from_uci(candidate)
                if parsed in board.legal_moves:
                    return parsed
            else:
                return board.parse_san(candidate)
        except ValueError:
            continue
    return None


def _clean(text: str) -> str:
    # PGN header values and comments cannot contain braces or stray quotes safely.
    return text.replace("{", "(").replace("}", ")")


def build_annotated_pgn(
    analysis: CoachAnalysis,
    *,
    include_evals: bool = True,
    include_clocks: bool = True,
    include_variations: bool = True,
) -> str:
    meta = analysis.game
    game = chess.pgn.Game()
    start_fen = analysis.moves[0].fen_before if analysis.moves else chess.STARTING_FEN
    if start_fen != chess.STARTING_FEN:
        game.setup(chess.Board(start_fen))

    headers = game.headers
    headers["Event"] = f"{meta.source} game" if meta.source and meta.source != "pgn" else "?"
    headers["Site"] = meta.link or "?"
    headers["Date"] = meta.date or "????.??.??"
    headers["White"] = meta.white or "?"
    headers["Black"] = meta.black or "?"
    headers["Result"] = meta.result or "*"
    if meta.time_control:
        headers["TimeControl"] = meta.time_control
    opening = _opening_label(analysis)
    eco = (opening or {}).get("eco") or meta.eco
    if eco:
        headers["ECO"] = str(eco)
    if opening and opening.get("name"):
        headers["Opening"] = str(opening["name"])
    headers["Annotator"] = ANNOTATOR

    if analysis.accuracy and (
        analysis.accuracy.white is not None or analysis.accuracy.black is not None
    ):
        def fmt(value: float | None) -> str:
            return "?" if value is None else f"{value:.1f}%"

        game.comment = (
            f"Accuracy: {meta.white} (White) {fmt(analysis.accuracy.white)}, "
            f"{meta.black} (Black) {fmt(analysis.accuracy.black)}."
        )

    moments = {moment.ply: moment for moment in analysis.moments}
    node: chess.pgn.GameNode = game
    for move in analysis.moves:
        board = node.board()
        try:
            played = board.parse_san(move.san)
        except ValueError:
            played = chess.Move.from_uci(move.uci)
        moment = moments.get(move.ply)
        child = node.add_variation(played)

        nag = NAGS.get(move.classification or "")
        if nag is None and moment is not None:
            nag = NAGS.get(moment.judgment)
        if nag is not None:
            child.nags.add(nag)
        if include_evals and (score := _score(move)) is not None:
            child.set_eval(score)
        if include_clocks and move.clock_seconds is not None:
            child.set_clock(move.clock_seconds)
        comment = _move_comment(move, moment)
        if comment:
            child.comment = _clean(_join(child.comment, comment))

        wants_line = moment is not None or move.classification in NEEDS_BEST
        if include_variations and wants_line:
            best = _best_move(board, move, moment)
            if best is not None and best != played:
                line = node.add_variation(best)
                line.comment = "Best move"
        node = child

    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exporter) + "\n"


def pgn_filename(analysis: CoachAnalysis) -> str:
    meta = analysis.game

    def slug(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value or "").strip("_")
        return cleaned[:40] or "unknown"

    date = (meta.date or "").replace(".", "-")
    date = slug(date) if date and "?" not in date else "undated"
    return f"{slug(meta.white)}-vs-{slug(meta.black)}-{date}.pgn"
