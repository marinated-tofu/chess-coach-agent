import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { Activity, ArrowRight, BarChart3, Info, Loader2, Target, TimerReset } from 'lucide-react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';
import { createTrainingSession, getProgress } from '../lib/api';
import {
  formatGameDate,
  formatMonth,
  getLibraryProgress,
  themeLabel,
  TIME_CLASSES,
  timeClassLabel,
  type TimeClass
} from '../lib/libraryApi';
import { EmptyState } from '../components/EmptyState';
import { OpeningsPanel } from '../components/OpeningsPanel';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './ProgressPage.css';

const MAX_TICKS = 8;

function toTime(date: string) {
  const [year, month, day] = date.split('-').map(Number);
  return Date.UTC(year, month - 1, day);
}

/** First-of-month ticks between two timestamps, thinned to at most MAX_TICKS labels. */
function monthTicks(start: number, end: number): number[] {
  const first = new Date(start);
  const ticks: number[] = [];
  let year = first.getUTCFullYear();
  let month = first.getUTCMonth() + 1;
  for (;;) {
    if (month > 11) { month = 0; year += 1; }
    const tick = Date.UTC(year, month, 1);
    if (tick > end) break;
    ticks.push(tick);
    month += 1;
  }
  if (ticks.length <= MAX_TICKS) return ticks;
  // Keep every 2nd, 3rd, 6th or 12th month so labels stay evenly spaced.
  const step = [2, 3, 6, 12].find((value) => ticks.length / value <= MAX_TICKS) ?? Math.ceil(ticks.length / MAX_TICKS);
  return ticks.filter((tick) => new Date(tick).getUTCMonth() % step === 0);
}

function RatingTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: { time: number; rating: number } }> }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="progress-tooltip">
      <strong>{point.rating.toLocaleString()}</strong>
      <span>{formatGameDate(new Date(point.time).toISOString())}</span>
    </div>
  );
}

