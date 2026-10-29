/** Stockfish analysis and bot moves for the analysis board (backend: engine_api.py). */

export type EngineLine = {
  rank: number;
  move_san: string;
  move_uci: string;
  /** Centipawns from White's point of view; null when the line is a forced mate. */
  eval_cp: number | null;
  /** Moves to mate from White's point of view: > 0 White mates, < 0 Black mates. */
  mate: number | null;
  pv_san: string[];
};

export type EngineAnalysis = {
  fen: string;
  side_to_move: 'white' | 'black';
  lines: EngineLine[];
  depth: number | null;
  /** Set when the position is already over: "checkmate", "stalemate", "insufficient_material"... */
  result: string | null;
};

export type BotMove = {
  move_san: string;
  move_uci: string;
  fen_after: string;
  level: number;
};

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `Engine request failed (${response.status})`);
  }
  return response.json();
}

export function analyzePosition(
  fen: string,
  options: { multipv?: number; depth?: number; movetimeMs?: number; signal?: AbortSignal } = {}
): Promise<EngineAnalysis> {
  return post(
    '/api/engine/analyze',
    { fen, multipv: options.multipv ?? 3, depth: options.depth, movetime_ms: options.movetimeMs },
    options.signal
  );
}

export function requestBotMove(fen: string, level: number, signal?: AbortSignal): Promise<BotMove> {
  return post('/api/engine/move', { fen, level }, signal);
}

/** "+1.3", "−0.4", "M3" (White mates) or "−M3" (Black mates), always from White's view. */
export function formatEval(line: Pick<EngineLine, 'eval_cp' | 'mate'>): string {
  if (line.mate != null) return line.mate < 0 ? `−M${Math.abs(line.mate)}` : `M${line.mate}`;
  const pawns = (line.eval_cp ?? 0) / 100;
  if (Math.abs(pawns) < 0.05) return '0.0';
  return pawns > 0 ? `+${pawns.toFixed(1)}` : `−${Math.abs(pawns).toFixed(1)}`;
}

/** White's winning chance in percent, Lichess formula; a forced mate pins it to 0 or 100. */
export function whiteWinPercent(line: Pick<EngineLine, 'eval_cp' | 'mate'>): number {
  if (line.mate != null) return line.mate < 0 ? 0 : 100;
  const cp = Math.max(-1000, Math.min(1000, line.eval_cp ?? 0));
  return 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);
}
