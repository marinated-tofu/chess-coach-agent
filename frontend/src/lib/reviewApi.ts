import { useQuery } from '@tanstack/react-query';
import { getGameOpening } from './openingsApi';
import type { CoachAnalysis, MoveClassification, Platform } from './types';

export type ReviewMove = CoachAnalysis['moves'][number];

/** Opening name for one stored game. Null while loading, when unmatched, or on error. */
export function useGameOpening(username: string, platform: Platform | 'pgn', gameId: string) {
  return useQuery({
    queryKey: ['game-opening', platform, username.trim().toLowerCase(), gameId],
    queryFn: () => getGameOpening(username.trim(), platform, gameId),
    enabled: username.trim().length > 0 && gameId.length > 0,
    staleTime: 5 * 60_000,
    retry: false
  });
}

/** True when the game was analyzed with per-move engine data (win chance, labels). */
export function hasEngineData(analysis: CoachAnalysis): boolean {
  return analysis.moves.some((move) => move.win_pct != null);
}

/** "12." for White's 12th move, "12..." for Black's. */
export function moveLabel(move: Pick<ReviewMove, 'move_number' | 'color'>): string {
  return move.color === 'white' ? `${move.move_number}.` : `${move.move_number}...`;
}

/** "+1.3", "−0.4", "M3", "−M3"; a mate of 0 means the game ended in checkmate. */
export function formatEvalValue(evalCp: number | null | undefined, evalMate: number | null | undefined, mover?: 'white' | 'black'): string {
  if (evalMate === 0) return mover === 'black' ? '0-1' : '1-0';
  if (evalMate != null) return evalMate < 0 ? `−M${Math.abs(evalMate)}` : `M${evalMate}`;
  if (evalCp == null) return '–';
  const pawns = evalCp / 100;
  if (Math.abs(pawns) < 0.05) return '0.0';
  return pawns > 0 ? `+${pawns.toFixed(1)}` : `−${Math.abs(pawns).toFixed(1)}`;
}

export function formatClock(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  const total = Math.max(0, seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const secText = total < 10 ? secs.toFixed(1).padStart(4, '0') : String(Math.floor(secs)).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secText}` : `${minutes}:${secText}`;
}

/** White win chance (0–100) shown at a ply; ply 0 is the start position. */
export function winPctAtPly(moves: ReviewMove[], ply: number): number | null {
  if (ply <= 0) return 50;
  const move = moves[ply - 1];
  if (!move) return null;
  if (move.win_pct != null) return move.win_pct;
  if (move.eval_mate === 0) return move.color === 'white' ? 100 : 0;
  return null;
}

export function countClassifications(analysis: CoachAnalysis): Record<'white' | 'black', Partial<Record<MoveClassification, number>>> {
  const fromApi = analysis.classification_counts;
  if (fromApi && (fromApi.white || fromApi.black)) {
    return { white: fromApi.white ?? {}, black: fromApi.black ?? {} };
  }
  const counts: Record<'white' | 'black', Partial<Record<MoveClassification, number>>> = { white: {}, black: {} };
  for (const move of analysis.moves) {
    if (!move.classification) continue;
    const side = counts[move.color];
    side[move.classification] = (side[move.classification] ?? 0) + 1;
  }
  return counts;
}

export function boardFenAt(moves: ReviewMove[], ply: number): string | undefined {
  const clamped = Math.max(0, Math.min(ply, moves.length));
  return clamped === 0 ? moves[0]?.fen_before : moves[clamped - 1]?.fen_after;
}
