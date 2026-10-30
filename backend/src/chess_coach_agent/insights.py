"""Where a player loses games: phase, clock, opponent strength, color and conversion stats.

Everything is computed from what sync already stored, without rebuilding CoachAnalysis
objects (see openings_api.py for the same approach):

* ``GameRow.metadata_json["moves"]`` holds every ply. Games analyzed with the current
  pipeline also carry per-move ``win_pct`` / ``accuracy`` / ``win_pct_loss`` and, when the
  PGN had them, clock fields. Older games only have SAN/FEN.
* Tactics found and missed come from stored engine moves and python-chess; see tactics.py.
* ``CriticalMomentRow`` exists for every analyzed game (old and new). ``severity`` is the
  Win% the player gave up, ``phase`` comes from ``phase_for_board`` on the position before
  the move.

Each metric is computed only from games that have the fields it needs, and every section
reports its own ``sample_size`` so the UI can hide sections with too little data.

Leak heuristic ("estimated points lost")
----------------------------------------
* Theme leaks: in every game the player did not win, the points dropped (1 for a loss,
  0.5 for a draw) are split across the player's mistakes and blunders in proportion to the
  Win% each one gave up. Summing a theme's share over all games and dividing by the number
  of games gives "points lost per game" to that theme.
* Conversion leak: points dropped in games where the player reached a winning position
  (Win% >= 75, about +3) and kept it for two plies, but did not win.
* Opening leak: points dropped in games where the player was already clearly worse
  (Win% <= 25, about -3) after move 12 and did not win.
The lenses overlap (a blown win is also made of themed blunders), so they are ranked side by
side as separate views, not added together.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from math import sqrt
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .classification import BLUNDER_LOSS, INACCURACY_LOSS, MISTAKE_LOSS, game_accuracy
from .db_models import CriticalMomentRow, GameRow, PlayerRow
from .pgn import parse_time_control
from .tactics import (
    MAX_EXAMPLES,
    MIN_CHANCES,
    MOTIFS,
    Chance,
    TacticExample,
    TacticRow,
    TacticsSection,
    cached_game_chances,
    has_stored_evals,
)

Phase = Literal["opening", "middlegame", "endgame"]
TimeCategory = Literal["bullet", "blitz", "rapid", "daily"]
PHASES: tuple[Phase, ...] = ("opening", "middlegame", "endgame")
CATEGORIES: tuple[TimeCategory, ...] = ("bullet", "blitz", "rapid", "daily")
MIN_SAMPLE = 10

# Win% (player's point of view) thresholds; 75 is about +3 pawns, 25 about -3.
WINNING_PCT = 75.0
LOSING_PCT = 25.0
OPENING_END_PLY = 24  # phase_for_board calls fullmove <= 12 the opening

# Severity is stored in Win% points; the classification thresholds are in winning-chance
# units (Win% / 50).
INACCURACY_PCT = INACCURACY_LOSS * 50
MISTAKE_PCT = MISTAKE_LOSS * 50
BLUNDER_PCT = BLUNDER_LOSS * 50

THEME_TITLES = {
    "missed_tactic": "Missed tactics",
    "loose_piece": "Hanging pieces",
    "king_safety": "King safety",
    "opening_drift": "Early queen moves",
    "endgame_conversion": "Endgame technique",
    "time_pressure": "Time trouble",
}
THEME_NOUNS = {
    "missed_tactic": "missed tactics",
    "loose_piece": "pieces left hanging",
    "king_safety": "king safety errors",
    "opening_drift": "early queen moves",
    "endgame_conversion": "endgame errors",
    "time_pressure": "moves in time trouble",
}

# (key, label, first hour) in the player's timezone. Blocks, not single hours: most players
# have too few games in any one hour to say anything about it.
DAY_PARTS: tuple[tuple[str, str, int], ...] = (
    ("night", "Night (0-6)", 0),
    ("morning", "Morning (6-12)", 6),
    ("afternoon", "Afternoon (12-18)", 12),
    ("evening", "Evening (18-24)", 18),
)
WEEKDAYS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WILSON_Z = 1.96  # 95% interval

OPPONENT_BUCKETS: tuple[tuple[str, str], ...] = (
    ("much_lower", "200+ lower"),
    ("lower", "50-200 lower"),
    ("even", "Within 50"),
    ("higher", "50-200 higher"),
    ("much_higher", "200+ higher"),
)


# --------------------------------------------------------------------------- response


class PhaseRow(BaseModel):
    phase: Phase
    games: int  # games in which the player made at least one move in this phase
    accuracy: float | None = None  # mean per-move accuracy (engine-annotated games only)
    accuracy_moves: int = 0
    inaccuracies_per_game: float = 0
    mistakes_per_game: float = 0
    blunders_per_game: float = 0
    errors_per_game: float = 0
    blunder_share_pct: float = 0  # this phase's share of all the player's blunders


class PhaseSection(BaseModel):
    sample_size: int
    accuracy_sample_size: int
    rows: list[PhaseRow]


class TimeControlRow(BaseModel):
    category: TimeCategory
    games: int
    score_pct: float
    accuracy: float | None = None
    accuracy_games: int = 0
    blunders_per_game: float = 0


class PressureRow(BaseModel):
    state: Literal["normal", "time_pressure"]
    moves: int
    accuracy: float | None = None
    blunders_per_100_moves: float = 0


class TimeSpent(BaseModel):
    sample_size: int
    avg_seconds_all: float | None = None
    avg_seconds_critical: float | None = None
    critical_moves: int = 0


class LostOnTime(BaseModel):
    sample_size: int  # games whose stored metadata includes the PGN Termination
    losses: int = 0
    lost_on_time: int = 0
    pct_of_losses: float | None = None


class TimeSection(BaseModel):
    sample_size: int  # games with clock data and engine annotations
    by_control: list[TimeControlRow]
    by_control_sample_size: int
    pressure: list[PressureRow]
    time_spent: TimeSpent
    lost_on_time: LostOnTime


class ScheduleRow(BaseModel):
    key: str
    label: str
    games: int
    low_sample: bool  # fewer than MIN_SAMPLE games: show it, but draw no conclusion from it
    score_pct: float | None = None
    # 95% interval on the score, so a 70% from 12 games reads as the wide guess it is.
    score_low_pct: float | None = None
    score_high_pct: float | None = None
    accuracy: float | None = None
    accuracy_games: int = 0
    blunders_per_game: float = 0


class ScheduleBreakdown(BaseModel):
    rows: list[ScheduleRow]
    # Set only when the best and worst rows both have enough games and their intervals do
    # not overlap. Otherwise the differences are within noise and nothing is called out.
    best: str | None = None
    worst: str | None = None


class ScheduleSection(BaseModel):
    sample_size: int  # games with a start time
    undated_games: int  # games left out because they have none
    timezone: str  # the timezone used, which is UTC if the requested one was unknown
    by_time_of_day: ScheduleBreakdown
    by_day_of_week: ScheduleBreakdown


class OpponentRow(BaseModel):
    bucket: str
    label: str
    games: int
    score_pct: float | None = None
    accuracy: float | None = None
    accuracy_games: int = 0


class OpponentSection(BaseModel):
    sample_size: int
    rows: list[OpponentRow]


class ColorRow(BaseModel):
    color: Literal["white", "black"]
    games: int
    wins: int
    draws: int
    losses: int
    score_pct: float | None = None
    accuracy: float | None = None
    accuracy_games: int = 0


class ColorSection(BaseModel):
    sample_size: int
    accuracy_sample_size: int
    rows: list[ColorRow]


class ConversionSection(BaseModel):
    sample_size: int
    winning_threshold_pct: float = WINNING_PCT
    losing_threshold_pct: float = LOSING_PCT
    winning_games: int = 0
    failed_conversions: int = 0
    failed_conversion_pct: float | None = None
    losing_games: int = 0
    saves: int = 0  # drew or won from a losing position
    save_pct: float | None = None


class LeakAction(BaseModel):
    type: Literal["practice", "openings"]
    theme: str | None = None
    label: str


class Leak(BaseModel):
    id: str
    title: str
    detail: str
    points_per_10_games: float
    sample_size: int
    action: LeakAction


class InsightsResponse(BaseModel):
    platform: str
    username: str
    last: int
    total_games: int
    games_considered: int
    engine_games: int
    clock_games: int
    min_sample: int = MIN_SAMPLE
    leaks: list[Leak] = Field(default_factory=list)
    phases: PhaseSection
    time: TimeSection
    opponents: OpponentSection
    colors: ColorSection
    conversion: ConversionSection
    schedule: ScheduleSection
    tactics: TacticsSection = Field(default_factory=TacticsSection)


# --------------------------------------------------------------------------- helpers


def phase_from_fen(fen: str) -> Phase:
    """``pgn.phase_for_board`` computed from the FEN string, without building a Board."""
    parts = fen.split(" ")
    placement = parts[0]
    fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
    if fullmove <= 12:
        return "opening"
    non_pawn = sum(placement.count(c) for c in "nbrqNBRQ")
    queens = placement.count("q") + placement.count("Q")
    if non_pawn <= 8 or queens == 0:
        return "endgame"
    return "middlegame"


def time_category(time_control: str) -> TimeCategory | None:
    """Chess.com/Lichess style bucket from a PGN TimeControl, using base + 40 * increment."""
    value = (time_control or "").strip()
    if "/" in value:
        return "daily"
    parsed = parse_time_control(value)
    if parsed is None:
        return None
    estimate = parsed[0] + 40 * parsed[1]
    if estimate < 180:
        return "bullet"
    if estimate < 600:
        return "blitz"
    return "rapid"


def resolve_timezone(name: str | None) -> tuple[tzinfo, str]:
    """The named IANA timezone, or UTC when it is missing or this system does not know it."""
    if name:
        try:
            return ZoneInfo(name), name
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return UTC, "UTC"


def wilson_interval(score: float, n: int) -> tuple[float, float]:
    """95% Wilson interval, in percent, for a score (0-1) over ``n`` games."""
    z2 = WILSON_Z**2
    centre = (score + z2 / (2 * n)) / (1 + z2 / n)
    margin = WILSON_Z * sqrt(score * (1 - score) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return round(max(0.0, centre - margin) * 100, 1), round(min(1.0, centre + margin) * 100, 1)


def judgment_for(severity: float) -> str | None:
    if severity >= BLUNDER_PCT:
        return "blunder"
    if severity >= MISTAKE_PCT:
        return "mistake"
    if severity >= INACCURACY_PCT:
        return "inaccuracy"
    return None


def _score(result: str) -> float | None:
    return {"win": 1.0, "draw": 0.5, "loss": 0.0}.get(result)


def _pct(part: float, whole: float) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _is_players_ply(ply: int, color: str) -> bool:
    return (ply % 2 == 1) == (color == "white")


def _opponent_elo(game: dict[str, Any], color: str) -> int | None:
    for key in ("opponent_elo", "black_elo" if color == "white" else "white_elo"):
        value = game.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _opponent_bucket(diff: int) -> str:
    if diff <= -200:
        return "much_lower"
    if diff < -50:
        return "lower"
    if diff <= 50:
        return "even"
    if diff < 200:
        return "higher"
    return "much_higher"


@dataclass
class _Moment:
    ply: int
    phase: str
    theme: str
    severity: float


@dataclass
class _Game:
    row_id: str
    external_id: str
    color: str
    result: str
    time_control: str
    player_elo: int | None
    opponent_elo: int | None
    termination: str | None
    moves: list[dict[str, Any]]
    started_at: datetime | None = None
    moments: list[_Moment] = field(default_factory=list)


def _load_games(session: Session, player_id: str, last: int) -> list[_Game]:
    rows = session.execute(
        select(
            GameRow.id,
            GameRow.external_game_id,
            GameRow.player_color,
            GameRow.player_result,
            GameRow.time_control,
            GameRow.player_elo,
            GameRow.metadata_json,
            GameRow.started_at,
        )
        .where(GameRow.player_id == player_id)
        .order_by(GameRow.played_at.desc(), GameRow.created_at.desc())
        .limit(last)
    ).all()
    games: dict[str, _Game] = {}
    for row_id, external_id, color, result, time_control, elo, stored, started_at in rows:
        if color not in ("white", "black") or result not in ("win", "draw", "loss"):
            continue
        stored = stored or {}
        meta = stored.get("game") or {}
        termination = meta.get("termination")
        games[row_id] = _Game(
            row_id=row_id,
            external_id=external_id,
            color=color,
            result=result,
            time_control=time_control or "",
            player_elo=elo,
            opponent_elo=_opponent_elo(meta, color),
            termination=termination if isinstance(termination, str) else None,
            moves=stored.get("moves") or [],
            started_at=started_at,
        )
    moment_rows = session.execute(
        select(
            CriticalMomentRow.game_id,
            CriticalMomentRow.ply,
            CriticalMomentRow.phase,
            CriticalMomentRow.theme,
            CriticalMomentRow.severity,
        )
        .join(GameRow, GameRow.id == CriticalMomentRow.game_id)
        .where(GameRow.player_id == player_id)
    ).all()
    for game_id, ply, phase, theme, severity in moment_rows:
        game = games.get(game_id)
        if game is not None and _is_players_ply(ply, game.color):
            game.moments.append(_Moment(ply, phase, theme, float(severity or 0)))
    return list(games.values())


def _has_engine(moves: list[dict[str, Any]]) -> bool:
    return bool(moves) and all(move.get("win_pct") is not None for move in moves)


def _has_clock(moves: list[dict[str, Any]]) -> bool:
    return any(move.get("clock_seconds") is not None for move in moves)


def _player_win_pcts(game: _Game) -> list[float]:
    flip = game.color == "black"
    return [100 - m["win_pct"] if flip else m["win_pct"] for m in game.moves]


def _held(series: list[float], test: Callable[[float], bool]) -> bool:
    return any(test(a) and test(b) for a, b in zip(series, series[1:]))


# --------------------------------------------------------------------------- build


def build_insights(
    session: Session, player: PlayerRow, last: int, total_games: int, timezone: str | None = None
) -> InsightsResponse:
    games = _load_games(session, player.id, last)
    engine_games = [g for g in games if _has_engine(g.moves)]
    clock_games = [g for g in engine_games if _has_clock(g.moves)]
    accuracy_by_game: dict[str, float] = {}
    for game in engine_games:
        side = game_accuracy(
            [m["win_pct"] for m in game.moves],
            white_moves_first=game.moves[0].get("color", "white") == "white",
        ).get(game.color)
        if side is not None:
            accuracy_by_game[game.row_id] = side

    phases = _phase_section(games, engine_games)
    time_section = _time_section(games, clock_games, accuracy_by_game)
    opponents = _opponent_section(games, accuracy_by_game)
    colors = _color_section(games, accuracy_by_game)
    conversion, conversion_leak, opening_leak = _conversion_section(engine_games)
    leaks = _rank_leaks(games, conversion_leak, opening_leak)
    return InsightsResponse(
        platform=player.platform,
        username=player.username,
        last=last,
        total_games=total_games,
        games_considered=len(games),
        engine_games=len(engine_games),
        clock_games=len(clock_games),
        leaks=leaks,
        phases=phases,
        time=time_section,
        opponents=opponents,
        colors=colors,
        conversion=conversion,
        schedule=_schedule_section(games, accuracy_by_game, timezone),
        tactics=_tactics_section(games),
    )


def _tactic_example(game: _Game, chance: Chance) -> TacticExample:
    return TacticExample(
        game_id=game.external_id,
        ply=chance.ply,
        move_number=chance.move_number,
        color=chance.color,  # type: ignore[arg-type]
        played_san=chance.played_san,
        best_san=chance.best_san,
        fen=chance.fen,
    )


def _tactics_section(games: list[_Game]) -> TacticsSection:
    """Games arrive newest first, so each row's examples are its latest misses."""
    scanned = [g for g in games if has_stored_evals(g.moves)]
    found: Counter[str] = Counter()
    missed: Counter[str] = Counter()
    examples: dict[str, list[TacticExample]] = defaultdict(list)
    for game in scanned:
        for chance in cached_game_chances(game.row_id, game.moves, game.color):
            if chance.found:
                found[chance.motif] += 1
                continue
            missed[chance.motif] += 1
            if len(examples[chance.motif]) < MAX_EXAMPLES:
                examples[chance.motif].append(_tactic_example(game, chance))
    rows = []
    for motif, label, tag in MOTIFS:
        chances = found[motif] + missed[motif]
        row = TacticRow(
            motif=motif,
            label=label,
            found=found[motif],
            missed=missed[motif],
            chances=chances,
            low_sample=chances < MIN_CHANCES,
            practice_tag=tag,
            examples=examples[motif],
        )
        if not row.low_sample:
            rate = found[motif] / chances
            row.found_pct = round(rate * 100, 1)
            row.found_low_pct, row.found_high_pct = wilson_interval(rate, chances)
        rows.append(row)
    return TacticsSection(
        sample_size=len(scanned),
        games_without_evals=len(games) - len(scanned),
        found=sum(found.values()),
        missed=sum(missed.values()),
        rows=rows,
    )


