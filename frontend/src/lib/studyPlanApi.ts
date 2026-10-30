import type { Platform } from './types';

export type PlanTaskKind = 'due_review' | 'leak_practice' | 'game_review' | 'repertoire_review' | 'repertoire_build';
export type PlanTaskStatus = 'todo' | 'in_progress' | 'done' | 'overdue';

export interface PlanTask {
  id: string;
  kind: PlanTaskKind;
  title: string;
  detail: string;
  target: number;
  /** Counted by the server from real activity; there is no way to tick a task by hand. */
  progress: number;
  status: PlanTaskStatus;
  theme: string | null;
  session_mode: 'mixed' | 'puzzles' | 'due' | null;
  game_id: string | null;
  moment_id: string | null;
  repertoire_id: string | null;
  repertoire_color: 'white' | 'black' | null;
}

export interface PlanDay {
  index: number;
  date: string;
  tasks: PlanTask[];
}

export interface StudyPlan {
  id: string;
  start_date: string;
  end_date: string;
  today_index: number;
  summary: string;
  rationale: string | null;
  done_tasks: number;
  total_tasks: number;
  days: PlanDay[];
}

export interface StudyPlanResponse {
  platform: string;
  username: string;
  known: boolean;
  plan: StudyPlan | null;
  last_plan: { start_date: string; end_date: string; done_tasks: number; total_tasks: number } | null;
}

/** The player's calendar date; the plan's days follow it, not the server's UTC date. */
export function localDate(now = new Date()) {
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export function studyPlanKey(platform: Platform, player: string) {
  return ['study-plan', platform, player.trim().toLowerCase()] as const;
}

function planUrl(username: string, platform: Platform) {
  return `/api/study-plan/${encodeURIComponent(platform)}/${encodeURIComponent(username.trim())}`;
}

export async function getStudyPlan(username: string, platform: Platform): Promise<StudyPlanResponse> {
  const response = await fetch(`${planUrl(username, platform)}?today=${localDate()}`);
  if (!response.ok) throw new Error('Could not load your study plan');
  return response.json();
}

export async function createStudyPlan(username: string, platform: Platform): Promise<StudyPlanResponse> {
  const response = await fetch(planUrl(username, platform), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ today: localDate() })
  });
  if (!response.ok) throw new Error('Could not build your study plan');
  return response.json();
}

/** Logs a finished retry on the review page. Progress only, so a failure is not shown. */
export function recordGameRetry(username: string, platform: Platform, gameId: string, ply: number) {
  void fetch(`${planUrl(username, platform)}/game-retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ game_id: gameId, ply })
  }).catch(() => undefined);
}
