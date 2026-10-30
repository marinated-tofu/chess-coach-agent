import { useQuery } from '@tanstack/react-query';
import type { Platform } from './types';

export type CoachQuota = {
  limit: number;
  used: number;
  remaining: number;
  resets_at: string;
};

export type LinkedPlayer = {
  platform: Platform;
  username: string;
};

export type AuthState = {
  signed_in: boolean;
  lichess_username: string | null;
  display_name: string | null;
  plan: 'free' | 'paid' | null;
  players: LinkedPlayer[];
  coach_quota: CoachQuota;
};

export type UserSettings = {
  speak_answers: boolean;
};

export const AUTH_KEY = ['auth-me'] as const;
export const SETTINGS_KEY = ['account-settings'] as const;

export async function getAuthState(): Promise<AuthState> {
  const response = await fetch('/api/auth/me', { credentials: 'same-origin' });
  if (!response.ok) throw new Error('Could not check sign-in status');
  return response.json();
}

/** The shared sign-in state; every consumer reads the same cached request. */
export function useAuth() {
  return useQuery({ queryKey: AUTH_KEY, queryFn: getAuthState, staleTime: 5 * 60_000, retry: false });
}

export async function signOut(): Promise<void> {
  const response = await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  if (!response.ok) throw new Error('Could not sign out');
}

export function lichessLoginUrl(nextPath: string): string {
  return `/api/auth/lichess/login?next=${encodeURIComponent(nextPath || '/')}`;
}

async function accountRequest<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/account/${path}`, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    let detail = 'That did not work. Try again.';
    try {
      const parsed = await response.json();
      if (typeof parsed?.detail === 'string' && parsed.detail) detail = parsed.detail;
    } catch {
      // Keep the generic message.
    }
    throw new Error(detail);
  }
  return response.json();
}

export function getSettings() {
  return accountRequest<UserSettings>('settings', 'GET');
}

export function saveSettings(settings: UserSettings) {
  return accountRequest<UserSettings>('settings', 'PUT', settings);
}

export function getChessComCode(username: string) {
  return accountRequest<{ username: string; code: string }>('chesscom/code', 'POST', { username });
}

export function verifyChessCom(username: string) {
  return accountRequest<LinkedPlayer>('chesscom/verify', 'POST', { username });
}