def _phase_section(games: list[_Game], engine_games: list[_Game]) -> PhaseSection:
    reached: Counter[str] = Counter()
    judgments: dict[str, Counter[str]] = {phase: Counter() for phase in PHASES}
    accuracies: dict[str, list[float]] = defaultdict(list)
    engine_ids = {g.row_id for g in engine_games}
    for game in games:
        seen: set[str] = set()
        engine = game.row_id in engine_ids
        for move in game.moves:
            if move.get("color") != game.color:
                continue
            phase = phase_from_fen(move.get("fen_before", ""))
            seen.add(phase)
            if engine and move.get("accuracy") is not None:
                accuracies[phase].append(float(move["accuracy"]))
        reached.update(seen)
        for moment in game.moments:
            label = judgment_for(moment.severity)
            if label and moment.phase in judgments:
                judgments[moment.phase][label] += 1
    total_blunders = sum(counter["blunder"] for counter in judgments.values())
    rows = []
    for phase in PHASES:
        n = reached[phase]
        counts = judgments[phase]

        def per_game(value: int, n: int = n) -> float:
            return round(value / n, 2) if n else 0.0

        rows.append(
            PhaseRow(
                phase=phase,
                games=n,
                accuracy=_mean(accuracies[phase]),
                accuracy_moves=len(accuracies[phase]),
                inaccuracies_per_game=per_game(counts["inaccuracy"]),
                mistakes_per_game=per_game(counts["mistake"]),
                blunders_per_game=per_game(counts["blunder"]),
                errors_per_game=per_game(sum(counts.values())),
                blunder_share_pct=_pct(counts["blunder"], total_blunders) or 0.0,
            )
        )
    return PhaseSection(
        sample_size=len(games), accuracy_sample_size=len(engine_games), rows=rows
    )


