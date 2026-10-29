from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import CriticalMomentRow, GameRow, PlayerMemoryRow, PlayerRow, TrainingPositionRow
from .openrouter_client import complete_with_openrouter_sync
from .repositories import get_or_create_player, normalize_username


def _theme_label(theme: str) -> str:
    return theme.replace("_", " ")


def fetch_practice_candidates(
    session: Session,
    platform: str,
    username: str,
    theme: str | None = None,
    limit: int = 20,
) -> list[CriticalMomentRow]:
    player = get_or_create_player(session, platform, username)
    query = (
        select(CriticalMomentRow)
        .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
        .where(GameRow.player_id == player.id, CriticalMomentRow.best_san.is_not(None))
        .order_by(CriticalMomentRow.severity.desc())
    )
    if theme:
        query = query.where(CriticalMomentRow.theme == theme)
    candidates = session.scalars(query).all()
    trainable = [
        item for item in candidates if (item.explanation or {}).get("trainable", False)
    ]
    return (trainable or candidates)[:limit]


def candidate_payload(moment: CriticalMomentRow) -> dict[str, Any]:
    explanation = moment.explanation or {}
    return {
        "moment_id": moment.id,
        "theme": moment.theme,
        "severity": moment.severity,
        "what_happened": explanation.get("what_happened", ""),
        "principle": explanation.get("principle", ""),
        "trainable": explanation.get("trainable", False),
    }


def rank_moments_with_llm(
    session: Session,
    platform: str,
    username: str,
    candidates: list[CriticalMomentRow],
    position_count: int = 5,
) -> tuple[list[str], bool]:
    if not candidates:
        return [], False
    player = session.scalar(
        select(PlayerRow).where(
            PlayerRow.platform == platform,
            PlayerRow.username_normalized == normalize_username(username),
        )
    )
    memory = session.get(PlayerMemoryRow, player.id) if player else None
    weakness = (memory.recurring_themes if memory else {}) or {}
    payload = [candidate_payload(item) for item in candidates]
    system = (
        "You rank chess practice positions for a club player. "
        "Return JSON only: {\"moment_ids\": [\"id1\", \"id2\", ...]}. "
        "Use only IDs from the candidate list. Prefer themes the player repeats."
    )
    prompt = (
        f"Pick the best {position_count} drill positions.\n"
        f"Player weakness frequency: {json.dumps(weakness)}\n"
        f"Candidates: {json.dumps(payload)}"
    )
    raw, used = complete_with_openrouter_sync(system, prompt, temperature=0.0)
    if not used:
        return [item.id for item in candidates[:position_count]], False
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return [item.id for item in candidates[:position_count]], False
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return [item.id for item in candidates[:position_count]], False
    allowed = {item.id for item in candidates}
    ranked = [item for item in data.get("moment_ids", []) if item in allowed]
    if not ranked:
        return [item.id for item in candidates[:position_count]], False
    return ranked[:position_count], True


def generate_quiz_copy_with_llm(
    theme: str,
    what_happened: str,
    principle: str,
    difficulty: str,
) -> tuple[str, str | None, bool]:
    theme_label = _theme_label(theme)
    fallback_prompt = f"You had a {theme_label} pattern in your game — what would you play?"
    fallback_hint = (
        f"Start with checks and captures. Theme: {theme_label}."
        if difficulty == "beginner"
        else None
    )
    system = (
        "Write a short practice quiz question and optional hint for a chess position. "
        "Return JSON only: {\"prompt\": \"...\", \"hint\": \"...\" or null}. "
        "Do not invent moves or variations. Ground copy in the supplied facts only."
    )
    prompt = (
        f"Theme: {theme}\n"
        f"What happened: {what_happened}\n"
        f"Principle: {principle}\n"
        f"Difficulty: {difficulty}\n"
        "Ask what the player would play. Hint should nudge scanning, not give the move."
    )
    raw, used = complete_with_openrouter_sync(system, prompt, temperature=0.2)
    if not used:
        return fallback_prompt, fallback_hint, False
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return fallback_prompt, fallback_hint, False
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return fallback_prompt, fallback_hint, False
    question = str(data.get("prompt", fallback_prompt)).strip()
    hint_value = data.get("hint")
    hint = str(hint_value).strip() if hint_value else None
    if difficulty != "beginner":
        hint = None
    if not question:
        question = fallback_prompt
    return question, hint, True


def apply_llm_quiz_copy(session: Session, plan_id: str) -> bool:
    positions = session.scalars(
        select(TrainingPositionRow)
        .where(TrainingPositionRow.plan_id == plan_id)
        .order_by(TrainingPositionRow.position_order)
    ).all()
    used_llm = False
    for position in positions:
        moment = session.get(CriticalMomentRow, position.moment_id) if position.moment_id else None
        explanation = (moment.explanation or {}) if moment else {}
        prompt, hint, used = generate_quiz_copy_with_llm(
            position.theme,
            position.explanation or explanation.get("what_happened", ""),
            explanation.get("principle", ""),
            position.difficulty,
        )
        position.prompt = prompt
        position.hint = hint
        used_llm = used_llm or used
    session.flush()
    return used_llm
