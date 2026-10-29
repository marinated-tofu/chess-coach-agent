import { useEffect, useMemo, useState } from 'react';
import { Link } from '@tanstack/react-router';
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  FlipVertical2,
  Map,
  Microscope,
  RotateCcw,
  Trophy
} from 'lucide-react';
import { ARROW_COLORS, ChessBoard, type BoardArrow, type BoardHighlight } from './ChessBoard';
import { EvalBar } from './EvalBar';
import { EvalGraph } from './EvalGraph';
import { MoveList } from './MoveList';
import { MOVE_LABELS, MoveBadge, RETRY_LABELS } from './moveLabels';
import { RetryPanel, useRetry } from './RetryMistake';
import type { CoachAnalysis } from '../lib/types';
import { boardFenAt, formatClock, formatEvalValue, hasEngineData, moveLabel, winPctAtPly } from '../lib/reviewApi';
import {
  computeSquareControl,
  strongestSquare,
  weakestOccupiedSquare,
  type HeatmapMode,
  type PieceColor
} from '../lib/squareControl';

const HEATMAP_MODES: Array<{ id: HeatmapMode; label: string }> = [
  { id: 'you', label: 'You' },
  { id: 'opponent', label: 'Opponent' },
  { id: 'both', label: 'Both' },
  { id: 'off', label: 'Off' }
];

const FALLBACK_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const NOT_WORTH_AN_ARROW = new Set(['best', 'brilliant', 'great', 'book']);

function uciSquares(uci: string | null | undefined): { from: string; to: string } | null {
  if (!uci || uci.length < 4) return null;
  return { from: uci.slice(0, 2), to: uci.slice(2, 4) };
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"], [role="dialog"]'));
}

