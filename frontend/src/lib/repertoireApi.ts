import { throwIfDenied } from './access';
import type { Platform } from './types';

export type RepertoireColor = 'white' | 'black';

export interface RepertoireNode {
  id: string;
  san: string;
  uci: string;
  ply: number;
  parent_fen: string;
  fen_after: string;
  comment: string;
  mistake_count: number;
  is_player_move: boolean;
  due: boolean;
  streak: number | null;
  /** Position already shown elsewhere in the tree; its children are listed there. */
  transposition: boolean;
  children: RepertoireNode[];
}

export interface RepertoireSummary {
  id: string;
  color: RepertoireColor;
  name: string;
  created_at: string;
  due_count: number;
}

export interface Repertoire extends RepertoireSummary {
  tree: RepertoireNode[];
}

export interface SeedFlag {
  move_id: string;
  fen: string;
  played_san: string;
  best_san: string;
  times: number;
}

export interface SeedResult extends Repertoire {
  games_used: number;
  added: number;
  flagged: SeedFlag[];
}

export interface DrillItem {
  move_id: string;
  fen: string;
  line: string[];
  line_uci: string[];
  last_move: string | null;
  due_at: string;
  streak: number;
}

export interface DrillResponse {
  due_count: number;
  items: DrillItem[];
}

export interface DrillResult {
  correct: boolean;
  played_san: string | null;
  expected_san: string;
  expected_uci: string;
  comment: string;
  next_due_at: string;
  interval_days: number;
  streak: number;
  due_count: number;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined
  });
  await throwIfDenied(response);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // keep the status message
    }
    throw new Error(detail);
  }
  return response.json();
}

export function listRepertoires(username: string, platform: Platform | 'pgn') {
  const query = new URLSearchParams({ platform, username });
  return request<RepertoireSummary[]>(`/api/repertoire?${query}`);
}

export function createRepertoire(username: string, platform: Platform | 'pgn', color: RepertoireColor) {
  return request<Repertoire>('/api/repertoire', {
    method: 'POST',
    body: JSON.stringify({ platform, username, color })
  });
}

export function getRepertoire(id: string) {
  return request<Repertoire>(`/api/repertoire/${id}`);
}

export function seedRepertoire(id: string) {
  return request<SeedResult>(`/api/repertoire/${id}/seed`, { method: 'POST' });
}

export function addRepertoireMove(id: string, parentFen: string, move: string) {
  return request<Repertoire & { move_id: string; san: string; created: boolean }>(
    `/api/repertoire/${id}/moves`,
    { method: 'POST', body: JSON.stringify({ parent_fen: parentFen, move }) }
  );
}

export function removeRepertoireMove(id: string, moveId: string) {
  return request<Repertoire & { removed: number }>(`/api/repertoire/${id}/moves/${moveId}`, {
    method: 'DELETE'
  });
}

export function getDrill(id: string, limit = 10, includeAll = false) {
  const query = new URLSearchParams({ limit: String(limit), include_all: String(includeAll) });
  return request<DrillResponse>(`/api/repertoire/${id}/drill?${query}`);
}

export function answerDrill(id: string, moveId: string, move: string) {
  return request<DrillResult>(`/api/repertoire/${id}/drill/answer`, {
    method: 'POST',
    body: JSON.stringify({ move_id: moveId, move })
  });
}