def _time_section(
    games: list[_Game], clock_games: list[_Game], accuracy_by_game: dict[str, float]
) -> TimeSection:
    by_cat: dict[str, list[_Game]] = defaultdict(list)
    for game in games:
        category = time_category(game.time_control)
        if category:
            by_cat[category].append(game)
    control_rows = []
    for category in CATEGORIES:
        members = by_cat.get(category, [])
        if not members:
            continue
        scores = [_score(g.result) or 0.0 for g in members]
        accs = [accuracy_by_game[g.row_id] for g in members if g.row_id in accuracy_by_game]
        blunders = sum(
            1 for g in members for m in g.moments if m.severity >= BLUNDER_PCT
        )
        control_rows.append(
            TimeControlRow(
                category=category,
                games=len(members),
                score_pct=round(sum(scores) / len(scores) * 100, 1),
                accuracy=_mean(accs),
                accuracy_games=len(accs),
                blunders_per_game=round(blunders / len(members), 2),
            )
        )

    pressure: dict[str, list[float]] = {"normal": [], "time_pressure": []}
    pressure_blunders: Counter[str] = Counter()
    spent_all: list[float] = []
    spent_critical: list[float] = []
    for game in clock_games:
        critical_plies = {m.ply for m in game.moments if m.severity >= MISTAKE_PCT}
        for move in game.moves:
            if move.get("color") != game.color or move.get("clock_seconds") is None:
                continue
            state = "time_pressure" if move.get("time_pressure") else "normal"
            if move.get("accuracy") is not None:
                pressure[state].append(float(move["accuracy"]))
            if (move.get("win_pct_loss") or 0) >= BLUNDER_PCT:
                pressure_blunders[state] += 1
            spent = move.get("time_spent_seconds")
            if spent is not None:
                spent_all.append(float(spent))
                if move.get("ply") in critical_plies:
                    spent_critical.append(float(spent))
    pressure_rows = [
        PressureRow(
            state=state,  # type: ignore[arg-type]
            moves=len(values),
            accuracy=_mean(values),
            blunders_per_100_moves=round(pressure_blunders[state] / len(values) * 100, 2)
            if values
            else 0.0,
        )
        for state, values in pressure.items()
    ]

    with_termination = [g for g in games if g.termination]
    losses = [g for g in with_termination if g.result == "loss"]
    on_time = [g for g in losses if "time" in (g.termination or "").lower()]
    return TimeSection(
        sample_size=len(clock_games),
        by_control=control_rows,
        by_control_sample_size=sum(len(v) for v in by_cat.values()),
        pressure=pressure_rows,
        time_spent=TimeSpent(
            sample_size=len(clock_games),
            avg_seconds_all=_mean(spent_all),
            avg_seconds_critical=_mean(spent_critical),
            critical_moves=len(spent_critical),
        ),
        lost_on_time=LostOnTime(
            sample_size=len(with_termination),
            losses=len(losses),
            lost_on_time=len(on_time),
            pct_of_losses=_pct(len(on_time), len(losses)),
        ),
    )


