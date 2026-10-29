import { Chess, type Move, type Square } from 'chess.js';
import type { PieceColor } from './squareControl';

export type PromotionPiece = 'q' | 'r' | 'b' | 'n';

export type BoardMove = {
  from: string;
  to: string;
  promotion?: PromotionPiece;
  san: string;
  uci: string;
};

export type MoveRequest = { from: string; to: string; promotion?: PromotionPiece };

const SQUARE_RE = /^[a-h][1-8]$/;
const UCI_RE = /^([a-h][1-8])([a-h][1-8])([qrbn])?$/i;

export function isSquare(value: string): value is Square {
  return SQUARE_RE.test(value);
}

/** Returns a chess.js game for the FEN, or null when the FEN cannot be loaded. */
export function loadGame(fen: string): Chess | null {
  try {
    return new Chess(fen);
  } catch {
    try {
      return new Chess(fen, { skipValidation: true });
    } catch {
      return null;
    }
  }
}

function toBoardMove(move: Move): BoardMove {
  const promotion = move.promotion as PromotionPiece | undefined;
  return {
    from: move.from,
    to: move.to,
    promotion,
    san: move.san,
    uci: `${move.from}${move.to}${promotion ?? ''}`
  };
}

export function sideToMove(fen: string): PieceColor {
  return fen.split(' ')[1] === 'b' ? 'black' : 'white';
}

/** All legal moves for the side to move, optionally from one square. */
export function legalMoves(fen: string, from?: string): BoardMove[] {
  const game = loadGame(fen);
  if (!game) return [];
  if (from && !isSquare(from)) return [];
  const moves = from ? game.moves({ square: from as Square, verbose: true }) : game.moves({ verbose: true });
  return moves.map(toBoardMove);
}

/** Destination squares reachable from `from`, de-duplicated across promotion choices. */
export function legalTargets(fen: string, from: string): string[] {
  return [...new Set(legalMoves(fen, from).map((move) => move.to))];
}

export function isPromotionMove(fen: string, from: string, to: string): boolean {
  return legalMoves(fen, from).some((move) => move.to === to && move.promotion);
}

/** Plays a move request and returns the resolved move plus the resulting FEN, or null if illegal. */
export function playMove(fen: string, request: MoveRequest | string): { move: BoardMove; fen: string } | null {
  const game = loadGame(fen);
  if (!game) return null;
  try {
    const move = game.move(request);
    return { move: toBoardMove(move), fen: game.fen() };
  } catch {
    return null;
  }
}

/** Parses SAN ("Nf3", "exd8=Q+") or UCI ("g1f3", "e7e8q") into a legal move. */
export function parseMove(fen: string, input: string): BoardMove | null {
  const text = input.trim();
  if (!text) return null;
  const uci = UCI_RE.exec(text);
  if (uci) {
    const result = playMove(fen, {
      from: uci[1].toLowerCase(),
      to: uci[2].toLowerCase(),
      promotion: uci[3]?.toLowerCase() as PromotionPiece | undefined
    });
    if (result) return result.move;
  }
  return playMove(fen, text)?.move ?? null;
}

export function sanToUci(fen: string, san: string): string | null {
  return parseMove(fen, san)?.uci ?? null;
}

export function uciToSan(fen: string, uci: string): string | null {
  return parseMove(fen, uci)?.san ?? null;
}

/** Square of the king that is in check, if the side to move is in check. */
export function checkedKingSquare(fen: string): string | null {
  const game = loadGame(fen);
  if (!game || !game.inCheck()) return null;
  return game.findPiece({ type: 'k', color: game.turn() })[0] ?? null;
}

/** Color of the piece on a square, or null when the square is empty. */
export function pieceColorAt(fen: string, square: string): PieceColor | null {
  const game = loadGame(fen);
  if (!game || !isSquare(square)) return null;
  const piece = game.get(square);
  if (!piece) return null;
  return piece.color === 'w' ? 'white' : 'black';
}
