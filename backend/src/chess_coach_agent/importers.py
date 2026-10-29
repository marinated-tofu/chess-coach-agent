from __future__ import annotations

import asyncio
import io
from urllib.parse import quote

import chess.pgn
import httpx

from .models import GamePreview
from .pgn import parse_pgn_text

USER_AGENT = "chess-coach-agent/0.1 educational capstone"
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
    if response.status_code == 429:
        raise ImportSourceError(f"{name} is rate limiting requests. Wait a minute and sync again.")
    if response.status_code >= 400:
        raise ImportSourceError(f"{name} returned HTTP {response.status_code} for '{username}'.")
    return response


async def fetch_chesscom_pgn(username: str, max_games: int = 20) -> str:
    username = username.strip()
    # Chess.com answers mixed-case usernames with a 301 to the lowercase URL.
    player_url = f"https://api.chess.com/pub/player/{quote(username.lower(), safe='')}"
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
        archives = await _get(client, f"{player_url}/games/archives", "chess.com", username)
        urls = archives.json().get("archives", [])
        chunks: list[str] = []
        for url in reversed(urls):
            response = await _get(client, url + "/pgn", "chess.com", username)
            chunks.append(response.text)
            if sum(chunk.count("[Event ") for chunk in chunks) >= max_games:
                break
    return "\n\n".join(chunks)


async def fetch_lichess_pgn(username: str, max_games: int = 20) -> str:
    username = username.strip()
    headers = {"Accept": "application/x-chess-pgn", "User-Agent": USER_AGENT}
    url = (
        f"https://lichess.org/api/games/user/{quote(username, safe='')}"
        f"?max={max_games}&pgnInJson=false&clocks=true&evals=false"
    )
    async with httpx.AsyncClient(timeout=45, headers=headers, follow_redirects=True) as client:
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
