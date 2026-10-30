"""Peer benchmarks: how a player compares with other players, from real data only.

Two sources, and nothing else. See docs/peer-benchmarks.md for what was checked and rejected.

* Lichess rating percentile. The percentile comes live from Lichess's user performance API,
  which leaves it out while a rating is provisional. The API has no sample size, so the player
  counts are a dated snapshot of the weekly distribution page (LICHESS_WEEKLY_PLAYERS). That
  page sits behind a Cloudflare bot check, so the app doesn't fetch it. Lichess ratings only:
  Chess.com has no public distribution, and the two rating scales differ, so a Chess.com rating
  is never placed on the Lichess curve.
* This database. Metrics are compared with other analyzed players on the same site, in the same
  time control and rating band, and only when at least MIN_COHORT_PLAYERS others have that
  metric. Below that the metric is left out.

Everything here is built from public games (GameRow, CriticalMomentRow), so it is the same for
every viewer and never touches a player's practice data. If a source fails, its part is left
out of the response; a figure is never estimated to fill the gap.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from statistics import fmean, median
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .classification import game_accuracy
from .db_models import CriticalMomentRow, GameRow, PlayerRow
from .explorer import _TtlLru
from .importers import lichess_user_agent
from .insights import (
    MIN_SAMPLE,
    PHASES,
    _Game,
    _has_engine,
    _load_games,
    judgment_for,
    phase_from_fen,
    time_category,
)
from .pgn import parse_time_control

MIN_COHORT_PLAYERS = 30  # other players, not counting the one being compared
MIN_PHASE_MOVES = 30  # a phase accuracy below this says little about the player
BAND_WIDTH = 200
LAST_GAMES = 500  # same default window as Insights

LICHESS_BASE = "https://lichess.org"
CACHE_SECONDS = 6 * 3600
FAILURE_CACHE_SECONDS = 300
COHORT_CACHE_SECONDS = 600
TIMEOUT_SECONDS = 6.0
DEFAULT_BACKOFF_SECONDS = 60.0  # Lichess asks clients to wait a full minute after a 429

METRICS: tuple[tuple[str, str, bool], ...] = (
    ("accuracy", "Game accuracy", True),
    ("blunders_per_game", "Blunders per game", False),
    ("opening_accuracy", "Opening accuracy", True),
    ("middlegame_accuracy", "Middlegame accuracy", True),
    ("endgame_accuracy", "Endgame accuracy", True),
)

# Totals of https://lichess.org/stat/rating/distribution/{perf}, read by hand. Update both
# together. Correspondence has no weekly distribution.
LICHESS_WEEKLY_PLAYERS = {
    "ultraBullet": 11_906,
    "bullet": 373_087,
    "blitz": 734_567,
    "rapid": 543_607,
    "classical": 42_771,
}
LICHESS_PLAYERS_AS_OF = "2026-10-31"

LICHESS_SOURCE = "Lichess user performance API and weekly rating distribution"
LICHESS_SCALE_NOTE = (
    "Lichess ratings only. They run on a different scale from Chess.com ratings, "
    "so don't compare the two directly."
)


class RatingPercentile(BaseModel):
    perf: str
    rating: int
    percentile: float  # share of the week's players below this rating, as Lichess reports it
    players: int  # players in the dated distribution snapshot, not a live count
    players_as_of: str
    source_url: str


class PeerMetric(BaseModel):
    key: str
    label: str
    higher_is_better: bool
    value: float
    peer_median: float
    better_than: int  # peers this player beats on the metric; ties don't count
    players: int  # peers who have the metric, never fewer than MIN_COHORT_PLAYERS


class PeerCohort(BaseModel):
    category: str
    band_low: int
    band_high: int
    players: int  # peers behind the widest metric
    games: int  # analyzed games those peers contribute
    metrics: list[PeerMetric]


class BenchmarksResponse(BaseModel):
    platform: str
    username: str
    min_cohort_players: int = MIN_COHORT_PLAYERS
    rating_source: str = LICHESS_SOURCE
    rating_scale_note: str = LICHESS_SCALE_NOTE
    rating_percentiles: list[RatingPercentile] = []
    cohorts: list[PeerCohort] = []


# --------------------------------------------------------------------------- Lichess


class SourceUnavailable(Exception):
    """An external source gave no usable answer, so its figures are left out."""


@dataclass(frozen=True)
class LichessPerf:
    rating: int | None
    percentile: float | None


_cache = _TtlLru(2000, CACHE_SECONDS)
_recent_failures = _TtlLru(2000, FAILURE_CACHE_SECONDS)
_backoff_until = 0.0
_backoff_lock = threading.Lock()


def reset_lichess_state() -> None:
    """For tests: forget cached answers, recent failures and any rate-limit back-off."""
    global _backoff_until
    _cache.clear()
    _recent_failures.clear()
    with _backoff_lock:
        _backoff_until = 0.0


def lichess_perf(time_control: str) -> str | None:
    """Lichess's own speed for a time control. Correspondence has no weekly distribution."""
    parsed = parse_time_control((time_control or "").strip())
    if parsed is None:
        return None
    estimate = parsed[0] + 40 * parsed[1]
    if estimate < 30:
        return "ultraBullet"
    if estimate < 180:
        return "bullet"
    if estimate < 480:
        return "blitz"
    if estimate < 1500:
        return "rapid"
    return "classical"


