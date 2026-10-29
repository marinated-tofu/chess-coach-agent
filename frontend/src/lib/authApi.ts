export type AuthState = {
  signed_in: boolean;
  lichess_username: string | null;
};

export async function getAuthState(): Promise<AuthState> {
  const response = await fetch('/api/auth/me', { credentials: 'same-origin' });
  if (!response.ok) throw new Error('Could not check sign-in status');
  return response.json();
}

export async function signOut(): Promise<void> {
  const response = await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  if (!response.ok) throw new Error('Could not sign out');
}

export function lichessLoginUrl(nextPath: string): string {
  return `/api/auth/lichess/login?next=${encodeURIComponent(nextPath || '/')}`;
}
