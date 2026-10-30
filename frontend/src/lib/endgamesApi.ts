/** Endgame trainer (backend: endgames_api.py, judging rules in endgames.py). */
import { isDeniedStatus } from './access';
import type { Platform } from './types';

export type EndgameDrill = {
  id: string;
  kind: 'essential' | 'game';
  title: string;
  category: string;
  fen: string;
  player_color: 'white' | 'black';
  goal: 'win' | 'draw';
  /** "mate" drills only pass on checkmate; "engine" drills also pass on an engine-judged conversion. */
  finish: 'engine' | 'mate';
  move_limit: number;
  summary: string;
  hint: string;
  game_id: string | null;
  opponent: string | null;
  played_at: string | null;
  played_san: string | null;
  move_number: number | null;
  attempts: number;
  passes: number;
  last_passed: boolean | null;
  due_at: string | null;
  due: boolean;
};

export type EndgameTurnRequest = {
  drill_id: string;
  moves_uci: string[];
  strikes: number;
  resign?: boolean;
  hints_used: number;
  elapsed_ms: number;
  platform?: Platform;
  username?: string;
};

export type EndgameTurn = {
  status: 'playing' | 'passed' | 'failed';
  result: string;
  reason: string;
  fen: string;
  reply_san: string | null;
  reply_uci: string | null;
  strikes: number;
  recorded: boolean;
  next_review_at: string | null;
  interval_days: number | null;
};

export function endgamesKey(platform: Platform, player: string) {
  return ['endgames', platform, player.trim().toLowerCase()] as const;
}

async function readError(response: Response, fallback: string): Promise<Error> {
  const detail = await response.json().catch(() => null);
  return new Error(typeof detail?.detail === 'string' ? detail.detail : `${fallback} (${response.status})`);
}

export type EndgameDrills = {
  drills: EndgameDrill[];
  /** The current player is private: these are the essentials only, and results are not saved. */
  private: boolean;
};

export async function getEndgameDrills(username: string, platform: Platform): Promise<EndgameDrills> {
  const params = username.trim() ? `?${new URLSearchParams({ platform, username: username.trim() })}` : '';
  let response = await fetch(`/api/endgames${params}`);
  const denied = isDeniedStatus(response.status);
  // The essential positions are public; only this player's drills and results are not.
  if (denied) response = await fetch('/api/endgames');
  if (!response.ok) throw await readError(response, 'Could not load endgames');
  return { ...((await response.json()) as { drills: EndgameDrill[] }), private: denied };
}

export async function takeEndgameTurn(body: EndgameTurnRequest): Promise<EndgameTurn> {
  const response = await fetch('/api/endgames/turn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw await readError(response, 'Stockfish could not reply');
  return (await response.json()) as EndgameTurn;
}
