"""A 7-day study plan built from the player's own leaks, due drills and repertoire reviews.

The plan is stored once and stays put for the week: ``build_plan`` is a pure function of what
``gather_inputs`` read, so the same data always gives the same plan, with or without an LLM key.
Tasks never store whether they are done. Progress is recomputed on every read from what the
player really did during the plan's window:

* drills count legal quiz attempts, one per position (review sessions and themed practice are
  separate pools, so one attempt does not tick both);
* repertoire tasks count distinct moves answered in the drill, logged in ``study_activity``;
* game reviews count a retried move on the review page, also logged, or a quiz attempt on a
  position from that game;
* building a repertoire counts moves added to it.

Tasks are filled in schedule order, so activity goes to the earliest open task and working
ahead finishes later tasks. Nothing here can be ticked by hand.

With OPENROUTER_API_KEY set, ``write_rationale`` may add a short note. It only sees the facts
in ``plan_facts`` and is dropped unless every number it quotes is one of those facts and it
names no chess move (see ``verify_rationale``).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db_models import (
    CriticalMomentRow,
    GameRow,
    PlayerRow,
    QuizAttemptRow,
    RepertoireMoveRow,
    RepertoireRow,
    StudyActivityRow,
    StudyPlanRow,
    TrainingPlanRow,
    TrainingPositionRow,
)
from .insights import (
    MISTAKE_PCT,
    THEME_NOUNS,
    THEME_TITLES,
    Leak,
    LeakAction,
    _is_players_ply,
    build_insights,
)
from .openrouter_client import complete_with_openrouter
from .puzzles import normalize_theme
from .repertoire import _due_reviews, count_due
from .today_api import DueSummary, _aware, _dated, _due, _recency
from .training import REVIEW_PLAN_STATUS, top_weakness

PLAN_DAYS = 7
SESSION_SIZE = 5  # practice sessions hold five positions
REPERTOIRE_BATCH = 8
MIN_TASKS = PLAN_DAYS  # every day gets at least one task
MAX_TASKS = 12
MAX_DUE_BATCHES = 3
MAX_REPERTOIRE_BATCHES = 2
MAX_GAME_REVIEWS = 2
LEAK_SESSIONS = (2, 1, 1)  # practice sessions per leak, biggest leak first
RECENT_GAMES = 15
MAX_RATIONALE_CHARS = 320

GAME_RETRY = "game_retry"
REPERTOIRE_REVIEW = "repertoire_review"

TaskKind = Literal[
    "due_review", "leak_practice", "game_review", "repertoire_review", "repertoire_build"
]
TaskStatus = Literal["todo", "in_progress", "done", "overdue"]
SessionMode = Literal["mixed", "puzzles"]


# --------------------------------------------------------------------------- response


class PlanTask(BaseModel):
    id: str = ""
    kind: TaskKind
    title: str
    detail: str
    target: int
    # Where the task's button goes; which of these is set depends on ``kind``.
    theme: str | None = None
    session_mode: Literal["mixed", "puzzles", "due"] | None = None
    game_id: str | None = None
    moment_id: str | None = None
    repertoire_id: str | None = None
    repertoire_color: str | None = None


class TaskView(PlanTask):
    progress: int = 0
    status: TaskStatus = "todo"


class DayView(BaseModel):
    index: int
    date: str
    tasks: list[TaskView] = Field(default_factory=list)


class PlanView(BaseModel):
    id: str
    start_date: str
    end_date: str
    today_index: int
    summary: str
    rationale: str | None = None
    done_tasks: int
    total_tasks: int
    days: list[DayView]


class PastPlan(BaseModel):
    start_date: str
    end_date: str
    done_tasks: int
    total_tasks: int


class StudyPlanResponse(BaseModel):
    platform: str
    username: str
    known: bool = False
    plan: PlanView | None = None
    last_plan: PastPlan | None = None


# --------------------------------------------------------------------------- inputs


@dataclass
class RepertoireInput:
    id: str
    name: str
    color: str
    due: int
    drillable: int


@dataclass
class GameInput:
    game_id: str
    opponent: str
    result: str
    moment_id: str
    move_number: int
    played_san: str
    best_san: str


@dataclass
class ThemeSupply:
    """How many stored positions a practice session could draw on, per theme."""

    positions: dict[str, int] = field(default_factory=dict)

    def session_for(self, theme: str | None) -> tuple[SessionMode, int] | None:
        """The session mode for a theme and how many of its positions carry that theme."""
        stored = self.positions.get(theme or "", 0)
        if normalize_theme(theme):  # library puzzles top the session up with the same theme
            return ("mixed" if stored else "puzzles"), SESSION_SIZE
        return ("mixed", min(stored, SESSION_SIZE)) if stored else None


@dataclass
class PlanInputs:
    leaks: list[Leak] = field(default_factory=list)
    due: DueSummary = field(default_factory=DueSummary)
    repertoires: list[RepertoireInput] = field(default_factory=list)
    games: list[GameInput] = field(default_factory=list)
    supply: ThemeSupply = field(default_factory=ThemeSupply)


def _theme_supply(session: Session, player_id: str) -> ThemeSupply:
    rows = session.execute(
        select(CriticalMomentRow.theme, func.count())
        .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
        .where(GameRow.player_id == player_id, CriticalMomentRow.best_san.is_not(None))
        .group_by(CriticalMomentRow.theme)
    ).all()
    return ThemeSupply({theme: count for theme, count in rows})


def _games_to_review(session: Session, player_id: str) -> list[GameInput]:
    """Newest games the player did not win and has not retried yet, with their worst error."""
    retried = set(
        session.scalars(
            select(StudyActivityRow.ref).where(
                StudyActivityRow.player_id == player_id, StudyActivityRow.kind == GAME_RETRY
            )
        ).all()
    )
    rows = session.execute(
        select(
            GameRow.id,
            GameRow.external_game_id,
            GameRow.played_at,
            GameRow.link,
            GameRow.created_at,
            GameRow.white,
            GameRow.black,
            GameRow.player_color,
            GameRow.player_result,
        ).where(
            GameRow.player_id == player_id,
            GameRow.player_result.in_(("loss", "draw")),
            *_dated(),
        )
    ).all()
    rows.sort(key=lambda row: _recency(row.played_at, row.link, row.created_at), reverse=True)
    candidates = [row for row in rows if row.external_game_id not in retried][:RECENT_GAMES]
    if not candidates:
        return []
    moments: dict[str, list[CriticalMomentRow]] = {}
    for moment in session.scalars(
        select(CriticalMomentRow).where(
            CriticalMomentRow.game_id.in_([row.id for row in candidates]),
            CriticalMomentRow.best_san.is_not(None),
        )
    ):
        moments.setdefault(moment.game_id, []).append(moment)
    games: list[GameInput] = []
    for row in candidates:
        errors = [
            item
            for item in moments.get(row.id, [])
            if _is_players_ply(item.ply, row.player_color) and item.severity >= MISTAKE_PCT
        ]
        if not errors:
            continue
        worst = max(errors, key=lambda item: (item.severity, -item.ply))
        games.append(
            GameInput(
                game_id=row.external_game_id,
                opponent=row.black if row.player_color == "white" else row.white,
                result=row.player_result,
                moment_id=worst.external_moment_id,
                move_number=worst.move_number,
                played_san=worst.played_san,
                best_san=worst.best_san or "",
            )
        )
        if len(games) == MAX_GAME_REVIEWS:
            break
    return games


def gather_inputs(session: Session, player: PlayerRow, now: datetime) -> PlanInputs:
    total = session.scalar(
        select(func.count()).select_from(GameRow).where(GameRow.player_id == player.id)
    )
    leaks = build_insights(session, player, 500, total or 0).leaks
    supply = _theme_supply(session, player.id)
    if not leaks:
        # Too few games to rank leaks: fall back on the most frequent theme, if there is one.
        theme = top_weakness(session, player)
        if theme in THEME_TITLES and supply.positions.get(theme):
            leaks = [
                Leak(
                    id=f"theme:{theme}",
                    title=THEME_TITLES[theme],
                    detail="Your most frequent error so far.",
                    points_per_10_games=0,
                    sample_size=0,
                    action=LeakAction(type="practice", theme=theme, label="Practice these"),
                )
            ]
    reps = session.scalars(
        select(RepertoireRow)
        .where(RepertoireRow.player_id == player.id)
        .order_by(RepertoireRow.created_at)
    ).all()
    return PlanInputs(
        leaks=leaks,
        due=_due(session, player.id, now),
        repertoires=[
            RepertoireInput(
                id=rep.id,
                name=rep.name,
                color=rep.color,
                due=count_due(session, rep),
                drillable=len(_due_reviews(session, rep, include_all=True)),
            )
            for rep in reps
        ],
        games=_games_to_review(session, player.id),
        supply=supply,
    )


# --------------------------------------------------------------------------- build


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _due_tasks(inputs: PlanInputs) -> list[PlanTask]:
    remaining = inputs.due.count
    top = inputs.due.themes[0].theme if inputs.due.themes else ""
    theme = THEME_NOUNS.get(top, top.replace("_", " "))
    tasks = []
    while remaining > 0 and len(tasks) < MAX_DUE_BATCHES:
        size = min(remaining, SESSION_SIZE)
        tasks.append(
            PlanTask(
                kind="due_review",
                title=f"Review {_plural(size, 'due position')}",
                detail=f"Positions from your earlier sessions, mostly {theme}.",
                target=size,
                session_mode="due",
            )
        )
        remaining -= size
    return tasks


def _practice_task(leak: Leak, mode: SessionMode, target: int) -> PlanTask:
    cost = f"{leak.points_per_10_games:.1f} points lost per 10 games. "
    return PlanTask(
        kind="leak_practice",
        title=f"Practice: {leak.title}",
        detail=f"{cost if leak.points_per_10_games else ''}{leak.detail}",
        target=target,
        theme=leak.action.theme,
        session_mode=mode,
    )


def _opening_task(leak: Leak, inputs: PlanInputs) -> PlanTask:
    drillable = [rep for rep in inputs.repertoires if rep.drillable]
    if not drillable:
        return PlanTask(
            kind="repertoire_build",
            title="Build an opening repertoire",
            detail=f"Add at least {SESSION_SIZE} moves. {leak.detail}",
            target=SESSION_SIZE,
        )
    rep = max(drillable, key=lambda item: item.drillable)
    return PlanTask(
        kind="repertoire_review",
        title=f"Drill {rep.name}",
        detail=f"Turn on moves that are not due yet. {leak.detail}",
        target=min(rep.drillable, SESSION_SIZE),
        repertoire_id=rep.id,
        repertoire_color=rep.color,
    )


def _leak_tasks(inputs: PlanInputs) -> list[PlanTask]:
    tasks: list[PlanTask] = []
    for leak, sessions in zip(inputs.leaks, LEAK_SESSIONS):
        if leak.action.type == "openings":
            tasks.append(_opening_task(leak, inputs))
            continue
        slot = inputs.supply.session_for(leak.action.theme)
        if slot is not None:
            tasks.extend(_practice_task(leak, *slot) for _ in range(sessions))
    return tasks


def _repertoire_tasks(inputs: PlanInputs) -> list[PlanTask]:
    tasks = []
    for rep in sorted(inputs.repertoires, key=lambda item: -item.due):
        remaining = rep.due
        for _ in range(MAX_REPERTOIRE_BATCHES):
            if remaining <= 0:
                break
            size = min(remaining, REPERTOIRE_BATCH)
            tasks.append(
                PlanTask(
                    kind="repertoire_review",
                    title=f"Drill {rep.name}",
                    detail=f"{_plural(size, 'move')} due as {rep.color}.",
                    target=size,
                    repertoire_id=rep.id,
                    repertoire_color=rep.color,
                )
            )
            remaining -= size
    return tasks


def _game_tasks(inputs: PlanInputs) -> list[PlanTask]:
    return [
        PlanTask(
            kind="game_review",
            title=f"Review your {game.result} against {game.opponent}",
            detail=(
                f"Move {game.move_number}: you played {game.played_san}, "
                f"{game.best_san} was better. Retry it on the board."
            ),
            target=1,
            game_id=game.game_id,
            moment_id=game.moment_id,
        )
        for game in inputs.games
    ]


def _fillers(inputs: PlanInputs) -> list[PlanTask]:
    """Repeatable sessions that keep every day of the plan non-empty."""
    fillers = []
    for leak in inputs.leaks:
        slot = inputs.supply.session_for(leak.action.theme)
        if leak.action.type == "practice" and slot is not None:
            fillers.append(_practice_task(leak, *slot))
    return fillers or [
        PlanTask(
            kind="leak_practice",
            title="Solve library puzzles",
            detail="Puzzles near your rating, until your games show a clear leak.",
            target=SESSION_SIZE,
            session_mode="puzzles",
        )
    ]


def build_plan(inputs: PlanInputs) -> list[list[PlanTask]]:
    """Deal tasks across the week. Returns seven lists, or an empty list with nothing to do."""
    queues = [
        _due_tasks(inputs),
        _leak_tasks(inputs),
        _game_tasks(inputs),
        _repertoire_tasks(inputs),
    ]
    tasks: list[PlanTask] = []
    while any(queues) and len(tasks) < MAX_TASKS:
        for queue in queues:
            if queue and len(tasks) < MAX_TASKS:
                tasks.append(queue.pop(0))
    if not tasks:
        return []
    fillers = _fillers(inputs)
    position = 0
    while len(tasks) < MIN_TASKS:
        tasks.append(fillers[position % len(fillers)])
        position += 1
    days: list[list[PlanTask]] = [[] for _ in range(PLAN_DAYS)]
    for index, task in enumerate(tasks):
        # Even spread: one or two tasks a day.
        day = days[index * PLAN_DAYS // len(tasks)]
        day.append(task.model_copy(update={"id": f"t{index + 1}"}))
    return days


def plan_facts(inputs: PlanInputs, days: list[list[PlanTask]]) -> dict[str, Any]:
    """The verified numbers behind a plan: its summary and the only data the LLM may use."""
    return {
        "leaks": [
            {
                "title": leak.title,
                "points_per_10_games": leak.points_per_10_games,
                "games": leak.sample_size,
            }
            for leak in inputs.leaks
        ],
        "due_positions": inputs.due.count,
        "repertoire_moves_due": sum(rep.due for rep in inputs.repertoires),
        "games_to_review": len(inputs.games),
        "days": PLAN_DAYS,
        "tasks": sum(len(day) for day in days),
    }


def plan_summary(facts: dict[str, Any]) -> str:
    parts = []
    if facts["leaks"]:
        titles = [leak["title"] for leak in facts["leaks"][:2]]
        parts.append(f"Focus: {' and '.join(titles)}.")
    backlog = []
    if facts["due_positions"]:
        backlog.append(_plural(facts["due_positions"], "due position"))
    if facts["repertoire_moves_due"]:
        backlog.append(_plural(facts["repertoire_moves_due"], "repertoire move"))
    if facts["games_to_review"]:
        backlog.append(_plural(facts["games_to_review"], "game") + " to review")
    if backlog:
        parts.append(f"Backlog: {', '.join(backlog)}.")
    return " ".join(parts) or "General practice this week."


# --------------------------------------------------------------------------- persistence


def local_date(value: str | None, now: datetime | None = None) -> date:
    """The client's calendar date, trusted only within a day of UTC; UTC's date otherwise."""
    utc_today = (now or datetime.now(UTC)).date()
    try:
        parsed = date.fromisoformat(value or "")
    except ValueError:
        return utc_today
    return parsed if abs((parsed - utc_today).days) <= 1 else utc_today


def _latest_plan(session: Session, player_id: str) -> StudyPlanRow | None:
    return session.scalar(
        select(StudyPlanRow)
        .where(StudyPlanRow.player_id == player_id)
        .order_by(StudyPlanRow.start_date.desc())
        .limit(1)
    )


def _is_current(plan: StudyPlanRow, today: date) -> bool:
    return (today - date.fromisoformat(plan.start_date)).days < PLAN_DAYS


def create_plan(
    session: Session, player: PlayerRow, today: date, now: datetime | None = None
) -> StudyPlanRow | None:
    """Return the current plan, building one if needed. None when there is nothing to plan."""
    latest = _latest_plan(session, player.id)
    if latest is not None and _is_current(latest, today):
        return latest
    now = now or datetime.now(UTC)
    inputs = gather_inputs(session, player, now)
    days = build_plan(inputs)
    if not days:
        return None
    facts = plan_facts(inputs, days)
    plan = StudyPlanRow(
        player_id=player.id,
        start_date=today.isoformat(),
        starts_at=now,
        ends_at=now + timedelta(days=PLAN_DAYS),
        days=[[task.model_dump() for task in day] for day in days],
        facts=facts,
        summary=plan_summary(facts),
    )
    session.add(plan)
    session.flush()
    return plan


def record_activity(
    session: Session, player_id: str, kind: str, ref: str, context: str = ""
) -> None:
    session.add(StudyActivityRow(player_id=player_id, kind=kind, ref=ref, context=context))
    session.flush()


# --------------------------------------------------------------------------- progress


def activity_pools(session: Session, plan: StudyPlanRow) -> Counter[str]:
    """How much of each kind of work the player did during the plan's window."""
    start, end = _aware(plan.starts_at), _aware(plan.ends_at)
    attempts = session.execute(
        select(
            QuizAttemptRow.position_id,
            TrainingPositionRow.theme,
            TrainingPlanRow.status,
            GameRow.external_game_id,
        )
        .join(TrainingPositionRow, TrainingPositionRow.id == QuizAttemptRow.position_id)
        .join(TrainingPlanRow, TrainingPlanRow.id == TrainingPositionRow.plan_id)
        .outerjoin(CriticalMomentRow, CriticalMomentRow.id == TrainingPositionRow.moment_id)
        .outerjoin(GameRow, GameRow.id == CriticalMomentRow.game_id)
        .where(
            QuizAttemptRow.player_id == plan.player_id,
            QuizAttemptRow.legal.is_(True),
            QuizAttemptRow.created_at >= start,
            QuizAttemptRow.created_at < end,
        )
        .distinct()
    ).all()
    pools: Counter[str] = Counter()
    games: set[str] = set()
    for _position, theme, status, game_id in attempts:
        if status == REVIEW_PLAN_STATUS:
            pools["review"] += 1
        else:
            pools[f"theme:{theme}"] += 1
            pools["any"] += 1
        if game_id:
            games.add(game_id)

    logged = session.execute(
        select(StudyActivityRow.kind, StudyActivityRow.ref, StudyActivityRow.context)
        .where(
            StudyActivityRow.player_id == plan.player_id,
            StudyActivityRow.created_at >= start,
            StudyActivityRow.created_at < end,
        )
        .distinct()
    ).all()
    for kind, ref, context in logged:
        if kind == REPERTOIRE_REVIEW:
            pools[f"rep:{context}"] += 1
        elif kind == GAME_RETRY:
            games.add(ref)
    for game_id in games:
        pools[f"game:{game_id}"] = 1

    pools["build"] = (
        session.scalar(
            select(func.count())
            .select_from(RepertoireMoveRow)
            .join(RepertoireRow, RepertoireRow.id == RepertoireMoveRow.repertoire_id)
            .where(
                RepertoireRow.player_id == plan.player_id,
                RepertoireMoveRow.created_at >= start,
                RepertoireMoveRow.created_at < end,
            )
        )
        or 0
    )
    return pools


