"""Opening explorer: a position index over a player's own games, plus a cached Lichess proxy."""

from __future__ import annotations

import os
import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from .openings import fen_to_epd, opening_book

ColorFilter = Literal["white", "black", "both"]
LichessDb = Literal["masters", "lichess"]

MISTAKE_LABELS = {"inaccuracy", "mistake", "blunder"}
# A move is flagged when the player went wrong with it at least this often.
FREQUENT_MISTAKE_MIN_GAMES = 2
FREQUENT_MISTAKE_RATE = 0.2


# ---------------------------------------------------------------------------
# Player position index
# ---------------------------------------------------------------------------


@dataclass
class _MoveAgg:
    san: str
    uci: str
    games: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    accuracy_sum: float = 0.0
    accuracy_n: int = 0
    mistakes: int = 0
    player_moves: int = 0  # times the player (not the opponent) made this move
    labels: Counter[str] = field(default_factory=Counter)
    best_sans: Counter[str] = field(default_factory=Counter)
    last_played: str = ""


@dataclass
class GameSummary:
    """The few stored fields the index needs from one game row."""

    color: str
    result: str
    played_at: str
    moves: list[dict[str, Any]]


# epd -> player color -> uci -> aggregate
PositionIndex = dict[str, dict[str, dict[str, _MoveAgg]]]


def build_position_index(games: list[GameSummary]) -> PositionIndex:
    index: PositionIndex = {}
    for game in games:
        if game.color not in ("white", "black"):
            continue
        for move in game.moves:
            fen = move.get("fen_before")
            uci = move.get("uci")
            if not fen or not uci:
                continue
            by_color = index.setdefault(fen_to_epd(fen), {})
            moves = by_color.setdefault(game.color, {})
            agg = moves.get(uci)
            if agg is None:
                agg = moves[uci] = _MoveAgg(san=move.get("san") or uci, uci=uci)
            agg.games += 1
            if game.result == "win":
                agg.wins += 1
            elif game.result == "draw":
                agg.draws += 1
            elif game.result == "loss":
                agg.losses += 1
            agg.last_played = max(agg.last_played, game.played_at)
            is_player = move.get("is_player_move")
            if is_player is None:
                is_player = move.get("color") == game.color
            if not is_player:
                continue
            agg.player_moves += 1
            accuracy = move.get("accuracy")
            if isinstance(accuracy, (int, float)):
                agg.accuracy_sum += float(accuracy)
                agg.accuracy_n += 1
            label = move.get("classification")
            if label in MISTAKE_LABELS:
                agg.mistakes += 1
                agg.labels[label] += 1
                if move.get("best_san"):
                    agg.best_sans[move["best_san"]] += 1
    return index


def _merge(aggs: list[_MoveAgg]) -> _MoveAgg:
    if len(aggs) == 1:
        return aggs[0]
    out = _MoveAgg(san=aggs[0].san, uci=aggs[0].uci)
    for agg in aggs:
        out.games += agg.games
        out.wins += agg.wins
        out.draws += agg.draws
        out.losses += agg.losses
        out.accuracy_sum += agg.accuracy_sum
        out.accuracy_n += agg.accuracy_n
        out.mistakes += agg.mistakes
        out.player_moves += agg.player_moves
        out.labels.update(agg.labels)
        out.best_sans.update(agg.best_sans)
        out.last_played = max(out.last_played, agg.last_played)
    return out


def _score(wins: int, draws: int, losses: int) -> float | None:
    decided = wins + draws + losses
    return round((wins + 0.5 * draws) / decided * 100, 1) if decided else None


def is_frequent_mistake(mistakes: int, player_moves: int) -> bool:
    return (
        mistakes >= FREQUENT_MISTAKE_MIN_GAMES
        and player_moves > 0
        and mistakes / player_moves >= FREQUENT_MISTAKE_RATE
    )


def opening_for_fen(fen: str) -> dict[str, str] | None:
    opening = opening_book().get(fen_to_epd(fen))
    return {"eco": opening.eco, "name": opening.name} if opening else None


def query_player_index(index: PositionIndex, fen: str, color: ColorFilter) -> dict[str, Any]:
    by_color = index.get(fen_to_epd(fen), {})
    colors = ["white", "black"] if color == "both" else [color]
    grouped: dict[str, list[_MoveAgg]] = {}
    for c in colors:
        for uci, agg in by_color.get(c, {}).items():
            grouped.setdefault(uci, []).append(agg)
    rows: list[dict[str, Any]] = []
    worst: tuple[float, dict[str, Any]] | None = None
    for aggs in grouped.values():
        agg = _merge(aggs)
        frequent = is_frequent_mistake(agg.mistakes, agg.player_moves)
        row = {
            "san": agg.san,
            "uci": agg.uci,
            "games": agg.games,
            "wins": agg.wins,
            "draws": agg.draws,
            "losses": agg.losses,
            "score_pct": _score(agg.wins, agg.draws, agg.losses),
            "avg_accuracy": (
                round(agg.accuracy_sum / agg.accuracy_n, 1) if agg.accuracy_n else None
            ),
            "mistakes": agg.mistakes,
            "player_moves": agg.player_moves,
            "frequent_mistake": frequent,
            "last_played": agg.last_played,
        }
        rows.append(row)
        if agg.mistakes:
            rate = agg.mistakes / max(agg.player_moves, 1)
            key = rate * agg.mistakes
            if worst is None or key > worst[0]:
                best = agg.best_sans.most_common(1)
                worst = (
                    key,
                    {
                        "san": agg.san,
                        "uci": agg.uci,
                        "mistakes": agg.mistakes,
                        "player_moves": agg.player_moves,
                        "label": agg.labels.most_common(1)[0][0],
                        "best_san": best[0][0] if best else None,
                        "frequent": frequent,
                    },
                )
    rows.sort(key=lambda r: (-r["games"], r["san"]))
    return {
        "fen": fen,
        "color": color,
        "total": sum(r["games"] for r in rows),
        "opening": opening_for_fen(fen),
        "moves": rows,
        "common_mistake": worst[1] if worst else None,
    }


