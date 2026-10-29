/** Board-editor FEN helpers: free piece placement plus the extra FEN fields, checked with chess.js. */
import { Chess, validateFen } from 'chess.js';

export type PieceCode = `${'w' | 'b'}${'K' | 'Q' | 'R' | 'B' | 'N' | 'P'}`;
export type Placement = Record<string, PieceCode>;
export type CastlingRights = { K: boolean; Q: boolean; k: boolean; q: boolean };
export type EditorState = {
  placement: Placement;
  turn: 'w' | 'b';
  castling: CastlingRights;
  enPassant: string | null;
};

export const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
export const EMPTY_FEN = '8/8/8/8/8/8/8/8 w - - 0 1';
const FILES = 'abcdefgh';

function codeFromSymbol(symbol: string): PieceCode | null {
  if (!/^[pnbrqkPNBRQK]$/.test(symbol)) return null;
  const color = symbol === symbol.toUpperCase() ? 'w' : 'b';
  return `${color}${symbol.toUpperCase()}` as PieceCode;
}

function symbolFromCode(code: PieceCode): string {
  return code[0] === 'w' ? code[1] : code[1].toLowerCase();
}

/** Lenient parse: any well-formed placement works even if the position is illegal. */
export function parseFen(fen: string): EditorState | null {
  const [board, turn = 'w', castling = '-', ep = '-'] = fen.trim().split(/\s+/);
  const ranks = board?.split('/');
  if (!ranks || ranks.length !== 8) return null;
  const placement: Placement = {};
  for (let r = 0; r < 8; r += 1) {
    let file = 0;
    for (const char of ranks[r]) {
      if (/[1-8]/.test(char)) {
        file += Number(char);
        continue;
      }
      const code = codeFromSymbol(char);
      if (!code || file > 7) return null;
      placement[`${FILES[file]}${8 - r}`] = code;
      file += 1;
    }
    if (file !== 8) return null;
  }
  if (turn !== 'w' && turn !== 'b') return null;
  return {
    placement,
    turn,
    castling: { K: castling.includes('K'), Q: castling.includes('Q'), k: castling.includes('k'), q: castling.includes('q') },
    enPassant: /^[a-h][36]$/.test(ep) ? ep : null
  };
}

export function placementFen(placement: Placement): string {
  const rows: string[] = [];
  for (let rank = 8; rank >= 1; rank -= 1) {
    let row = '';
    let empty = 0;
    for (const file of FILES) {
      const code = placement[`${file}${rank}`];
      if (!code) {
        empty += 1;
        continue;
      }
      if (empty) row += String(empty);
      empty = 0;
      row += symbolFromCode(code);
    }
    rows.push(empty ? row + String(empty) : row);
  }
  return rows.join('/');
}

/** Castling right is only possible with king and rook still on their home squares. */
export function castlingAvailable(placement: Placement): CastlingRights {
  return {
    K: placement.e1 === 'wK' && placement.h1 === 'wR',
    Q: placement.e1 === 'wK' && placement.a1 === 'wR',
    k: placement.e8 === 'bK' && placement.h8 === 'bR',
    q: placement.e8 === 'bK' && placement.a8 === 'bR'
  };
}

/** Squares a pawn could capture en passant on, given who moves next. */
export function enPassantOptions(placement: Placement, turn: 'w' | 'b'): string[] {
  const [pawnRank, targetRank, fromRank, mover] = turn === 'w' ? [5, 6, 7, 'bP'] : [4, 3, 2, 'wP'];
  const capturer = turn === 'w' ? 'wP' : 'bP';
  return [...FILES].filter((file, index) => {
    if (placement[`${file}${pawnRank}`] !== mover) return false;
    if (placement[`${file}${targetRank}`] || placement[`${file}${fromRank}`]) return false;
    return [FILES[index - 1], FILES[index + 1]].some((side) => side && placement[`${side}${pawnRank}`] === capturer);
  }).map((file) => `${file}${targetRank}`);
}

export function buildFen(state: EditorState): string {
  const available = castlingAvailable(state.placement);
  const castling = (['K', 'Q', 'k', 'q'] as const).filter((key) => state.castling[key] && available[key]).join('') || '-';
  const ep = state.enPassant && enPassantOptions(state.placement, state.turn).includes(state.enPassant) ? state.enPassant : '-';
  return `${placementFen(state.placement)} ${state.turn} ${castling} ${ep} 0 1`;
}

/** Plain-language reason the position cannot be analysed, or null when it is legal. */
export function positionError(fen: string): string | null {
  const state = parseFen(fen);
  if (!state) return 'That FEN is not well formed. It needs 8 ranks separated by "/".';
  const pieces = Object.entries(state.placement);
  for (const [color, name] of [['w', 'White'], ['b', 'Black']] as const) {
    const kings = pieces.filter(([, code]) => code === `${color}K`).length;
    if (kings === 0) return `${name} needs a king.`;
    if (kings > 1) return `${name} has ${kings} kings. Remove the extras.`;
    if (pieces.filter(([, code]) => code === `${color}P`).length > 8) return `${name} has more than 8 pawns.`;
  }
  const backRankPawn = pieces.find(([square, code]) => code[1] === 'P' && /[18]$/.test(square));
  if (backRankPawn) return `There is a pawn on ${backRankPawn[0]}. Pawns can't stand on the first or last rank.`;
  const verdict = validateFen(fen);
  if (!verdict.ok) return verdict.error ?? 'chess.js rejected this FEN.';
  const waiting = fen.replace(/ ([wb]) /, (_match, side: string) => (side === 'w' ? ' b ' : ' w '));
  try {
    if (new Chess(waiting.replace(/ [a-h][36] /, ' - ')).inCheck()) {
      const side = state.turn === 'w' ? 'Black' : 'White';
      return `${side} is in check, so it can't be ${state.turn === 'w' ? 'White' : 'Black'} to move.`;
    }
  } catch {
    return 'chess.js rejected this FEN.';
  }
  return null;
}