def _pool_key(task: PlanTask) -> str:
    if task.kind == "due_review":
        return "review"
    if task.kind == "leak_practice":
        return f"theme:{task.theme}" if task.theme else "any"
    if task.kind == "game_review":
        return f"game:{task.game_id}"
    if task.kind == "repertoire_review":
        return f"rep:{task.repertoire_id}"
    return "build"


def _status(progress: int, target: int, past_day: bool) -> TaskStatus:
    if progress >= target:
        return "done"
    if past_day:
        return "overdue"
    return "in_progress" if progress else "todo"


def plan_view(session: Session, plan: StudyPlanRow, today: date) -> PlanView:
    start = date.fromisoformat(plan.start_date)
    today_index = max(0, min(PLAN_DAYS - 1, (today - start).days))
    pools = activity_pools(session, plan)
    days: list[DayView] = []
    for index, stored in enumerate(plan.days):
        tasks = []
        for raw in stored:
            task = PlanTask.model_validate(raw)
            key = _pool_key(task)
            progress = min(task.target, pools[key])
            pools[key] -= progress
            tasks.append(
                TaskView(
                    **task.model_dump(),
                    progress=progress,
                    status=_status(progress, task.target, index < today_index),
                )
            )
        days.append(
            DayView(index=index, date=(start + timedelta(days=index)).isoformat(), tasks=tasks)
        )
    every_task = [task for day in days for task in day.tasks]
    return PlanView(
        id=plan.id,
        start_date=plan.start_date,
        end_date=(start + timedelta(days=PLAN_DAYS - 1)).isoformat(),
        today_index=today_index,
        summary=plan.summary,
        rationale=plan.rationale,
        done_tasks=sum(task.status == "done" for task in every_task),
        total_tasks=len(every_task),
        days=days,
    )


