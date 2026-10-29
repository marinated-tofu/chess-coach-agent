import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { AlertCircle, ArrowRight, Lightbulb, Loader2 } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
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
  type PhaseRow
} from '../lib/insightsApi';
import { PageHeader } from '../components/PageHeader';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './InsightsPage.css';

const RANGES = [
  { value: 100, label: 'Last 100' },
  { value: 500, label: 'Last 500' },
  { value: 3000, label: 'All' }
];

const SEVERITY = {
  inaccuracy: '#e39a68',
  mistake: '#c8642c',
  blunder: '#8f3412'
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
          <button className="primary leak-button" onClick={practice} disabled={starting}>
            {starting ? <Loader2 className="spin" size={16} /> : <ArrowRight size={16} />}
            {leak.action.label}
          </button>
        ) : (
          <Link className="secondary leak-button" to="/progress">
            <ArrowRight size={16} /> {leak.action.label}
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
              <CartesianGrid stroke="#edf1ee" vertical={false} />
              <XAxis dataKey="phase" tickFormatter={(value: string) => PHASE_LABEL[value]} tick={{ fontSize: 12, fill: '#5b6961' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#7a867f" }} axisLine={false} tickLine={false} width={34} tickCount={4} allowDecimals tickFormatter={(value: number) => value.toFixed(1)} />
              <Tooltip content={<PhaseTooltip />} cursor={{ fill: 'rgba(23, 32, 27, 0.04)' }} />
              <Bar isAnimationActive={false} dataKey="blunders_per_game" stackId="e" fill={SEVERITY.blunder} stroke="#fff" strokeWidth={2} />
              <Bar isAnimationActive={false} dataKey="mistakes_per_game" stackId="e" fill={SEVERITY.mistake} stroke="#fff" strokeWidth={2} />
              <Bar isAnimationActive={false} dataKey="inaccuracies_per_game" stackId="e" fill={SEVERITY.inaccuracy} stroke="#fff" strokeWidth={2} radius={[4, 4, 0, 0]} />
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
            <CartesianGrid stroke="#edf1ee" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#5b6961' }} axisLine={false} tickLine={false} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#7a867f' }} axisLine={false} tickLine={false} width={40} unit="%" />
            <ReferenceLine y={50} stroke="#b9c4bd" strokeDasharray="3 3" />
            <Tooltip
              cursor={{ fill: 'rgba(23, 32, 27, 0.04)' }}
              formatter={(value) => [`${value}%`, 'Score']}
              labelFormatter={(label) => `Opponent ${String(label)}`}
            />
            <Bar isAnimationActive={false} dataKey="score_pct" fill="#397c57" radius={[4, 4, 0, 0]} maxBarSize={56} />
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
  const query = useQuery({
    queryKey: ['insights', workspace.platform, workspace.player, last],
    queryFn: () => getInsights(workspace.player, workspace.platform, last),
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
  }

  return (
    <main className="route-page insights-page">
      <PageHeader
        eyebrow="Insights"
        title="Where you lose points"
        detail={data
          ? `${workspace.player}'s last ${count(data.games_considered)} games, ${count(data.engine_games)} with full engine data.`
          : `Patterns across ${workspace.player}'s analyzed games.`}
        actions={
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
        }
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
          {data.opponents.sample_size >= min && <OpponentSection data={data} />}
          <div className="insights-pair">
            <ColorSection data={data} />
            {data.conversion.sample_size >= min && <ConversionSection data={data} />}
          </div>
          {missing.length > 0 && (
            <section className="insights-missing">
              <p>
                {missing.join(' ')} Older analyses are missing clocks and engine data; a full
                re-sync adds them.
              </p>
              <Link className="secondary" to="/games" search={{ import: true }}>Re-sync games</Link>
            </section>
          )}
        </>
      )}
    </main>
  );
}
