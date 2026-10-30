from __future__ import annotations

import chess
import httpx
import pytest
from fastapi.testclient import TestClient

from chess_coach_agent import benchmarks
from chess_coach_agent.api import app
from chess_coach_agent.benchmarks import (
    MIN_COHORT_PLAYERS,
    SourceUnavailable,
    band_for,
    compare,
    LICHESS_PLAYERS_AS_OF,
    LICHESS_WEEKLY_PLAYERS,
    fetch_lichess_perf,
    lichess_percentiles,
    lichess_perf,
)
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import (
    CriticalMomentRow,
    GameRow,
    PlayerMemoryRow,
    UserPlayerRow,
    UserRow,
)
from chess_coach_agent.repositories import get_or_create_player

LINE = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3", "Nf6", "d4", "exd4", "cxd4", "Bb4+"]
BLUNDER_SEVERITY = 40.0


def _moves(accuracy: float) -> list[dict]:
    board = chess.Board()
    moves = []
    for index, san in enumerate(LINE):
        fen_before = board.fen()
        color = "white" if board.turn == chess.WHITE else "black"
        board.push_san(san)
        moves.append(
            {
                "ply": index + 1,
                "color": color,
                "san": san,
                "fen_before": fen_before,
                "win_pct": 50.0,
                "accuracy": accuracy,
            }
        )
    return moves


def _seed_player(
    platform: str,
    username: str,
    elo: int = 1500,
    games: int = 10,
    time_control: str = "300",
    accuracy: float = 80.0,
    blunders: int = 0,
    engine: bool = True,
) -> None:
    with session_scope() as session:
        player = get_or_create_player(session, platform, username)
        for number in range(games):
            moves = _moves(accuracy)
            if not engine:
                for move in moves:
                    del move["win_pct"]
            row = GameRow(
                player_id=player.id,
                external_game_id=f"{username}-{number}",
                white=username,
                black="opp",
                result="1-0",
                player_result="win",
                player_color="white",
                player_elo=elo,
                played_at=f"2026.02.{number % 27 + 1:02d}",
                time_control=time_control,
                metadata_json={"game": {"player_color": "white"}, "moves": moves},
            )
            session.add(row)
            session.flush()
            for moment in range(blunders if number == 0 else 0):
                session.add(
                    CriticalMomentRow(
                        game_id=row.id,
                        external_moment_id=f"m{moment}",
                        move_number=1,
                        ply=moment * 2 + 1,
                        phase="opening",
                        theme="missed_tactic",
                        played_san="e4",
                        fen_before=chess.STARTING_FEN,
                        fen_after=chess.STARTING_FEN,
                        severity=BLUNDER_SEVERITY,
                    )
                )


def _seed_peers(platform: str, prefix: str, count: int, elo: int = 1500, **kwargs) -> None:
    for number in range(count):
        _seed_player(platform, f"{prefix}{number}", elo=elo, accuracy=70.0 + number * 0.1, **kwargs)


@pytest.fixture(autouse=True)
def clean_state():
    benchmarks.reset_lichess_state()
    benchmarks.clear_cohort_cache()
    yield
    benchmarks.reset_lichess_state()
    benchmarks.clear_cohort_cache()


