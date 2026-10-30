export type MoveClassification =
  | 'brilliant'
  | 'great'
  | 'best'
  | 'excellent'
  | 'good'
  | 'book'
  | 'inaccuracy'
  | 'mistake'
  | 'miss'
  | 'blunder';

type MoveRecord = {
  ply: number;
  move_number: number;
  color: 'white' | 'black';
  san: string;
  uci: string;
  fen_before: string;
  fen_after: string;
  is_player_move: boolean;
  // Engine fields (analysis v2; absent/null on games analyzed earlier). White's POV, after the move.
  eval_cp?: number | null;
  eval_mate?: number | null;
  win_pct?: number | null;
  win_pct_loss?: number | null;
  accuracy?: number | null;
  classification?: MoveClassification | null;
  best_uci?: string | null;
  best_san?: string | null;
  clock_seconds?: number | null;
  time_spent_seconds?: number | null;
  time_pressure?: boolean;
};

export type EvalPoint = {
  ply: number;
  eval_cp: number | null;
  eval_mate: number | null;
  win_pct: number;
};

export type CriticalMoment = {
  id: string;
  game_id: string;
  ply: number;
  move_number: number;
  phase: 'opening' | 'middlegame' | 'endgame';
  theme: string;
  played_san: string;
  best_san: string | null;
  fen_before: string;
  fen_after: string;
  fen_best: string | null;
  eval_before: number | null;
  eval_after: number | null;
  eval_swing: number | null;
  severity: number;
  judgment: 'inaccuracy' | 'mistake' | 'blunder';
  win_probability_loss: number;
  move_accuracy: number;
  trainable: boolean;
  summary: string;
  what_happened: string;
  better_plan: string;
  principle: string;
  drill_prompt: string;
};

export type CoachAnalysis = {
  game: {
    game_id: string;
    source: string;
    white: string;
    black: string;
    result: string;
    date: string;
    link: string;
    eco: string;
    time_control: string;
    player_color: string;
    player_result: string;
    player_elo: number | null;
  };
  moves: MoveRecord[];
  moments: CriticalMoment[];
  summary: string;
  training_plan: string[];
  retrieval_notes: string[];
  accuracy?: { white: number | null; black: number | null } | null;
  eval_series?: EvalPoint[];
  classification_counts?: Record<string, Partial<Record<MoveClassification, number>>>;
};

export type AnalyzeResponse = {
  analyses: CoachAnalysis[];
  generated_at: string;
};

export type Platform = 'chess.com' | 'lichess';

type Difficulty = 'beginner' | 'intermediate' | 'advanced';

type PlayerProfile = {
  id: string;
  platform: Platform | 'pgn';
  username: string;
  current_rating: number | null;
  recurring_themes: Record<string, number>;
  quiz_accuracy: Record<string, number>;
  mastered_positions: number;
  due_positions: number;
};

export type EvaluationPanel = {
  type: 'evaluation';
  position_id: string;
  fen: string;
  submitted_move: string;
  best_move: string;
  legal: boolean;
  correct: boolean;
  cp_loss: number | null;
  explanation: string;
  next_review_at: string;
};

type TrainingPosition = {
  id: string;
  order: number;
  fen: string;
  choices: string[];
  theme: string;
  difficulty: Difficulty;
  prompt: string;
  source?: 'game' | 'puzzle';
  rating?: number | null;
  hint: string | null;
};

export type TrainingSession = {
  id: string;
  player_id: string;
  focus_themes: string[];
  difficulty: Difficulty;
  status: string;
  positions: TrainingPosition[];
};

export type ProgressSummary = {
  player: PlayerProfile;
  total_games: number;
  record: Record<string, number>;
  rating_history: Array<{ date: string; rating: number; result: string }>;
  theme_frequency: Record<string, number>;
  quiz_accuracy: Record<string, number>;
  recent_attempts: number;
  transfer_score: number | null;
  /** Practice figures were left out: another account owns this player. */
  private?: boolean;
};

export type SyncJob = {
  id: string;
  platform: Platform;
  username: string;
  status: 'queued' | 'fetching' | 'analyzing' | 'complete' | 'failed';
  total_games: number;
  analyzed_games: number;
  skipped_games: number;
  error: string;
  created_at: string;
  updated_at: string;
};

export type MonitoringSummary = {
  total_events: number;
  event_counts: Record<string, number>;
  feedback_count: number;
  helpful_rate: number | null;
  feedback_themes: Record<string, number>;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  average_chat_latency_ms: number | null;
  tool_usage: Record<string, number>;
  stream_failures: number;
  training_sessions: number;
  quiz_attempts: number;
  quiz_accuracy: number | null;
  hint_use_rate: number | null;
  retrieval_methods: Record<string, number>;
  memory_retrievals: number;
  practice_agent_runs: number;
  practice_agent_fallback_rate: number | null;
  recent_events: Array<Record<string, unknown>>;
};

export interface CoachingOutput {
  answer: string;
  evidence: string[];
  recommended_move: string | null;
  principle: string;
  drill: string;
  confidence: number;
}

export interface CoachAskResponse {
  answer: string;
  coaching: CoachingOutput;
  used_llm: boolean;
  tools_used: string[];
  retrieved_notes: string[];
  message_history: unknown[];
}
