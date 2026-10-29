from datetime import UTC, datetime, timedelta
from uuid import uuid4

import chess
from fastapi.testclient import TestClient

from chess_coach_agent import repertoire
from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import GameRow, RepertoireReviewRow, RepertoireRow
from chess_coach_agent.repositories import get_or_create_player

client = TestClient(app)


def _player() -> tuple[str, str]:
    username = f"rep-{uuid4().hex[:10]}"
    with session_scope() as session:
        player = get_or_create_player(session, "chess.com", username)
        return player.id, username


def _game(
    player_id: str, color: str, sans: list[str], result: str, labels: dict[int, dict] | None = None
):
    board = chess.Board()
    moves = []
    for ply, san in enumerate(sans):
        move = board.parse_san(san)
        record = {
            "ply": ply + 1,
            "san": san,
            "uci": move.uci(),
            "color": "white" if board.turn else "black",
        }
        record.update((labels or {}).get(ply, {}))
        moves.append(record)
        board.push(move)
    with session_scope() as session:
        session.add(
            GameRow(
                player_id=player_id,
                external_game_id=uuid4().hex,
                white="a",
                black="b",
                result="*",
                player_result=result,
                player_color=color,
                metadata_json={"moves": moves},
            )
        )


def _create(username: str, color: str = "white") -> dict:
    response = client.post(
        "/api/repertoire", json={"platform": "chess.com", "username": username, "color": color}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _flatten(tree: list[dict]) -> list[dict]:
    out = []
    for node in tree:
        out.append(node)
        out.extend(_flatten(node["children"]))
    return out


def test_crud_and_legality():
    _, username = _player()
    rep = _create(username)
    assert rep["name"] == "White repertoire" and rep["tree"] == [] and rep["due_count"] == 0

    listed = client.get("/api/repertoire", params={"platform": "chess.com", "username": username})
    assert [r["id"] for r in listed.json()] == [rep["id"]]

    start = chess.STARTING_FEN
    added = client.post(
        f"/api/repertoire/{rep['id']}/moves", json={"parent_fen": start, "move": "e4"}
    )
    assert added.status_code == 200 and added.json()["san"] == "e4"
    assert added.json()["due_count"] == 1  # player's move gets a review row

    illegal = client.post(
        f"/api/repertoire/{rep['id']}/moves", json={"parent_fen": start, "move": "e5"}
    )
    assert illegal.status_code == 422

    after_e4 = added.json()["tree"][0]["fen_after"]
    reply = client.post(
        f"/api/repertoire/{rep['id']}/moves", json={"parent_fen": after_e4, "move": "c7c5"}
    )
    assert reply.json()["san"] == "c5"
    assert reply.json()["due_count"] == 1  # opponent moves are not drilled
    dup = client.post(
        f"/api/repertoire/{rep['id']}/moves", json={"parent_fen": after_e4, "move": "c5"}
    )
    assert dup.json()["created"] is False

    tree = reply.json()["tree"]
    assert tree[0]["san"] == "e4" and tree[0]["children"][0]["san"] == "c5"
    assert tree[0]["is_player_move"] and not tree[0]["children"][0]["is_player_move"]

    removed = client.delete(f"/api/repertoire/{rep['id']}/moves/{tree[0]['id']}")
    assert removed.json()["removed"] == 2 and removed.json()["tree"] == []

    assert client.delete(f"/api/repertoire/{rep['id']}").status_code == 200
    assert client.get(f"/api/repertoire/{rep['id']}").status_code == 404


def test_seed_from_games_picks_frequent_lines_and_replaces_mistakes():
    player_id, username = _player()
    for _ in range(4):
        _game(player_id, "white", ["e4", "e5", "Nf3", "Nc6", "Bc4"], "win")
    for _ in range(3):
        _game(player_id, "white", ["e4", "c5", "Nf3", "d6", "d4"], "draw")
    _game(player_id, "white", ["d4", "d5"], "loss")
    # Against the French the player keeps playing an inaccuracy on move 2.
    bad = {2: {"classification": "inaccuracy", "best_uci": "d2d4", "best_san": "d4"}}
    for _ in range(3):
        _game(player_id, "white", ["e4", "e6", "Qh5", "d5"], "loss", labels=bad)
    rep = _create(username)

    seeded = client.post(f"/api/repertoire/{rep['id']}/seed").json()
    assert seeded["games_used"] == 11
    nodes = _flatten(seeded["tree"])
    assert seeded["tree"][0]["san"] == "e4" and len(seeded["tree"]) == 1
    replies = {child["san"] for child in seeded["tree"][0]["children"]}
    assert replies == {"e5", "c5", "e6"}
    assert any(n["san"] == "Bc4" for n in nodes)
    assert not any(n["san"] == "d4" and n["parent_fen"] == chess.Board().epd() for n in nodes)

    french = next(c for c in seeded["tree"][0]["children"] if c["san"] == "e6")
    fix = french["children"][0]
    assert fix["san"] == "d4" and fix["mistake_count"] == 3
    assert fix["comment"] == "You played Qh5?! here 3 times; the engine prefers d4."
    assert not any(n["san"] == "Qh5" for n in nodes)
    assert seeded["flagged"][0]["played_san"] == "Qh5"

    again = client.post(f"/api/repertoire/{rep['id']}/seed").json()
    assert again["added"] == 0


def test_seed_uses_engine_when_no_stored_best():
    player_id, username = _player()
    for _ in range(3):
        _game(
            player_id,
            "black",
            ["e4", "f6", "d4"],
            "loss",
            labels={1: {"classification": "mistake"}},
        )
    with session_scope() as session:
        rep = RepertoireRow(player_id=player_id, color="black", name="b")
        session.add(rep)
        session.flush()
        report = repertoire.seed_from_games(
            session, rep, engine_best=lambda board: chess.Move.from_uci("e7e5")
        )
        assert report.flagged[0]["best_san"] == "e5"
        tree = repertoire.build_tree(session, rep)
    assert tree[0]["san"] == "e4" and not tree[0]["is_player_move"]
    assert (
        tree[0]["children"][0]["comment"] == "You played f6? here 3 times; the engine prefers e5."
    )


def test_drill_and_scheduling():
    _, username = _player()
    rep = _create(username)
    rid = rep["id"]
    first = client.post(
        f"/api/repertoire/{rid}/moves", json={"parent_fen": chess.STARTING_FEN, "move": "e4"}
    ).json()
    after_e4 = first["tree"][0]["fen_after"]
    reply = client.post(
        f"/api/repertoire/{rid}/moves", json={"parent_fen": after_e4, "move": "e5"}
    ).json()
    after_e5 = reply["tree"][0]["children"][0]["fen_after"]
    client.post(f"/api/repertoire/{rid}/moves", json={"parent_fen": after_e5, "move": "Nf3"})

    drill = client.get(f"/api/repertoire/{rid}/drill", params={"limit": 10}).json()
    assert drill["due_count"] == 2
    nf3 = next(item for item in drill["items"] if item["line"] == ["e4", "e5"])
    assert nf3["last_move"] == "e7e5"
    assert chess.Board(nf3["fen"]).epd() == after_e5

    wrong = client.post(
        f"/api/repertoire/{rid}/drill/answer", json={"move_id": nf3["move_id"], "move": "Nc3"}
    ).json()
    assert wrong["correct"] is False and wrong["expected_san"] == "Nf3" and wrong["streak"] == 0
    assert wrong["due_count"] == 1  # back in ten minutes

    right = client.post(
        f"/api/repertoire/{rid}/drill/answer", json={"move_id": nf3["move_id"], "move": "g1f3"}
    ).json()
    assert right["correct"] is True and right["interval_days"] == 1 and right["streak"] == 1

    only_due = client.get(f"/api/repertoire/{rid}/drill").json()
    assert [i["line"] for i in only_due["items"]] == [[]]
    everything = client.get(f"/api/repertoire/{rid}/drill", params={"include_all": True}).json()
    assert len(everything["items"]) == 2


def test_schedule_grows_and_resets():
    review = RepertoireReviewRow(
        move_id="x", due_at=datetime.now(UTC), interval_days=0, ease=2.5, streak=0
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    intervals = []
    for _ in range(4):
        repertoire.schedule(review, True, now)
        intervals.append(review.interval_days)
    assert intervals[:2] == [1, 3] and intervals[2] > 3 and intervals[3] > intervals[2]
    assert review.due_at == now + timedelta(days=intervals[-1])
    repertoire.schedule(review, False, now)
    assert review.streak == 0 and review.interval_days == 0
    assert review.due_at == now + timedelta(minutes=10) and review.last_result == "wrong"