@pytest.fixture
def no_lichess(monkeypatch):
    """Any call that reaches the network here is a failure of the test's setup."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("unexpected Lichess call")

    monkeypatch.setattr(benchmarks, "_request", refuse)


def _lichess(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _perf_json(rating: float = 1744.46, percentile: float | None = 74.6) -> dict:
    data: dict = {"perf": {"glicko": {"rating": rating, "deviation": 49.4}, "nb": 100}}
    if percentile is not None:
        data["percentile"] = percentile
    return data


def _healthy(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_perf_json())


# --------------------------------------------------------------------------- pure helpers


@pytest.mark.parametrize(
    "control,perf",
    [
        ("15+0", "ultraBullet"),
        ("60", "bullet"),
        ("180+2", "blitz"),
        ("480", "rapid"),  # Lichess rapid; the app's own blitz bucket runs to 600 s
        ("900+10", "rapid"),
        ("1800+20", "classical"),
        ("-", None),
        ("1/259200", None),
    ],
)
def test_lichess_perf_uses_lichess_speeds(control, perf):
    assert lichess_perf(control) == perf


@pytest.mark.parametrize("rating,band", [(1400, 1400), (1599, 1400), (1600, 1600), (87, 0)])
def test_rating_bands(rating, band):
    assert band_for(rating) == band


def test_compare_respects_direction_and_does_not_count_ties():
    assert compare(80.0, [70.0, 80.0, 90.0], True) == (80.0, 1)
    assert compare(0.5, [0.2, 0.5, 0.9], False) == (0.5, 1)


# --------------------------------------------------------------------------- Lichess source


def test_percentile_row_carries_the_real_numbers_and_sample_size():
    rows = lichess_percentiles("thibault", ["blitz"], _lichess(_healthy))
    assert len(rows) == 1
    assert rows[0].rating == 1744
    assert rows[0].percentile == 74.6
    assert rows[0].players == LICHESS_WEEKLY_PLAYERS["blitz"]
    assert rows[0].players_as_of == LICHESS_PLAYERS_AS_OF
    assert rows[0].source_url == "https://lichess.org/stat/rating/distribution/blitz"


def test_provisional_rating_is_left_out():
    client = _lichess(lambda _request: httpx.Response(200, json=_perf_json(percentile=None)))
    assert lichess_percentiles("newcomer", ["classical"], client) == []


def test_speed_without_a_cited_sample_size_is_left_out():
    client = _lichess(_healthy)
    assert lichess_percentiles("thibault", ["correspondence"], client) == []


def test_unknown_lichess_user_is_left_out():
    client = _lichess(lambda _request: httpx.Response(404))
    assert lichess_percentiles("nobody", ["blitz"], client) == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"perf": {}}),
        httpx.Response(200, json=_perf_json(percentile=140.0)),
    ],
)
def test_bad_lichess_answers_are_left_out(response):
    client = _lichess(lambda _request: response)
    assert lichess_percentiles("thibault", ["blitz"], client) == []


def test_network_failure_is_left_out():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    assert lichess_percentiles("thibault", ["blitz"], _lichess(handler)) == []


def test_answers_are_cached():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _healthy(request)

    client = _lichess(handler)
    first = lichess_percentiles("thibault", ["blitz"], client)
    assert lichess_percentiles("THIBAULT", ["blitz"], client) == first
    assert len(calls) == 1


def test_failure_is_not_retried_straight_away():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500)

    client = _lichess(handler)
    for _ in range(2):
        with pytest.raises(SourceUnavailable):
            fetch_lichess_perf("thibault", "blitz", client)
    assert len(calls) == 1


def test_rate_limit_stops_every_lichess_call():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(429, headers={"Retry-After": "1"})

    client = _lichess(handler)
    with pytest.raises(SourceUnavailable):
        fetch_lichess_perf("thibault", "blitz", client)
    with pytest.raises(SourceUnavailable):
        fetch_lichess_perf("someone-else", "rapid", client)
    assert len(calls) == 1


# --------------------------------------------------------------------------- route


def test_unknown_player_and_pasted_pgn_get_nothing(no_lichess):
    client = TestClient(app)
    for path in ("/api/benchmarks/lichess/nobody_here", "/api/benchmarks/pgn/anyone"):
        body = client.get(path).json()
        assert body["rating_percentiles"] == []
        assert body["cohorts"] == []


def test_chess_com_player_never_gets_a_lichess_percentile(no_lichess):
    _seed_player("chess.com", "bm_chesscom_only")
    body = TestClient(app).get("/api/benchmarks/chess.com/bm_chesscom_only").json()
    assert body["rating_percentiles"] == []


def test_lichess_percentile_only_for_speeds_the_player_plays(monkeypatch):
    _seed_player("lichess", "bm_percentile", games=12, time_control="300")
    _seed_player("lichess", "bm_percentile_other", games=2, time_control="60")
    asked: list[list[str]] = []

    def fake(_username, perfs, _client=None):
        asked.append(perfs)
        return []

    monkeypatch.setattr("chess_coach_agent.benchmarks_api.lichess_percentiles", fake)
    assert TestClient(app).get("/api/benchmarks/lichess/bm_percentile").status_code == 200
    assert asked == [["blitz"]]


def test_lichess_failure_empties_the_section(monkeypatch):
    _seed_player("lichess", "bm_failure", games=12)

    def down(_url, _client):
        raise SourceUnavailable("down")

    monkeypatch.setattr(benchmarks, "_request", down)
    response = TestClient(app).get("/api/benchmarks/lichess/bm_failure")
    assert response.status_code == 200
    assert response.json()["rating_percentiles"] == []


def test_cohort_one_short_shows_nothing_and_loads_no_games(no_lichess, monkeypatch):
    _seed_peers("chess.com", "bm_short_", MIN_COHORT_PLAYERS - 1, elo=1100)
    _seed_player("chess.com", "bm_short_me", elo=1100)
    loaded: list[str] = []
    real = benchmarks._load_games
    monkeypatch.setattr(
        benchmarks, "_load_games", lambda *args: loaded.append(args[1]) or real(*args)
    )
    body = TestClient(app).get("/api/benchmarks/chess.com/bm_short_me").json()
    assert body["cohorts"] == []
    assert loaded == []


def test_cohort_at_the_threshold_compares_real_values(no_lichess):
    _seed_peers("chess.com", "bm_full_", MIN_COHORT_PLAYERS, elo=1300)
    _seed_player("chess.com", "bm_full_me", elo=1399, accuracy=71.05, blunders=3)
    body = TestClient(app).get("/api/benchmarks/chess.com/bm_full_me").json()
    assert len(body["cohorts"]) == 1
    cohort = body["cohorts"][0]
    assert (cohort["category"], cohort["band_low"], cohort["band_high"]) == ("blitz", 1200, 1399)
    assert cohort["players"] == MIN_COHORT_PLAYERS
    assert cohort["games"] == MIN_COHORT_PLAYERS * 10
    metrics = {metric["key"]: metric for metric in cohort["metrics"]}
    # Peers run 70.0, 70.1, ... 72.9, so 71.05 sits above 11 of them; the player is excluded.
    opening = metrics["opening_accuracy"]
    assert opening["value"] == 71.05
    assert opening["peer_median"] == pytest.approx(71.45)
    assert opening["better_than"] == 11
    assert opening["players"] == MIN_COHORT_PLAYERS
    # Peers have no blunders, the player has 3 in 10 games, and lower is better.
    assert metrics["blunders_per_game"]["value"] == 0.3
    assert metrics["blunders_per_game"]["peer_median"] == 0.0
    assert metrics["blunders_per_game"]["better_than"] == 0
    assert metrics["blunders_per_game"]["higher_is_better"] is False


def test_other_site_and_other_band_do_not_count_towards_the_cohort(no_lichess):
    _seed_peers("lichess", "bm_scale_", MIN_COHORT_PLAYERS, elo=1700)  # same number, other scale
    _seed_peers("chess.com", "bm_band_", MIN_COHORT_PLAYERS, elo=1900)  # same site, other band
    _seed_player("chess.com", "bm_scale_me", elo=1700)
    body = TestClient(app).get("/api/benchmarks/chess.com/bm_scale_me").json()
    assert body["cohorts"] == []


def test_other_time_controls_do_not_count_towards_the_cohort(no_lichess):
    _seed_peers("chess.com", "bm_tc_", MIN_COHORT_PLAYERS, elo=2100, time_control="60")
    _seed_player("chess.com", "bm_tc_me", elo=2100, time_control="600")
    body = TestClient(app).get("/api/benchmarks/chess.com/bm_tc_me").json()
    assert body["cohorts"] == []


def test_peers_without_engine_data_do_not_count(no_lichess):
    _seed_peers("chess.com", "bm_raw_", MIN_COHORT_PLAYERS, elo=2300, engine=False)
    _seed_player("chess.com", "bm_raw_me", elo=2300)
    body = TestClient(app).get("/api/benchmarks/chess.com/bm_raw_me").json()
    assert body["cohorts"] == []


def test_player_with_too_few_analyzed_games_is_not_compared(no_lichess):
    _seed_peers("chess.com", "bm_new_", MIN_COHORT_PLAYERS, elo=2500)
    _seed_player("chess.com", "bm_new_me", elo=2500, games=9)
    body = TestClient(app).get("/api/benchmarks/chess.com/bm_new_me").json()
    assert body["cohorts"] == []


def test_non_owner_sees_the_same_public_figures_and_no_practice_data(no_lichess):
    _seed_peers("chess.com", "bm_priv_", MIN_COHORT_PLAYERS, elo=2700)
    _seed_player("chess.com", "bm_priv_me", elo=2700)
    client = TestClient(app)
    before = client.get("/api/benchmarks/chess.com/bm_priv_me").json()
    assert before["cohorts"]

    with session_scope() as session:
        player = get_or_create_player(session, "chess.com", "bm_priv_me")
        user = UserRow(display_name="owner")
        session.add(user)
        session.flush()
        session.add(UserPlayerRow(user_id=user.id, player_id=player.id, verified_by="test"))
        memory = session.get_one(PlayerMemoryRow, player.id)
        memory.quiz_accuracy = {"missed_tactic": 0.1}
        memory.mastered_positions = 7
        memory.due_positions = 3
    benchmarks.clear_cohort_cache()

    after = client.get("/api/benchmarks/chess.com/bm_priv_me")
    assert after.status_code == 200
    assert after.json() == before
    assert "quiz" not in after.text
    assert "mastered" not in after.text
