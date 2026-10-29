import type { Platform } from './types';

export type ExplorerColor = 'white' | 'black' | 'both';
export type LichessDb = 'masters' | 'lichess';

export interface ExplorerOpening {
  eco: string;
  name: string;
}

export interface PlayerExplorerMove {
  san: string;
  uci: string;
  games: number;
  wins: number;
  draws: number;
  losses: number;
  score_pct: number | null;
  avg_accuracy: number | null;
  /** Times the player's own move here was an inaccuracy, mistake or blunder. */
  mistakes: number;
  /** Times the player (not the opponent) made this move here. */
  player_moves: number;
  frequent_mistake: boolean;
  last_played: string;
}

export interface PlayerExplorerMistake {
  san: string;
  uci: string;
  mistakes: number;
  player_moves: number;
  label: 'inaccuracy' | 'mistake' | 'blunder';
  best_san: string | null;
  frequent: boolean;
}

export interface PlayerExplorerResponse {
  fen: string;
  color: ExplorerColor;
  total: number;
  opening: ExplorerOpening | null;
  moves: PlayerExplorerMove[];
  common_mistake: PlayerExplorerMistake | null;
}

export interface LichessExplorerMove {
  san: string;
  uci: string;
  games: number;
  white: number;
  draws: number;
  black: number;
  avg_rating: number | null;
  white_pct: number;
  draw_pct: number;
  black_pct: number;
  opening: ExplorerOpening | null;
}

export interface LichessExplorerGame {
  id: string;
  uci: string | null;
  white: string;
  white_rating: number | null;
  black: string;
  black_rating: number | null;
  winner: 'white' | 'black' | null;
  year: number | null;
  month: string | null;
  url: string | null;
}

export interface LichessExplorerResponse {
  db: LichessDb;
  total: number;
  white: number;
  draws: number;
  black: number;
  opening: ExplorerOpening | null;
  moves: LichessExplorerMove[];
  top_games: LichessExplorerGame[];
  recent_games: LichessExplorerGame[];
}

export class ExplorerError extends Error {}

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  if (response.ok) return response.json();
  let message = fallback;
  try {
    const body = await response.json();
    if (typeof body?.error === 'string') message = body.error;
  } catch {
    // keep the fallback message
  }
  throw new ExplorerError(message);
}

export async function getPlayerExplorer(
  params: { platform: Platform | 'pgn'; username: string; fen: string; color: ExplorerColor },
  signal?: AbortSignal
): Promise<PlayerExplorerResponse> {
  const query = new URLSearchParams(params);
  const response = await fetch(`/api/explorer/player?${query}`, { signal });
  return readJson(response, 'Could not load your games for this position.');
}

export async function getLichessExplorer(
  params: { fen: string; db: LichessDb; ratings?: string; speeds?: string },
  signal?: AbortSignal
): Promise<LichessExplorerResponse> {
  const query = new URLSearchParams({ fen: params.fen, db: params.db });
  if (params.ratings) query.set('ratings', params.ratings);
  if (params.speeds) query.set('speeds', params.speeds);
  const response = await fetch(`/api/explorer/lichess?${query}`, { signal });
  return readJson(response, 'The Lichess explorer is not available right now.');
}