# ---------------------------------------------------------------------------
# Lichess explorer proxy
# ---------------------------------------------------------------------------

LICHESS_EXPLORER = "https://explorer.lichess.ovh"
USER_AGENT = "chess-coach-agent/0.2 (opening explorer; educational capstone)"
CACHE_SIZE = 2000
CACHE_TTL_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 6.0
DEFAULT_BACKOFF_SECONDS = 60.0


class ExplorerUnavailable(Exception):
    """Lichess could not answer; the message is safe to show to the user."""


class _TtlLru:
    def __init__(self, size: int, ttl: float) -> None:
        self.size = size
        self.ttl = ttl
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            stored_at, value = item
            if time.monotonic() - stored_at > self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_lichess_cache = _TtlLru(CACHE_SIZE, CACHE_TTL_SECONDS)
_backoff_until = 0.0
_backoff_lock = threading.Lock()


def reset_lichess_state() -> None:
    """For tests: forget cached responses and any rate-limit back-off."""
    global _backoff_until
    _lichess_cache.clear()
    with _backoff_lock:
        _backoff_until = 0.0


def _lichess_token() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    return os.getenv("LICHESS_API_TOKEN", "").strip()


def normalize_lichess(payload: dict[str, Any], db: LichessDb) -> dict[str, Any]:
    def row(entry: dict[str, Any]) -> dict[str, Any]:
        white, draws, black = (int(entry.get(k) or 0) for k in ("white", "draws", "black"))
        total = white + draws + black
        return {
            "san": entry.get("san", ""),
            "uci": entry.get("uci", ""),
            "games": total,
            "white": white,
            "draws": draws,
            "black": black,
            "avg_rating": entry.get("averageRating"),
            "white_pct": round(white / total * 100, 1) if total else 0.0,
            "draw_pct": round(draws / total * 100, 1) if total else 0.0,
            "black_pct": round(black / total * 100, 1) if total else 0.0,
            "opening": entry.get("opening"),
        }

    def game(entry: dict[str, Any]) -> dict[str, Any]:
        white = entry.get("white") or {}
        black = entry.get("black") or {}
        game_id = entry.get("id", "")
        return {
            "id": game_id,
            "uci": entry.get("uci"),
            "white": white.get("name", "?"),
            "white_rating": white.get("rating"),
            "black": black.get("name", "?"),
            "black_rating": black.get("rating"),
            "winner": entry.get("winner"),
            "year": entry.get("year"),
            "month": entry.get("month"),
            "url": f"https://lichess.org/{game_id}" if game_id else None,
        }

    white, draws, black = (int(payload.get(k) or 0) for k in ("white", "draws", "black"))
    return {
        "db": db,
        "total": white + draws + black,
        "white": white,
        "draws": draws,
        "black": black,
        "opening": payload.get("opening"),
        "moves": [row(m) for m in payload.get("moves", [])],
        "top_games": [game(g) for g in payload.get("topGames", [])],
        "recent_games": [game(g) for g in payload.get("recentGames", [])],
    }


def fetch_lichess(
    fen: str,
    db: LichessDb,
    ratings: str = "",
    speeds: str = "",
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    global _backoff_until
    key = (db, fen_to_epd(fen), ratings, speeds)
    cached = _lichess_cache.get(key)
    if cached is not None:
        return cached
    with _backoff_lock:
        wait = _backoff_until - time.monotonic()
    if wait > 0:
        raise ExplorerUnavailable(
            f"Lichess is rate limiting the explorer. Try again in {int(wait) + 1} s."
        )

    params: dict[str, str] = {"fen": fen, "moves": "12", "topGames": "8"}
    if db == "lichess":
        params["recentGames"] = "0"
        if ratings:
            params["ratings"] = ratings
        if speeds:
            params["speeds"] = speeds
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    token = _lichess_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    own_client = client is None
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = http.get(f"{LICHESS_EXPLORER}/{db}", params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise ExplorerUnavailable("Lichess explorer did not answer in time.") from exc
    except httpx.HTTPError as exc:
        raise ExplorerUnavailable("Could not reach the Lichess explorer.") from exc
    finally:
        if own_client:
            http.close()

    if response.status_code == 429:
        try:
            delay = float(response.headers.get("Retry-After", ""))
        except ValueError:
            delay = DEFAULT_BACKOFF_SECONDS
        with _backoff_lock:
            _backoff_until = time.monotonic() + max(delay, 1.0)
        raise ExplorerUnavailable("Lichess is rate limiting the explorer. Try again in a minute.")
    if response.status_code in (401, 403):
        raise ExplorerUnavailable(
            "The Lichess explorer needs an API token. Add LICHESS_API_TOKEN to backend/.env "
            "(a personal token from lichess.org/account/oauth/token, no scopes needed)."
        )
    if response.status_code >= 400:
        raise ExplorerUnavailable(f"Lichess explorer returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExplorerUnavailable("Lichess explorer sent an unreadable response.") from exc
    result = normalize_lichess(payload, db)
    _lichess_cache.put(key, result)
    return result