export function ProgressPage() {
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const progress = useQuery({
    queryKey: ['progress', workspace.platform, workspace.player],
    queryFn: () => getProgress(workspace.player, workspace.platform)
  });
  const library = useQuery({
    queryKey: ['library-progress', workspace.platform, workspace.player],
    queryFn: () => getLibraryProgress(workspace.player, workspace.platform),
    enabled: workspace.player.trim().length > 0
  });
  const data = progress.data;
  const series = library.data?.rating_series ?? {};
  const available = TIME_CLASSES.filter((name) => (series[name]?.length ?? 0) > 1);
  const busiest = [...available].sort((a, b) => (series[b]?.length ?? 0) - (series[a]?.length ?? 0))[0];
  const [picked, setPicked] = useState<TimeClass | null>(null);
  const timeClass = picked && available.includes(picked) ? picked : busiest;
  const points = useMemo(
    () => (timeClass ? series[timeClass] ?? [] : []).map((point) => ({ time: toTime(point.date), rating: point.rating })),
    [series, timeClass]
  );
  const ticks = useMemo(
    () => (points.length ? monthTicks(points[0].time, points[points.length - 1].time) : []),
    [points]
  );
  const blindspots = library.data?.blindspots ?? [];
  const [practicing, setPracticing] = useState('');

  async function practiceTheme(theme: string) {
    setPracticing(theme);
    try {
      const session = await createTrainingSession(workspace.player, workspace.platform, theme);
      await navigate({ to: '/practice/$sessionId', params: { sessionId: session.id } });
    } finally {
      setPracticing('');
    }
  }

  const totalGames = library.data?.total_games ?? data?.total_games;
  const loading = library.isPending && library.fetchStatus !== 'idle';

  return (
    <main className="route-page progress-page">
      <PageHeader
        eyebrow="Learning outcomes"
        title="Progress"
        detail={`Game trends and practice results for ${workspace.player}.`}
      />
      <div className="progress-metrics">
        <div><Activity size={18} /><strong>{totalGames == null ? '–' : totalGames.toLocaleString()}</strong><span>Games analyzed</span></div>
        <div><Target size={18} /><strong>{(data?.recent_attempts ?? 0).toLocaleString()}</strong><span>Practice attempts</span></div>
        <div>
          <BarChart3 size={18} />
          <strong>{data?.transfer_score == null ? '–' : `${Math.round(data.transfer_score * 100)}%`}</strong>
          <span className="progress-metric-label">
            Fixed in real games
            <span
              className="progress-info"
              tabIndex={0}
              role="note"
              aria-label="Average of your practice accuracy and how rarely these mistakes show up in your recent games."
              title="Average of your practice accuracy and how rarely these mistakes show up in your recent games."
            ><Info size={13} /></span>
          </span>
        </div>
        <div><TimerReset size={18} /><strong>{(data?.player.due_positions ?? 0).toLocaleString()}</strong><span>Positions due</span></div>
      </div>
      <section className="progress-band">
        <div className="progress-chart">
          <div className="progress-chart-head">
            <h2>Rating over time</h2>
            {available.length > 1 && (
              <div className="progress-toggle" role="group" aria-label="Time control">
                {available.map((name) => {
                  const last = series[name]?.[series[name]!.length - 1];
                  return (
                    <button key={name} type="button" aria-pressed={timeClass === name} onClick={() => setPicked(name)}>
                      {timeClassLabel(name)}
                      {last && <span>{last.rating.toLocaleString()}</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          {loading ? (
            <Skeleton variant="card" label="Loading rating history" />
          ) : points.length > 1 ? (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={points} margin={{ top: 12, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid stroke="var(--gray-100)" vertical={false} />
                <XAxis
                  dataKey="time"
                  type="number"
                  scale="time"
                  domain={['dataMin', 'dataMax']}
                  ticks={ticks}
                  tickFormatter={formatMonth}
                  tick={{ fontSize: 12, fill: 'var(--gray-500)' }}
                  tickLine={false}
                  axisLine={{ stroke: 'var(--gray-150)' }}
                  minTickGap={12}
                />
                <YAxis
                  domain={[(min: number) => Math.floor((min - 10) / 50) * 50, (max: number) => Math.ceil((max + 10) / 50) * 50]}
                  tickCount={5}
                  tick={{ fontSize: 12, fill: 'var(--gray-500)' }}
                  tickFormatter={(value: number) => Math.round(value).toLocaleString()}
                  tickLine={false}
                  axisLine={false}
                  width={48}
                  allowDecimals={false}
                />
                <Tooltip content={<RatingTooltip />} />
                <Line
                  type="monotone"
                  dataKey="rating"
                  stroke="var(--green-500)"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="monitoring-empty">Rating history appears after online games are analyzed.</p>
          )}
          {timeClass && points.length > 1 && (
            <p className="progress-chart-note">
              {timeClassLabel(timeClass)} rating after your last game each day, {points.length.toLocaleString()} days with games.
            </p>
          )}
        </div>
        <div className="theme-table progress-blindspots">
          <h2>Recurring blindspots</h2>
          <p className="progress-blindspots-note">Share of your games with at least one mistake of this kind.</p>
          {loading ? <Skeleton lines={5} label="Loading blindspots" /> : blindspots.length ? (
            <ul>
              {blindspots.slice(0, 8).map((spot) => (
                <li key={spot.theme}>
                  <div className="progress-blindspot-text">
                    <span>{themeLabel(spot.theme)}</span>
                    <small>{spot.games.toLocaleString()} games · {spot.moments.toLocaleString()} moments</small>
                  </div>
                  <strong>{Math.round(spot.pct_of_games)}%</strong>
                  <button
                    type="button"
                    className="ghost progress-practice"
                    disabled={Boolean(practicing)}
                    onClick={() => void practiceTheme(spot.theme)}
                    aria-label={`Practice ${themeLabel(spot.theme).toLowerCase()}`}
                  >
                    {practicing === spot.theme ? <Loader2 className="spin" size={14} /> : <ArrowRight size={14} />}
                    Practice
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No blindspots yet" body="Analyze a few games and the mistakes you repeat show up here." />
          )}
        </div>
      </section>
      <OpeningsPanel username={workspace.player} platform={workspace.platform} />
    </main>
  );
}