def _opponent_section(games: list[_Game], accuracy_by_game: dict[str, float]) -> OpponentSection:
    buckets: dict[str, list[_Game]] = defaultdict(list)
    for game in games:
        if game.player_elo and game.opponent_elo:
            buckets[_opponent_bucket(game.opponent_elo - game.player_elo)].append(game)
    rows = []
    for key, label in OPPONENT_BUCKETS:
        members = buckets.get(key, [])
        accs = [accuracy_by_game[g.row_id] for g in members if g.row_id in accuracy_by_game]
        rows.append(
            OpponentRow(
                bucket=key,
                label=label,
                games=len(members),
                score_pct=_pct(sum(_score(g.result) or 0.0 for g in members), len(members)),
                accuracy=_mean(accs),
                accuracy_games=len(accs),
            )
        )
    return OpponentSection(sample_size=sum(len(v) for v in buckets.values()), rows=rows)


def _color_section(games: list[_Game], accuracy_by_game: dict[str, float]) -> ColorSection:
    rows = []
    for color in ("white", "black"):
        members = [g for g in games if g.color == color]
        results = Counter(g.result for g in members)
        accs = [accuracy_by_game[g.row_id] for g in members if g.row_id in accuracy_by_game]
        rows.append(
            ColorRow(
                color=color,  # type: ignore[arg-type]
                games=len(members),
                wins=results["win"],
                draws=results["draw"],
                losses=results["loss"],
                score_pct=_pct(results["win"] + 0.5 * results["draw"], len(members)),
                accuracy=_mean(accs),
                accuracy_games=len(accs),
            )
        )
    return ColorSection(
        sample_size=len(games), accuracy_sample_size=len(accuracy_by_game), rows=rows
    )


