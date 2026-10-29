import type { Platform } from './types';

export type OpeningColor = 'white' | 'black';
export type OpeningGrouping = 'family' | 'variation';

export interface OpeningStat {
  eco: string;
  name: string;
  color: OpeningColor;
  games: number;
  wins: number;
  draws: number;
  losses: number;
  score_pct: number;
  avg_accuracy: number | null;
  top_theme: string | null;
  top_theme_count: number;
  common_first_mistake_ply: number | null;
  common_first_mistake_games: number;
  common_book_exit_ply: number | null;
  top_variation: string | null;
  last_played: string;
}

export interface OpeningsResponse {
  platform: string;
  username: string;
  group: OpeningGrouping;
  total_games: number;
  classified_games: number;
  white: OpeningStat[];
  black: OpeningStat[];
}

export interface GameOpening {
  game_id: string;
  eco: string;
  name: string;
  family: string;
  book_ply: number;
}

export async function getOpenings(
  username: string,
  platform: Platform | 'pgn',
  group: OpeningGrouping = 'family'
): Promise<OpeningsResponse> {
  const response = await fetch(
    `/api/openings/${encodeURIComponent(platform)}/${encodeURIComponent(username)}?group=${group}`
  );
  if (!response.ok) throw new Error('Could not load opening stats');
  return response.json();
}

/** Opening label for one stored game, or null when no named line matches. */
export async function getGameOpening(
  username: string,
  platform: Platform | 'pgn',
  gameId: string
): Promise<GameOpening | null> {
  const response = await fetch(
    `/api/openings/${encodeURIComponent(platform)}/${encodeURIComponent(username)}/games/${encodeURIComponent(gameId)}`
  );
  if (response.status === 404) return null;
  if (!response.ok) throw new Error('Could not load the opening for this game');
  return response.json();
}

/** Ply 9 is White's 5th move ("5."), ply 10 is Black's ("5..."). */
export function plyToMoveLabel(ply: number): string {
  const move = Math.ceil(ply / 2);
  return ply % 2 === 1 ? `${move}.` : `${move}...`;
}
