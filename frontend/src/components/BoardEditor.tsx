import { useId, useMemo, useState } from 'react';
import {
  Chessboard,
  ChessboardProvider,
  SparePiece,
  type PieceDropHandlerArgs,
  type PositionDataType,
  type SquareHandlerArgs
} from 'react-chessboard';
import { Eraser, FlipVertical2, Hand, RotateCcw, Trash2 } from 'lucide-react';
import {
  EMPTY_FEN,
  START_FEN,
  buildFen,
  castlingAvailable,
  enPassantOptions,
  parseFen,
  positionError,
  type EditorState,
  type PieceCode
} from '../lib/positionSetup';
import './BoardEditor.css';

type Tool = PieceCode | 'eraser' | 'hand';

const PIECE_NAMES: Record<string, string> = { K: 'king', Q: 'queen', R: 'rook', B: 'bishop', N: 'knight', P: 'pawn' };
const ROW: Array<PieceCode[number]> = ['K', 'Q', 'R', 'B', 'N', 'P'];
const CASTLING = [
  { key: 'K', label: 'White O-O' },
  { key: 'Q', label: 'White O-O-O' },
  { key: 'k', label: 'Black O-O' },
  { key: 'q', label: 'Black O-O-O' }
] as const;

const EMPTY_STATE = parseFen(EMPTY_FEN)!;

function PaletteRow({ color, tool, onPick }: { color: 'w' | 'b'; tool: Tool; onPick: (tool: Tool) => void }) {
  return (
    <div className="be-palette-row" role="group" aria-label={color === 'w' ? 'White pieces' : 'Black pieces'}>
      {ROW.map((letter) => {
        const code = `${color}${letter}` as PieceCode;
        const name = `${color === 'w' ? 'White' : 'Black'} ${PIECE_NAMES[letter]}`;
        return (
          <button
            key={code}
            type="button"
            className="be-piece"
            aria-pressed={tool === code}
            aria-label={name}
            title={`${name}: click squares to place, or drag onto the board`}
            onClick={() => onPick(tool === code ? 'hand' : code)}
          >
            <SparePiece pieceType={code} />
          </button>
        );
      })}
    </div>
  );
}

