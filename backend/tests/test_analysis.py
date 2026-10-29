from chess_coach_agent.agent import ChessCoachAgent, sample_pgn
from chess_coach_agent.analysis import (
    classify_win_chance_loss,
    move_accuracy,
    winning_chances,
)


def test_agent_returns_critical_moments_for_sample():
    response = ChessCoachAgent().import_pgn_text(sample_pgn(), player="kfctofu", max_games=4)
    assert len(response.analyses) == 4
    assert len({len(analysis.moments) for analysis in response.analyses}) > 1
    for analysis in response.analyses:
        assert analysis.moments
        assert analysis.training_plan
        assert analysis.moves
        assert all(moment.win_probability_loss >= 5 for moment in analysis.moments)
        assert all(
            moment.judgment in {"inaccuracy", "mistake", "blunder"}
            for moment in analysis.moments
        )


def test_lichess_style_win_chance_thresholds():
    assert classify_win_chance_loss(0.099) is None
    assert classify_win_chance_loss(0.10) == "inaccuracy"
    assert classify_win_chance_loss(0.20) == "mistake"
    assert classify_win_chance_loss(0.30) == "blunder"
    assert winning_chances(-300) < winning_chances(0) < winning_chances(300)
    assert move_accuracy(0) == 100
    assert move_accuracy(0.30) < move_accuracy(0.10)


import pytest  # noqa: E402

from chess_coach_agent.analysis import analyze_parsed_game  # noqa: E402
from chess_coach_agent.engine import stockfish_path  # noqa: E402
from chess_coach_agent.models import GameMetadata  # noqa: E402
from chess_coach_agent.pgn import (  # noqa: E402
    parse_pgn_text,
    parse_time_control,
    parsed_game_from_moves,
)

needs_stockfish = pytest.mark.skipif(stockfish_path() is None, reason="Stockfish not installed")

SCHOLARS_MATE = """[White "kfctofu"]
[Black "opponent"]
[Result "1-0"]
[TimeControl "180+2"]

1. e4 {[%clk 0:03:01]} 1... e5 {[%clk 0:02:58.5]} 2. Bc4 {[%clk 0:02:55]}
2... Nc6 {[%clk 0:02:40]} 3. Qh5 {[%clk 0:02:50]} 3... Nf6 {[%clk 0:00:15.2]}
4. Qxf7# {[%clk 0:02:49]} 1-0
"""

HANGING_QUEEN = """[White "kfctofu"]
[Black "opponent"]
[Result "0-1"]

1. e4 d5 2. Qg4 Bxg4 0-1
"""


def test_clock_comments_are_parsed():
    moves = parse_pgn_text(SCHOLARS_MATE, player="kfctofu")[0].moves
    assert [m.clock_seconds for m in moves] == [181.0, 178.5, 175.0, 160.0, 170.0, 15.2, 169.0]
    # Time spent = previous clock of the same side - clock now + 2 s increment.
    assert moves[0].time_spent_seconds == 1.0
    assert moves[2].time_spent_seconds == 8.0
    assert moves[5].time_spent_seconds == 146.8
    # 15.2 s is under 10% of the 180 s base.
    assert [m.time_pressure for m in moves] == [False] * 5 + [True, False]


def test_time_control_parsing():
    assert parse_time_control("900+10") == (900, 10)
    assert parse_time_control("600") == (600, 0)
    assert parse_time_control("1/259200") is None
    assert parse_time_control("-") is None


def test_pgn_without_clocks_has_no_clock_fields():
    moves = parse_pgn_text(HANGING_QUEEN, player="kfctofu")[0].moves
    assert all(m.clock_seconds is None and not m.time_pressure for m in moves)


def test_stored_moves_rebuild_keeps_clocks():
    parsed = parse_pgn_text(SCHOLARS_MATE, player="kfctofu")[0]
    metadata = GameMetadata.model_validate(parsed.metadata.model_dump())
    rebuilt = parsed_game_from_moves(metadata, parsed.moves)
    assert [m.uci for m in rebuilt.moves] == [m.uci for m in parsed.moves]
    assert [m.clock_seconds for m in rebuilt.moves] == [m.clock_seconds for m in parsed.moves]
    assert rebuilt.game_id == parsed.game_id


@needs_stockfish
def test_mate_in_one_is_best_and_scored_as_mate():
    analysis = analyze_parsed_game(parse_pgn_text(SCHOLARS_MATE, player="kfctofu")[0])
    by_san = {m.san: m for m in analysis.moves}
    assert by_san["Qxf7#"].classification == "best"
    # Win% follows the Lichess 1000 cp clamp, so even a mate tops out at 97.5.
    assert by_san["Qxf7#"].eval_mate == 0 and by_san["Qxf7#"].win_pct == 97.5
    assert by_san["Nf6"].classification == "blunder"
    assert by_san["Nf6"].eval_mate == 1  # White mates in one
    assert by_san["Nf6"].best_san is not None
    # Opening moves of a named line are Book.
    assert by_san["e4"].classification == "book"
    assert analysis.accuracy is not None
    assert analysis.accuracy.white is not None and analysis.accuracy.black is not None
    assert analysis.accuracy.white > analysis.accuracy.black
    assert len(analysis.eval_series) == len(analysis.moves)
    # Every move of both sides carries an eval.
    assert all(m.win_pct is not None and m.classification for m in analysis.moves)


@needs_stockfish
def test_hanging_queen_is_a_blunder_and_capture_is_best():
    analysis = analyze_parsed_game(parse_pgn_text(HANGING_QUEEN, player="kfctofu")[0])
    qg4, bxg4 = analysis.moves[2], analysis.moves[3]
    assert qg4.classification == "blunder"
    assert qg4.win_pct_loss is not None and qg4.win_pct_loss > 15
    assert bxg4.classification in {"best", "great"}
    assert [m.judgment for m in analysis.moments] == ["blunder"]
    assert analysis.moments[0].ply == 3


@needs_stockfish
def test_mistake_in_time_pressure_gets_time_pressure_theme():
    pgn = HANGING_QUEEN.replace('[Result "0-1"]', '[Result "0-1"]\n[TimeControl "60"]').replace(
        "2. Qg4", "2. Qg4 {[%clk 0:00:04]}"
    )
    analysis = analyze_parsed_game(parse_pgn_text(pgn, player="kfctofu")[0])
    assert analysis.moves[2].time_pressure
    assert analysis.moments[0].theme == "time_pressure"
