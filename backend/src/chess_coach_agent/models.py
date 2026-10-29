from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from .classification import MoveClassification, game_accuracy


class MoveRecord(BaseModel):
    ply: int
    move_number: int
    color: Literal["white", "black"]
    san: str
    uci: str
    fen_before: str
    fen_after: str
    is_player_move: bool = False
    # Engine view after this move, from White's point of view (see classification.py).
    eval_cp: int | None = None  # None when the score is a mate
    eval_mate: int | None = None  # > 0 White mates in N, < 0 Black mates, 0 = checkmate on board
    win_pct: float | None = None  # White Win% 0-100 after the move
    # Quality of this move for the side that played it.
    win_pct_loss: float | None = None  # Win% points the mover gave up (>= 0)
    accuracy: float | None = None  # Lichess move accuracy 0-100
    classification: MoveClassification | None = None
    best_uci: str | None = None  # engine's top move in the position before this move
    best_san: str | None = None
    # From PGN %clk comments; None when the PGN has no clocks.
    clock_seconds: float | None = None  # mover's clock after the move
    time_spent_seconds: float | None = None  # includes the increment
    time_pressure: bool = False  # clock below 10% of the base time after this move


class CriticalMoment(BaseModel):
    id: str
    game_id: str
    ply: int
    move_number: int
    phase: Literal["opening", "middlegame", "endgame"]
    theme: str
    played_san: str
    best_san: str | None = None
    fen_before: str
    fen_after: str
    fen_best: str | None = None
    eval_before: float | None = None
    eval_after: float | None = None
    eval_swing: float | None = None
    severity: float = 0
    judgment: Literal["inaccuracy", "mistake", "blunder"]
    win_probability_loss: float
    move_accuracy: float
    trainable: bool = False
    summary: str
    what_happened: str
    better_plan: str
    principle: str
    drill_prompt: str


class GameMetadata(BaseModel):
    game_id: str
    source: str = "pgn"
    white: str
    black: str
    result: str
    date: str = "????.??.??"
    link: str = ""
    eco: str = ""
    time_control: str = ""
    player_color: Literal["white", "black", "unknown"] = "unknown"
    player_result: Literal["win", "loss", "draw", "unknown"] = "unknown"
    player_elo: int | None = None
    opponent_elo: int | None = None
    termination: str = ""


class SideAccuracy(BaseModel):
    white: float | None = None
    black: float | None = None


class EvalPoint(BaseModel):
    ply: int
    eval_cp: int | None = None
    eval_mate: int | None = None
    win_pct: float