def _schedule_row(
    key: str, label: str, members: list[_Game], accuracy_by_game: dict[str, float]
) -> ScheduleRow:
    n = len(members)
    row = ScheduleRow(key=key, label=label, games=n, low_sample=n < MIN_SAMPLE)
    if not n:
        return row
    score = sum(_score(g.result) or 0.0 for g in members) / n
    accs = [accuracy_by_game[g.row_id] for g in members if g.row_id in accuracy_by_game]
    blunders = sum(1 for g in members for m in g.moments if m.severity >= BLUNDER_PCT)
    row.score_pct = round(score * 100, 1)
    row.score_low_pct, row.score_high_pct = wilson_interval(score, n)
    row.accuracy = _mean(accs)
    row.accuracy_games = len(accs)
    row.blunders_per_game = round(blunders / n, 2)
    return row


def _breakdown(rows: list[ScheduleRow]) -> ScheduleBreakdown:
    solid = [row for row in rows if not row.low_sample]
    if len(solid) < 2:
        return ScheduleBreakdown(rows=rows)
    best = max(solid, key=lambda row: row.score_pct or 0)
    worst = min(solid, key=lambda row: row.score_pct or 0)
    if (best.score_low_pct or 0) <= (worst.score_high_pct or 0):
        return ScheduleBreakdown(rows=rows)
    return ScheduleBreakdown(rows=rows, best=best.key, worst=worst.key)


