import { useId, useMemo, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import { Chessboard, defaultPieces, type Arrow, type PieceHandlerArgs, type PieceDropHandlerArgs, type SquareHandlerArgs } from 'react-chessboard';
import { heatAlpha, type HeatmapMode, type PieceColor } from '../lib/squareControl';
import {
  checkedKingSquare,
  isPromotionMove,
  legalTargets,
  pieceColorAt,
  playMove,
  sideToMove,
  type BoardMove,
  type PromotionPiece
} from '../lib/chessRules';
import './ChessBoard.css';

export type { BoardMove } from '../lib/chessRules';
export type BoardArrow = { from: string; to: string; color?: string };
export type BoardHighlight = { square: string; color?: string };

const YOU_RGB = '25, 135, 84';
const OPPONENT_RGB = '180, 38, 46';
const EVEN_RGB = '179, 91, 18';

export const ARROW_COLORS = {
  best: 'rgba(21, 120, 75, 0.85)',
  mistake: 'rgba(180, 38, 46, 0.8)',
  idea: 'rgba(32, 98, 196, 0.8)'
} as const;
const DEFAULT_HIGHLIGHT = 'rgba(32, 98, 196, 0.38)';
const FILES = 'abcdefgh';
const PROMOTION_PIECES: Array<{ piece: PromotionPiece; label: string }> = [
  { piece: 'q', label: 'queen' },
  { piece: 'r', label: 'rook' },
  { piece: 'b', label: 'bishop' },
  { piece: 'n', label: 'knight' }
];

function overlayColor(youCount: number, opponentCount: number, mode: HeatmapMode): string | undefined {
  if (mode === 'off') return undefined;
  if (mode === 'you' && youCount > 0) return `rgba(${YOU_RGB}, ${heatAlpha(youCount)})`;
  if (mode === 'opponent' && opponentCount > 0) return `rgba(${OPPONENT_RGB}, ${heatAlpha(opponentCount)})`;
  if (mode === 'both') {
    if (youCount === 0 && opponentCount === 0) return undefined;
    if (youCount > opponentCount) return `rgba(${YOU_RGB}, ${heatAlpha(youCount)})`;
    if (opponentCount > youCount) return `rgba(${OPPONENT_RGB}, ${heatAlpha(opponentCount)})`;
    return `rgba(${EVEN_RGB}, ${heatAlpha(youCount)})`;
  }
  return undefined;
}

function gridIndex(square: string): [number, number] {
  return [FILES.indexOf(square[0]), 8 - Number(square[1])];
}

const reducedMotionQuery = '(prefers-reduced-motion: reduce)';
function subscribeReducedMotion(callback: () => void) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => undefined;
  const media = window.matchMedia(reducedMotionQuery);
  media.addEventListener('change', callback);
  return () => media.removeEventListener('change', callback);
}
function getReducedMotion() {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.(reducedMotionQuery).matches);
}

const notationBase: CSSProperties = { zIndex: 3, fontSize: 11, fontWeight: 700, userSelect: 'none' };

