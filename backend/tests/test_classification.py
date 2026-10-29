import chess

from chess_coach_agent.classification import (
    MoveContext,
    classify_move,
    game_accuracy,
    sacrificed_material,
    win_percent,
)
from chess_coach_agent.models import CoachAnalysis, GameMetadata, MoveRecord

# Classic Greek gift: Bxh7+ gives a bishop for a pawn and only the king can take back.
GREEK_GIFT = "r1bq1rk1/pppn1ppp/4p3/3pP3/1b1P4/2NB1N2/PPP2PPP/R1BQK2R w KQ - 0 8"


def _ctx(**overrides) -> MoveContext:
    values = {
        "board_before": chess.Board(),
        "move": chess.Move.from_uci("e2e4"),
        "loss": 0.0,
        "wc_before": 0.0,
        "wc_after": 0.0,
    }
    values.update(overrides)
    return MoveContext(**values)


def test_loss_thresholds_map_to_labels():
    assert classify_move(_ctx(loss=0.0)) == "best"
    assert classify_move(_ctx(loss=0.009)) == "best"
    assert classify_move(_ctx(loss=0.03)) == "excellent"
    assert classify_move(_ctx(loss=0.08)) == "good"
    assert classify_move(_ctx(loss=0.10, wc_after=-0.10)) == "inaccuracy"
    assert classify_move(_ctx(loss=0.20, wc_after=-0.20)) == "mistake"
    assert classify_move(_ctx(loss=0.30, wc_after=-0.30)) == "blunder"


def test_engine_best_move_is_never_an_error():
    assert classify_move(_ctx(loss=0.25, is_engine_best=True)) == "best"


def test_book_only_covers_non_errors():
    assert classify_move(_ctx(loss=0.05, in_book=True)) == "book"
    assert classify_move(_ctx(loss=0.35, in_book=True, wc_after=-0.35)) == "blunder"


def test_miss_requires_opponent_error_and_no_net_damage():
    # Opponent blundered (0.40), mover gives 0.15 back but is still better than before it.
    missed = _ctx(loss=0.15, wc_before=0.40, wc_after=0.25, opponent_loss=0.40,
                  wc_before_opponent_move=0.0)
    assert classify_move(missed) == "miss"
    # Same loss after only an inaccuracy by the opponent is a plain inaccuracy.
    assert classify_move(_ctx(loss=0.15, wc_before=0.40, wc_after=0.25, opponent_loss=0.12,
                              wc_before_opponent_move=0.28)) == "inaccuracy"
    # Ending up worse than before the opponent's error is a blunder, not a miss.
    assert classify_move(_ctx(loss=0.45, wc_before=0.30, wc_after=-0.15, opponent_loss=0.30,
                              wc_before_opponent_move=0.0)) == "blunder"


def test_great_is_the_only_move_that_keeps_the_outcome():
    great = _ctx(is_engine_best=True, wc_before=0.10, wc_after=0.10, wc_second=-0.60)
    assert classify_move(great) == "great"
    # A big gap that stays inside the same outcome bucket (still winning) is just best.
    assert classify_move(_ctx(is_engine_best=True, wc_before=0.95, wc_after=0.95,
                              wc_second=0.60)) == "best"
    # Recapturing on the square the opponent just captured on is never Great.
    board = chess.Board("4k3/8/4p3/3N4/8/8/8/4K3 b - - 0 1")
    previous = chess.Move.from_uci("c3d5")
    recapture = _ctx(board_before=board, move=chess.Move.from_uci("e6d5"), is_engine_best=True,
                     wc_second=-0.60, previous_move=previous)
    assert classify_move(recapture) == "best"


def test_sacrifice_detection_and_brilliant():
    board = chess.Board(GREEK_GIFT)
    bxh7 = chess.Move.from_uci("d3h7")
    assert sacrificed_material(board, bxh7) == 330 - 100
    brilliant = _ctx(board_before=board, move=bxh7, is_engine_best=True,
                     wc_before=0.30, wc_after=0.30)
    assert classify_move(brilliant) == "brilliant"
    # Not brilliant when the mover was already completely winning.
    assert classify_move(_ctx(board_before=board, move=bxh7, is_engine_best=True,
                              wc_before=0.95, wc_after=0.95)) == "best"


def test_even_trade_is_not_a_sacrifice():
    board = chess.Board("4k3/8/4p3/3n4/8/2N5/8/4K3 w - - 0 1")
    assert sacrificed_material(board, chess.Move.from_uci("c3d5")) == 0


def test_checkmate_is_not_scored_as_a_sacrifice():
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    assert sacrificed_material(board, chess.Move.from_uci("h5f7")) == 0


def test_game_accuracy_lichess_formula():
    flat = [win_percent(15)] * 40
    perfect = game_accuracy(flat)
    assert perfect == {"white": 100.0, "black": 100.0}
    # White drops 30 Win% on move 11 and never recovers; Black plays perfectly.
    series = flat[:20] + [win_percent(15) - 30] * 20
    accuracy = game_accuracy(series)
    assert accuracy["black"] == 100.0
    assert accuracy["white"] is not None and accuracy["white"] < 90
    assert game_accuracy([]) == {"white": None, "black": None}


def test_coach_analysis_derives_accuracy_and_eval_series_from_moves():
    board = chess.Board()
    moves = []
    for ply, (san, win) in enumerate([("e4", 52.0), ("e5", 51.0), ("Qh5", 45.0)], start=1):
        color = "white" if board.turn else "black"
        fen_before = board.fen()
        move = board.push_san(san)
        moves.append(
            MoveRecord(
                ply=ply, move_number=(ply + 1) // 2, color=color, san=san, uci=move.uci(),
                fen_before=fen_before, fen_after=board.fen(), win_pct=win,
                eval_cp=10, classification="best",
            )
        )
    analysis = CoachAnalysis(
        game=GameMetadata(game_id="g", white="a", black="b", result="*"),
        moves=moves, moments=[], summary="", training_plan=[],
    )
    assert [p.ply for p in analysis.eval_series] == [1, 2, 3]
    assert analysis.accuracy is not None and analysis.accuracy.white is not None
    assert analysis.classification_counts == {"white": {"best": 2}, "black": {"best": 1}}
    # Stored analyses without engine fields stay as they were.
    for move in moves:
        move.win_pct = None
    legacy = CoachAnalysis(
        game=GameMetadata(game_id="g", white="a", black="b", result="*"),
        moves=moves, moments=[], summary="", training_plan=[],
    )
    assert legacy.accuracy is None and legacy.eval_series == []
