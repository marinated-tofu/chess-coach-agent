import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { AlertCircle, ArrowRight, Lightbulb, Loader2 } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';
import { createTrainingSession } from '../lib/api';
import {
  getInsights,
  type InsightsResponse,
  type Leak,
  type PhaseRow,
  type ScheduleBreakdown,
  type ScheduleRow
} from '../lib/insightsApi';
import { PageHeader } from '../components/PageHeader';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './InsightsPage.css';

const RANGES = [
  { value: 100, label: 'Last 100' },
  { value: 500, label: 'Last 500' },
  { value: 3000, label: 'All' }
];

// SVG presentation attributes read CSS variables, so the charts use the same tokens as the CSS.
const SEVERITY = {
  inaccuracy: 'var(--amber-300)',
  mistake: 'var(--amber-600)',
  blunder: 'var(--red-600)'
};
const CHART = {
  grid: 'var(--gray-100)',
  tick: 'var(--gray-600)',
  tickMuted: 'var(--gray-500)',
  reference: 'var(--gray-300)',
  cursor: 'rgb(var(--shadow-rgb) / 0.04)',
  bar: 'var(--green-500)',
  barThin: 'var(--gray-200)',
  barStroke: 'var(--gray-0)'
};

const PHASE_LABEL: Record<string, string> = {
  opening: 'Opening',
  middlegame: 'Middlegame',
  endgame: 'Endgame'
};

const fmt = (value: number | null | undefined, digits = 1, suffix = '') =>
  value == null ? '–' : `${value.toFixed(digits)}${suffix}`;

const count = (value: number) => value.toLocaleString('en-US');

function SampleNote({ n, unit = 'games' }: { n: number; unit?: string }) {
  return <span className="insights-sample">Based on {count(n)} {unit}</span>;
}

function SectionHead({ title, n, unit }: { title: string; n: number; unit?: string }) {
  return (
    <header className="insights-section-head">
      <h2>{title}</h2>
      <SampleNote n={n} unit={unit} />
    </header>
  );
}

function LeakCard({ leak, rank, username, platform }: {
  leak: Leak;
  rank: number;
  username: string;
  platform: InsightsResponse['platform'];
}) {
  const navigate = useNavigate();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');

  async function practice() {
    if (!leak.action.theme) return;
    setStarting(true);
    setError('');
    try {
      const session = await createTrainingSession(
        username,
        platform as 'chess.com' | 'lichess',
        leak.action.theme
      );
      await navigate({ to: '/practice/$sessionId', params: { sessionId: session.id } });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start practice');
      setStarting(false);
    }
  }

  return (
    <article className="leak-card">
      <div className="leak-top">
        <span className="leak-rank">{rank}</span>
        <div className="leak-cost">
          <strong>{leak.points_per_10_games.toFixed(1)}</strong>
          <span>points lost per 10 games</span>
        </div>
      </div>
      <h3>{leak.title}</h3>
      <p>{leak.detail}</p>
      <div className="leak-action">
        {leak.action.type === 'practice' ? (
          <button className={`${rank === 1 ? 'primary' : 'secondary'} leak-button`} onClick={practice} disabled={starting}>
            {starting ? <Loader2 className="spin" size={16} /> : <ArrowRight size={16} />}
            {leak.action.label}
          </button>
        ) : (
          <Link className="secondary leak-button" to="/progress">
            <ArrowRight size={16} /> {leak.action.label}
          </Link>
        )}
        {leak.action.theme && (
          <Link
            className="leak-examples"
            to="/games"
            search={{ import: false, theme: leak.action.theme } as { import: boolean }}
          >
            See examples
          </Link>
        )}
        {error && <span className="leak-error" role="alert"><AlertCircle size={14} /> {error}</span>}
      </div>
    </article>
  );
}

function PhaseTooltip({ active, payload }: {
  active?: boolean;
  payload?: { payload: PhaseRow }[];
}) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="insights-tooltip">
      <strong>{PHASE_LABEL[row.phase]}</strong>
      <span><i style={{ background: SEVERITY.blunder }} />Blunders {row.blunders_per_game.toFixed(2)}</span>
      <span><i style={{ background: SEVERITY.mistake }} />Mistakes {row.mistakes_per_game.toFixed(2)}</span>
      <span><i style={{ background: SEVERITY.inaccuracy }} />Inaccuracies {row.inaccuracies_per_game.toFixed(2)}</span>
      <span>per game, over {count(row.games)} games</span>
    </div>
  );
}

