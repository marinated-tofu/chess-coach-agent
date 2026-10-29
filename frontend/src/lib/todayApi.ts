import type { Platform } from './types';

export type TimeCategory = 'bullet' | 'blitz' | 'rapid' | 'daily';

export interface TodayFirstMoment {
  id: string;
  ply: number;
  move_number: number;
  fen_before: string;
  played_san: string;
  best_san: string | null;
  theme: string;
  judgment: string;
}

export interface TodayLatestGame {
  game_id: string;
  white: string;
  black: string;
  opponent: string;
  player_color: string;
  player_result: 'win' | 'loss' | 'draw' | 'unknown' | string;
  date: string;
  time_control: string;
  time_category: TimeCategory | null;
  accuracy: number | null;
  blunders: number;
  mistakes: number;
  first_moment: TodayFirstMoment | null;
}

export interface TodaySummary {
  platform: string;
  username: string;
  known: boolean;
  /** Games stored on the server for this player; use this, not the size of a local cache. */
  total_games: number;
  /** Latest rating per time control, from the newest game of each. */
  current_rating: Partial<Record<TimeCategory, number>>;
  last_synced_at: string | null;
  due: {
    count: number;
    themes: { theme: string; count: number }[];
    next_due_at: string | null;
  };
  latest_game: TodayLatestGame | null;
}

export function todayKey(platform: Platform, player: string) {
  return ['today', platform, player.trim().toLowerCase()] as const;
}

export async function getToday(username: string, platform: Platform): Promise<TodaySummary> {
  const response = await fetch(`/api/today/${encodeURIComponent(platform)}/${encodeURIComponent(username.trim())}`);
  if (!response.ok) throw new Error('Could not load your summary');
  return response.json();
}

const PGN_DATE = /^(\d{4})\.(\d{2})\.(\d{2})$/;

/** "2026.06.22" -> "22 Jun 2026"; unknown dates return an empty string. */
export function formatPgnDate(value: string) {
  const match = PGN_DATE.exec(value || '');
  if (!match) return '';
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date);
}
