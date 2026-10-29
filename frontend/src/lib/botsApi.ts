/** Human-like bot opponents for the Play page (backend: bots_api.py, model in bots.py). */

export type BotStyle = 'solid' | 'aggressive' | 'tricky' | 'sparring';

export type BotPersona = {
  id: string;
  name: string;
  rating: number;
  style: BotStyle;
  blurb: string;
  initial: string;
  color: string;
  /** Base blunder chance per move, before the position-complexity factor. */
  blunder_rate: number;
};

export type BotMoveResult = {
  move_san: string;
  move_uci: string;
  fen_after: string;
  /** How long the UI should appear to think before showing the move. */
  thinking_ms: number;
  source: 'book' | 'sparring' | 'engine' | 'blunder' | 'only';
  rating: number;
  comment: string | null;
};

export type BotMoveRequest = {
  fen: string;
  bot_id: string;
  moves_uci?: string[];
  platform?: string;
  username?: string;
};

async function readError(response: Response, fallback: string): Promise<Error> {
  const detail = await response.json().catch(() => null);
  return new Error(typeof detail?.detail === 'string' ? detail.detail : `${fallback} (${response.status})`);
}

export async function getBots(): Promise<BotPersona[]> {
  const response = await fetch('/api/bots');
  if (!response.ok) throw await readError(response, 'Could not load bots');
  return ((await response.json()) as { bots: BotPersona[] }).bots;
}

export async function requestBotMove(body: BotMoveRequest, signal?: AbortSignal): Promise<BotMoveResult> {
  const response = await fetch('/api/bots/move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal
  });
  if (!response.ok) throw await readError(response, 'The bot could not move');
  return (await response.json()) as BotMoveResult;
}
