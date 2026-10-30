import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { ArrowRight, Loader2, Timer } from 'lucide-react';
import { createTimeTrainerSession } from '../lib/api';
import { formatGameDate, getTimeTrainerStatus } from '../lib/libraryApi';
import type { EvaluationPanel, TimeTrainerResult } from '../lib/types';
import { useWorkspace } from '../workspace/WorkspaceContext';
import { EmptyState } from './EmptyState';
import { Skeleton } from './Skeleton';
import './TimeTrainer.css';

const VERDICT_LABEL: Record<string, string> = {
  best: 'Best move',
  good: 'Good move',
  inaccuracy: 'Inaccuracy',
  mistake: 'Mistake',
  blunder: 'Blunder',
  timed_out: 'Out of time',
  unavailable: 'No engine verdict'
};

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

export function TimeTrainerHome() {
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const hasPlayer = workspace.player.trim().length > 0;
  const status = useQuery({
    queryKey: ['time-trainer', workspace.platform, workspace.player],
    queryFn: () => getTimeTrainerStatus(workspace.player, workspace.platform),
    enabled: hasPlayer
  });

  async function start() {
    setBusy(true);
    setError('');
    try {
      const session = await createTimeTrainerSession(workspace.player, workspace.platform);
      await navigate({ to: '/practice/$sessionId', params: { sessionId: session.id } });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the time trainer');
      setBusy(false);
    }
  }

  if (status.isLoading) return <Skeleton lines={4} label="Checking your clock data" />;
  if (status.isError) return (
    <EmptyState
      icon={<Timer size={22} />}
      title="Your clock data didn’t load"
      action={<button className="primary" onClick={() => status.refetch()}>Try again</button>}
    />
  );
  const data = status.data;
  if (!data || data.status === 'no_clock_data') return (
    <EmptyState
      icon={<Timer size={22} />}
      title="No clock data yet"
      body="The time trainer needs move times, and your saved games don’t have any. Syncing from Chess.com or Lichess brings them in."
      action={<Link className="primary" to="/games" search={{ import: true }}>Sync your games</Link>}
    />
  );
  if (data.status === 'no_candidates') return (
    <EmptyState
      icon={<Timer size={22} />}
      title="No clock problems to train"
      body={`We checked ${data.clock_games.toLocaleString()} games and found no fast move that cost you and no long think in a quiet position.`}
      action={<Link className="primary" to="/practice">Back to practice</Link>}
    />
  );
  return (
    <section className="time-home">
      <div className="practice-queue-counts">
        <div>
          <strong>{data.rushed_count.toLocaleString()}</strong>
          <span>Fast moves that cost you</span>
        </div>
        <div>
          <strong>{data.burned_count.toLocaleString()}</strong>
          <span>Long thinks to review</span>
        </div>
      </div>
      <p>
        You get five positions from your last {data.clock_games.toLocaleString()} games with clocks. Each one has a countdown
        set from your pace in that game: longer where the position was critical, short where a sound move was easy to find.
      </p>
      <div className="practice-start-actions">
        <button className="primary" disabled={busy} onClick={start}>
          {busy ? <Loader2 className="spin" size={17} /> : <ArrowRight size={17} />} Start time trainer
        </button>
      </div>
      {error && <p className="route-status error" role="alert">{error}</p>}
      <p className="time-home-note">Stockfish checks each position before you see it and grades your move afterwards.</p>
    </section>
  );
}

/** Runs against a wall-clock deadline, so a throttled background tab still flags on time. */
export function Countdown({ deadline, totalSeconds, stoppedAt, onExpire }: {
  deadline: number;
  totalSeconds: number;
  /** Set once a move is in; the display freezes there. */
  stoppedAt: number | null;
  onExpire: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const expired = useRef(false);
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;

  useEffect(() => {
    if (stoppedAt != null) return;
    const tick = () => {
      const current = Date.now();
      setNow(current);
      if (current >= deadline && !expired.current) {
        expired.current = true;
        onExpireRef.current();
      }
    };
    tick();
    const interval = window.setInterval(tick, 100);
    return () => window.clearInterval(interval);
  }, [deadline, stoppedAt]);

  const remaining = Math.max(0, (deadline - (stoppedAt ?? now)) / 1000);
  const share = Math.min(1, remaining / totalSeconds);
  const tone = share <= 0.15 ? 'low' : share <= 0.4 ? 'warn' : 'ok';
  return (
    <div className={`time-countdown ${tone}`} role="timer" aria-label={`${Math.ceil(remaining)} seconds left`}>
      <strong>{clock(Math.ceil(remaining))}</strong>
      <div className="time-countdown-track" aria-hidden="true">
        <span style={{ transform: `scaleX(${share})` }} />
      </div>
    </div>
  );
}

function ClockRow({ label, detail, seconds, move, verdict }: {
  label: string;
  detail?: string;
  seconds: number | null;
  move: string;
  verdict: string;
}) {
  return (
    <tr>
      <th scope="row">{label}{detail && <small>{detail}</small>}</th>
      <td className="time-seconds">{seconds == null ? '–' : `${seconds.toFixed(1)}s`}</td>
      <td>{move || '–'}</td>
      <td>{VERDICT_LABEL[verdict] ?? verdict}</td>
    </tr>
  );
}

function gameDetail(result: TimeTrainerResult) {
  const parts = [
    result.opponent && `vs ${result.opponent}`,
    result.move_number > 0 && `move ${result.move_number}`,
    formatGameDate(result.played_at)
  ];
  return parts.filter(Boolean).join(', ');
}

/** Original clock use, this attempt and Stockfish's verdict, side by side. */
export function TimeTrainerVerdict({ evaluation, result }: {
  evaluation: EvaluationPanel;
  result: TimeTrainerResult;
}) {
  const good = result.verdict === 'best' || result.verdict === 'good';
  const cost = evaluation.cp_loss == null ? '' : ` · ${evaluation.cp_loss.toFixed(2)} pawn loss`;
  return (
    <div className="time-verdict">
      <div className={`evaluation-status ${good ? 'correct' : 'incorrect'}`}>
        <strong>{VERDICT_LABEL[result.verdict]}</strong>
        <span className="practice-best">Stockfish: {evaluation.best_move}{cost}</span>
      </div>
      <p className="time-verdict-kind">
        {result.kind === 'rushed'
          ? `Critical position. Your clock for it was ${result.budget_seconds}s.`
          : `Simple position. Your clock for it was ${result.budget_seconds}s.`}
      </p>
      <table className="time-compare">
        <thead>
          <tr><th scope="col" aria-label="When" /><th scope="col">Time</th><th scope="col">Move</th><th scope="col">Stockfish</th></tr>
        </thead>
        <tbody>
          <ClockRow
            label="In your game"
            detail={gameDetail(result)}
            seconds={result.original_seconds}
            move={result.played_san}
            verdict={result.played_verdict}
          />
          <ClockRow
            label="Just now"
            seconds={result.timed_out ? result.budget_seconds : result.attempt_seconds}
            move={evaluation.submitted_move}
            verdict={result.verdict}
          />
        </tbody>
      </table>
      <p>{evaluation.explanation}</p>
    </div>
  );
}
