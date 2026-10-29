import type { PieceColor } from '../lib/squareControl';

/**
 * Vertical win-chance bar beside the board. The white fill is scaled with transform so the
 * change animates on the compositor; it never animates height.
 */
export function EvalBar({
  winPct,
  evalText,
  orientation
}: {
  /** White's win chance, 0–100. */
  winPct: number;
  evalText: string;
  orientation: PieceColor;
}) {
  const white = Math.max(0, Math.min(100, winPct));
  const whiteAhead = white >= 50;
  // White sits at the bottom when the board shows White at the bottom.
  const whiteAtBottom = orientation === 'white';
  const labelAtBottom = whiteAhead === whiteAtBottom;
  return (
    <div
      className="eval-bar"
      role="meter"
      aria-label="Evaluation"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(white)}
      aria-valuetext={`${evalText}, White ${Math.round(white)}% win chance`}
    >
      <span
        className="eval-bar-fill"
        style={{ transform: `scaleY(${white / 100})`, transformOrigin: whiteAtBottom ? 'bottom' : 'top' }}
      />
      <span className="eval-bar-mid" aria-hidden="true" />
      <span
        className="eval-bar-text"
        data-side={whiteAhead ? 'white' : 'black'}
        data-pos={labelAtBottom ? 'bottom' : 'top'}
        aria-hidden="true"
      >
        {evalText}
      </span>
    </div>
  );
}