def _schedule_section(
    games: list[_Game], accuracy_by_game: dict[str, float], timezone: str | None
) -> ScheduleSection:
    zone, zone_name = resolve_timezone(timezone)
    parts: dict[str, list[_Game]] = defaultdict(list)
    days: dict[int, list[_Game]] = defaultdict(list)
    dated = [g for g in games if g.started_at is not None]
    for game in dated:
        started = game.started_at
        # SQLite drops the offset; stored values are always UTC.
        local = (started if started.tzinfo else started.replace(tzinfo=UTC)).astimezone(zone)
        part = next(key for key, _, hour in reversed(DAY_PARTS) if local.hour >= hour)
        parts[part].append(game)
        days[local.weekday()].append(game)
    return ScheduleSection(
        sample_size=len(dated),
        undated_games=len(games) - len(dated),
        timezone=zone_name,
        by_time_of_day=_breakdown(
            [_schedule_row(key, label, parts[key], accuracy_by_game) for key, label, _ in DAY_PARTS]
        ),
        by_day_of_week=_breakdown(
            [
                _schedule_row(label.lower(), label, days[index], accuracy_by_game)
                for index, label in enumerate(WEEKDAYS)
            ]
        ),
    )


@dataclass
class _LensLeak:
    points: float
    sample: int
    hits: int
    outcomes: int


