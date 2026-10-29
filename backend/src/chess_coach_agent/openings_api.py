"""Per-opening performance for a player, and opening labels for single games."""

from __future__ import annotations

import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import session_scope
from .db_models import CriticalMomentRow, GameRow, PlayerRow
from .openings import classify_moves, label_game, opening_book
from .repositories import normalize_username

router = APIRouter(prefix="/api")

Grouping = Literal["family", "variation"]


class OpeningStat(BaseModel):
    eco: str
    name: str
    color: Literal["white", "black"]
    games: int
    wins: int
    draws: int
    losses: int
    score_pct: float
    avg_accuracy: float | None = None
    top_theme: str | None = None
    top_theme_count: int = 0
    common_first_mistake_ply: int | None = None
    common_first_mistake_games: int = 0
    common_book_exit_ply: int | None = None
    top_variation: str | None = None
    last_played: str = ""


class OpeningsResponse(BaseModel):
    platform: str
    username: str
    group: Grouping
    total_games: int
    classified_games: int
    white: list[OpeningStat]
    black: list[OpeningStat]


class GameOpening(BaseModel):
    game_id: str
    eco: str
    name: str
    family: str
    book_ply: int


@dataclass
class _GameFacts:
    """What the aggregation needs from one stored game."""

    row_id: str
    color: str
    result: str
    played_at: str
    eco: str
    name: str
    family: str
    book_ply: int
    accuracy: float | None


@dataclass
class _Bucket:
    eco: Counter[str] = field(default_factory=Counter)
    variations: Counter[str] = field(default_factory=Counter)
    games: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    accuracies: list[float] = field(default_factory=list)
    themes: Counter[str] = field(default_factory=Counter)
    first_mistake: Counter[int] = field(default_factory=Counter)
    book_exit: Counter[int] = field(default_factory=Counter)
    last_played: str = ""


# (platform, normalized username, group) -> ((games, moments), response)
_CACHE: dict[tuple[str, str, str], tuple[tuple[int, int], OpeningsResponse]] = {}
_CACHE_LOCK = threading.Lock()

# Build the opening book in the background so the first request doesn't pay for it.
threading.Thread(target=opening_book, name="opening-book-warmup", daemon=True).start()


def _player_accuracy(game: dict[str, Any], color: str) -> float | None:
    """Optional per-game accuracy written by the analysis pipeline, if present."""
    for key in ("player_accuracy", f"{color}_accuracy"):
        value = game.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    nested = game.get("accuracy")
    if isinstance(nested, dict) and isinstance(nested.get(color), (int, float)):
        return float(nested[color])
    return None


def _find_player(session: Session, platform: str, username: str) -> PlayerRow | None:
    return session.scalar(
        select(PlayerRow).where(
            PlayerRow.platform == platform,
            PlayerRow.username_normalized == normalize_username(username),
        )
    )


def _game_facts(session: Session, player_id: str) -> tuple[list[_GameFacts], int]:
    rows = session.execute(
        select(
            GameRow.id,
            GameRow.player_color,
            GameRow.player_result,
            GameRow.played_at,
            GameRow.metadata_json,
        ).where(GameRow.player_id == player_id)
    ).all()
    facts: list[_GameFacts] = []
    for row_id, color, result, played_at, stored in rows:
        if color not in ("white", "black"):
            continue
        stored = stored or {}
        match = classify_moves(stored.get("moves", []))
        if match is None:
            continue
        facts.append(
            _GameFacts(
                row_id=row_id,
                color=color,
                result=result,
                played_at=played_at or "",
                eco=match.opening.eco,
                name=match.opening.name,
                family=match.opening.family,
                book_ply=match.book_ply,
                accuracy=_player_accuracy(stored.get("game", {}), color),
            )
        )
    return facts, len(rows)


def _player_moments(session: Session, player_id: str) -> dict[str, list[tuple[int, str]]]:
    """(ply, theme) of every critical moment, keyed by game row id, in one query."""
    rows = session.execute(
        select(CriticalMomentRow.game_id, CriticalMomentRow.ply, CriticalMomentRow.theme)
        .join(GameRow, GameRow.id == CriticalMomentRow.game_id)
        .where(GameRow.player_id == player_id)
    ).all()
    moments: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for game_id, ply, theme in rows:
        moments[game_id].append((ply, theme))
    return moments


def _is_players_ply(ply: int, color: str) -> bool:
    return (ply % 2 == 1) == (color == "white")