class CoachAnalysis(BaseModel):
    game: GameMetadata
    moves: list[MoveRecord]
    moments: list[CriticalMoment]
    summary: str
    training_plan: list[str]
    retrieval_notes: list[str] = Field(default_factory=list)
    # Derived from the per-move engine fields, so analyses loaded from storage get them too.
    accuracy: SideAccuracy | None = None
    eval_series: list[EvalPoint] = Field(default_factory=list)
    classification_counts: dict[str, dict[str, int]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _derive_engine_summary(self) -> CoachAnalysis:
        if not self.moves or any(move.win_pct is None for move in self.moves):
            return self
        if not self.eval_series:
            self.eval_series = [
                EvalPoint(
                    ply=move.ply,
                    eval_cp=move.eval_cp,
                    eval_mate=move.eval_mate,
                    win_pct=move.win_pct,  # type: ignore[arg-type]
                )
                for move in self.moves
            ]
        if self.accuracy is None:
            self.accuracy = SideAccuracy(
                **game_accuracy(
                    [move.win_pct for move in self.moves],  # type: ignore[misc]
                    white_moves_first=self.moves[0].color == "white",
                )
            )
        if not self.classification_counts:
            counts: dict[str, dict[str, int]] = {"white": {}, "black": {}}
            for move in self.moves:
                if move.classification:
                    side = counts[move.color]
                    side[move.classification] = side.get(move.classification, 0) + 1
            self.classification_counts = counts
        return self


class AnalyzeRequest(BaseModel):
    pgn: str
    player: Annotated[str, StringConstraints(strip_whitespace=True)] = "kfctofu"
    max_games: int = Field(default=1, ge=1, le=100)
    platform: Literal["chess.com", "lichess", "pgn"] = "pgn"


class AnalyzeResponse(BaseModel):
    analyses: list[CoachAnalysis]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BoardArrow(BaseModel):
    from_square: str = Field(description="Start square in algebraic notation, for example e2")
    to_square: str = Field(description="End square in algebraic notation, for example e4")
    kind: Literal["best", "played", "threat", "idea"] = Field(
        default="idea",
        description=(
            "best: the recommended move; played: the move the player chose; threat: a move the "
            "opponent threatens; idea: a plan or piece route that need not be a legal move now"
        ),
    )


class SquareHighlight(BaseModel):
    square: str = Field(description="Square in algebraic notation, for example f7")
    kind: Literal["focus", "weakness", "threat", "idea"] = Field(
        default="focus",
        description="focus: the square the answer talks about; weakness: a weak square or loose "
        "piece; threat: a square under attack; idea: a target square for a plan",
    )


class CoachingOutput(BaseModel):
    answer: str = Field(description="A concise, practical answer in Markdown")
    evidence: list[str] = Field(
        default_factory=list,
        description="Concrete engine, move, or retrieved-principle facts supporting the answer",
    )
    recommended_move: str | None = Field(
        default=None,
        description="A legal SAN move when the supplied analysis supports one",
    )
    principle: str = Field(description="The main reusable chess principle")
    drill: str = Field(description="A specific practice exercise based on the player's game")
    confidence: float = Field(ge=0, le=1)
    arrows: list[BoardArrow] = Field(
        default_factory=list,
        description="Up to 4 arrows to draw on the player's board (the position in the given FEN)",
    )
    highlights: list[SquareHighlight] = Field(
        default_factory=list,
        description="Up to 4 squares to highlight on the player's board",
    )


class CoachAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    platform: Literal["chess.com", "lichess", "pgn"] = "chess.com"
    username: str = "kfctofu"
    game_id: str | None = None
    fen: str | None = None
    message_history: list[dict[str, Any]] = Field(default_factory=list)


class CoachAskResponse(BaseModel):
    answer: str
    coaching: CoachingOutput
    used_llm: bool
    tools_used: list[str] = Field(default_factory=list)
    retrieved_notes: list[str] = Field(default_factory=list)
    message_history: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    arrows: list[BoardArrow] = Field(default_factory=list)
    highlights: list[SquareHighlight] = Field(default_factory=list)
    annotations_dropped: int = 0
    fallback_reason: str = ""


class CoachFeedbackRequest(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=8000)
    rating: Literal["helpful", "not_helpful"]
    game_id: str | None = None
    fen: str | None = None
    tools_used: list[str] = Field(default_factory=list)


class SyncGamesRequest(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    platform: Literal["chess.com", "lichess"]
    max_games: int = Field(default=2000, ge=1, le=5000)


class SyncJobView(BaseModel):
    id: str
    platform: str
    username: str
    status: Literal["queued", "fetching", "analyzing", "complete", "failed"]
    total_games: int
    analyzed_games: int
    skipped_games: int
    error: str = ""
    created_at: datetime
    updated_at: datetime


class GamePreview(BaseModel):
    game_id: str
    pgn: str
    source: Literal["chess.com", "lichess"]
    white: str
    black: str
    result: str
    date: str
    time_control: str = ""
    link: str = ""
    player_color: Literal["white", "black", "unknown"]
    player_result: Literal["win", "loss", "draw", "unknown"]
    player_elo: int | None = None
    opponent: str
    opponent_elo: int | None = None


class FeedbackRequest(BaseModel):
    moment_id: str
    game_id: str
    rating: Literal["helpful", "not_helpful"]
    theme: str
    fen: str
    comment: str = ""


Platform = Literal["chess.com", "lichess", "pgn"]
Difficulty = Literal["beginner", "intermediate", "advanced"]


class PlayerProfile(BaseModel):
    id: str
    platform: Platform
    username: str
    current_rating: int | None = None
    recurring_themes: dict[str, float] = Field(default_factory=dict)
    quiz_accuracy: dict[str, float] = Field(default_factory=dict)
    mastered_positions: int = 0
    due_positions: int = 0


class BoardPanel(BaseModel):
    type: Literal["board"] = "board"
    fen: str
    title: str
    description: str = ""


class QuizPanel(BaseModel):
    type: Literal["quiz"] = "quiz"
    training_session_id: str
    position_id: str
    fen: str
    question: str
    choices: list[str] = Field(default_factory=list)
    theme: str
    difficulty: Difficulty
    hint: str | None = None


class EvaluationPanel(BaseModel):
    type: Literal["evaluation"] = "evaluation"
    position_id: str
    fen: str
    submitted_move: str
    best_move: str
    legal: bool
    correct: bool
    cp_loss: float | None = None
    explanation: str
    next_review_at: datetime


CoachPanel = Annotated[
    BoardPanel | QuizPanel | EvaluationPanel,
    Field(discriminator="type"),
]


class TrainingSessionCreate(BaseModel):
    platform: Platform = "chess.com"
    username: str = "kfctofu"
    theme: str | None = None
    moment_id: str | None = None
    position_count: int = Field(default=5, ge=1, le=10)
    # "mixed": own-game positions first, topped up with library puzzles when short.
    # "puzzles": only library puzzles for the theme (or the player's top weakness).
    mode: Literal["mixed", "puzzles"] = "mixed"


class TrainingPositionView(BaseModel):
    id: str
    order: int
    fen: str
    choices: list[str]
    theme: str
    difficulty: Difficulty
    prompt: str = "What would you play?"
    source: Literal["game", "puzzle"] = "game"
    rating: int | None = None


class TrainingSessionView(BaseModel):
    id: str
    player_id: str
    focus_themes: list[str]
    difficulty: Difficulty
    status: str
    positions: list[TrainingPositionView]


class QuizAttemptCreate(BaseModel):
    position_id: str
    move: str
    hints_used: int = Field(default=0, ge=0, le=5)
    elapsed_ms: int = Field(default=0, ge=0)


class ProgressSummary(BaseModel):
    player: PlayerProfile
    total_games: int
    record: dict[str, int]
    rating_history: list[dict[str, Any]]
    theme_frequency: dict[str, int]
    quiz_accuracy: dict[str, float]
    recent_attempts: int
    transfer_score: float | None = None
