import { useEffect, useRef, useState } from 'react';
import { Link } from '@tanstack/react-router';
import { AlertCircle, CheckCircle2, LoaderCircle, X } from 'lucide-react';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './AppNav.css';

type Phase = 'idle' | 'running' | 'done' | 'failed';

const DONE_VISIBLE_MS = 12_000;
const RUNNING = new Set(['queued', 'fetching', 'analyzing']);

/**
 * Reports background work from workspace state, so it keeps showing while the user moves
 * between pages. Game sync reads `syncJob`; a pasted-PGN analysis (no job) reads `loading`.
 */
export function SyncToast() {
  const { syncJob, loading, status, error, activeGameId } = useWorkspace();
  const syncRunning = RUNNING.has(syncJob.status);
  const busy = syncRunning || (loading && syncJob.status !== 'complete' && syncJob.status !== 'failed');
  const [phase, setPhase] = useState<Phase>(busy ? 'running' : 'idle');
  const wasBusy = useRef(busy);

  useEffect(() => {
    if (busy) setPhase('running');
    else if (wasBusy.current && !loading) {
      setPhase(syncJob.status === 'failed' || error ? 'failed' : 'done');
    }
    // Stay "busy" until the library refresh after the job finishes (loading drops last).
    wasBusy.current = busy || (wasBusy.current && loading);
  }, [busy, loading, syncJob.status, error]);

  useEffect(() => {
    if (phase !== 'done') return;
    const timer = window.setTimeout(() => setPhase('idle'), DONE_VISIBLE_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  let message = '';
  if (phase === 'running') {
    if (!syncRunning) message = status;
    else if (syncJob.total > 0) {
      message = `Syncing games ${Math.min(syncJob.done, syncJob.total).toLocaleString()}/${syncJob.total.toLocaleString()}`;
    } else message = syncJob.status === 'queued' ? 'Sync queued' : 'Fetching your games';
  } else if (phase === 'done') {
    if (syncJob.status === 'complete') {
      const count = syncJob.analyzed;
      message = count > 0
        ? `Imported ${count.toLocaleString()} new ${count === 1 ? 'game' : 'games'}.`
        : 'No new games. Your library is up to date.';
    } else message = status;
  } else if (phase === 'failed') {
    message = syncJob.error || error || 'Sync failed.';
  }

  return (
    <div className="toast-region" role="status" aria-live="polite">
      {phase !== 'idle' && (
        <div className={`toast toast-${phase}`}>
          {phase === 'running' && <LoaderCircle size={18} className="spin" aria-hidden />}
          {phase === 'done' && <CheckCircle2 size={18} aria-hidden />}
          {phase === 'failed' && <AlertCircle size={18} aria-hidden />}
          <div className="toast-text">
            <p>{message}</p>
            {phase === 'done' && activeGameId && (
              <Link
                to="/games/$gameId"
                params={{ gameId: activeGameId }}
                search={{ moment: undefined }}
                className="toast-action"
                onClick={() => setPhase('idle')}
              >
                Review latest
              </Link>
            )}
          </div>
          {phase !== 'running' && (
            <button type="button" className="toast-close" aria-label="Dismiss" onClick={() => setPhase('idle')}>
              <X size={16} aria-hidden />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