export function ChessBoard({
  fen,
  heatmapMode = 'off',
  youColor = 'white',
  orientation = 'white',
  whiteControl,
  blackControl,
  onMove,
  arrows,
  highlights,
  lastMove
}: {
  fen: string;
  heatmapMode?: HeatmapMode;
  youColor?: PieceColor;
  orientation?: PieceColor;
  whiteControl?: number[][];
  blackControl?: number[][];
  /** Called with a legal move. Return false to reject it. Without this prop the board is view-only. */
  onMove?: (move: BoardMove) => boolean | void;
  arrows?: BoardArrow[];
  highlights?: BoardHighlight[];
  lastMove?: { from: string; to: string };
}) {
  const boardId = `cb${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const reduceMotion = useSyncExternalStore(subscribeReducedMotion, getReducedMotion, () => false);
  const [selection, setSelection] = useState<{ fen: string; square: string } | null>(null);
  const [promotion, setPromotion] = useState<{ fen: string; from: string; to: string } | null>(null);

  const interactive = Boolean(onMove);
  const turn = sideToMove(fen);
  const selected = interactive && selection?.fen === fen ? selection.square : null;
  const pendingPromotion = interactive && promotion?.fen === fen ? promotion : null;
  const targets = useMemo(() => (selected ? new Set(legalTargets(fen, selected)) : new Set<string>()), [fen, selected]);
  const checkSquare = useMemo(() => checkedKingSquare(fen), [fen]);

  const youGrid = youColor === 'black' ? blackControl : whiteControl;
  const opponentGrid = youColor === 'black' ? whiteControl : blackControl;
  const showHeat = heatmapMode !== 'off' && Boolean(youGrid && opponentGrid);

  const highlightMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of highlights ?? []) map.set(item.square, item.color ?? DEFAULT_HIGHLIGHT);
    return map;
  }, [highlights]);

  const boardArrows: Arrow[] = useMemo(
    () =>
      (arrows ?? [])
        .filter((arrow) => arrow.from !== arrow.to)
        .map((arrow) => ({ startSquare: arrow.from, endSquare: arrow.to, color: arrow.color ?? ARROW_COLORS.best })),
    [arrows]
  );

  function commit(from: string, to: string, promotionPiece?: PromotionPiece): boolean {
    if (!onMove) return false;
    const result = playMove(fen, { from, to, promotion: promotionPiece });
    setSelection(null);
    if (!result) return false;
    return onMove(result.move) !== false;
  }

  function attempt(from: string, to: string): boolean {
    if (!onMove || from === to) return false;
    if (isPromotionMove(fen, from, to)) {
      setSelection(null);
      setPromotion({ fen, from, to });
      return false;
    }
    return commit(from, to);
  }

  function ownsTurn(square: string) {
    return pieceColorAt(fen, square) === turn;
  }

  function handleSquareClick({ square }: SquareHandlerArgs) {
    if (!interactive) return;
    if (selected && targets.has(square)) {
      attempt(selected, square);
      return;
    }
    if (square !== selected && ownsTurn(square)) setSelection({ fen, square });
    else setSelection(null);
  }

  function handleDrop({ sourceSquare, targetSquare }: PieceDropHandlerArgs): boolean {
    if (!targetSquare) {
      setSelection(null);
      return false;
    }
    return attempt(sourceSquare, targetSquare);
  }

  function canDrag({ piece, isSparePiece }: PieceHandlerArgs) {
    return interactive && !isSparePiece && piece.pieceType[0] === (turn === 'white' ? 'w' : 'b');
  }

  function renderSquare({ square, children }: SquareHandlerArgs & { children?: ReactNode }) {
    const [fileIndex, rankIndex] = gridIndex(square);
    const youCount = youGrid?.[rankIndex]?.[fileIndex] ?? 0;
    const opponentCount = opponentGrid?.[rankIndex]?.[fileIndex] ?? 0;
    const heat = showHeat ? overlayColor(youCount, opponentCount, heatmapMode) : undefined;
    const isLast = lastMove && (lastMove.from === square || lastMove.to === square);
    const highlight = highlightMap.get(square);
    const isTarget = targets.has(square);
    const occupied = isTarget && pieceColorAt(fen, square) !== null;
    return (
      <div
        className="cb-square"
        data-square={square}
        title={showHeat ? `${square}: you ${youCount}, opponent ${opponentCount}` : undefined}
      >
        {isLast ? <span className="cb-layer cb-last" /> : null}
        {highlight ? <span className="cb-layer" style={{ backgroundColor: highlight }} /> : null}
        {selected === square ? <span className="cb-layer cb-selected" /> : null}
        {checkSquare === square ? <span className="cb-layer cb-check" /> : null}
        {heat ? <span className="cb-layer" style={{ backgroundColor: heat }} /> : null}
        {children}
        {isTarget ? <span className={occupied ? 'cb-target cb-capture' : 'cb-target cb-dot'} /> : null}
      </div>
    );
  }

  function cancelPromotion() {
    setPromotion(null);
  }

  function onPromotionKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      cancelPromotion();
    }
  }

  const label = showHeat
    ? `Chess board with ${heatmapMode} square control heatmap`
    : interactive
      ? `Chess board, ${turn} to move. Drag a piece or click it, then click a target square.`
      : 'Chess board';
  const colorPrefix = turn === 'white' ? 'w' : 'b';

  return (
    <div
      className="cb-board"
      role={interactive ? 'group' : 'img'}
      aria-label={label}
      data-interactive={interactive || undefined}
    >
      <Chessboard
        options={{
          id: boardId,
          position: fen,
          boardOrientation: orientation,
          allowDragging: interactive,
          canDragPiece: canDrag,
          onPieceDrag: ({ square }) => {
            if (square) setSelection({ fen, square });
          },
          onPieceDragCancel: () => setSelection(null),
          onPieceDrop: handleDrop,
          onSquareClick: handleSquareClick,
          squareRenderer: renderSquare,
          arrows: boardArrows,
          clearArrowsOnPositionChange: true,
          showAnimations: !reduceMotion,
          animationDurationInMs: 180,
          lightSquareStyle: { backgroundColor: '#efd9ad' },
          darkSquareStyle: { backgroundColor: '#b9855d' },
          lightSquareNotationStyle: { color: 'rgba(120, 82, 48, 0.85)' },
          darkSquareNotationStyle: { color: 'rgba(250, 236, 208, 0.92)' },
          alphaNotationStyle: { ...notationBase, position: 'absolute', right: 4, bottom: 2 },
          numericNotationStyle: { ...notationBase, position: 'absolute', left: 4, top: 2 },
          dropSquareStyle: { boxShadow: 'inset 0 0 0 3px rgba(255, 255, 255, 0.75)' },
          boardStyle: { borderRadius: 0 }
        }}
      />
      {pendingPromotion ? (
        <div className="cb-promotion-scrim" onClick={cancelPromotion} onKeyDown={onPromotionKey}>
          <div
            className="cb-promotion"
            role="dialog"
            aria-modal="true"
            aria-label="Choose a promotion piece"
            onClick={(event) => event.stopPropagation()}
          >
            <span className="cb-promotion-title">Promote to</span>
            <div className="cb-promotion-options">
              {PROMOTION_PIECES.map(({ piece, label: name }, index) => {
                const render = defaultPieces[`${colorPrefix}${piece.toUpperCase()}`];
                return (
                  <button
                    key={piece}
                    type="button"
                    autoFocus={index === 0}
                    aria-label={`Promote to ${name}`}
                    title={name}
                    onClick={() => {
                      setPromotion(null);
                      commit(pendingPromotion.from, pendingPromotion.to, piece);
                    }}
                  >
                    {render?.()}
                  </button>
                );
              })}
            </div>
            <button type="button" className="cb-promotion-cancel" onClick={cancelPromotion}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
