import type {
  AnalyzeResponse,
  CoachAskResponse,
  CriticalMoment,
  MonitoringSummary,
  Platform,
  EvaluationPanel,
  ProgressSummary,
  TrainingSession,
  SyncJob
} from './types';

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string' && body.detail) return body.detail;
  } catch {
    // Non-JSON error bodies (proxy errors, HTML pages) fall back to the generic message.
  }
  return fallback;
}

export async function getSample(): Promise<{ player: string; pgn: string }> {
  const response = await fetch('/api/sample');
  if (!response.ok) throw new Error('Could not load sample PGN');
  return response.json();
}

export async function analyzeGames(
  pgn: string,
  player: string,
  maxGames: number,
  platform: Platform | 'pgn' = 'pgn'
): Promise<AnalyzeResponse> {
  const response = await fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pgn, player, max_games: maxGames, platform })
  });
  if (!response.ok) throw new Error(await errorMessage(response, 'Analysis failed'));
  return response.json();
}

export async function sendMomentFeedback(
  moment: CriticalMoment,
  rating: 'helpful' | 'not_helpful',
  comment = ''
): Promise<void> {
  const response = await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      moment_id: moment.id,
      game_id: moment.game_id,
      rating,
      theme: moment.theme,
      fen: moment.fen_before,
      comment
    })
  });
  if (!response.ok) throw new Error('Could not record feedback');
}

export async function getMonitoring(): Promise<MonitoringSummary> {
  const response = await fetch('/api/monitoring');
  if (!response.ok) throw new Error('Could not load monitoring summary');
  return response.json();
}

export async function createTrainingSession(
  username: string,
  platform: Platform,
  theme?: string,
  momentId?: string
): Promise<TrainingSession> {
  const response = await fetch('/api/training/sessions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username,
      platform,
      theme: theme || null,
      moment_id: momentId || null,
      position_count: momentId ? 1 : 5
    })
  });
  if (!response.ok) throw new Error('Could not build training session');
  return response.json();
}

export async function getTrainingSession(sessionId: string): Promise<TrainingSession> {
  const response = await fetch(`/api/training/sessions/${sessionId}`);
  if (!response.ok) throw new Error('Could not load training session');
  return response.json();
}

export async function submitTrainingAttempt(
  trainingSessionId: string,
  positionId: string,
  move: string,
  hintsUsed: number,
  elapsedMs: number
): Promise<EvaluationPanel> {
  const response = await fetch(`/api/training/sessions/${trainingSessionId}/attempts`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ position_id: positionId, move, hints_used: hintsUsed, elapsed_ms: elapsedMs })
  });
  if (!response.ok) throw new Error('Could not evaluate move');
  return response.json();
}

export async function getProgress(username: string, platform: Platform): Promise<ProgressSummary> {
  const response = await fetch(`/api/progress/${platform}/${encodeURIComponent(username)}`);
  if (!response.ok) throw new Error('Could not load progress');
  return response.json();
}

export async function getAnalyzedGames(
  username: string,
  platform: Platform | 'pgn',
  gameId?: string
): Promise<AnalyzeResponse> {
  const query = gameId ? `?game_id=${encodeURIComponent(gameId)}` : '';
  const response = await fetch(`/api/games/${platform}/${encodeURIComponent(username.trim())}${query}`);
  if (!response.ok) throw new Error('Could not load analyzed games');
  return response.json();
}

export async function startGameSync(
  username: string,
  platform: Platform,
  maxGames = 5000
): Promise<SyncJob> {
  const response = await fetch('/api/games/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: username.trim(), platform, max_games: maxGames })
  });
  if (!response.ok) throw new Error(await errorMessage(response, `Could not sync games from ${platform}`));
  return response.json();
}

export async function getGameSync(jobId: string): Promise<SyncJob> {
  const response = await fetch(`/api/games/sync/${jobId}`);
  if (!response.ok) throw new Error(await errorMessage(response, 'Could not read game sync progress'));
  return response.json();
}

export async function askCoach(request: {
  question: string;
  username: string;
  platform: Platform;
  gameId?: string;
  fen?: string;
  messageHistory: unknown[];
}): Promise<CoachAskResponse> {
  const response = await fetch('/api/coach/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: request.question,
      username: request.username,
      platform: request.platform,
      game_id: request.gameId || null,
      fen: request.fen || null,
      message_history: request.messageHistory
    })
  });
  if (!response.ok) throw new Error('The coach could not answer. Try again.');
  return response.json();
}
