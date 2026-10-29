from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

import chess
import chess.engine


PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


# Mate scores are folded into centipawns as +/-(MATE_CP - plies to mate), so any score at or
# beyond the 1000-cp win-chance clamp sorts correctly. Same convention as score(mate_score=...).
MATE_CP = 100000


@dataclass
class EngineLine:
    best_move: chess.Move | None
    score_cp: int | None


@dataclass(frozen=True)
class LineScore:
    """One principal variation's first move and its score, always from White's point of view."""

    move: chess.Move | None
    value: int  # centipawns with mates folded in (see MATE_CP)
    cp: int | None = None  # plain centipawns, None for mate scores
    mate: int | None = None  # moves to mate: > 0 White mates, < 0 Black mates, 0 = game over

    @classmethod
    def from_score(cls, move: chess.Move | None, score: chess.engine.PovScore) -> LineScore:
        white = score.white()
        return cls(
            move=move,
            value=white.score(mate_score=MATE_CP) or 0,
            cp=white.score(),
            mate=white.mate(),
        )

    def pov(self, color: bool) -> int:
        return self.value if color == chess.WHITE else -self.value


@dataclass(frozen=True)
class PositionEval:
    """Engine view of one position: the best line first, then the runner-up (MultiPV 2)."""

    lines: tuple[LineScore, ...]

    @property
    def best(self) -> LineScore:
        return self.lines[0]

    @property
    def second(self) -> LineScore | None:
        return self.lines[1] if len(self.lines) > 1 else None


def stockfish_path() -> str | None:
    configured = os.getenv("STOCKFISH_PATH")
    if configured and os.path.exists(configured):
        return configured
    return shutil.which("stockfish")


def material_score(board: chess.Board, color: bool) -> int:
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        total += len(board.pieces(piece_type, color)) * value
        total -= len(board.pieces(piece_type, not color)) * value
    return total


def simple_position_score(board: chess.Board, pov: bool) -> int:
    if board.is_checkmate():
        return -100000 if board.turn == pov else 100000
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    score = material_score(board, pov)
    mobility = len(list(board.legal_moves)) if board.turn == pov else -len(list(board.legal_moves))
    return score + mobility * 3


class EngineAnalyzer:
    def __init__(
        self,
        depth: int | None = None,
        engine_path: str | None = None,
        max_nodes: int | None = None,
    ) -> None:
        self.depth = depth if depth is not None else int(os.getenv("STOCKFISH_DEPTH", "9"))
        # A node cap bounds the rare position where a fixed depth explodes; 0 disables it.
        nodes = max_nodes if max_nodes is not None else int(os.getenv("STOCKFISH_MAX_NODES", "60000"))
        self.max_nodes = nodes or None
        self.engine_path = engine_path or stockfish_path()
        self._engine: chess.engine.SimpleEngine | None = None

    def _limit(self) -> chess.engine.Limit:
        return chess.engine.Limit(depth=self.depth, nodes=self.max_nodes)

    def close(self) -> None:
        if self._engine:
            self._engine.quit()
            self._engine = None

    def analyse(self, board: chess.Board, pov: bool) -> EngineLine:
        if not self.engine_path:
            return EngineLine(best_move=_fallback_best_move(board), score_cp=simple_position_score(board, pov))
        try:
            if self._engine is None:
                self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
            info = self._engine.analyse(board, chess.engine.Limit(depth=self.depth))
            score = info["score"].pov(pov).score(mate_score=100000)
            pv = info.get("pv", [])
            return EngineLine(best_move=pv[0] if pv else None, score_cp=score)
        except Exception:
            self.close()
            return EngineLine(best_move=_fallback_best_move(board), score_cp=simple_position_score(board, pov))

    def evaluate(self, board: chess.Board, multipv: int = 2) -> PositionEval:
        """Score a position from White's point of view with up to ``multipv`` lines.

        Finished games are scored without the engine: checkmate is a mate score of 0 for
        the side that delivered it, any draw is 0 cp. Without Stockfish, a material and
        mobility heuristic gives a single line.
        """
        if board.is_checkmate():
            value = -MATE_CP if board.turn == chess.WHITE else MATE_CP
            return PositionEval(lines=(LineScore(move=None, value=value, mate=0),))
        if board.is_game_over(claim_draw=False):
            return PositionEval(lines=(LineScore(move=None, value=0, cp=0),))
        if self.engine_path:
            try:
                if self._engine is None:
                    self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
                infos = self._engine.analyse(board, self._limit(), multipv=multipv)
                lines = tuple(
                    LineScore.from_score(info["pv"][0] if info.get("pv") else None, info["score"])
                    for info in infos
                    if "score" in info
                )
                if lines:
                    return PositionEval(lines=lines)
            except Exception:
                self.close()
        cp = simple_position_score(board, chess.WHITE)
        return PositionEval(lines=(LineScore(move=_fallback_best_move(board), value=cp, cp=cp),))


def _fallback_best_move(board: chess.Board) -> chess.Move | None:
    best: chess.Move | None = None
    best_gain = -10_000
    for move in board.legal_moves:
        gain = 0
        if board.is_capture(move):
            victim = board.piece_at(move.to_square)
            attacker = board.piece_at(move.from_square)
            if victim and attacker:
                gain += PIECE_VALUES[victim.piece_type] - PIECE_VALUES[attacker.piece_type] // 10
        if board.gives_check(move):
            gain += 80
        if gain > best_gain:
            best_gain = gain
            best = move
    return best or next(iter(board.legal_moves), None)
