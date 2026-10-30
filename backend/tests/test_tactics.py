"""Precision fixtures for tactics.py.

Every FEN below was checked by hand on a board. Positives come from real games and Lichess
puzzles, with the reason the motif holds. Negatives are the look-alikes the detector has to
refuse, including every kind of false positive found while tuning it on real games.
"""

from __future__ import annotations

import chess
import pytest
from fastapi.testclient import TestClient

from chess_coach_agent import tactics
from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import GameRow
from chess_coach_agent.puzzles import filter_puzzles
from chess_coach_agent.repositories import get_or_create_player
from chess_coach_agent.tactics import (
    MIN_CHANCES,
    MIN_GAIN_CP,
    detect_material_motif,
    game_chances,
    has_stored_evals,
)

MOTIF_FIXTURES = [
    # Forks
    ("fork", "r2qk2r/1pp2p2/p1np1p1p/4p1N1/2B1P3/3P4/PPPQ1PPP/2Kb3R w kq - 0 12", "g5f7"),  # Q+R, Bc4 guards f7
    ("fork", "rnbqkbnr/pppp3p/6p1/4p2Q/4P3/8/PPPP1PPP/RNB1KB1R w KQkq - 0 5", "h5e5"),  # K+Rh8
    ("fork", "r2qk2r/p1pnbppp/8/5QN1/1P6/Pb1P4/1Pn1KPPP/1NB4R b kq - 4 18", "c2d4"),  # K+Qf5
    ("fork", "2k1r2r/ppp5/8/2b5/5ppP/2P5/PP1N2K1/R6R b - - 0 21", "e8e2"),  # K+Nd2
    ("fork", "4k3/8/8/2n1n3/8/3P4/8/7K w - - 0 1", "d3d4"),  # pawn on two knights
    ("fork", "r1b1k2r/p4p1p/4p3/1p1pPp2/q2P4/2Q2N1P/5PP1/1B3RK1 w kq - 0 21", "c3c6"),  # K+Ra8
    # Pins, new and piled on
    ("pin", "r4rk1/ppp2ppp/2n1b3/b1RPP3/4P3/3QKNPP/P5B1/7R b - - 0 20", "a5b6"),  # Rc5 to Ke3
    ("pin", "rnb2rk1/pp3p1p/3p2p1/2pP4/2P5/5P2/qb1BN1PP/1R1QKB1R w K - 0 13", "d1c2"),  # Bb2 to Qa2
    ("pin", "8/5pk1/4b2p/8/2r1N1P1/4PK1P/5R2/8 b - - 13 51", "e6d5"),  # Ne4 to Kf3, Rc4 attacks it
    ("pin", "8/5BqR/npp3b1/6k1/p7/5P2/P5K1/8 w - - 0 52", "h7g7"),  # Bg6 to Kg5, Bf7 attacks it
    ("pin", "6k1/p4p2/1p5p/4r3/P3B3/1P2KP2/2P3PP/8 b - - 1 29", "f7f5"),  # pawn hits pinned Be4
    # Skewers
    ("skewer", "r3k3/7R/4r3/p1p5/1p6/7P/PKP3P1/3R4 w - - 0 27", "h7h8"),  # K then Ra8
    ("skewer", "1r3rk1/p4ppp/4b3/2p5/6PP/2PP4/n1K1BP2/3R3R b - - 4 24", "e6b3"),  # K then Rd1
    ("skewer", "3Q4/8/5pk1/8/8/1p2P3/1P1K4/6q1 w - - 0 61", "d8g8"),  # K then Qg1
    ("skewer", "8/8/1R5P/8/1pk5/7R/r1r5/1K6 w - - 7 55", "b6c6"),  # K then Rc2
    # Mate threats that also win material
    ("mate_threat", "rnb2rk1/pp3ppp/2p5/4P1q1/2BNp3/8/PPP2PPP/R2Q1RK1 b - - 1 13", "c8h3"),  # Qxg2#, or Bxf1
]

