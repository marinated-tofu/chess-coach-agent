import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Eye, Loader2, RotateCcw } from 'lucide-react';
import { analyzePosition, type EngineAnalysis } from '../lib/engineApi';
import { parseMove, playMove, type BoardMove } from '../lib/chessRules';
import { moveLabel, type ReviewMove } from '../lib/reviewApi';
import type { CriticalMoment } from '../lib/types';

export type RetryStatus = 'playing' | 'checking' | 'correct' | 'fine' | 'wrong' | 'revealed' | 'unknown';

export type RetryState = {
  ply: number;
  move: ReviewMove;
  fen: string;
  bestSan: string | null;
  bestMove: BoardMove | null;
  status: RetryStatus;
  attempt: { move: BoardMove; fen: string } | null;
  engineBestSan: string | null;
};

/** Moves within half a pawn of the engine's choice count as fine. */
const FINE_MARGIN_CP = 50;

function normalizeSan(san: string | null | undefined): string {
  return (san ?? '').replace(/[+#!?]/g, '').trim();
}

function scoreFor(analysis: EngineAnalysis, mover: 'white' | 'black'): number | null {
  const sign = mover === 'white' ? 1 : -1;
  if (analysis.result === 'checkmate') {
    // The side to move is mated.
    return analysis.side_to_move === mover ? -10_000 : 10_000;
  }
  if (analysis.result) return 0;
  const line = analysis.lines[0];
  if (!line) return null;
  if (line.mate != null) return sign * (line.mate > 0 ? 10_000 - line.mate : -10_000 - line.mate);
  return sign * (line.eval_cp ?? 0);
}

export function useRetry(moments: CriticalMoment[]) {
  const [retry, setRetry] = useState<RetryState | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const start = useCallback(
    (move: ReviewMove) => {
      abortRef.current?.abort();
      const moment = moments.find((item) => item.ply === move.ply);
      const fen = move.fen_before;
      const bestSan = move.best_san || moment?.best_san || null;
      const bestMove = (move.best_uci && parseMove(fen, move.best_uci)) || (bestSan ? parseMove(fen, bestSan) : null);
      setRetry({ ply: move.ply, move, fen, bestSan: bestMove?.san ?? bestSan, bestMove, status: 'playing', attempt: null, engineBestSan: null });
    },
    [moments]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setRetry(null);
  }, []);

  const again = useCallback(() => {
    abortRef.current?.abort();
    setRetry((state) => (state ? { ...state, status: 'playing', attempt: null } : state));
  }, []);

  const reveal = useCallback(() => {
    abortRef.current?.abort();
    setRetry((state) => (state ? { ...state, status: 'revealed', attempt: null } : state));
  }, []);

  const submit = useCallback(
    (played: BoardMove): boolean => {
      if (!retry || retry.status !== 'playing') return false;
      const result = playMove(retry.fen, { from: played.from, to: played.to, promotion: played.promotion });
      if (!result) return false;
      const fenAfter = result.fen;
      const attempt = { move: played, fen: fenAfter };
      const isBest =
        (retry.bestMove && retry.bestMove.uci === played.uci) ||
        (retry.bestSan && normalizeSan(retry.bestSan) === normalizeSan(played.san));
      if (isBest) {
        setRetry({ ...retry, status: 'correct', attempt });
        return true;
      }
      setRetry({ ...retry, status: 'checking', attempt });
      const controller = new AbortController();
      abortRef.current = controller;
      const mover = retry.move.color;
      Promise.all([
        analyzePosition(retry.fen, { multipv: 1, signal: controller.signal }),
        analyzePosition(fenAfter, { multipv: 1, signal: controller.signal })
      ])
        .then(([before, after]) => {
          if (controller.signal.aborted) return;
          const top = before.lines[0];
          const engineBest = top ? parseMove(retry.fen, top.move_uci) : null;
          const bestScore = scoreFor(before, mover);
          const userScore = scoreFor(after, mover);
          let status: RetryStatus = 'wrong';
          if (engineBest && engineBest.uci === played.uci) status = 'correct';
          else if (bestScore != null && userScore != null && bestScore - userScore <= FINE_MARGIN_CP) status = 'fine';
          setRetry((state) =>
            state && state.ply === retry.ply
              ? {
                  ...state,
                  status,
                  engineBestSan: engineBest?.san ?? null,
                  // Prefer the stored best move; fall back to the live engine's choice.
                  bestMove: state.bestMove ?? engineBest,
                  bestSan: state.bestSan ?? engineBest?.san ?? null
                }
              : state
          );
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setRetry((state) =>
            state && state.ply === retry.ply ? { ...state, status: state.bestSan ? 'wrong' : 'unknown' } : state
          );
        });
      return true;
    },
    [retry]
  );

  return { retry, start, stop, again, reveal, submit };
}

export function RetryPanel({
  retry,
  onAgain,
  onReveal,
  onBack
}: {
  retry: RetryState;
  onAgain: () => void;
  onReveal: () => void;
  onBack: () => void;
}) {
  const side = retry.move.color === 'white' ? 'White' : 'Black';
  const best = retry.bestSan;
  let message: string;
  switch (retry.status) {
    case 'playing':
      message = `Find a better move for ${side} than ${retry.move.san}.`;
      break;
    case 'checking':
      message = `Checking ${retry.attempt?.move.san ?? 'your move'}…`;
      break;
    case 'correct':
      message = `Correct. ${retry.attempt?.move.san} is the engine's move.`;
      break;
    case 'fine':
      message = `Good — also fine. ${retry.attempt?.move.san} keeps the position within half a pawn${best ? `; the engine's first choice is ${best}` : ''}.`;
      break;
    case 'wrong':
      message = best ? `Not quite — the engine prefers ${best}.` : 'Not quite.';
      break;
    case 'revealed':
      message = best ? `The engine plays ${best} here.` : 'No stored best move for this position.';
      break;
    default:
      message = 'The engine is unavailable, so this move could not be checked.';
  }
  const done = retry.status === 'correct' || retry.status === 'fine';
  return (
    <div className="retry-panel" data-status={retry.status} role="region" aria-label="Retry this move">
      <div className="retry-head">
        <strong>Retry {moveLabel(retry.move)} {retry.move.san}</strong>
        <span>{side} to move</span>
      </div>
      <p className="retry-message" role="status" aria-live="polite">
        {retry.status === 'checking' && <Loader2 className="spin" size={14} aria-hidden="true" />}
        {message}
      </p>
      <div className="retry-actions">
        {(retry.status === 'wrong' || retry.status === 'revealed' || retry.status === 'unknown' || done) && (
          <button type="button" className="rv-button" onClick={onAgain}>
            <RotateCcw size={15} aria-hidden="true" /> Try again
          </button>
        )}
        {(retry.status === 'playing' || retry.status === 'unknown') && best && (
          <button type="button" className="rv-button" onClick={onReveal}>
            <Eye size={15} aria-hidden="true" /> Show answer
          </button>
        )}
        <button type="button" className="rv-button" onClick={onBack}>
          <ArrowLeft size={15} aria-hidden="true" /> Back to game
        </button>
      </div>
    </div>
  );
}