export function BoardEditor({
  fen,
  onChange,
  orientation,
  onOrientationChange
}: {
  fen: string;
  onChange: (fen: string) => void;
  orientation: 'white' | 'black';
  onOrientationChange: (orientation: 'white' | 'black') => void;
}) {
  const fenInputId = useId();
  const [tool, setTool] = useState<Tool>('hand');
  const [draft, setDraft] = useState<{ text: string; basis: string } | null>(null);

  const state: EditorState = useMemo(() => parseFen(fen) ?? EMPTY_STATE, [fen]);
  const fenText = draft && draft.basis === fen ? draft.text : fen;
  const error = useMemo(() => positionError(fenText), [fenText]);
  const available = castlingAvailable(state.placement);
  const epOptions = enPassantOptions(state.placement, state.turn);

  const position: PositionDataType = useMemo(
    () => Object.fromEntries(Object.entries(state.placement).map(([square, code]) => [square, { pieceType: code }])),
    [state.placement]
  );

  function commit(next: Partial<EditorState>) {
    onChange(buildFen({ ...state, ...next }));
  }

  function setSquare(square: string, code: PieceCode | null) {
    const placement = { ...state.placement };
    if (code) placement[square] = code;
    else delete placement[square];
    // A freshly placed king and rook on home squares should come with the castling right.
    const castling = { ...state.castling };
    const before = castlingAvailable(state.placement);
    const after = castlingAvailable(placement);
    for (const key of ['K', 'Q', 'k', 'q'] as const) if (after[key] && !before[key]) castling[key] = true;
    commit({ placement, castling });
  }

  function handleSquareClick({ square }: SquareHandlerArgs) {
    if (tool === 'hand') return;
    if (tool === 'eraser') setSquare(square, null);
    else setSquare(square, state.placement[square] === tool ? null : tool);
  }

  function handleDrop({ piece, sourceSquare, targetSquare }: PieceDropHandlerArgs): boolean {
    const code = piece.pieceType as PieceCode;
    if (piece.isSparePiece) {
      if (targetSquare) setSquare(targetSquare, code);
      return Boolean(targetSquare);
    }
    const placement = { ...state.placement };
    delete placement[sourceSquare];
    if (targetSquare) placement[targetSquare] = code;
    commit({ placement });
    return true;
  }

  function onFenInput(text: string) {
    setDraft({ text, basis: fen });
    if (parseFen(text)) {
      const parts = text.trim().split(/\s+/);
      // Fill in missing fields so the board and controls always see a complete FEN.
      const full = [parts[0], parts[1] ?? 'w', parts[2] ?? '-', parts[3] ?? '-', parts[4] ?? '0', parts[5] ?? '1'].join(' ');
      setDraft({ text, basis: full });
      onChange(full);
    }
  }

  return (
    <section className="be" aria-label="Board editor">
      <ChessboardProvider
        options={{
          id: 'board-editor',
          position,
          boardOrientation: orientation,
          allowDragOffBoard: true,
          allowDrawingArrows: false,
          showAnimations: false,
          onSquareClick: handleSquareClick,
          onSquareRightClick: ({ square }) => setSquare(square, null),
          onPieceDrop: handleDrop,
          lightSquareStyle: { backgroundColor: '#efd9ad' },
          darkSquareStyle: { backgroundColor: '#b9855d' },
          lightSquareNotationStyle: { color: 'rgba(120, 82, 48, 0.85)', fontSize: 11, fontWeight: 700 },
          darkSquareNotationStyle: { color: 'rgba(250, 236, 208, 0.92)', fontSize: 11, fontWeight: 700 },
          dropSquareStyle: { boxShadow: 'inset 0 0 0 3px rgba(255, 255, 255, 0.75)' },
          boardStyle: { borderRadius: 0 }
        }}
      >
        <div className="be-layout">
          <div className="be-board-column">
            <PaletteRow color={orientation === 'white' ? 'b' : 'w'} tool={tool} onPick={setTool} />
            <div className="be-board" data-tool={tool}>
              <Chessboard />
            </div>
            <PaletteRow color={orientation === 'white' ? 'w' : 'b'} tool={tool} onPick={setTool} />
            <div className="be-tools" role="group" aria-label="Pointer tools">
              <button type="button" className="be-tool" aria-pressed={tool === 'hand'} onClick={() => setTool('hand')}>
                <Hand size={16} aria-hidden /> Move
              </button>
              <button type="button" className="be-tool" aria-pressed={tool === 'eraser'} onClick={() => setTool(tool === 'eraser' ? 'hand' : 'eraser')}>
                <Eraser size={16} aria-hidden /> Erase
              </button>
              <span className="be-hint">
                {tool === 'hand' ? 'Drag pieces to move them. Drag off the board or right-click to remove.'
                  : tool === 'eraser' ? 'Click a piece to remove it.'
                  : 'Click squares to place this piece. Click it again to remove.'}
              </span>
            </div>
          </div>

          <div className="be-controls">
            <fieldset className="be-field">
              <legend>Side to move</legend>
              <div className="be-segmented">
                {(['w', 'b'] as const).map((side) => (
                  <label key={side} className="be-segment">
                    <input
                      type="radio"
                      name={`${fenInputId}-turn`}
                      checked={state.turn === side}
                      onChange={() => commit({ turn: side, enPassant: null })}
                    />
                    <span>{side === 'w' ? 'White' : 'Black'}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="be-field">
              <legend>Castling</legend>
              <div className="be-castling">
                {CASTLING.map(({ key, label }) => (
                  <label key={key} className="be-check" data-disabled={!available[key] || undefined}>
                    <input
                      type="checkbox"
                      checked={state.castling[key] && available[key]}
                      disabled={!available[key]}
                      onChange={(event) => commit({ castling: { ...state.castling, [key]: event.target.checked } })}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="be-field be-ep">
              <span className="be-label">En passant square</span>
              <select
                value={state.enPassant && epOptions.includes(state.enPassant) ? state.enPassant : ''}
                disabled={epOptions.length === 0}
                onChange={(event) => commit({ enPassant: event.target.value || null })}
              >
                <option value="">{epOptions.length ? 'None' : 'None possible'}</option>
                {epOptions.map((square) => <option key={square} value={square}>{square}</option>)}
              </select>
            </label>

            <div className="be-actions">
              <button type="button" className="secondary" onClick={() => onChange(START_FEN)}>
                <RotateCcw size={16} aria-hidden /> Start position
              </button>
              <button type="button" className="secondary" onClick={() => onChange(EMPTY_FEN)}>
                <Trash2 size={16} aria-hidden /> Clear
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => onOrientationChange(orientation === 'white' ? 'black' : 'white')}
              >
                <FlipVertical2 size={16} aria-hidden /> Flip
              </button>
            </div>

            <div className="be-field">
              <label className="be-label" htmlFor={fenInputId}>FEN</label>
              <input
                id={fenInputId}
                className="be-fen"
                value={fenText}
                spellCheck={false}
                autoComplete="off"
                aria-invalid={Boolean(error)}
                aria-describedby={`${fenInputId}-status`}
                onChange={(event) => onFenInput(event.target.value)}
              />
              <p id={`${fenInputId}-status`} className={error ? 'be-status be-error' : 'be-status be-ok'} aria-live="polite">
                {error ?? 'Legal position.'}
              </p>
            </div>
          </div>
        </div>
      </ChessboardProvider>
    </section>
  );
}
