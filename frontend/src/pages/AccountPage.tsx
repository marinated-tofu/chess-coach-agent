import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouterState } from '@tanstack/react-router';
import { Loader2, LogIn } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import {
  AUTH_KEY,
  getChessComCode,
  lichessLoginUrl,
  useAuth,
  verifyChessCom,
  type CoachQuota,
  type LinkedPlayer
} from '../lib/authApi';
import { useSpeech } from '../lib/useSpeech';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './AccountPage.css';

const PLATFORM_NAMES: Record<string, string> = { 'chess.com': 'Chess.com', lichess: 'Lichess' };

export function AccountPage() {
  const auth = useAuth();
  const currentPath = useRouterState({ select: (state) => state.location.href });

  if (auth.isPending) {
    return (
      <main className="route-page account-page">
        <PageHeader eyebrow="Account" title="Your account" />
      </main>
    );
  }

  if (auth.isError) {
    return (
      <main className="route-page account-page">
        <PageHeader eyebrow="Account" title="Your account" />
        <section className="account-section" role="alert">
          <p>Could not load your account.</p>
          <button type="button" className="secondary" onClick={() => void auth.refetch()}>Try again</button>
        </section>
      </main>
    );
  }

  if (!auth.data?.signed_in) {
    return (
      <main className="route-page account-page">
        <PageHeader
          eyebrow="Account"
          title="Keep your practice private"
          detail="Sign in to claim your player. Your practice history and repertoires then open only for you."
        />
        <section className="account-section">
          <a className="primary account-signin-link" href={lichessLoginUrl(currentPath)}>
            <LogIn size={16} aria-hidden="true" /> Sign in with Lichess
          </a>
          <p className="account-hint">You can keep trying the app with any username without signing in.</p>
          <QuotaLine quota={auth.data?.coach_quota} />
        </section>
      </main>
    );
  }

  return (
    <main className="route-page account-page">
      <PageHeader eyebrow="Account" title={auth.data.display_name || 'Your account'} />
      <section className="account-section" aria-labelledby="account-plan">
        <h2 id="account-plan">Plan</h2>
        <p className="account-plan-name">{auth.data.plan === 'paid' ? 'Paid' : 'Free'}</p>
        <QuotaLine quota={auth.data.coach_quota} />
      </section>
      <section className="account-section" aria-labelledby="account-players">
        <h2 id="account-players">Your players</h2>
        <PlayerList players={auth.data.players} />
        <ChessComLink />
      </section>
      <section className="account-section" aria-labelledby="account-preferences">
        <h2 id="account-preferences">Preferences</h2>
        <SpeechPreference />
      </section>
    </main>
  );
}

function QuotaLine({ quota }: { quota?: CoachQuota }) {
  if (!quota) return null;
  if (quota.limit === 0) return <p className="account-hint">Coach questions aren't available on this plan.</p>;
  return (
    <p className="account-hint num">
      {quota.remaining.toLocaleString()} of {quota.limit.toLocaleString()} coach questions left today. The count resets at midnight UTC.
    </p>
  );
}

function PlayerList({ players }: { players: LinkedPlayer[] }) {
  const workspace = useWorkspace();
  if (!players.length) return <p className="account-hint">No players linked yet.</p>;
  return (
    <ul className="account-players">
      {players.map((item) => {
        const active = workspace.platform === item.platform
          && workspace.player.trim().toLowerCase() === item.username.toLowerCase();
        return (
          <li key={`${item.platform}:${item.username}`}>
            <span className="account-player-name">{item.username}</span>
            <span className="account-player-platform">{PLATFORM_NAMES[item.platform] ?? item.platform}</span>
            {active ? (
              <span className="account-hint">In use</span>
            ) : (
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  workspace.setPlatform(item.platform);
                  workspace.setPlayer(item.username);
                }}
              >
                Use
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function ChessComLink() {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState('');
  const [pending, setPending] = useState<{ username: string; code: string } | null>(null);
  const [linked, setLinked] = useState('');

  const code = useMutation({
    mutationFn: getChessComCode,
    onSuccess: (result) => {
      setPending(result);
      setLinked('');
    }
  });
  const verify = useMutation({
    mutationFn: verifyChessCom,
    onSuccess: async (result) => {
      setLinked(result.username);
      setPending(null);
      setUsername('');
      await queryClient.invalidateQueries({ queryKey: AUTH_KEY });
    }
  });
  const error = (code.error ?? verify.error) as Error | null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (username.trim()) code.mutate(username.trim());
  }

  return (
    <div className="account-link">
      <h3>Link a Chess.com player</h3>
      <p className="account-hint">Chess.com has no sign-in for other apps, so you prove the player is yours with a short code on your profile.</p>
      <form className="account-link-form" onSubmit={submit}>
        <label>
          <span>Chess.com username</span>
          <input
            value={username}
            onChange={(event) => {
              setUsername(event.target.value);
              setPending(null);
            }}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <button type="submit" className="secondary" disabled={!username.trim() || code.isPending}>
          {code.isPending && <Loader2 className="spin" size={14} />} Get a code
        </button>
      </form>
      {pending && (
        <div className="account-link-steps">
          <ol>
            <li>Copy this code: <code>{pending.code}</code></li>
            <li>Open your <a href="https://www.chess.com/settings/profile" target="_blank" rel="noreferrer">Chess.com profile settings</a> and paste it into Location. Save.</li>
            <li>Come back and check. You can remove the code afterwards.</li>
          </ol>
          <button type="button" className="primary" disabled={verify.isPending} onClick={() => verify.mutate(pending.username)}>
            {verify.isPending && <Loader2 className="spin" size={14} />} Check my profile
          </button>
        </div>
      )}
      {linked && <p className="account-hint" role="status">{linked} is now linked to your account.</p>}
      {error && <p className="account-error" role="alert">{error.message}</p>}
    </div>
  );
}

function SpeechPreference() {
  const speech = useSpeech();
  if (!speech.ttsSupported) return <p className="account-hint">This browser cannot read answers aloud.</p>;
  return (
    <label className="account-check">
      <input
        type="checkbox"
        checked={speech.speakEnabled}
        onChange={(event) => speech.setSpeakEnabled(event.target.checked)}
      />
      <span>Read coach answers aloud</span>
    </label>
  );
}
