from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Vector384(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(384))
        return dialect.type_descriptor(JSON())


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("plan IN ('free', 'paid')", name="ck_users_plan"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    plan: Mapped[str] = mapped_column(String(20), default="free", server_default="free")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuthIdentityRow(Base):
    """One way to sign in. Adding a provider means adding rows, not columns on users."""

    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayerRow(Base):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("platform", "username_normalized"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    username: Mapped[str] = mapped_column(String(100))
    username_normalized: Mapped[str] = mapped_column(String(100), index=True)
    current_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserPlayerRow(Base):
    """A verified claim on a player. A player has at most one owner."""

    __tablename__ = "user_players"

    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # How ownership was proven: "lichess_oauth" or "chesscom_profile".
    verified_by: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CoachUsageRow(Base):
    """Coach questions asked per UTC day. Subject is "user:<id>" or "anon:<hash of address>"."""

    __tablename__ = "coach_usage"

    subject: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    questions: Mapped[int] = mapped_column(Integer, default=0)


class GameRow(Base):
    __tablename__ = "games"
    __table_args__ = (UniqueConstraint("player_id", "external_game_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    external_game_id: Mapped[str] = mapped_column(String(64), index=True)
    white: Mapped[str] = mapped_column(String(100))
    black: Mapped[str] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(12))
    player_result: Mapped[str] = mapped_column(String(12))
    player_color: Mapped[str] = mapped_column(String(12))
    player_elo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    played_at: Mapped[str] = mapped_column(String(24), default="")
    # UTC start time. Null for games imported before it was stored and PGNs without UTCTime.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_control: Mapped[str] = mapped_column(String(40), default="")
    link: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisRow(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), unique=True)
    summary: Mapped[str] = mapped_column(Text)
    training_plan: Mapped[list[str]] = mapped_column(JSON, default=list)
    retrieval_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CriticalMomentRow(Base):
    __tablename__ = "critical_moments"
    __table_args__ = (UniqueConstraint("game_id", "external_moment_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    external_moment_id: Mapped[str] = mapped_column(String(80), index=True)
    move_number: Mapped[int] = mapped_column(Integer)
    ply: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(20))
    theme: Mapped[str] = mapped_column(String(40), index=True)
    played_san: Mapped[str] = mapped_column(String(30))
    best_san: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fen_before: Mapped[str] = mapped_column(Text)
    fen_after: Mapped[str] = mapped_column(Text)
    eval_swing: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[float] = mapped_column(Float, default=0)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CoachSessionRow(Base):
    __tablename__ = "coach_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    focus_theme: Mapped[str] = mapped_column(String(40), default="candidate_move_discipline")
    summary: Mapped[str] = mapped_column(Text, default="")
    accumulated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("session_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("coach_sessions.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    message_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionSummaryRow(Base):
    __tablename__ = "session_summaries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("coach_sessions.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    through_sequence: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector384, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayerMemoryRow(Base):
    __tablename__ = "player_memories"

    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    recurring_themes: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    quiz_accuracy: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    mastered_positions: Mapped[int] = mapped_column(Integer, default=0)
    due_positions: Mapped[int] = mapped_column(Integer, default=0)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# Holds the positions behind puzzles solved on the puzzle page, one plan per player. It is not
# a session: nothing serves its positions again, so they stay out of "due" counts.
LIBRARY_PLAN_STATUS = "library"


class TrainingPlanRow(Base):
    __tablename__ = "training_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    focus_themes: Mapped[list[str]] = mapped_column(JSON, default=list)
    difficulty: Mapped[str] = mapped_column(String(20), default="intermediate")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrainingPositionRow(Base):
    __tablename__ = "training_positions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    moment_id: Mapped[str | None] = mapped_column(ForeignKey("critical_moments.id", ondelete="SET NULL"), nullable=True)
    position_order: Mapped[int] = mapped_column(Integer)
    fen: Mapped[str] = mapped_column(Text)
    correct_move: Mapped[str] = mapped_column(String(30))
    choices: Mapped[list[str]] = mapped_column(JSON, default=list)
    theme: Mapped[str] = mapped_column(String(40), index=True)
    difficulty: Mapped[str] = mapped_column(String(20))
    explanation: Mapped[str] = mapped_column(Text, default="")
    # "game" for positions from the player's own games, "puzzle" for library puzzles.
    source: Mapped[str] = mapped_column(String(10), default="game", server_default="game")
    puzzle_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Full solution line in UCI, starting with the player's move (puzzles only).
    solution: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Time trainer positions only: countdown, original clock use, engine view of the played move.
    timing: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, default="What would you play in this position?")
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuizAttemptRow(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("training_positions.id", ondelete="CASCADE"), index=True)
    submitted_move: Mapped[str] = mapped_column(String(30))
    correct: Mapped[bool] = mapped_column(Boolean)
    legal: Mapped[bool] = mapped_column(Boolean)
    cp_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewScheduleRow(Base):
    __tablename__ = "review_schedule"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("training_positions.id", ondelete="CASCADE"), unique=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=1)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(160), index=True)
    title: Mapped[str] = mapped_column(String(200))
    section: Mapped[str] = mapped_column(String(200), default="")
    theme: Mapped[str] = mapped_column(String(60), index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="all")
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector384, nullable=True)


class StreamEventRow(Base):
    __tablename__ = "stream_events"
    __table_args__ = (UniqueConstraint("message_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SyncJobRow(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    username: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    total_games: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_games: Mapped[int] = mapped_column(Integer, default=0)
    skipped_games: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RepertoireRow(Base):
    __tablename__ = "repertoires"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    color: Mapped[str] = mapped_column(String(5))
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RepertoireMoveRow(Base):
    __tablename__ = "repertoire_moves"
    __table_args__ = (UniqueConstraint("repertoire_id", "parent_fen_epd", "uci"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    repertoire_id: Mapped[str] = mapped_column(
        ForeignKey("repertoires.id", ondelete="CASCADE"), index=True
    )
    parent_fen_epd: Mapped[str] = mapped_column(String(100), index=True)
    san: Mapped[str] = mapped_column(String(12))
    uci: Mapped[str] = mapped_column(String(5))
    fen_after: Mapped[str] = mapped_column(String(100))
    comment: Mapped[str] = mapped_column(Text, default="")
    # Games where the player's own move here was an inaccuracy/mistake/blunder (seeded lines).
    mistake_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RepertoireReviewRow(Base):
    __tablename__ = "repertoire_reviews"

    move_id: Mapped[str] = mapped_column(
        ForeignKey("repertoire_moves.id", ondelete="CASCADE"), primary_key=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    last_result: Mapped[str | None] = mapped_column(String(10), nullable=True)


class StudyPlanRow(Base):
    """A 7-day plan. ``days`` holds tasks only; progress is recomputed from activity on read."""

    __tablename__ = "study_plans"
    __table_args__ = (UniqueConstraint("player_id", "start_date"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[str] = mapped_column(String(10))  # the player's local date, YYYY-MM-DD
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    days: Mapped[list[list[dict[str, Any]]]] = mapped_column(JSON, default=list)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudyActivityRow(Base):
    """Things the player did that leave no other dated trace: drill answers and game retries."""

    __tablename__ = "study_activity"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    # repertoire_review: ref is the move id, context the repertoire id.
    # game_retry: ref is the external game id, context the ply.
    ref: Mapped[str] = mapped_column(String(64))
    context: Mapped[str] = mapped_column(String(32), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