def _conversion_section(
    engine_games: list[_Game],
) -> tuple[ConversionSection, _LensLeak, _LensLeak]:
    winning = failed = losing = saves = 0
    failed_points = 0.0
    bad_openings = bad_opening_lost = 0
    bad_opening_points = 0.0
    for game in engine_games:
        series = _player_win_pcts(game)
        score = _score(game.result) or 0.0
        if _held(series, lambda v: v >= WINNING_PCT):
            winning += 1
            if game.result != "win":
                failed += 1
                failed_points += 1 - score
        if _held(series, lambda v: v <= LOSING_PCT):
            losing += 1
            if game.result != "loss":
                saves += 1
        if len(series) >= OPENING_END_PLY and series[OPENING_END_PLY - 1] <= LOSING_PCT:
            bad_openings += 1
            if game.result != "win":
                bad_opening_lost += 1
                bad_opening_points += 1 - score
    n = len(engine_games)
    section = ConversionSection(
        sample_size=n,
        winning_games=winning,
        failed_conversions=failed,
        failed_conversion_pct=_pct(failed, winning),
        losing_games=losing,
        saves=saves,
        save_pct=_pct(saves, losing),
    )
    return (
        section,
        _LensLeak(failed_points, n, winning, failed),
        _LensLeak(bad_opening_points, n, bad_openings, bad_opening_lost),
    )


