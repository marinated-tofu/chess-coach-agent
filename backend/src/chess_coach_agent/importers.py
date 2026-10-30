from __future__ import annotations

import asyncio
import io
import os
from urllib.parse import quote

import chess.pgn
import httpx

from .models import GamePreview
from .pgn import parse_pgn_text
from .repositories import normalize_username

CHESSCOM_API_BASE = "https://api.chess.com/pub/player"
LICHESS_GAMES_URL = "https://lichess.org/api/games/user"


def chesscom_user_agent() -> str:
    contact = os.getenv("CHESSCOM_API_CONTACT", "chess-coach-agent@users.noreply.github.com")
    return f"chess-coach-agent/0.2 (contact: {contact})"


def lichess_user_agent() -> str:
    contact = os.getenv("LICHESS_API_CONTACT", "chess-coach-agent@users.noreply.github.com")
    return f"chess-coach-agent/0.2 (contact: {contact})"


def _http_client(headers: dict[str, str], timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)


PLATFORM_NAMES = {"chess.com": "Chess.com", "lichess": "Lichess"}
RATE_LIMIT_RETRIES = 3


class ImportSourceError(Exception):
    """A user-facing failure while fetching games from Chess.com or Lichess."""


async def _get(client: httpx.AsyncClient, url: str, platform: str, username: str) -> httpx.Response:
    name = PLATFORM_NAMES.get(platform, platform)
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise ImportSourceError(f"{name} did not respond in time. Try again shortly.") from exc
        except httpx.RequestError as exc:
            raise ImportSourceError(f"Could not reach {name}: {exc.__class__.__name__}.") from exc
        if response.status_code != 429 or attempt == RATE_LIMIT_RETRIES:
            break
        try:
            delay = float(response.headers.get("Retry-After", ""))
        except ValueError:
            delay = 2.0 * (attempt + 1)
        await asyncio.sleep(min(delay, 60.0))
    if response.status_code == 404:
        raise ImportSourceError(f"{name} player '{username}' was not found.")
    if response.status_code == 403 and platform == "chess.com":
        raise ImportSourceError(
            "Chess.com returned 403 Forbidden. Set CHESSCOM_API_CONTACT in backend/.env "
            "(an email or Chess.com username) and retry. Chess.com often blocks cloud-host "
            "IPs, so sync locally or use Lichess if it keeps failing."
        )
    if response.status_code == 429:
        raise ImportSourceError(f"{name} is rate limiting requests. Wait a minute and sync again.")
    if response.status_code >= 400:
        raise ImportSourceError(f"{name} returned HTTP {response.status_code} for '{username}'.")
    return response


async def fetch_chesscom_pgn(username: str, max_games: int = 20) -> str:
    # Chess.com answers mixed-case usernames with a 301 to the lowercase URL.
    handle = normalize_username(username)
    headers = {"User-Agent": chesscom_user_agent()}
    async with _http_client(headers, timeout=30) as client:
        archives = await _get(
            client,
            f"{CHESSCOM_API_BASE}/{quote(handle, safe='')}/games/archives",
            "chess.com",
            username,
        )
        urls = archives.json().get("archives", [])
        if not urls:
            return ""
        chunks: list[str] = []
        for url in reversed(urls):
            response = await _get(client, url + "/pgn", "chess.com", username)
            chunks.append(response.text)
            if sum(chunk.count("[Event ") for chunk in chunks) >= max_games:
                break
            # Chess.com asks clients not to hammer archive endpoints.
            await asyncio.sleep(0.15)
    return "\n\n".join(chunks)


async def fetch_lichess_pgn(username: str, max_games: int = 20) -> str:
    handle = normalize_username(username)
    headers = {
        "Accept": "application/x-chess-pgn",
        "User-Agent": lichess_user_agent(),
    }
    url = (
        f"{LICHESS_GAMES_URL}/{quote(handle, safe='')}"
        f"?max={max_games}&pgnInJson=false&clocks=true&evals=false"
    )
    async with _http_client(headers, timeout=45) as client:
        response = await _get(client, url, "lichess", username)
        return response.text


async def fetch_platform_pgn(platform: str, username: str, max_games: int) -> str:
    if platform == "chess.com":
        return await fetch_chesscom_pgn(username, max_games)
    return await fetch_lichess_pgn(username, max_games)


def preview_pgn_games(
    pgn_text: str,
    username: str,
    platform: str,
    max_games: int = 50,
) -> list[GamePreview]:
    handle = io.StringIO(pgn_text)
    previews: list[GamePreview] = []
    while len(previews) < max_games:
        game = chess.pgn.read_game(handle)
        if game is None:
            break
        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=True)
        game_pgn = game.accept(exporter)
        parsed = parse_pgn_text(game_pgn, player=username, max_games=1)
        if not parsed:
            continue
        metadata = parsed[0].metadata
        headers = game.headers
        if metadata.player_color == "white":
            opponent = metadata.black
            opponent_elo_raw = headers.get("BlackElo", "")
        elif metadata.player_color == "black":
            opponent = metadata.white
            opponent_elo_raw = headers.get("WhiteElo", "")
        else:
            opponent = metadata.black
            opponent_elo_raw = ""
        try:
            opponent_elo = int(opponent_elo_raw)
        except ValueError:
            opponent_elo = None
        previews.append(
            GamePreview(
                game_id=metadata.game_id,
                pgn=game_pgn,
                source=platform,  # type: ignore[arg-type]
                white=metadata.white,
                black=metadata.black,
                result=metadata.result,
                date=metadata.date,
                started_at=metadata.started_at,
                time_control=metadata.time_control,
                link=metadata.link,
                player_color=metadata.player_color,
                player_result=metadata.player_result,
                player_elo=metadata.player_elo,
                opponent=opponent,
                opponent_elo=opponent_elo,
            )
        )
    return previews