REFUSED = [
    # Starting positions and ordinary development
    ("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 3", "f1b5"),  # Spanish: no win
    ("rnbqkb1r/ppp2ppp/4pn2/3p4/2PP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 4", "c1g5"),  # a pin, wins nothing
    # Fork shapes that lose or win nothing
    ("4k3/2q1r3/4p3/8/8/2N5/8/4K3 w - - 0 1", "c3d5"),  # exd5 takes the forking knight
    ("6k1/5ppp/2r1r3/8/8/8/5PPP/3Q2K1 w - - 0 1", "d1d5"),  # both rooks defended
    ("4k3/8/8/5p2/1r6/8/8/4NK2 w - - 0 1", "e1d3"),  # only one piece attacked
    # Scholar's mate try: a threat, parried at no cost
    ("rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 2 3", "d1h5"),
    # King steps next to the rear piece, so the skewer loses the rook
    ("8/7n/8/7k/8/8/8/K5R1 w - - 0 1", "g1h1"),
]

NOT_THIS_MOTIF = [
    # Each wins material, but not by the motif a looser check would name.
    ("r1b1kb1r/pp2pppp/n3qn2/8/3p4/2N2N2/PPP1BPPP/R1BQR1K1 w kq - 0 9", "e2b5", "skewer"),  # discovered attack on Qe6
    ("rnb5/pp2nk1p/2pq1Br1/8/8/5Q2/P4PPP/R4KNR w - - 0 16", "f6e5", "skewer"),  # discovered check
    ("1r4k1/5ppp/8/1r2R3/q2p2PP/P2P1P2/1PQ5/1K5R b - - 1 29", "a4c2", "pin"),  # queen trade, Re5 hung anyway
    ("r4r1k/ppp2pp1/2nb3q/3n2NQ/3P4/2P5/PP3PPP/RNB3K1 w - - 2 18", "g5f7", "pin"),  # deflection
]


def _detect(fen: str, uci: str) -> str | None:
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    assert board.is_legal(move), f"fixture move {uci} is illegal"
    return detect_material_motif(board, move)


@pytest.mark.parametrize(("motif", "fen", "uci"), MOTIF_FIXTURES)
def test_detects_hand_checked_motif(motif: str, fen: str, uci: str) -> None:
    assert _detect(fen, uci) == motif


@pytest.mark.parametrize(("fen", "uci"), REFUSED)
def test_refuses_look_alikes(fen: str, uci: str) -> None:
    assert _detect(fen, uci) is None


@pytest.mark.parametrize(("fen", "uci", "wrong"), NOT_THIS_MOTIF)
def test_does_not_mislabel(fen: str, uci: str, wrong: str) -> None:
    assert _detect(fen, uci) != wrong


def test_fixture_precision_is_total() -> None:
    """The figure quoted in the report: nothing refused or mislabeled across the fixture set."""
    hits = sum(_detect(fen, uci) == motif for motif, fen, uci in MOTIF_FIXTURES)
    false_positives = sum(_detect(fen, uci) is not None for fen, uci in REFUSED)
    assert (hits, false_positives) == (len(MOTIF_FIXTURES), 0)


# --------------------------------------------------------------------------- a game

FORK_FEN = MOTIF_FIXTURES[0][1]
FORK_UCI = MOTIF_FIXTURES[0][2]
BLACK_FORK_FEN = MOTIF_FIXTURES[2][1]
BLACK_FORK_UCI = MOTIF_FIXTURES[2][2]
MATE_IN_ONE_FEN = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
MATE_IN_ONE_UCI = "a1a8"


