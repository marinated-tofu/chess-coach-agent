import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link, useRouterState } from '@tanstack/react-router';
import { LogIn, LogOut, UserCheck } from 'lucide-react';
import { lichessLoginUrl, signOut, useAuth } from '../lib/authApi';
import { forgetStoredWorkspace, useWorkspace } from '../workspace/WorkspaceContext';
import './AccountButton.css';

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

export function AccountButton({ onNavigate }: { onNavigate?: () => void }) {
  const { player, platform, setPlayer, setPlatform } = useWorkspace();
  const currentPath = useRouterState({ select: (state) => state.location.href });
  const auth = useAuth();
  const signedIn = auth.data?.signed_in ?? false;
  const username = signedIn ? auth.data?.lichess_username ?? null : null;
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
      const owned = auth.data?.players.some((item) => (
        item.platform === platform && item.username.toLowerCase() === player.trim().toLowerCase()
      ));
      if (owned) forgetStoredWorkspace();
      // A full load clears cached practice data and any open coach conversation.
      window.location.assign('/');
    },
    onError: () => setError('Sign-out failed. Try again.')
  });

  if (auth.isPending) return <div className="account-box" aria-hidden="true" />;

  if (!signedIn) {
    return (
      <div className="account-box">
        <a className="account-signin" href={lichessLoginUrl(currentPath)}>
          <LogIn size={16} aria-hidden="true" />
          <span>Sign in with Lichess</span>
        </a>
        <p className="account-note">Keeps your practice private. You can still try any username.</p>
      </div>
    );
  }

  return (
    <div className="account-box">
      <div className="account-row">
        <UserCheck size={16} aria-hidden="true" />
        <Link to="/account" className="account-name" title="Your account" onClick={onNavigate}>
          {auth.data?.display_name}
        </Link>
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
      {username && !usingAccount && (
        <button type="button" className="account-use" onClick={() => applyAccount(username!)}>
          Use my Lichess account
        </button>
      )}
      {error && <p className="account-note error" role="alert">{error}</p>}
    </div>
  );
}