def distribution_url(perf: str) -> str:
    return f"{LICHESS_BASE}/stat/rating/distribution/{perf}"


def _request(url: str, client: httpx.Client | None) -> httpx.Response:
    global _backoff_until
    with _backoff_lock:
        waiting = _backoff_until > time.monotonic()
    if waiting:
        raise SourceUnavailable("Lichess is rate limiting us.")
    own_client = client is None
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)
    try:
        response = http.get(url, headers={"User-Agent": lichess_user_agent()})
    except httpx.HTTPError as exc:
        raise SourceUnavailable("Could not reach Lichess.") from exc
    finally:
        if own_client:
            http.close()
    if response.status_code == 429:
        try:
            delay = float(response.headers.get("Retry-After", ""))
        except ValueError:
            delay = DEFAULT_BACKOFF_SECONDS
        with _backoff_lock:
            _backoff_until = time.monotonic() + max(delay, DEFAULT_BACKOFF_SECONDS)
        raise SourceUnavailable("Lichess is rate limiting us.")
    return response


def _once_per_ttl(key: tuple[str, ...], fetch: Callable[[], Any]) -> Any:
    """Serve from cache, and don't retry a source that just failed for this key."""
    cached = _cache.get(key)
    if cached is not None:
        return cached
    if _recent_failures.get(key):
        raise SourceUnavailable("Lichess failed for this request a moment ago.")
    try:
        value = fetch()
    except SourceUnavailable:
        _recent_failures.put(key, True)
        raise
    _cache.put(key, value)
    return value


def fetch_lichess_perf(username: str, perf: str, client: httpx.Client | None = None) -> LichessPerf:
    def fetch() -> LichessPerf:
        url = f"{LICHESS_BASE}/api/user/{quote(username, safe='')}/perf/{perf}"
        response = _request(url, client)
        if response.status_code == 404:
            return LichessPerf(None, None)
        if response.status_code != 200:
            raise SourceUnavailable(f"Lichess returned HTTP {response.status_code}.")
        try:
            payload = response.json()
            rating = payload["perf"]["glicko"]["rating"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceUnavailable("Lichess sent an unreadable answer.") from exc
        percentile = payload.get("percentile")
        valid = isinstance(percentile, (int, float)) and 0 <= percentile <= 100
        return LichessPerf(round(rating), float(percentile) if valid else None)

    return _once_per_ttl(("perf", username.lower(), perf), fetch)


def lichess_percentiles(
    username: str, perfs: list[str], client: httpx.Client | None = None
) -> list[RatingPercentile]:
    rows = []
    for perf in perfs:
        players = LICHESS_WEEKLY_PLAYERS.get(perf)
        if players is None:
            continue
        try:
            stats = fetch_lichess_perf(username, perf, client)
        except SourceUnavailable:
            continue
        # No percentile means Lichess doesn't rank this rating yet (it is provisional).
        if stats.rating is None or stats.percentile is None:
            continue
        rows.append(
            RatingPercentile(
                perf=perf,
                rating=stats.rating,
                percentile=stats.percentile,
                players=players,
                players_as_of=LICHESS_PLAYERS_AS_OF,
                source_url=distribution_url(perf),
            )
        )
    return rows


def perfs_worth_checking(games: list[_Game]) -> list[str]:
    """Speeds the player really plays, most played first."""
    counts = Counter(lichess_perf(game.time_control) for game in games)
    return [
        perf for perf, n in counts.most_common() if perf is not None and n >= MIN_SAMPLE
    ]


# --------------------------------------------------------------------------- this database


def band_for(rating: int) -> int:
    return rating - rating % BAND_WIDTH


def player_metrics(games: list[_Game]) -> dict[str, dict[str, float]]:
    """Per time control: the metrics of a player with enough analyzed games in it."""
    by_category: dict[str, list[_Game]] = defaultdict(list)
    for game in games:
        category = time_category(game.time_control)
        if category is not None and _has_engine(game.moves):
            by_category[category].append(game)
    out: dict[str, dict[str, float]] = {}
    for category, rows in by_category.items():
        if len(rows) < MIN_SAMPLE:
            continue
        accuracies: list[float] = []
        phases: dict[str, list[float]] = defaultdict(list)
        blunders = 0
        for game in rows:
            side = game_accuracy(
                [move["win_pct"] for move in game.moves],
                white_moves_first=game.moves[0].get("color", "white") == "white",
            ).get(game.color)
            if side is not None:
                accuracies.append(side)
            for move in game.moves:
                if move.get("color") == game.color and move.get("accuracy") is not None:
                    phases[phase_from_fen(move.get("fen_before", ""))].append(float(move["accuracy"]))
            blunders += sum(judgment_for(m.severity) == "blunder" for m in game.moments)
        metrics = {"games": float(len(rows)), "blunders_per_game": blunders / len(rows)}
        # Unrounded: rounding here would turn close values into ties in `compare`.
        if accuracies:
            metrics["accuracy"] = fmean(accuracies)
        for phase in PHASES:
            if len(phases[phase]) >= MIN_PHASE_MOVES:
                metrics[f"{phase}_accuracy"] = fmean(phases[phase])
        out[category] = metrics
    return out


def _rating_index(
    session: Session, platform: str
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, int], set[str]]]:
    """Without opening any game's moves: everyone's latest rating and who sits in each band."""
    rows = session.execute(
        select(GameRow.player_id, GameRow.time_control, GameRow.player_elo)
        .join(PlayerRow, PlayerRow.id == GameRow.player_id)
        .where(PlayerRow.platform == platform, GameRow.player_elo.is_not(None))
        .order_by(GameRow.played_at.desc(), GameRow.created_at.desc())
    ).all()
    latest: dict[tuple[str, str], int] = {}
    played: Counter[tuple[str, str]] = Counter()
    for player_id, control, rating in rows:
        category = time_category(control or "")
        if category is None:
            continue
        latest.setdefault((player_id, category), rating)
        played[(player_id, category)] += 1
    bands: dict[tuple[str, int], set[str]] = defaultdict(set)
    for key, rating in latest.items():
        if played[key] >= MIN_SAMPLE:
            bands[(key[1], band_for(rating))].add(key[0])
    return latest, bands