def _record(
    ply: int,
    fen: str,
    uci: str,
    best: str,
    eval_cp: int | None = None,
    eval_mate: int | None = None,
) -> dict:
    board = chess.Board(fen)
    color = "white" if board.turn == chess.WHITE else "black"
    move = chess.Move.from_uci(uci)
    best_move = chess.Move.from_uci(best)
    san, best_san = board.san(move), board.san(best_move)
    board.push(move)
    return {
        "ply": ply,
        "move_number": (ply + 1) // 2,
        "color": color,
        "san": san,
        "uci": uci,
        "best_uci": best,
        "best_san": best_san,
        "fen_before": fen,
        "fen_after": board.fen(),
        "eval_cp": eval_cp,
        "eval_mate": eval_mate,
    }


def _previous(ply: int, eval_cp: int | None = None, eval_mate: int | None = None) -> dict:
    """The opponent's move before the position under test: only its stored score matters."""
    return {"ply": ply, "color": "other", "eval_cp": eval_cp, "eval_mate": eval_mate}


def _material(fen: str, color: bool = chess.WHITE) -> int:
    return tactics._material_from_fen(fen, color)


def _fork_game(before_cp: int, played: str, after_cp: int) -> list[dict]:
    return [_previous(22, before_cp), _record(23, FORK_FEN, played, FORK_UCI, eval_cp=after_cp)]


def test_material_from_fen_is_from_the_players_side() -> None:
    fen = "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"
    assert _material(fen, chess.WHITE) == 500
    assert _material(fen, chess.BLACK) == -500


def test_found_fork() -> None:
    value = _material(FORK_FEN) + 400
    [chance] = game_chances(_fork_game(value, FORK_UCI, value), "white")
    assert (chance.motif, chance.found, chance.best_san) == ("fork", True, "Nxf7")


def test_missed_fork_needs_a_real_eval_drop() -> None:
    value = _material(FORK_FEN) + 400
    [chance] = game_chances(_fork_game(value, "h1e1", value - MIN_GAIN_CP), "white")
    assert (chance.motif, chance.found, chance.best_san) == ("fork", False, "Nxf7")


def test_other_move_that_keeps_the_advantage_counts_as_neither() -> None:
    value = _material(FORK_FEN) + 400
    assert game_chances(_fork_game(value, "h1e1", value - MIN_GAIN_CP + 1), "white") == []


def test_no_chance_when_the_eval_shows_no_win() -> None:
    value = _material(FORK_FEN) + MIN_GAIN_CP - 1
    assert game_chances(_fork_game(value, FORK_UCI, value), "white") == []


def test_black_scores_are_flipped() -> None:
    value = _material(BLACK_FORK_FEN, chess.BLACK) + 400
    game = [
        _previous(35, -value),
        _record(36, BLACK_FORK_FEN, BLACK_FORK_UCI, BLACK_FORK_UCI, eval_cp=-value),
    ]
    [chance] = game_chances(game, "black")
    assert (chance.motif, chance.found) == ("fork", True)
    assert game_chances(game, "white") == []  # the opponent's moves are not the player's chances


def test_first_ply_has_no_stored_score_to_judge_it() -> None:
    game = [_record(1, FORK_FEN, FORK_UCI, FORK_UCI, eval_cp=800)]
    assert game_chances(game, "white") == []


def test_illegal_stored_engine_move_is_ignored() -> None:
    value = _material(FORK_FEN) + 400
    game = _fork_game(value, FORK_UCI, value)
    game[1]["best_uci"] = "a1a8"
    assert game_chances(game, "white") == []


def test_mate_in_one_found_and_missed() -> None:
    found = [
        _previous(10, eval_mate=1),
        _record(11, MATE_IN_ONE_FEN, MATE_IN_ONE_UCI, MATE_IN_ONE_UCI, eval_mate=0),
    ]
    [chance] = game_chances(found, "white")
    assert (chance.motif, chance.found) == ("mate_1", True)
    missed = [
        _previous(10, eval_mate=1),
        _record(11, MATE_IN_ONE_FEN, "g2g3", MATE_IN_ONE_UCI, eval_cp=500),
    ]
    [chance] = game_chances(missed, "white")
    assert (chance.motif, chance.found) == ("mate_1", False)


