import type { Platform } from './types';

export type TimeClass = 'bullet' | 'blitz' | 'rapid' | 'daily';
export const TIME_CLASSES: TimeClass[] = ['bullet', 'blitz', 'rapid', 'daily'];

export interface LibraryGame {
  game_id: string;
  /** ISO date (YYYY-MM-DD), or empty when the PGN has none. */
  date: string;
  white: string;
  black: string;
  opponent: string;
  player_color: string;
  player_result: string;
  result: string;
  player_elo: number | null;
  opponent_elo: number | null;
  time_control: string;
  time_class: TimeClass | null;
  opening: string | null;
  opening_family: string | null;
  eco: string;
  move_count: number;
  moment_count: number;
  blunders: number;
  mistakes: number;
  top_themes: string[];
  accuracy: number | null;
  link: string;
}

export interface FacetCount {
  name: string;
  count: number;
}

export interface LibraryPage {
  platform: string;
  username: string;
  library_total: number;
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  items: LibraryGame[];
  facets: {
    results: Record<string, number>;
    colors: Record<string, number>;
    time_classes: Record<string, number>;
    openings: FacetCount[];
    openings_ready: boolean;
  };
}

export interface LibraryFilters {
  result?: 'win' | 'loss' | 'draw';
  color?: 'white' | 'black';
  time_class?: TimeClass;
  opening?: string;
  q?: string;
  sort?: 'date' | 'blunders';
  /** Games with at least one critical moment of this theme (from the URL, not stored). */
  theme?: string;
}

export const LIBRARY_PAGE_SIZE = 50;

export async function getLibraryPage(
  username: string,
  platform: Platform,
  filters: LibraryFilters,
  offset = 0,
  limit = LIBRARY_PAGE_SIZE
): Promise<LibraryPage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  for (const [key, value] of Object.entries(filters)) {
    if (typeof value === 'string' && value.trim()) params.set(key, value.trim());
  }
  const response = await fetch(`/api/library/${platform}/${encodeURIComponent(username.trim())}?${params}`);
  if (!response.ok) throw new Error('Could not load your games');
  return response.json();
}

export interface RatingPoint {
  date: string;
  rating: number;
}

export interface Blindspot {
  theme: string;
  games: number;
  moments: number;
  pct_of_games: number;
}

export interface LibraryProgress {
  total_games: number;
  rating_series: Partial<Record<TimeClass, RatingPoint[]>>;
  blindspots: Blindspot[];
}

export async function getLibraryProgress(username: string, platform: Platform): Promise<LibraryProgress> {
  const response = await fetch(`/api/library/${platform}/${encodeURIComponent(username.trim())}/progress`);
  if (!response.ok) throw new Error('Could not load progress');
  return response.json();
}

export interface PracticeQueue {
  due_count: number;
  due_themes: FacetCount[];
  next_due_at: string | null;
  candidate_count: number;
  candidate_themes: FacetCount[];
  preview: {
    moment_id: string;
    game_id: string;
    fen: string;
    theme: string;
    judgment: string;
    played_san: string;
    move_number: number;
    opponent: string;
    date: string;
  } | null;
}

export async function getPracticeQueue(username: string, platform: Platform): Promise<PracticeQueue> {
  const response = await fetch(`/api/library/${platform}/${encodeURIComponent(username.trim())}/practice-queue`);
  if (!response.ok) throw new Error('Could not load the practice queue');
  return response.json();
}

export interface TimeTrainerStatus {
  status: 'ready' | 'no_clock_data' | 'no_candidates';
  clock_games: number;
  rushed_count: number;
  burned_count: number;
}

export async function getTimeTrainerStatus(username: string, platform: Platform): Promise<TimeTrainerStatus> {
  const response = await fetch(`/api/library/${platform}/${encodeURIComponent(username.trim())}/time-trainer`);
  if (!response.ok) throw new Error('Could not load your clock data');
  return response.json();
}

const dayFormat = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const monthFormat = new Intl.DateTimeFormat(undefined, { month: 'short', year: 'numeric', timeZone: 'UTC' });

/** "22 Jun 2026" from an ISO date or a PGN date ("2026.06.22"); empty for unknown dates. */
export function formatGameDate(value: string): string {
  const match = /^(\d{4})[.-](\d{2})[.-](\d{2})/.exec(value || '');
  if (!match) return '';
  return dayFormat.format(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

/** "Jun 2026" for chart ticks, from a millisecond timestamp. */
export function formatMonth(timestamp: number): string {
  return monthFormat.format(timestamp);
}

export function themeLabel(theme: string): string {
  const text = theme.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function timeClassLabel(value: string | null | undefined): string {
  if (!value) return '';
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function resultLabel(result: string): string {
  if (result === 'win') return 'Win';
  if (result === 'loss') return 'Loss';
  if (result === 'draw') return 'Draw';
  return 'Unknown';
}

export async function getOpeningPosition(name: string): Promise<{ name: string; eco: string; fen: string; ply: number }> {
  const response = await fetch(`/api/library/opening-position?name=${encodeURIComponent(name)}`);
  if (!response.ok) throw new Error('Could not find that opening on the board');
  return response.json();
}
