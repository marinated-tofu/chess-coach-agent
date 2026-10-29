import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouterState } from '@tanstack/react-router';
import { LogIn, LogOut, UserCheck } from 'lucide-react';
import { getAuthState, lichessLoginUrl, signOut } from '../lib/authApi';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './AccountButton.css';

const AUTH_KEY = ['auth-me'] as const;
// Remembers which Lichess account was already applied, so a later manual choice is never overwritten.
const LINKED_KEY = 'chess-coach-lichess-linked';

function readLinked() {
  try {
    return localStorage.getItem(LINKED_KEY) || '';
  } catch {
    return '';
  }
}

function writeLinked(value: string) {
  try {
    if (value) localStorage.setItem(LINKED_KEY, value);
    else localStorage.removeItem(LINKED_KEY);
  } catch {
    // Optional convenience only.
  }
}

export function AccountButton() {
  const queryClient = useQueryClient();
  const { player, platform, setPlayer, setPlatform } = useWorkspace();
  const currentPath = useRouterState({ select: (state) => state.location.href });
  const auth = useQuery({ queryKey: AUTH_KEY, queryFn: getAuthState, staleTime: 5 * 60_000, retry: false });
  const username = auth.data?.signed_in ? auth.data.lichess_username : null;
  const [error, setError] = useState('');

  const usingAccount = Boolean(
    username && platform === 'lichess' && player.trim().toLowerCase() === username.toLowerCase()
  );

  function applyAccount(name: string) {
    setPlatform('lichess');
    setPlayer(name);
    writeLinked(name.toLowerCase());
  }

  useEffect(() => {
    if (!username || readLinked() === username.toLowerCase()) return;
    // Only fill an empty identity; a username the user typed (or the sample) is left alone.
    if (!player.trim()) applyAccount(username);
    // Only re-check when the signed-in account changes.
  }, [username]);

  const logout = useMutation({
    mutationFn: signOut,
    onSuccess: () => {
      writeLinked('');
      setError('');
      queryClient.setQueryData(AUTH_KEY, { signed_in: false, lichess_username: null });
    },
    onError: () => setError('Sign-out failed. Try again.')
  });

  if (auth.isPending) return <div className="account-box" aria-hidden="true" />;

  if (!username) {
    return (
      <div className="account-box">
        <a className="account-signin" href={lichessLoginUrl(currentPath)}>
          <LogIn size={16} aria-hidden="true" />
          <span>Sign in with Lichess</span>
        </a>
        <p className="account-note">Optional. You can still type any username.</p>
      </div>
    );
  }

  return (
    <div className="account-box">
      <div className="account-row">
        <UserCheck size={16} aria-hidden="true" />
        <span className="account-name" title={`lichess: ${username}`}>lichess: {username}</span>
        <button
          type="button"
          className="account-icon-button"
          aria-label="Sign out"
          title="Sign out"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          <LogOut size={15} aria-hidden="true" />
        </button>
      </div>
      {!usingAccount && (
        <button type="button" className="account-use" onClick={() => applyAccount(username)}>
          Use my Lichess account
        </button>
      )}
      {error && <p className="account-note error" role="alert">{error}</p>}
    </div>
  );
}