def test_mate_in_one_must_be_mate_on_the_board() -> None:
    game = [_previous(10, eval_mate=1), _record(11, MATE_IN_ONE_FEN, "g2g3", "a1a7", eval_cp=500)]
    assert game_chances(game, "white") == []


def test_longer_mate_is_missed_only_when_the_win_is_gone() -> None:
    lost = [_previous(10, eval_mate=3), _record(11, MATE_IN_ONE_FEN, "g2g3", MATE_IN_ONE_UCI, eval_cp=120)]
    [chance] = game_chances(lost, "white")
    assert (chance.motif, chance.found) == ("mate_3", False)
    # +7 after a shallow search usually means the mate is still there.
    kept = [_previous(10, eval_mate=3), _record(11, MATE_IN_ONE_FEN, "g2g3", MATE_IN_ONE_UCI, eval_cp=700)]
    assert game_chances(kept, "white") == []


def test_mates_beyond_the_limit_are_left_out() -> None:
    game = [_previous(10, eval_mate=9), _record(11, MATE_IN_ONE_FEN, "g2g3", MATE_IN_ONE_UCI, eval_cp=100)]
    assert game_chances(game, "white") == []


def test_being_mated_is_not_a_chance() -> None:
    game = [_previous(10, eval_mate=-2), _record(11, MATE_IN_ONE_FEN, "g2g3", MATE_IN_ONE_UCI, eval_mate=-1)]
    assert game_chances(game, "white") == []


def test_mate_played_out_is_one_chance() -> None:
    game = [
        _previous(10, eval_mate=2),
        _record(11, MATE_IN_ONE_FEN, "g2g3", "g2g3", eval_mate=1),
        _previous(12, eval_mate=1),
        _record(13, MATE_IN_ONE_FEN, MATE_IN_ONE_UCI, MATE_IN_ONE_UCI, eval_mate=0),
    ]
    [chance] = game_chances(game, "white")
    assert (chance.motif, chance.found, chance.ply) == ("mate_2", True, 11)


def test_mate_thrown_away_midway_is_one_miss() -> None:
    game = [
        _previous(10, eval_mate=2),
        _record(11, MATE_IN_ONE_FEN, "g2g3", "g2g3", eval_mate=1),
        _previous(12, eval_mate=1),
        _record(13, MATE_IN_ONE_FEN, "f2f3", MATE_IN_ONE_UCI, eval_cp=300),
    ]
    [chance] = game_chances(game, "white")
    assert (chance.motif, chance.found, chance.ply) == ("mate_1", False, 13)


def test_has_stored_evals() -> None:
    value = _material(FORK_FEN) + 400
    game = [_record(1, FORK_FEN, FORK_UCI, FORK_UCI, eval_cp=value)]
    assert has_stored_evals(game)
    assert not has_stored_evals([])
    assert not has_stored_evals([{**game[0], "best_uci": None}])
    assert not has_stored_evals([{**game[0], "eval_cp": None}])
    assert has_stored_evals([{**game[0], "eval_cp": None, "eval_mate": 2}])


# --------------------------------------------------------------------------- the API


def _seed(username: str, games: list[list[dict] | None]) -> None:
    with session_scope() as session:
        player = get_or_create_player(session, "chess.com", username)
        for number, moves in enumerate(games):
            session.add(
                GameRow(
                    player_id=player.id,
                    external_game_id=f"{username}-{number}",
                    white=username,
                    black="opp",
                    result="1-0",
                    player_result="win",
                    player_color="white",
                    played_at=f"2026.01.{number + 1:02d}",
                    time_control="600",
                    metadata_json={
                        "game": {"player_color": "white"},
                        # win_pct only, as analyses from before best_uci was stored look.
                        "moves": moves if moves is not None else [{"ply": 1, "color": "white", "win_pct": 50.0}],
                    },
                )
            )


