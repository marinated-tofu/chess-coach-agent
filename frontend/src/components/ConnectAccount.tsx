import { useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useRouterState } from '@tanstack/react-router';
import { ArrowRight, Loader2 } from 'lucide-react';
import { getSample } from '../lib/api';
import { lichessLoginUrl } from '../lib/authApi';
import { getToday, todayKey } from '../lib/todayApi';
import type { Platform } from '../lib/types';
import { useWorkspace } from '../workspace/WorkspaceContext';

const PLATFORMS: { value: Platform; label: string }[] = [
  { value: 'chess.com', label: 'Chess.com' },
  { value: 'lichess', label: 'Lichess' }
];

// Enough analyzed games for the latest one to be worth opening before the sync ends.
const EARLY_GAMES = 10;

function isRunning(status: string) {
  return status === 'queued' || status === 'fetching' || status === 'analyzing';
}

/** First-run card: pick a platform and username, then watch the import progress in place. */
export function ConnectAccount() {
  const workspace = useWorkspace();
  const { syncJob } = workspace;
  const running = isRunning(syncJob.status);
  return (
    <section className="connect-card" aria-labelledby="connect-title">
      {running ? <SyncProgress /> : <ConnectForm key={`${workspace.platform}:${workspace.player}`} />}
      {!running && <ConnectAlternatives />}
    </section>
  );
}

function ConnectForm() {
  const workspace = useWorkspace();
  const [platform, setPlatform] = useState<Platform>(workspace.platform);
  const [username, setUsername] = useState(workspace.player);
  const [formError, setFormError] = useState('');
  const { syncJob } = workspace;
  const failed = syncJob.status === 'failed'
    ? syncJob.error
    : syncJob.status === 'complete' && syncJob.total === 0
      ? `No games found for ${syncJob.player} on ${syncJob.platform === 'lichess' ? 'Lichess' : 'Chess.com'}.`
      : '';
  const error = formError || failed;

  function submit(event: FormEvent) {
    event.preventDefault();
    const name = username.trim();
    if (!name) {
      setFormError(`Enter your ${platform === 'lichess' ? 'Lichess' : 'Chess.com'} username.`);
      return;
    }
    setFormError('');
    void workspace.startSync(name, platform);
  }

  return (
    <>
      <h1 id="connect-title">Review your own games</h1>
      <p className="connect-lede">
        Enter your Chess.com or Lichess username. We import your games and find the moves that cost you the most.
      </p>
      <form className="connect-form" onSubmit={submit} noValidate>
        <div className="connect-segmented" role="radiogroup" aria-label="Platform">
          {PLATFORMS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="radio"
              aria-checked={platform === item.value}
              className={platform === item.value ? 'active' : ''}
              onClick={() => setPlatform(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <label className="connect-field">
          <span>Username</span>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoCapitalize="none"
            autoCorrect="off"
            autoComplete="username"
            spellCheck={false}
            enterKeyHint="go"
            aria-invalid={Boolean(error)}
            aria-describedby={error ? 'connect-error' : undefined}
          />
        </label>
        {error && <p id="connect-error" className="connect-error" role="alert">{error}</p>}
        <button className="primary connect-submit" type="submit">Import my games</button>
      </form>
    </>
  );
}

function SyncProgress() {
  const navigate = useNavigate();
  const { syncJob } = useWorkspace();
  const fetching = syncJob.status !== 'analyzing' || syncJob.total === 0;
  const latest = useQuery({
    queryKey: todayKey(syncJob.platform, syncJob.player),
    queryFn: () => getToday(syncJob.player, syncJob.platform),
    enabled: syncJob.analyzed >= EARLY_GAMES
  });
  const latestGame = syncJob.analyzed >= EARLY_GAMES ? latest.data?.latest_game : null;
  const checking = Math.min(syncJob.done + 1, syncJob.total);
  const percent = syncJob.total ? Math.round((syncJob.done / syncJob.total) * 100) : 0;

  return (
    <>
      <h1 id="connect-title">Importing your games</h1>
      <p className="connect-lede">
        {fetching
          ? `Fetching ${syncJob.player}'s games from ${syncJob.platform === 'lichess' ? 'Lichess' : 'Chess.com'}.`
          : `Checking game ${checking.toLocaleString()} of ${syncJob.total.toLocaleString()}.`}
      </p>
      <div
        className={fetching ? 'connect-progress indeterminate' : 'connect-progress'}
        role="progressbar"
        aria-label="Import progress"
        aria-valuemin={0}
        aria-valuemax={syncJob.total || undefined}
        aria-valuenow={fetching ? undefined : syncJob.done}
      >
        <span style={{ transform: `scaleX(${fetching ? 0.3 : percent / 100})` }} />
      </div>
      <p className="connect-note num">
        {fetching
          ? 'You can leave this page. The import keeps running.'
          : `${syncJob.analyzed.toLocaleString()} analyzed · ${percent}%. You can leave this page.`}
      </p>
      {latestGame && (
        <button
          className="secondary connect-latest"
          onClick={() => navigate({ to: '/games/$gameId', params: { gameId: latestGame.game_id }, search: { moment: latestGame.first_moment?.id } })}
        >
          Open your latest game <ArrowRight size={16} />
        </button>
      )}
    </>
  );
}

function ConnectAlternatives() {
  const workspace = useWorkspace();
  const currentPath = useRouterState({ select: (state) => state.location.href });
  const [loadingSample, setLoadingSample] = useState(false);
  const [sampleError, setSampleError] = useState('');

  async function trySample() {
    setLoadingSample(true);
    setSampleError('');
    try {
      const sample = await getSample();
      workspace.setPlatform('chess.com');
      workspace.setPlayer(sample.player);
    } catch {
      setSampleError('Could not load the sample player.');
    } finally {
      setLoadingSample(false);
    }
  }

  return (
    <nav className="connect-alternatives" aria-label="Other ways to start">
      <a href={lichessLoginUrl(currentPath)}>Sign in with Lichess</a>
      <Link to="/games" search={{ import: true }}>Paste a PGN instead</Link>
      <button type="button" onClick={trySample} disabled={loadingSample}>
        {loadingSample && <Loader2 className="spin" size={14} />} Try with a sample player
      </button>
      {sampleError && <span className="connect-error" role="alert">{sampleError}</span>}
    </nav>
  );
}