def build_openings(
    session: Session, player: PlayerRow, group: Grouping = "family"
) -> OpeningsResponse:
    facts, total = _game_facts(session, player.id)
    moments = _player_moments(session, player.id)
    buckets: dict[tuple[str, str], _Bucket] = defaultdict(_Bucket)
    for game in facts:
        key_name = game.family if group == "family" else game.name
        bucket = buckets[(game.color, key_name)]
        bucket.games += 1
        bucket.eco[game.eco] += 1
        bucket.variations[game.name] += 1
        if game.result == "win":
            bucket.wins += 1
        elif game.result == "draw":
            bucket.draws += 1
        elif game.result == "loss":
            bucket.losses += 1
        if game.accuracy is not None:
            bucket.accuracies.append(game.accuracy)
        bucket.book_exit[game.book_ply + 1] += 1
        bucket.last_played = max(bucket.last_played, game.played_at)
        own = sorted(
            (ply, theme)
            for ply, theme in moments.get(game.row_id, [])
            if _is_players_ply(ply, game.color)
        )
        for _, theme in own:
            bucket.themes[theme] += 1
        if own:
            bucket.first_mistake[own[0][0]] += 1

    by_color: dict[str, list[OpeningStat]] = {"white": [], "black": []}
    for (color, name), bucket in buckets.items():
        decided = bucket.wins + bucket.draws + bucket.losses
        score = (bucket.wins + 0.5 * bucket.draws) / decided * 100 if decided else 0.0
        top_theme = bucket.themes.most_common(1)
        first_mistake = bucket.first_mistake.most_common(1)
        book_exit = bucket.book_exit.most_common(1)
        top_variation = bucket.variations.most_common(1)
        by_color[color].append(
            OpeningStat(
                eco=bucket.eco.most_common(1)[0][0],
                name=name,
                color=color,  # type: ignore[arg-type]
                games=bucket.games,
                wins=bucket.wins,
                draws=bucket.draws,
                losses=bucket.losses,
                score_pct=round(score, 1),
                avg_accuracy=(
                    round(sum(bucket.accuracies) / len(bucket.accuracies), 1)
                    if bucket.accuracies
                    else None
                ),
                top_theme=top_theme[0][0] if top_theme else None,
                top_theme_count=top_theme[0][1] if top_theme else 0,
                common_first_mistake_ply=first_mistake[0][0] if first_mistake else None,
                common_first_mistake_games=first_mistake[0][1] if first_mistake else 0,
                common_book_exit_ply=book_exit[0][0] if book_exit else None,
                top_variation=(
                    top_variation[0][0]
                    if group == "family" and top_variation and top_variation[0][0] != name
                    else None
                ),
                last_played=bucket.last_played,
            )
        )
    for stats in by_color.values():
        stats.sort(key=lambda stat: (-stat.games, stat.name))
    return OpeningsResponse(
        platform=player.platform,
        username=player.username,
        group=group,
        total_games=total,
        classified_games=len(facts),
        white=by_color["white"],
        black=by_color["black"],
    )


@router.get("/openings/{platform}/{username}", response_model=OpeningsResponse)
def get_openings(
    platform: str, username: str, group: Grouping = Query(default="family")
) -> OpeningsResponse:
    with session_scope() as session:
        player = _find_player(session, platform, username)
        if player is None:
            return OpeningsResponse(
                platform=platform,
                username=username,
                group=group,
                total_games=0,
                classified_games=0,
                white=[],
                black=[],
            )
        # Re-aggregate when games are added or re-analyzed (moment count changes).
        count = (
            session.scalar(
                select(func.count()).select_from(GameRow).where(GameRow.player_id == player.id)
            )
            or 0,
            session.scalar(
                select(func.count())
                .select_from(CriticalMomentRow)
                .join(GameRow, GameRow.id == CriticalMomentRow.game_id)
                .where(GameRow.player_id == player.id)
            )
            or 0,
        )
        key = (platform, player.username_normalized, group)
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached and cached[0] == count:
            return cached[1]
        response = build_openings(session, player, group)
        with _CACHE_LOCK:
            _CACHE[key] = (count, response)
        return response


@router.get("/openings/{platform}/{username}/games/{game_id}", response_model=GameOpening)
def get_game_opening(platform: str, username: str, game_id: str) -> GameOpening:
    with session_scope() as session:
        player = _find_player(session, platform, username)
        stored = None
        if player is not None:
            stored = session.scalar(
                select(GameRow.metadata_json).where(
                    GameRow.player_id == player.id, GameRow.external_game_id == game_id
                )
            )
    if stored is None:
        raise HTTPException(404, "Game not found.")
    label = label_game((stored or {}).get("moves", []))
    if label is None:
        raise HTTPException(404, "No named opening matches this game.")
    return GameOpening(game_id=game_id, **label)  # type: ignore[arg-type]