def _rank_leaks(games: list[_Game], conversion: _LensLeak, opening: _LensLeak) -> list[Leak]:
    theme_points: Counter[str] = Counter()
    theme_errors: Counter[str] = Counter()
    theme_phase: dict[str, Counter[str]] = defaultdict(Counter)
    for game in games:
        errors = [m for m in game.moments if m.severity >= MISTAKE_PCT]
        for moment in errors:
            theme_errors[moment.theme] += 1
            theme_phase[moment.theme][moment.phase] += 1
        dropped = 1 - (_score(game.result) or 0.0)
        total = sum(m.severity for m in errors)
        if dropped <= 0 or total <= 0:
            continue
        for moment in errors:
            theme_points[moment.theme] += dropped * moment.severity / total

    candidates: list[Leak] = []
    n = len(games)
    if n >= MIN_SAMPLE:
        for theme, points in theme_points.items():
            if theme not in THEME_TITLES or points <= 0:
                continue
            phase, phase_count = theme_phase[theme].most_common(1)[0]
            share = round(phase_count / theme_errors[theme] * 100)
            per10 = round(points / n * 10, 1)
            candidates.append(
                Leak(
                    id=f"theme:{theme}",
                    title=THEME_TITLES[theme],
                    detail=(
                        f"{theme_errors[theme]:,} mistakes and blunders from "
                        f"{THEME_NOUNS[theme]} in {n:,} games, {share}% of them in the {phase}."
                    ),
                    points_per_10_games=per10,
                    sample_size=n,
                    action=LeakAction(type="practice", theme=theme, label="Practice these positions"),
                )
            )
    if conversion.sample >= MIN_SAMPLE and conversion.outcomes:
        per10 = round(conversion.points / conversion.sample * 10, 1)
        candidates.append(
            Leak(
                id="conversion",
                title="Winning positions that slip away",
                detail=(
                    f"You were winning (about +3 or better) in {conversion.hits} of "
                    f"{conversion.sample} games and didn't win {conversion.outcomes} of them."
                ),
                points_per_10_games=per10,
                sample_size=conversion.sample,
                action=LeakAction(
                    type="practice", theme="endgame_conversion", label="Practice converting"
                ),
            )
        )
    if opening.sample >= MIN_SAMPLE and opening.outcomes:
        per10 = round(opening.points / opening.sample * 10, 1)
        candidates.append(
            Leak(
                id="opening",
                title="Bad positions out of the opening",
                detail=(
                    f"In {opening.hits} of {opening.sample} games you were down about 3 pawns "
                    f"or more by move 12, and you didn't win {opening.outcomes} of them."
                ),
                points_per_10_games=per10,
                sample_size=opening.sample,
                action=LeakAction(type="openings", label="Review your openings"),
            )
        )
    candidates.sort(key=lambda leak: -leak.points_per_10_games)
    leaks: list[Leak] = []
    seen_actions: set[tuple[str, str | None]] = set()
    for leak in candidates:
        key = (leak.action.type, leak.action.theme)
        if key in seen_actions:
            continue
        seen_actions.add(key)
        leaks.append(leak)
        if len(leaks) == 3:
            break
    return leaks