# (platform, category, band) -> (data version, built at, player id -> metrics)
_COHORTS: dict[tuple[str, str, int], tuple[tuple[int, int], float, dict[str, dict[str, float]]]] = {}
_COHORT_LOCK = threading.Lock()


def clear_cohort_cache() -> None:
    with _COHORT_LOCK:
        _COHORTS.clear()


def _data_version(session: Session) -> tuple[int, int]:
    games = session.scalar(select(func.count()).select_from(GameRow)) or 0
    moments = session.scalar(select(func.count()).select_from(CriticalMomentRow)) or 0
    return games, moments


def _cohort_metrics(
    session: Session, platform: str, category: str, band: int, members: set[str]
) -> dict[str, dict[str, float]]:
    key = (platform, category, band)
    version = _data_version(session)
    with _COHORT_LOCK:
        cached = _COHORTS.get(key)
    if cached and cached[0] == version and time.monotonic() - cached[1] < COHORT_CACHE_SECONDS:
        return cached[2]
    metrics: dict[str, dict[str, float]] = {}
    for member in members:
        stats = player_metrics(_load_games(session, member, LAST_GAMES)).get(category)
        if stats is not None:
            metrics[member] = stats
    with _COHORT_LOCK:
        _COHORTS[key] = (version, time.monotonic(), metrics)
    return metrics


def compare(value: float, peers: list[float], higher_is_better: bool) -> tuple[float, int]:
    """Peer median, and how many peers the value strictly beats."""
    beaten = sum(value > peer if higher_is_better else value < peer for peer in peers)
    return median(peers), beaten


def build_cohorts(session: Session, player: PlayerRow, games: list[_Game]) -> list[PeerCohort]:
    own = player_metrics(games)
    if not own:
        return []
    latest, bands = _rating_index(session, player.platform)
    cohorts = []
    for category in sorted(own, key=lambda name: -own[name]["games"]):
        rating = latest.get((player.id, category))
        if rating is None:
            continue
        band = band_for(rating)
        members = bands.get((category, band), set())
        # The band can only shrink from here, so a small one never loads anyone's games.
        if len(members - {player.id}) < MIN_COHORT_PLAYERS:
            continue
        stats = _cohort_metrics(session, player.platform, category, band, members)
        peers = {pid: row for pid, row in stats.items() if pid != player.id}
        metrics = []
        for key, label, higher_is_better in METRICS:
            value = own[category].get(key)
            values = [row[key] for row in peers.values() if key in row]
            if value is None or len(values) < MIN_COHORT_PLAYERS:
                continue
            peer_median, beaten = compare(value, values, higher_is_better)
            metrics.append(
                PeerMetric(
                    key=key,
                    label=label,
                    higher_is_better=higher_is_better,
                    value=round(value, 2),
                    peer_median=round(peer_median, 2),
                    better_than=beaten,
                    players=len(values),
                )
            )
        if metrics:
            cohorts.append(
                PeerCohort(
                    category=category,
                    band_low=band,
                    band_high=band + BAND_WIDTH - 1,
                    players=max(metric.players for metric in metrics),
                    games=int(sum(row["games"] for row in peers.values())),
                    metrics=metrics,
                )
            )
    return cohorts