def study_plan_response(
    session: Session, platform: str, username: str, player: PlayerRow | None, today: date
) -> StudyPlanResponse:
    if player is None:
        return StudyPlanResponse(platform=platform, username=username)
    response = StudyPlanResponse(platform=platform, username=player.username, known=True)
    latest = _latest_plan(session, player.id)
    if latest is None:
        return response
    view = plan_view(session, latest, today)
    if _is_current(latest, today):
        response.plan = view
    else:
        response.last_plan = PastPlan(
            start_date=view.start_date,
            end_date=view.end_date,
            done_tasks=view.done_tasks,
            total_tasks=view.total_tasks,
        )
    return response


# --------------------------------------------------------------------------- rationale

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_RATE_UNIT = re.compile(r"\bper 10 games\b", re.IGNORECASE)  # the unit of a fact, not a claim
_MOVE = re.compile(r"\b(?:O-O(?:-O)?|[KQRBN][a-h1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8]|[a-h][1-8])\b")


def _fact_numbers(value: Any) -> set[float]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)) and math.isfinite(value):
        return {float(value)}
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return {number for item in value for number in _fact_numbers(item)}
    return set()


def verify_rationale(text: str, facts: dict[str, Any]) -> bool:
    """Accept only short plain text that quotes the facts' numbers and names no moves."""
    if not text or len(text) > MAX_RATIONALE_CHARS or _MOVE.search(text):
        return False
    allowed = _fact_numbers(facts)
    quoted = _NUMBER.findall(_RATE_UNIT.sub("", text))
    return all(float(found) in allowed for found in quoted)


async def write_rationale(facts: dict[str, Any]) -> tuple[str | None, bool]:
    """The verified note, or None, and whether the model answered at all."""
    system = (
        "You write a short note explaining a chess player's weekly study plan. "
        'Return JSON only: {"rationale": "..."}. Two sentences at most, plain text. '
        "Use only the supplied facts. Do not add numbers that are not in them. "
        "Do not name chess moves, squares or openings, and do not promise rating gains."
    )
    raw, used = await complete_with_openrouter(
        system, f"Facts: {json.dumps(facts)}", temperature=0.2
    )
    if not used:
        return None, False
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None, True
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None, True
    text = str(data.get("rationale") or "").strip() if isinstance(data, dict) else ""
    return (text if verify_rationale(text, facts) else None), True
