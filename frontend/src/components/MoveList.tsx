import { useLayoutEffect, useRef } from 'react';
import { formatClock, formatEvalValue, moveLabel, type ReviewMove } from '../lib/reviewApi';
import { LIST_BADGED, MOVE_LABELS, MoveBadge } from './moveLabels';

function moveDescription(move: ReviewMove, isMoment: boolean): string {
  const parts = [`${moveLabel(move)} ${move.san}`];
  if (move.classification) parts.push(MOVE_LABELS[move.classification].name);
  if (move.eval_cp != null || move.eval_mate != null) parts.push(`eval ${formatEvalValue(move.eval_cp, move.eval_mate, move.color)}`);
  const clock = formatClock(move.clock_seconds);
  if (clock) parts.push(`clock ${clock}`);
  if (isMoment) parts.push('critical moment');
  return parts.join(', ');
}

function MoveCell({
  move,
  current,
  isMoment,
  showLabels,
  onSelect
}: {
  move: ReviewMove | undefined;
  current: boolean;
  isMoment: boolean;
  showLabels: boolean;
  onSelect: (ply: number) => void;
}) {
  if (!move) return <span className="mv-cell-empty" />;
  const label = showLabels ? move.classification : null;
  const description = moveDescription(move, isMoment);
  const clock = formatClock(move.clock_seconds);
  return (
    <button
      type="button"
      className="mv-cell"
      data-ply={move.ply}
      data-label={label ?? undefined}
      aria-current={current ? 'step' : undefined}
      aria-label={description}
      title={description}
      onClick={() => onSelect(move.ply)}
    >
      <span className="mv-badge-slot">{label && LIST_BADGED.has(label) ? <MoveBadge label={label} /> : null}</span>
      <span className="mv-san">{move.san}</span>
      {isMoment && <span className="mv-moment" aria-hidden="true" />}
      {clock && <span className="mv-clock" aria-hidden="true">{clock}</span>}
    </button>
  );
}

export function MoveList({
  moves,
  currentPly,
  momentPlies,
  showLabels,
  onSelectPly,
  caption
}: {
  moves: ReviewMove[];
  currentPly: number;
  momentPlies: ReadonlySet<number>;
  showLabels: boolean;
  onSelectPly: (ply: number) => void;
  caption: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the current move visible without scrolling the page itself.
  useLayoutEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const target = container.querySelector<HTMLElement>(`[data-ply="${currentPly}"]`);
    if (!target) {
      if (currentPly === 0) container.scrollTop = 0;
      return;
    }
    // .mv-scroll is position: relative, so offsetTop is measured from the scroll container.
    const top = target.offsetTop;
    const bottom = top + target.offsetHeight;
    if (top < container.scrollTop + 4) container.scrollTop = Math.max(0, top - 36);
    else if (bottom > container.scrollTop + container.clientHeight - 4) container.scrollTop = bottom - container.clientHeight + 36;
  }, [currentPly]);

  const rows = Array.from({ length: Math.ceil(moves.length / 2) }, (_, index) => index);
  return (
    <div className="mv-list">
      <div className="mv-head">
        <strong>Moves</strong>
        <span>{caption}</span>
      </div>
      <div className="mv-scroll" ref={scrollRef} role="list" aria-label="Moves. Use the left and right arrow keys to step through the game.">
        {rows.map((row) => {
          const white = moves[row * 2];
          const black = moves[row * 2 + 1];
          return (
            <div className="mv-row" role="listitem" key={row}>
              <span className="mv-num">{row + 1}.</span>
              <MoveCell
                move={white}
                current={white?.ply === currentPly}
                isMoment={Boolean(white && momentPlies.has(white.ply))}
                showLabels={showLabels}
                onSelect={onSelectPly}
              />
              <MoveCell
                move={black}
                current={black?.ply === currentPly}
                isMoment={Boolean(black && momentPlies.has(black.ply))}
                showLabels={showLabels}
                onSelect={onSelectPly}
              />
            </div>
          );
        })}
        {moves.length === 0 && <p className="mv-empty">No moves in this game.</p>}
      </div>
    </div>
  );
}
