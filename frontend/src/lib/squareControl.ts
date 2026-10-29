export type HeatmapMode = 'off' | 'you' | 'opponent' | 'both';
export type PieceColor = 'white' | 'black';

export type SquareControl = {
  board: string[][];
  white: number[][];
  black: number[][];
};

const FILES = 'abcdefgh';
const KNIGHT_STEPS = [
  [1, -2],
  [1, 2],
  [-1, -2],
  [-1, 2],
  [2, -1],
  [2, 1],
  [-2, -1],
  [-2, 1]
] as const;
const KING_STEPS = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
  [1, 1],
  [1, -1],
  [-1, 1],
  [-1, -1]
] as const;
const DIAGONALS = [
  [1, 1],
  [1, -1],
  [-1, 1],
  [-1, -1]
] as const;
const ORTHOGONALS = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1]
] as const;

function emptyGrid(): number[][] {
  return Array.from({ length: 8 }, () => Array.from({ length: 8 }, () => 0));
}

function onBoard(file: number, rankIndex: number): boolean {
  return file >= 0 && file < 8 && rankIndex >= 0 && rankIndex < 8;
}

export function boardFromFen(fen: string): string[][] {
  const placement = fen.split(' ')[0] || '8/8/8/8/8/8/8/8';
  return placement.split('/').map((rank) => {
    const row: string[] = [];
    for (const ch of rank) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < Number(ch); i += 1) row.push('');
      } else {
        row.push(ch);
      }
    }
    while (row.length < 8) row.push('');
    return row.slice(0, 8);
  });
}

function mark(grid: number[][], file: number, rankIndex: number): void {
  if (onBoard(file, rankIndex)) grid[rankIndex][file] += 1;
}

function slide(
  board: string[][],
  grid: number[][],
  file: number,
  rankIndex: number,
  steps: ReadonlyArray<readonly [number, number]>
): void {
  for (const [df, dr] of steps) {
    let nextFile = file + df;
    let nextRank = rankIndex + dr;
    while (onBoard(nextFile, nextRank)) {
      mark(grid, nextFile, nextRank);
      if (board[nextRank][nextFile]) break;
      nextFile += df;
      nextRank += dr;
    }
  }
}

function addPawnReach(
  board: string[][],
  grid: number[][],
  file: number,
  rankIndex: number,
  color: PieceColor
): void {
  const forward = color === 'white' ? -1 : 1;
  const startRank = color === 'white' ? 6 : 1;
  mark(grid, file - 1, rankIndex + forward);
  mark(grid, file + 1, rankIndex + forward);
  const oneAhead = rankIndex + forward;
  if (onBoard(file, oneAhead) && !board[oneAhead][file]) {
    mark(grid, file, oneAhead);
    const twoAhead = oneAhead + forward;
    if (rankIndex === startRank && onBoard(file, twoAhead) && !board[twoAhead][file]) {
      mark(grid, file, twoAhead);
    }
  }
}

export function computeSquareControl(fen: string): SquareControl {
  const board = boardFromFen(fen);
  const white = emptyGrid();
  const black = emptyGrid();

  for (let rankIndex = 0; rankIndex < 8; rankIndex += 1) {
    for (let file = 0; file < 8; file += 1) {
      const piece = board[rankIndex]?.[file];
      if (!piece) continue;
      const color: PieceColor = piece === piece.toUpperCase() ? 'white' : 'black';
      const grid = color === 'white' ? white : black;
      const kind = piece.toLowerCase();

      if (kind === 'p') {
        addPawnReach(board, grid, file, rankIndex, color);
      } else if (kind === 'n') {
        for (const [df, dr] of KNIGHT_STEPS) mark(grid, file + df, rankIndex + dr);
      } else if (kind === 'k') {
        for (const [df, dr] of KING_STEPS) mark(grid, file + df, rankIndex + dr);
      } else if (kind === 'b') {
        slide(board, grid, file, rankIndex, DIAGONALS);
      } else if (kind === 'r') {
        slide(board, grid, file, rankIndex, ORTHOGONALS);
      } else if (kind === 'q') {
        slide(board, grid, file, rankIndex, DIAGONALS);
        slide(board, grid, file, rankIndex, ORTHOGONALS);
      }
    }
  }

  return { board, white, black };
}

export function squareName(file: number, rankIndex: number): string {
  return `${FILES[file]}${8 - rankIndex}`;
}

function centerScore(file: number, rankIndex: number): number {
  return Math.abs(file - 3.5) + Math.abs(rankIndex - 3.5);
}

export function strongestSquare(grid: number[][]): { square: string; count: number } | null {
  let count = 0;
  let square = '';
  let centrality = Infinity;
  for (let rankIndex = 0; rankIndex < 8; rankIndex += 1) {
    for (let file = 0; file < 8; file += 1) {
      const value = grid[rankIndex][file];
      if (value < count) continue;
      const nextCenter = centerScore(file, rankIndex);
      if (value > count || nextCenter < centrality) {
        count = value;
        square = squareName(file, rankIndex);
        centrality = nextCenter;
      }
    }
  }
  return count > 0 ? { square, count } : null;
}

export function weakestOccupiedSquare(
  board: string[][],
  grid: number[][],
  color: PieceColor
): { square: string; count: number } | null {
  let count = Infinity;
  let square = '';
  for (let rankIndex = 0; rankIndex < 8; rankIndex += 1) {
    for (let file = 0; file < 8; file += 1) {
      const piece = board[rankIndex][file];
      if (!piece) continue;
      const pieceColor: PieceColor = piece === piece.toUpperCase() ? 'white' : 'black';
      if (pieceColor !== color) continue;
      const value = grid[rankIndex][file];
      if (value < count) {
        count = value;
        square = squareName(file, rankIndex);
      }
    }
  }
  return Number.isFinite(count) ? { square, count } : null;
}

export function heatAlpha(count: number): number {
  if (count <= 0) return 0;
  return Math.min(0.2 + (count - 1) * 0.16, 0.72);
}