export function GamePanel({
  analysis,
  currentPly,
  setCurrentPly,
  coachArrows = [],
  coachHighlights = []
}: {
  analysis: CoachAnalysis | null;
  currentPly: number;
  setCurrentPly: (ply: number) => void;
  coachArrows?: BoardArrow[];
  coachHighlights?: BoardHighlight[];
}) {
  const [heatmapMode, setHeatmapMode] = useState<HeatmapMode>('you');
  const [flipState, setFlipState] = useState({ gameId: '', flipped: false });
  const moves = analysis?.moves || [];
  const moments = analysis?.moments || [];
  const engine = analysis ? hasEngineData(analysis) : false;
  const clampedPly = Math.max(0, Math.min(currentPly, moves.length));
  const { retry, start, stop, again, reveal, submit } = useRetry(moments);

  const reviewFen = boardFenAt(moves, clampedPly) || FALLBACK_FEN;
  const retryFen = retry ? (retry.attempt && retry.status !== 'wrong' ? retry.attempt.fen : retry.fen) : null;
  const fen = retryFen ?? reviewFen;

  const youColor: PieceColor = analysis?.game.player_color === 'black' ? 'black' : 'white';
  const gameId = analysis?.game.game_id || '';
  const flipped = flipState.gameId === gameId && flipState.flipped;
  const orientation: PieceColor = flipped ? (youColor === 'black' ? 'white' : 'black') : youColor;
  const topColor: PieceColor = orientation === 'white' ? 'black' : 'white';
  const control = useMemo(() => computeSquareControl(fen), [fen]);
  const youGrid = youColor === 'black' ? control.black : control.white;
  const opponentGrid = youColor === 'black' ? control.white : control.black;
  const focusGrid = heatmapMode === 'opponent' ? opponentGrid : youGrid;
  const strongest = heatmapMode === 'off' ? null : strongestSquare(focusGrid);
  const weakest = heatmapMode === 'off' ? null : weakestOccupiedSquare(control.board, focusGrid, heatmapMode === 'opponent' ? (youColor === 'white' ? 'black' : 'white') : youColor);
  const momentPlies = useMemo(() => new Set(moments.map((moment) => moment.ply)), [moments]);

  const currentMove = clampedPly > 0 ? moves[clampedPly - 1] : null;
  const currentMoment = currentMove ? moments.find((moment) => moment.ply === currentMove.ply) : undefined;
  const canRetry = Boolean(
    currentMove &&
      (currentMoment || (currentMove.is_player_move && currentMove.classification && RETRY_LABELS.has(currentMove.classification)))
  );

  // Leaving the retried position (moment cards, graph, list) ends the retry.
  useEffect(() => {
    if (retry && retry.ply !== clampedPly) stop();
  }, [clampedPly]);

  useEffect(() => {
    stop();
  }, [gameId]);

  // ←/→/Home/End step through the game unless the user is typing or retrying.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (retry || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (isEditable(event.target)) return;
      let next: number | null = null;
      if (event.key === 'ArrowLeft') next = Math.max(0, clampedPly - 1);
      else if (event.key === 'ArrowRight') next = Math.min(moves.length, clampedPly + 1);
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = moves.length;
      if (next === null) return;
      event.preventDefault();
      if (next !== clampedPly) setCurrentPly(next);
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [retry, clampedPly, moves.length, setCurrentPly]);

  // Board marks: review mode shows the last move and the engine's better move; retry mode shows its own.
  const arrows: BoardArrow[] = [];
  const highlights: BoardHighlight[] = [];
  let lastMove: { from: string; to: string } | undefined;
  if (retry) {
    if (retry.attempt) lastMove = { from: retry.attempt.move.from, to: retry.attempt.move.to };
    if (retry.status === 'wrong' && retry.attempt) {
      arrows.push({ from: retry.attempt.move.from, to: retry.attempt.move.to, color: ARROW_COLORS.mistake });
      lastMove = undefined;
    }
    if ((retry.status === 'wrong' || retry.status === 'revealed') && retry.bestMove) {
      arrows.push({ from: retry.bestMove.from, to: retry.bestMove.to, color: ARROW_COLORS.best });
    }
  } else {
    lastMove = uciSquares(currentMove?.uci) ?? undefined;
    const best = uciSquares(currentMove?.best_uci);
    if (
      currentMove &&
      best &&
      currentMove.best_uci !== currentMove.uci &&
      !(currentMove.classification && NOT_WORTH_AN_ARROW.has(currentMove.classification))
    ) {
      arrows.push({ ...best, color: ARROW_COLORS.best });
    }
    arrows.push(...coachArrows);
    highlights.push(...coachHighlights);
  }

  const evalMove = retry ? null : currentMove;
  const winPct = retry ? winPctAtPly(moves, retry.ply - 1) ?? 50 : winPctAtPly(moves, clampedPly) ?? 50;
  const evalSource = retry ? (retry.ply > 1 ? moves[retry.ply - 2] : null) : evalMove;
  const evalText = evalSource ? formatEvalValue(evalSource.eval_cp, evalSource.eval_mate, evalSource.color) : '0.0';
  const label = currentMove?.classification ? MOVE_LABELS[currentMove.classification] : null;
  const clock = formatClock(currentMove?.clock_seconds);

  return (
    <section className="panel game-panel review-board-panel" aria-label="Game board">
      <div className="panel-title"><Trophy size={18} aria-hidden="true" /> Board</div>
      <PlayerPill
        className="above-board"
        color={topColor}
        name={topColor === 'black' ? analysis?.game.black || 'Black' : analysis?.game.white || 'White'}
      />
      <div className="review-board-row" data-engine={engine || undefined}>
        {engine && <EvalBar winPct={winPct} evalText={evalText} orientation={orientation} />}
        <div className="review-board">
          <ChessBoard
            fen={fen}
            heatmapMode={retry ? 'off' : heatmapMode}
            youColor={youColor}
            orientation={orientation}
            whiteControl={control.white}
            blackControl={control.black}
            arrows={arrows}
            highlights={highlights}
            lastMove={lastMove}
            onMove={retry && retry.status === 'playing' ? submit : undefined}
          />
        </div>
      </div>
      <PlayerPill
        className="below-board"
        color={orientation}
        name={orientation === 'black' ? analysis?.game.black || 'Black' : analysis?.game.white || 'White'}
      />

      {retry ? (
        <RetryPanel retry={retry} onAgain={again} onReveal={reveal} onBack={stop} />
      ) : (
        <>
          <div className="board-controls rv-controls">
            <button type="button" title="Start" aria-label="Start" onClick={() => setCurrentPly(0)} disabled={!moves.length || clampedPly === 0}><ChevronsLeft size={16} /></button>
            <button type="button" title="Previous move" aria-label="Previous move" onClick={() => setCurrentPly(Math.max(0, clampedPly - 1))} disabled={!moves.length || clampedPly === 0}><ChevronLeft size={16} /></button>
            <span className="ply-counter tnum">{moves.length ? `${clampedPly}/${moves.length}` : '0/0'}</span>
            <button type="button" title="Next move" aria-label="Next move" onClick={() => setCurrentPly(Math.min(moves.length, clampedPly + 1))} disabled={!moves.length || clampedPly === moves.length}><ChevronRight size={16} /></button>
            <button type="button" title="End" aria-label="End" onClick={() => setCurrentPly(moves.length)} disabled={!moves.length || clampedPly === moves.length}><ChevronsRight size={16} /></button>
            <button
              type="button"
              title="Flip board"
              aria-label="Flip board"
              aria-pressed={flipped}
              onClick={() => setFlipState({ gameId, flipped: !flipped })}
            >
              <FlipVertical2 size={16} />
            </button>
          </div>

          <div className="rv-current" aria-live="polite">
            {currentMove ? (
              <div className="rv-current-move">
                {engine && currentMove.classification && <MoveBadge label={currentMove.classification} size="md" />}
                <span className="rv-current-text">
                  <strong>{moveLabel(currentMove)} {currentMove.san}</strong>
                  {engine && label && <span className="rv-current-label">{label.name}</span>}
                  {engine && currentMove.best_san && currentMove.best_uci !== currentMove.uci && !NOT_WORTH_AN_ARROW.has(currentMove.classification ?? '') && (
                    <span className="rv-current-best">Best was <strong>{currentMove.best_san}</strong></span>
                  )}
                </span>
                {engine && (
                  <span className="rv-current-meta tnum">
                    {formatEvalValue(currentMove.eval_cp, currentMove.eval_mate, currentMove.color)}
                    {clock ? ` · ${clock}` : ''}
                  </span>
                )}
              </div>
            ) : (
              <div className="rv-current-move"><span>Start position. Press → to step through the game.</span></div>
            )}
            <div className="rv-current-actions">
              {canRetry && currentMove && (
                <button type="button" className="rv-button rv-button-primary" onClick={() => start(currentMove)}>
                  <RotateCcw size={15} aria-hidden="true" /> Retry this move
                </button>
              )}
              <Link className="rv-button" to="/analysis" search={{ fen }}>
                <Microscope size={15} aria-hidden="true" /> Open in analysis board
              </Link>
            </div>
          </div>
        </>
      )}

      {engine && (
        <EvalGraph
          moves={moves}
          currentPly={retry ? retry.ply : clampedPly}
          onSelectPly={(ply) => setCurrentPly(ply)}
          playerColor={analysis?.game.player_color === 'white' || analysis?.game.player_color === 'black' ? analysis.game.player_color : null}
        />
      )}

      <MoveList
        moves={moves}
        currentPly={retry ? retry.ply : clampedPly}
        momentPlies={momentPlies}
        showLabels={engine}
        onSelectPly={(ply) => setCurrentPly(ply)}
        caption={analysis ? `${analysis.game.result} · ${analysis.game.player_result}` : 'Load a game'}
      />

      <div className="heatmap-bar" data-mode={heatmapMode}>
        <div className="heatmap-label">
          <Map size={15} aria-hidden="true" />
          <strong>Square control</strong>
        </div>
        <div className="heatmap-modes" role="group" aria-label="Square control heatmap">
          {HEATMAP_MODES.map((mode) => (
            <button
              key={mode.id}
              type="button"
              aria-pressed={heatmapMode === mode.id}
              onClick={() => setHeatmapMode(mode.id)}
            >
              {mode.label}
            </button>
          ))}
        </div>
        {heatmapMode === 'off' ? (
          <p className="heatmap-legend">Turn this on to see where pieces can overlap on the next move.</p>
        ) : (
          <div className="heatmap-legend">
            <span>
              Strongest <strong>{strongest ? `${strongest.square} (${strongest.count})` : '—'}</strong>
              {' · '}
              Weakest piece <strong>{weakest ? `${weakest.square} (${weakest.count})` : '—'}</strong>
            </span>
            <span className="heat-scale" aria-hidden="true">
              <small>1</small>
              <i data-level="1" />
              <i data-level="2" />
              <i data-level="3" />
              <i data-level="4" />
              <small>4+</small>
            </span>
          </div>
        )}
      </div>
    </section>
  );
}

function PlayerPill({
  color,
  name,
  className
}: {
  color: PieceColor;
  name: string;
  className: string;
}) {
  return (
    <div className={`player-pill ${color} ${className}`}>
      <span aria-hidden="true">{color === 'black' ? '♛' : '♕'}</span>
      <strong>{name}</strong>
      <small>{color === 'black' ? 'Black' : 'White'}</small>
    </div>
  );
}