def _with_ids(game: list[dict]) -> list[dict]:
    return [{"best_uci": "e2e4", "fen_before": FORK_FEN, "san": "x", "uci": "e2e4", **m} for m in game]


def _insights(username: str, **params) -> dict:
    with TestClient(app) as client:
        response = client.get(f"/api/insights/chess.com/{username}", params=params)
    assert response.status_code == 200
    return response.json()["tactics"]


def _row(section: dict, motif: str) -> dict:
    return next(row for row in section["rows"] if row["motif"] == motif)


def test_insights_section_counts_and_rates() -> None:
    value = _material(FORK_FEN) + 400
    found = _with_ids(_fork_game(value, FORK_UCI, value))
    missed = _with_ids(_fork_game(value, "h1e1", value - 400))
    _seed("tactics_rate", [found] * 7 + [missed] * 3 + [None] * 2)
    section = _insights("tactics_rate")
    assert section["sample_size"] == 10
    assert section["games_without_evals"] == 2
    assert (section["found"], section["missed"]) == (7, 3)
    row = _row(section, "fork")
    assert (row["found"], row["missed"], row["chances"]) == (7, 3, MIN_CHANCES)
    assert row["low_sample"] is False
    assert row["found_pct"] == 70.0
    assert row["found_low_pct"] < 70 < row["found_high_pct"]
    assert row["practice_tag"] == "fork"
    assert len(row["examples"]) == tactics.MAX_EXAMPLES
    example = row["examples"][0]
    assert example["fen"] == FORK_FEN
    assert example["game_id"].startswith("tactics_rate-")
    assert example["best_san"] == "Nxf7"


def test_small_samples_show_counts_without_a_rate() -> None:
    value = _material(FORK_FEN) + 400
    _seed("tactics_small", [_with_ids(_fork_game(value, FORK_UCI, value))] * (MIN_CHANCES - 1))
    row = _row(_insights("tactics_small"), "fork")
    assert row["found"] == MIN_CHANCES - 1
    assert row["low_sample"] is True
    assert row["found_pct"] is None
    assert row["found_low_pct"] is None


def test_games_without_stored_evals_are_left_out_not_guessed() -> None:
    _seed("tactics_old", [None] * 3)
    section = _insights("tactics_old")
    assert section["sample_size"] == 0
    assert section["games_without_evals"] == 3
    assert section["found"] == section["missed"] == 0


def test_unknown_player_gets_an_empty_section() -> None:
    section = _insights("tactics_nobody")
    assert section["sample_size"] == 0
    assert section["rows"] == []


def test_every_motif_links_to_puzzles_that_exist() -> None:
    for _, _, tag in tactics.MOTIFS:
        assert filter_puzzles(tag=tag), tag


def test_per_game_results_are_cached_until_the_engine_data_changes(monkeypatch) -> None:
    value = _material(FORK_FEN) + 400
    game = _with_ids(_fork_game(value, FORK_UCI, value))
    calls = []
    real = tactics.game_chances
    monkeypatch.setattr(tactics, "game_chances", lambda *args: calls.append(args) or real(*args))
    tactics.cached_game_chances("cache-test", game, "white")
    tactics.cached_game_chances("cache-test", game, "white")
    assert len(calls) == 1
    changed = [dict(game[0]), {**game[1], "eval_cp": value - 1}]
    tactics.cached_game_chances("cache-test", changed, "white")
    assert len(calls) == 2


def test_puzzle_tag_filter() -> None:
    forks = filter_puzzles(tag="fork")
    assert forks and all("fork" in item.tags for item in forks)
    with TestClient(app) as client:
        response = client.get("/api/puzzles", params={"tag": "skewer", "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(filter_puzzles(tag="skewer"))
    assert len(body["puzzles"]) == 5
