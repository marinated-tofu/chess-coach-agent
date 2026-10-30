import type { Platform } from './types';

export interface PuzzleThemeOption {
  theme: string;
  label: string;
  count: number;
}

export interface PuzzleCatalog {
  total: number;
  min_rating: number | null;
  max_rating: number | null;
  themes: PuzzleThemeOption[];
}

export interface PuzzleSummary {
  id: string;
  fen: string;
  rating: number;
  theme: string;
  theme_label: string;
  status: 'solved' | 'failed' | null;
}

export interface PuzzlePage {
  total: number;
  offset: number;
  limit: number;
  puzzles: PuzzleSummary[];
}

export interface PuzzleFilters {
  theme?: string;
  minRating?: number;
  maxRating?: number;
}

/** Sent once a puzzle is over. A live puzzle's answer stays on the server. */
export interface PuzzleFinish {
  solution: string[];
  solution_san: string[];
  tags: string[];
  url: string;
  recorded: boolean;
  next_review_at: string | null;
  streak: number | null;
}

export interface PuzzleMoveResult {
  status: 'continue' | 'solved' | 'wrong';
  reply: string | null;
  finish: PuzzleFinish | null;
}

export interface PuzzlePlayer {
  username?: string;
  platform?: Platform;
  /** False for retries, which must not count toward mastery. */
  record: boolean;
  elapsed_ms: number;
}

export async function getPuzzleCatalog(): Promise<PuzzleCatalog> {
  const response = await fetch('/api/puzzles/catalog');
  if (!response.ok) throw new Error('Could not load puzzles');
  return response.json();
}

export async function getPuzzles(
  filters: PuzzleFilters,
  offset: number,
  limit: number,
  player: { username?: string; platform?: Platform }
): Promise<PuzzlePage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (filters.theme) params.set('theme', filters.theme);
  if (filters.minRating != null) params.set('min_rating', String(filters.minRating));
  if (filters.maxRating != null) params.set('max_rating', String(filters.maxRating));
  if (player.username && player.platform) {
    params.set('username', player.username);
    params.set('platform', player.platform);
  }
  const response = await fetch(`/api/puzzles?${params}`);
  if (!response.ok) throw new Error('Could not load puzzles');
  return response.json();
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error('Could not check that move');
  return response.json();
}

export function submitPuzzleMove(id: string, line: string[], player: PuzzlePlayer): Promise<PuzzleMoveResult> {
  return post(`/api/puzzles/${encodeURIComponent(id)}/moves`, { ...player, line });
}

export function revealPuzzle(id: string, player: PuzzlePlayer): Promise<PuzzleFinish> {
  return post(`/api/puzzles/${encodeURIComponent(id)}/reveal`, player);
}
