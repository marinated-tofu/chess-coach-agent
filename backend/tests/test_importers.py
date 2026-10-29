import asyncio
import hashlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from chess_coach_agent import importers
from chess_coach_agent.adaptive_api import _sync_failure_message
from chess_coach_agent.agent import sample_pgn
from chess_coach_agent.importers import (
    ImportSourceError,
    chesscom_user_agent,
    fetch_chesscom_pgn,
    fetch_lichess_pgn,
    preview_pgn_games,
)
from chess_coach_agent.pgn import parse_pgn_text


def test_preview_pgn_games_returns_selectable_metadata_and_unique_ids():
    games = preview_pgn_games(sample_pgn(), "kfctofu", "chess.com", max_games=8)
    assert len(games) == 8
    assert len({game.game_id for game in games}) == 8
    assert games[0].opponent
    assert games[0].player_result in {"win", "loss", "draw", "unknown"}
    assert "[Event " in games[0].pgn



GAME_PGN = '[Event "Live"]\n[Site "Chess.com"]\n[White "kfctofu"]\n[Black "rival"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'

REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_http(monkeypatch, handler):
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def client_factory(**kwargs):
        return REAL_ASYNC_CLIENT(transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr(importers.httpx, "AsyncClient", client_factory)

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(importers.asyncio, "sleep", no_sleep)
    return requests


def test_chesscom_fetch_uses_lowercase_username_and_sends_user_agent(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != request.url.path.lower():
            return httpx.Response(301, headers={"Location": str(request.url).lower()})
        if request.url.path.endswith("/archives"):
            return httpx.Response(
                200,
                json={"archives": ["https://api.chess.com/pub/player/kfctofu/games/2026/10"]},
            )
        return httpx.Response(200, text=GAME_PGN)

    requests = _mock_http(monkeypatch, handler)
    pgn = asyncio.run(fetch_chesscom_pgn(" KFCTofu ", max_games=5))
    assert "[Event " in pgn
    assert requests[0].url.path == "/pub/player/kfctofu/games/archives"
    assert requests[0].headers["User-Agent"].startswith("chess-coach-agent")


def test_unknown_player_raises_readable_error(monkeypatch):
    _mock_http(monkeypatch, lambda _request: httpx.Response(404, text="<html>Not found</html>"))
    with pytest.raises(ImportSourceError, match="Lichess player 'nobody' was not found"):
        asyncio.run(fetch_lichess_pgn("nobody"))
    with pytest.raises(ImportSourceError, match="Chess.com player 'nobody' was not found"):
        asyncio.run(fetch_chesscom_pgn("nobody"))


def test_rate_limit_is_retried_then_reported(monkeypatch):
    responses = iter([httpx.Response(429), httpx.Response(200, text=GAME_PGN)])
    _mock_http(monkeypatch, lambda _request: next(responses))
    assert "[Event " in asyncio.run(fetch_lichess_pgn("kfctofu"))

    _mock_http(monkeypatch, lambda _request: httpx.Response(429, headers={"Retry-After": "1"}))
    with pytest.raises(ImportSourceError, match="rate limiting"):
        asyncio.run(fetch_lichess_pgn("kfctofu"))


def test_network_failure_raises_readable_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("", request=request)

    _mock_http(monkeypatch, handler)
    with pytest.raises(ImportSourceError, match="Could not reach Chess.com: ConnectError"):
        asyncio.run(fetch_chesscom_pgn("kfctofu"))


def test_non_pgn_text_and_header_only_games_are_skipped():
    assert parse_pgn_text("hello world", player="kfctofu") == []
    assert parse_pgn_text('[White "a"]\n[Black "b"]\n[Result "*"]\n\n*', player="a") == []


def test_headerless_games_get_distinct_ids_and_readable_names():
    games = parse_pgn_text("1. e4 e5 2. Nf3 Nc6 *\n\n1. d4 d5 2. c4 *", player="kfctofu")
    assert len(games) == 2
    assert games[0].game_id != games[1].game_id
    assert (games[0].metadata.white, games[0].metadata.black) == ("White", "Black")
    assert games[0].metadata.link == ""


def test_source_identified_game_ids_are_unchanged():
    # Stored Chess.com/Lichess games are deduplicated by this id; it must stay stable.
    game = parse_pgn_text(sample_pgn(), player="kfctofu", max_games=1)[0]
    headers = game.game.headers
    raw_id = "|".join(
        [
            headers.get("Site", ""),
            headers.get("Link", ""),
            headers.get("Date", ""),
            headers.get("UTCTime", headers.get("StartTime", "")),
            headers.get("White", ""),
            headers.get("Black", ""),
            headers.get("Result", ""),
        ]
    )
    assert game.game_id == hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12]
def test_chesscom_user_agent_includes_contact():
    assert "contact:" in chesscom_user_agent()


@pytest.mark.asyncio
async def test_fetch_chesscom_pgn_uses_lowercase_handle():
    request = httpx.Request("GET", "https://api.chess.com/pub/player/magnuscarlsen/games/archives")
    response = httpx.Response(200, request=request, json={"archives": []})
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("chess_coach_agent.importers._http_client", return_value=client):
        await fetch_chesscom_pgn("MagnusCarlsen", max_games=1)

    assert client.get.await_args_list[0].args[0].endswith("/magnuscarlsen/games/archives")


def test_sync_failure_message_for_chesscom_403():
    request = httpx.Request("GET", "https://api.chess.com/pub/player/foo/games/archives")
    response = httpx.Response(403, request=request)
    exc = httpx.HTTPStatusError("blocked", request=request, response=response)
    message = _sync_failure_message(exc)
    assert "403" in message
    assert "CHESSCOM_API_CONTACT" in message
