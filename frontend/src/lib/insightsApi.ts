import type { Platform } from './types';

export type Phase = 'opening' | 'middlegame' | 'endgame';
export type TimeCategory = 'bullet' | 'blitz' | 'rapid' | 'daily';

export interface PhaseRow {
  phase: Phase;
  games: number;
  accuracy: number | null;
  accuracy_moves: number;
  inaccuracies_per_game: number;
  mistakes_per_game: number;
  blunders_per_game: number;
  errors_per_game: number;
  blunder_share_pct: number;
}

export interface TimeControlRow {
  category: TimeCategory;
  games: number;
  score_pct: number;
  accuracy: number | null;
  accuracy_games: number;
  blunders_per_game: number;
}

export interface PressureRow {
  state: 'normal' | 'time_pressure';
  moves: number;
  accuracy: number | null;
  blunders_per_100_moves: number;
}

export interface OpponentRow {
  bucket: string;
  label: string;
  games: number;
  score_pct: number | null;
  accuracy: number | null;
  accuracy_games: number;
}

export interface ColorRow {
  color: 'white' | 'black';
  games: number;
  wins: number;
  draws: number;
  losses: number;
  score_pct: number | null;
  accuracy: number | null;
  accuracy_games: number;
}

export interface ScheduleRow {
  key: string;
  label: string;
  games: number;
  /** Too few games to conclude anything: shown, but muted and never called out. */
  low_sample: boolean;
  score_pct: number | null;
  score_low_pct: number | null;
  score_high_pct: number | null;
  accuracy: number | null;
  accuracy_games: number;
  blunders_per_game: number;
}

export interface ScheduleBreakdown {
  rows: ScheduleRow[];
  best: string | null;
  worst: string | null;
}

export interface LeakAction {
  type: 'practice' | 'openings';
  theme: string | null;
  label: string;
}

export interface Leak {
  id: string;
  title: string;
  detail: string;
  points_per_10_games: number;
  sample_size: number;
  action: LeakAction;
}

export interface InsightsResponse {
  platform: string;
  username: string;
  last: number;
  total_games: number;
  games_considered: number;
  engine_games: number;
  clock_games: number;
  min_sample: number;
  leaks: Leak[];
  phases: { sample_size: number; accuracy_sample_size: number; rows: PhaseRow[] };
  time: {
    sample_size: number;
    by_control: TimeControlRow[];
    by_control_sample_size: number;
    pressure: PressureRow[];
    time_spent: {
      sample_size: number;
      avg_seconds_all: number | null;
      avg_seconds_critical: number | null;
      critical_moves: number;
    };
    lost_on_time: {
      sample_size: number;
      losses: number;
      lost_on_time: number;
      pct_of_losses: number | null;
    };
  };
  opponents: { sample_size: number; rows: OpponentRow[] };
  colors: { sample_size: number; accuracy_sample_size: number; rows: ColorRow[] };
  conversion: {
    sample_size: number;
    winning_threshold_pct: number;
    losing_threshold_pct: number;
    winning_games: number;
    failed_conversions: number;
    failed_conversion_pct: number | null;
    losing_games: number;
    saves: number;
    save_pct: number | null;
  };
  schedule: {
    sample_size: number;
    undated_games: number;
    timezone: string;
    by_time_of_day: ScheduleBreakdown;
    by_day_of_week: ScheduleBreakdown;
  };
}

export async function getInsights(
  username: string,
  platform: Platform | 'pgn',
  last = 500,
  timezone?: string
): Promise<InsightsResponse> {
  const params = new URLSearchParams({ last: String(last) });
  if (timezone) params.set('tz', timezone);
  const response = await fetch(
    `/api/insights/${encodeURIComponent(platform)}/${encodeURIComponent(username)}?${params}`
  );
  if (!response.ok) throw new Error('Could not load insights');
  return response.json();
}
