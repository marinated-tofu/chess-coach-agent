import { useState } from 'react';
import { Loader2, Puzzle } from 'lucide-react';
import type { Platform, TrainingSession } from '../lib/types';
import { errorMessage } from '../lib/api';

type Props = {
  username: string;
  platform: Platform;
  /** Optional theme; the backend falls back to the player's top weakness. */
  theme?: string;
  positionCount?: number;
  onStarted: (session: TrainingSession) => void | Promise<void>;
};

/** Starts a practice session made only of library puzzles (mode "puzzles"). */
export function PuzzleModeButton({ username, platform, theme, positionCount = 5, onStarted }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function start() {
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/training/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          platform,
          theme: theme || null,
          position_count: positionCount,
          mode: 'puzzles'
        })
      });
      if (!response.ok) throw new Error(await errorMessage(response, 'Could not build a puzzle session'));
      await onStarted(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not build a puzzle session');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className="secondary" disabled={busy} onClick={start}>
        {busy ? <Loader2 className="spin" size={17} /> : <Puzzle size={17} />} Themed puzzles
      </button>
      {error && <p role="alert">{error}</p>}
    </>
  );
}
