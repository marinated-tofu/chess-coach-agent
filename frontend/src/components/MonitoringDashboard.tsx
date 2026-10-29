import { useEffect, useMemo, useState } from 'react';
import { BarChart3, RefreshCw } from 'lucide-react';
import { getMonitoring } from '../lib/api';
import type { MonitoringSummary } from '../lib/types';

// Fields added to /api/monitoring after MonitoringSummary was written; optional for older servers.
type Summary = MonitoringSummary & {
  llm_runs?: number;
  llm_runs_without_usage?: number;
  llm_runs_by_event?: Record<string, number>;
};

const count = (value: number) => value.toLocaleString();

function eventLabel(name: string) {
  const text = name.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function MonitoringDashboard({ refreshKey }: { refreshKey: number }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);

  function refresh() {
    setLoading(true);
    getMonitoring().then(setSummary).catch(() => setSummary(null)).finally(() => setLoading(false));
  }

  useEffect(refresh, [refreshKey]);

  const eventRows = useMemo(() => {
    if (!summary) return [];
    const entries = Object.entries(summary.event_counts).sort((a, b) => b[1] - a[1]);
    const maximum = Math.max(...entries.map(([, value]) => value), 1);
    // Linear scale with a 2 px floor: a min-width percentage made every small count look the same.
    return entries.map(([name, value]) => ({ name, value, width: `max(2px, ${(value / maximum) * 100}%)` }));
  }, [summary]);

  return (
    <section className="monitoring-panel">
      <div className="monitoring-head">
        <div className="panel-title"><BarChart3 size={18} /> Quality monitoring</div>
        <button aria-label="Refresh monitoring" title="Refresh monitoring" onClick={refresh} disabled={loading}>
          <RefreshCw className={loading ? 'spin' : ''} size={17} />
        </button>
      </div>
      {!summary ? (
        <p className="monitoring-empty">Monitoring data will appear after an analysis or practice attempt.</p>
      ) : (
        <>
          <div className="monitoring-metrics">
            <div><strong>{count(summary.total_events)}</strong><span>Events</span></div>
            <div><strong>{count(summary.event_counts.analysis_completed || 0)}</strong><span>Analyses</span></div>
            <div><strong>{count(summary.feedback_count)}</strong><span>Ratings</span></div>
            <div>
              <strong>{summary.helpful_rate === null ? 'N/A' : `${Math.round(summary.helpful_rate * 100)}%`}</strong>
              <span>Helpful</span>
            </div>
            <div title={`${count(summary.input_tokens)} in, ${count(summary.output_tokens)} out`}>
              <strong>{count(summary.input_tokens + summary.output_tokens)}</strong>
              <span>Tokens{summary.llm_runs_without_usage ? ` (${count(summary.llm_runs_without_usage)} runs unmetered)` : ''}</span>
            </div>
            <div><strong>${summary.estimated_cost_usd.toFixed(4)}</strong><span>Est. cost</span></div>
            <div>
              <strong>{summary.average_chat_latency_ms === null ? 'N/A' : `${Math.round(summary.average_chat_latency_ms)} ms`}</strong>
              <span>Chat latency</span>
            </div>
            <div title={summary.llm_runs_by_event ? Object.entries(summary.llm_runs_by_event).map(([name, value]) => `${eventLabel(name)}: ${count(value)}`).join('\n') : undefined}>
              <strong>{count(summary.llm_calls)}</strong>
              <span>LLM requests{summary.llm_runs != null ? ` in ${count(summary.llm_runs)} runs` : ''}</span>
            </div>
            <div><strong>{count(summary.quiz_attempts)}</strong><span>Quiz attempts</span></div>
            <div>
              <strong>{summary.quiz_accuracy === null ? 'N/A' : `${Math.round(summary.quiz_accuracy * 100)}%`}</strong>
              <span>Quiz accuracy</span>
            </div>
            <div>
              <strong>{summary.hint_use_rate === null ? 'N/A' : `${Math.round(summary.hint_use_rate * 100)}%`}</strong>
              <span>Hint use</span>
            </div>
            <div><strong>{count(summary.stream_failures)}</strong><span>Stream failures</span></div>
          </div>
          <div className="event-bars">
            {eventRows.map((row) => (
              <div className="event-row" key={row.name}>
                <span>{eventLabel(row.name)}</span>
                <div><i style={{ width: row.width }} /></div>
                <strong>{count(row.value)}</strong>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