function PhaseSection({ data }: { data: InsightsResponse }) {
  const rows = data.phases.rows;
  const worst = [...rows].sort((a, b) => b.blunders_per_game - a.blunders_per_game)[0];
  const lowAcc = [...rows]
    .filter((row) => row.accuracy != null)
    .sort((a, b) => (a.accuracy ?? 0) - (b.accuracy ?? 0))[0];
  return (
    <section className="insights-section">
      <SectionHead title="By game phase" n={data.phases.sample_size} />
      <p className="insights-summary">
        You blunder most often in the {worst.phase}: {worst.blunders_per_game.toFixed(2)} blunders in
        each game that reaches it
        {lowAcc && data.phases.accuracy_sample_size >= data.min_sample
          ? `. Your accuracy is lowest in the ${lowAcc.phase} (${fmt(lowAcc.accuracy)}).`
          : '.'}
      </p>
      <div className="insights-split">
        <div className="insights-chart" role="img" aria-label="Errors per game by phase, stacked by severity">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="28%">
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="phase" tickFormatter={(value: string) => PHASE_LABEL[value]} tick={{ fontSize: 12, fill: CHART.tick }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: CHART.tickMuted }} axisLine={false} tickLine={false} width={34} tickCount={4} allowDecimals tickFormatter={(value: number) => value.toFixed(1)} />
              <Tooltip content={<PhaseTooltip />} cursor={{ fill: CHART.cursor }} />
              <Bar isAnimationActive={false} dataKey="blunders_per_game" stackId="e" fill={SEVERITY.blunder} stroke={CHART.barStroke} strokeWidth={2} />
              <Bar isAnimationActive={false} dataKey="mistakes_per_game" stackId="e" fill={SEVERITY.mistake} stroke={CHART.barStroke} strokeWidth={2} />
              <Bar isAnimationActive={false} dataKey="inaccuracies_per_game" stackId="e" fill={SEVERITY.inaccuracy} stroke={CHART.barStroke} strokeWidth={2} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="insights-legend" aria-hidden="true">
            <span><i style={{ background: SEVERITY.blunder }} />Blunders</span>
            <span><i style={{ background: SEVERITY.mistake }} />Mistakes</span>
            <span><i style={{ background: SEVERITY.inaccuracy }} />Inaccuracies</span>
          </div>
        </div>
        <table className="insights-table">
          <thead>
            <tr><th>Phase</th><th>Errors / game</th><th>Blunders / game</th><th>Accuracy</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.phase}>
                <th scope="row">{PHASE_LABEL[row.phase]}</th>
                <td>{row.errors_per_game.toFixed(2)}</td>
                <td>{row.blunders_per_game.toFixed(2)}</td>
                <td>{data.phases.accuracy_sample_size >= data.min_sample ? fmt(row.accuracy) : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="insights-footnote">
        Errors come from all {count(data.phases.sample_size)} games. Accuracy uses the{' '}
        {count(data.phases.accuracy_sample_size)} games with move-by-move engine data.
      </p>
    </section>
  );
}

