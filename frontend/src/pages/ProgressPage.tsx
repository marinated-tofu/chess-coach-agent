import { useQuery } from '@tanstack/react-query';
import { Activity, BarChart3, Target } from 'lucide-react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';
import { getProgress } from '../lib/api';
import { OpeningsPanel } from '../components/OpeningsPanel';
import { useWorkspace } from '../workspace/WorkspaceContext';

export function ProgressPage() {
  const workspace = useWorkspace();
  const progress = useQuery({
    queryKey: ['progress', workspace.platform, workspace.player],
    queryFn: () => getProgress(workspace.player, workspace.platform)
  });
  const data = progress.data;
  const themes = Object.entries(data?.theme_frequency || {}).sort((a, b) => b[1] - a[1]);

  return (
    <main className="route-page progress-page">
      <header className="page-header">
        <div><span className="page-eyebrow">Learning outcomes</span><h1>Progress</h1><p>Game trends and practice performance for {workspace.player}.</p></div>
      </header>
      <div className="progress-metrics">
        <div><Activity size={18} /><strong>{data?.total_games || 0}</strong><span>Stored games</span></div>
        <div><Target size={18} /><strong>{data?.recent_attempts || 0}</strong><span>Quiz attempts</span></div>
        <div><BarChart3 size={18} /><strong>{data?.transfer_score == null ? 'N/A' : `${Math.round(data.transfer_score * 100)}%`}</strong><span>Transfer score</span></div>
        <div><strong>{data?.player.due_positions || 0}</strong><span>Positions due</span></div>
      </div>
      <section className="progress-band">
        <div className="progress-chart">
          <h2>Rating over time</h2>
          {data?.rating_history.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={data.rating_history} margin={{ top: 12, right: 12, left: 0, bottom: 4 }}>
                <CartesianGrid stroke="#e3e9ed" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis domain={['dataMin - 25', 'dataMax + 25']} tick={{ fontSize: 11 }} width={44} />
                <Tooltip />
                <Line type="monotone" dataKey="rating" stroke="#397c57" strokeWidth={3} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : <p className="monitoring-empty">Rating history appears after online games are analyzed.</p>}
        </div>
        <div className="theme-table">
          <h2>Recurring blindspots</h2>
          {themes.length ? themes.map(([theme, count]) => (
            <div key={theme}><span>{theme.replace(/_/g, ' ')}</span><strong>{count}</strong></div>
          )) : <p className="monitoring-empty">No themes measured yet.</p>}
        </div>
      </section>
      <OpeningsPanel username={workspace.player} platform={workspace.platform} />
    </main>
  );
}
