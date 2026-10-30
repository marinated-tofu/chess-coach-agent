import { useQuery } from '@tanstack/react-query';
import { Loader2, RefreshCw } from 'lucide-react';
import { ConnectAccount } from '../components/ConnectAccount';
import { PageHeader } from '../components/PageHeader';
import { StudyPlanCard } from '../components/StudyPlanCard';
import { DueCard, LatestGameCard, LeakCard, RepertoireCard, relativePast } from '../components/TodayCards';
import { getToday, todayKey, type TimeCategory } from '../lib/todayApi';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './HomePage.css';

const CATEGORY_ORDER: TimeCategory[] = ['bullet', 'blitz', 'rapid', 'daily'];
const CATEGORY_LABEL: Record<TimeCategory, string> = { bullet: 'Bullet', blitz: 'Blitz', rapid: 'Rapid', daily: 'Daily' };

function isRunning(status: string) {
  return status === 'queued' || status === 'fetching' || status === 'analyzing';
}

export function HomePage() {
  const workspace = useWorkspace();
  const { player, platform, hasIdentity, syncJob } = workspace;
  const summary = useQuery({
    queryKey: todayKey(platform, player),
    queryFn: () => getToday(player, platform),
    enabled: hasIdentity,
    staleTime: 60_000
  });
  const syncingThisPlayer = isRunning(syncJob.status)
    && syncJob.player.toLowerCase() === player.trim().toLowerCase()
    && syncJob.platform === platform;

  if (!hasIdentity || syncingThisPlayer || (summary.isSuccess && summary.data.total_games === 0)) {
    return (
      <main className="route-page home-page home-first-run">
        <ConnectAccount />
      </main>
    );
  }

  const data = summary.data;
  const ratings = data
    ? CATEGORY_ORDER.filter((key) => data.current_rating[key] != null)
      .map((key) => `${CATEGORY_LABEL[key]} ${data.current_rating[key]}`)
      .join(' · ')
    : '';
  const platformLabel = platform === 'lichess' ? 'Lichess' : 'Chess.com';
  const detail = summary.isPending
    ? platformLabel
    : [platformLabel, ratings, data ? `${data.total_games.toLocaleString()} games` : ''].filter(Boolean).join(' · ');
  const due = data?.due.count ?? 0;
  const primary = !data ? null : due > 0 ? 'due' : data.latest_game ? 'latest' : 'leak';
  const syncing = isRunning(syncJob.status);

  return (
    <main className="route-page home-page">
      <PageHeader
        eyebrow="Today"
        title={data?.username || player}
        detail={detail}
        actions={(
          <button
            type="button"
            className="today-text-button today-sync"
            onClick={() => void workspace.startSync(player, platform)}
            disabled={syncing}
          >
            {syncing ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
            {syncing ? 'Syncing new games' : 'Sync new games'}
            {!syncing && data?.last_synced_at && (
              <span className="today-sync-time">Last synced {relativePast(data.last_synced_at)}</span>
            )}
          </button>
        )}
      />
      <StudyPlanCard player={player} platform={platform} />
      <div className="today-grid">
        <DueCard summary={summary} primary={primary === 'due'} />
        <LatestGameCard summary={summary} primary={primary === 'latest'} />
        <LeakCard player={player} platform={platform} primary={primary === 'leak'} />
        <RepertoireCard player={player} platform={platform} />
      </div>
    </main>
  );
}