function TimeSection({ data }: { data: InsightsResponse }) {
  const { time, min_sample } = data;
  const pressure = Object.fromEntries(time.pressure.map((row) => [row.state, row]));
  const hasClock = time.sample_size >= min_sample;
  const controls = time.by_control.filter((row) => row.games > 0);
  return (
    <section className="insights-section">
      <SectionHead title="By time control" n={time.by_control_sample_size} />
      <table className="insights-table wide">
        <thead>
          <tr><th>Time control</th><th>Games</th><th>Score</th><th>Accuracy</th><th>Blunders / game</th></tr>
        </thead>
        <tbody>
          {controls.map((row) => (
            <tr key={row.category}>
              <th scope="row">{row.category.charAt(0).toUpperCase() + row.category.slice(1)}</th>
              <td>{count(row.games)}</td>
              <td>{fmt(row.score_pct, 1, '%')}</td>
              <td>{row.accuracy_games >= min_sample ? fmt(row.accuracy) : '–'}</td>
              <td>{row.blunders_per_game.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {hasClock && (
        <div className="insights-tiles">
          <div className="insights-tile">
            <span>Accuracy under 10% clock</span>
            <strong>{fmt(pressure.time_pressure?.accuracy)}</strong>
            <small>vs {fmt(pressure.normal?.accuracy)} otherwise</small>
          </div>
          <div className="insights-tile">
            <span>Blunders per 100 moves in time trouble</span>
            <strong>{fmt(pressure.time_pressure?.blunders_per_100_moves)}</strong>
            <small>vs {fmt(pressure.normal?.blunders_per_100_moves)} otherwise</small>
          </div>
          <div className="insights-tile">
            <span>Time on moves that went wrong</span>
            <strong>{fmt(time.time_spent.avg_seconds_critical, 1, 's')}</strong>
            <small>vs {fmt(time.time_spent.avg_seconds_all, 1, 's')} on an average move</small>
          </div>
          {time.lost_on_time.sample_size >= min_sample && (
            <div className="insights-tile">
              <span>Losses on time</span>
              <strong>{fmt(time.lost_on_time.pct_of_losses, 0, '%')}</strong>
              <small>{time.lost_on_time.lost_on_time} of {time.lost_on_time.losses} losses</small>
            </div>
          )}
          <SampleNote n={time.sample_size} unit="games with clock data" />
        </div>
      )}
      <Link className="insights-time-link" to="/practice" search={{ mode: 'time' }}>
        Train your time use on positions from your games <ArrowRight size={15} />
      </Link>
    </section>
  );
}

function OpponentSection({ data }: { data: InsightsResponse }) {
  const rows = data.opponents.rows.filter((row) => row.games > 0);
  const best = [...rows].sort((a, b) => (b.score_pct ?? 0) - (a.score_pct ?? 0))[0];
  return (
    <section className="insights-section">
      <SectionHead title="By opponent rating" n={data.opponents.sample_size} />
      {best && <p className="insights-summary">You score best against opponents rated {best.label.toLowerCase()} ({fmt(best.score_pct, 0, '%')}).</p>}
      <div className="insights-chart" role="img" aria-label="Score percentage by opponent rating difference">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data.opponents.rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: CHART.tick }} axisLine={false} tickLine={false} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: CHART.tickMuted }} axisLine={false} tickLine={false} width={40} unit="%" />
            <ReferenceLine y={50} stroke={CHART.reference} strokeDasharray="3 3" />
            <Tooltip
              cursor={{ fill: CHART.cursor }}
              formatter={(value) => [`${value}%`, 'Score']}
              labelFormatter={(label) => `Opponent ${String(label)}`}
            />
            <Bar isAnimationActive={false} dataKey="score_pct" fill={CHART.bar} radius={[4, 4, 0, 0]} maxBarSize={56} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function ColorSection({ data }: { data: InsightsResponse }) {
  const showAccuracy = data.colors.accuracy_sample_size >= data.min_sample;
  return (
    <section className="insights-section">
      <SectionHead title="By color" n={data.colors.sample_size} />
      <div className="insights-tiles two">
        {data.colors.rows.map((row) => (
          <div className="insights-tile" key={row.color}>
            <span className={`color-chip ${row.color}`}>{row.color === 'white' ? 'White' : 'Black'}</span>
            <strong>{fmt(row.score_pct, 1, '%')}</strong>
            <small>
              {count(row.wins)}W {count(row.draws)}D {count(row.losses)}L
              {showAccuracy && row.accuracy != null ? ` · ${fmt(row.accuracy)} accuracy` : ''}
            </small>
          </div>
        ))}
      </div>
    </section>
  );
}

function ScheduleTooltip({ active, payload, minSample }: {
  active?: boolean;
  payload?: { payload: ScheduleRow }[];
  minSample: number;
}) {
  const row = payload?.[0]?.payload;
  if (!active || !row || !row.games) return null;
  return (
    <div className="insights-tooltip">
      <strong>{row.label}</strong>
      <span>Score {fmt(row.score_pct, 0, '%')}, likely {fmt(row.score_low_pct, 0)}-{fmt(row.score_high_pct, 0, '%')}</span>
      <span>{row.games < minSample ? `Only ${row.games} of the ${minSample} games needed` : `${count(row.games)} games`}</span>
    </div>
  );
}

function ScheduleBlock({ title, name, plural, breakdown, minSample }: {
  title: string;
  name: string;
  plural: string;
  breakdown: ScheduleBreakdown;
  minSample: number;
}) {
  const best = breakdown.rows.find((row) => row.key === breakdown.best);
  const worst = breakdown.rows.find((row) => row.key === breakdown.worst);
  const showAccuracy = breakdown.rows.some((row) => row.accuracy_games >= minSample);
  return (
    <div className="schedule-block">
      <h3>{title}</h3>
      <p className="schedule-verdict">
        {best && worst
          ? `${best.label.split(' ')[0]} beats ${worst.label.split(' ')[0]}: ${fmt(best.score_pct, 0, '%')} against ${fmt(worst.score_pct, 0, '%')}.`
          : `No clear gap between ${plural} yet.`}
      </p>
      <div className="insights-chart" role="img" aria-label={`Score percentage by ${name}. Grey bars have fewer than ${minSample} games.`}>
        <ResponsiveContainer width="100%" height={170}>
          <BarChart data={breakdown.rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="label" tickFormatter={(value: string) => value.split(' ')[0]} tick={{ fontSize: 11, fill: CHART.tick }} axisLine={false} tickLine={false} interval={0} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: CHART.tickMuted }} axisLine={false} tickLine={false} width={40} unit="%" />
            <ReferenceLine y={50} stroke={CHART.reference} strokeDasharray="3 3" />
            <Tooltip content={<ScheduleTooltip minSample={minSample} />} cursor={{ fill: CHART.cursor }} />
            <Bar isAnimationActive={false} dataKey="score_pct" radius={[4, 4, 0, 0]} maxBarSize={44}>
              {breakdown.rows.map((row) => <Cell key={row.key} fill={row.low_sample ? CHART.barThin : CHART.bar} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="schedule-table">
      <table className="insights-table">
        <thead>
          <tr>
            <th>{title.replace('By ', '').replace(/^./, (letter) => letter.toUpperCase())}</th>
            <th>Games</th><th>Score</th><th>Likely range</th>
            {showAccuracy && <th>Accuracy</th>}
            <th>Blunders / game</th>
          </tr>
        </thead>
        <tbody>
          {breakdown.rows.map((row) => (
            <tr key={row.key} className={row.low_sample ? 'schedule-thin' : undefined}>
              <th scope="row">{row.label}</th>
              <td>{count(row.games)}</td>
              <td>{fmt(row.score_pct, 0, '%')}</td>
              <td>{row.score_low_pct == null ? '–' : `${fmt(row.score_low_pct, 0)}-${fmt(row.score_high_pct, 0, '%')}`}</td>
              {showAccuracy && <td>{row.accuracy_games >= minSample ? fmt(row.accuracy) : '–'}</td>}
              <td>{row.games ? row.blunders_per_game.toFixed(2) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function ScheduleSection({ data }: { data: InsightsResponse }) {
  const { schedule, min_sample } = data;
  return (
    <section className="insights-section">
      <SectionHead title="By time of day and weekday" n={schedule.sample_size} unit="games with a start time" />
      <div className="schedule-grid">
        <ScheduleBlock title="By time of day" name="time of day" plural="times of day" breakdown={schedule.by_time_of_day} minSample={min_sample} />
        <ScheduleBlock title="By weekday" name="weekday" plural="weekdays" breakdown={schedule.by_day_of_week} minSample={min_sample} />
      </div>
      <p className="insights-footnote">
        Times are in {schedule.timezone.replace(/_/g, ' ')}. Grey rows have fewer than {min_sample} games.
        Likely range is the 95% interval on your score: if two ranges overlap, the gap may be chance.
        {schedule.undated_games > 0 && ` ${count(schedule.undated_games)} of ${count(schedule.sample_size + schedule.undated_games)} games have no start time and are left out; a re-sync adds it.`}
      </p>
    </section>
  );
}

function ConversionSection({ data }: { data: InsightsResponse }) {
  const c = data.conversion;
  return (
    <section className="insights-section">
      <SectionHead title="Winning and losing positions" n={c.sample_size} />
      <div className="insights-tiles two">
        <div className="insights-tile">
          <span>Winning positions you didn't win</span>
          <strong>{fmt(c.failed_conversion_pct, 0, '%')}</strong>
          <small>{c.failed_conversions} of {c.winning_games} games where you were up about +3</small>
        </div>
        <div className="insights-tile">
          <span>Lost positions you saved</span>
          <strong>{fmt(c.save_pct, 0, '%')}</strong>
          <small>{c.saves} of {c.losing_games} games where you were down about 3</small>
        </div>
      </div>
    </section>
  );
}

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
}

function SkeletonPage() {
  return (
    <div className="insights-skeleton" aria-busy="true" aria-label="Loading insights">
      <div className="leak-grid">{[0, 1, 2].map((i) => <div key={i} className="skeleton-block tall" />)}</div>
      <div className="skeleton-block" />
      <div className="skeleton-block" />
    </div>
  );
}

export function InsightsPage() {
  const workspace = useWorkspace();
  const [last, setLast] = useState(500);
  const timezone = useState(browserTimezone)[0];
  const query = useQuery({
    queryKey: ['insights', workspace.platform, workspace.player, last, timezone],
    queryFn: () => getInsights(workspace.player, workspace.platform, last, timezone),
    enabled: workspace.player.trim().length > 0,
    staleTime: 60_000
  });
  const data = query.data;
  const min = data?.min_sample ?? 10;
  const missing: string[] = [];
  if (data && data.games_considered >= min) {
    if (data.time.sample_size < min) missing.push('Time-pressure stats need clock times.');
    if (data.conversion.sample_size < min) missing.push('Winning and losing positions need move-by-move engine data.');
    if (data.opponents.sample_size < min) missing.push("Opponent-rating stats need opponent ratings, which aren't saved with games yet.");
    if (data.schedule.sample_size < min) missing.push('Time-of-day stats need game start times, which older imports did not save.');
  }

  return (
    <main className="route-page insights-page">
      <PageHeader
        eyebrow="Insights"
        title="Where you lose points"
        detail={data
          ? `${last >= data.total_games ? 'All' : 'Last'} ${count(Math.min(last, data.total_games))} games (${count(data.engine_games)} with engine data)`
          : `Patterns across ${workspace.player}'s analyzed games.`}
        actions={data && data.games_considered < min ? undefined : (
          <div className="insights-range" role="group" aria-label="Games to include">
            {RANGES.map((range) => (
              <button
                key={range.value}
                type="button"
                aria-pressed={last === range.value}
                onClick={() => setLast(range.value)}
              >
                {range.label}
              </button>
            ))}
          </div>
        )}
      />

      {query.isLoading && <SkeletonPage />}
      {query.isError && (
        <section className="empty-route">
          <AlertCircle size={28} />
          <h2>Insights didn't load</h2>
          <button className="primary" onClick={() => query.refetch()}>Try again</button>
        </section>
      )}
      {data && data.games_considered < min && (
        <section className="empty-route">
          <Lightbulb size={28} />
          <h2>Not enough games yet</h2>
          <p>Insights need at least {min} analyzed games. You have {data.games_considered}.</p>
          <Link className="primary" to="/games" search={{ import: true }}>Sync your games</Link>
        </section>
      )}
      {data && data.games_considered >= min && (
        <>
          <section className="insights-leaks" aria-labelledby="leaks-title">
            <h2 id="leaks-title">Biggest leaks</h2>
            {data.leaks.length ? (
              <div className="leak-grid">
                {data.leaks.map((leak, index) => (
                  <LeakCard key={leak.id} leak={leak} rank={index + 1} username={workspace.player} platform={data.platform} />
                ))}
              </div>
            ) : (
              <p className="insights-summary">No clear leaks in these games.</p>
            )}
          </section>
          <PhaseSection data={data} />
          <TimeSection data={data} />
          {data.schedule.sample_size >= min && <ScheduleSection data={data} />}
          {data.opponents.sample_size >= min && <OpponentSection data={data} />}
          <div className="insights-pair">
            <ColorSection data={data} />
            {data.conversion.sample_size >= min && <ConversionSection data={data} />}
          </div>
          {missing.length > 0 && (
            <section className="insights-missing">
              <p>
                {missing.join(' ')} Older analyses are missing this data; a full re-sync adds it.
              </p>
              <Link className="secondary" to="/games" search={{ import: true }}>Re-sync games</Link>
            </section>
          )}
        </>
      )}
    </main>
  );
}
