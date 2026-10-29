import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Link,
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  redirect
} from '@tanstack/react-router';
import {
  Activity,
  AlertCircle,
  Database,
  Library,
  Lightbulb,
  Loader2,
  Home,
  Microscope,
  Swords,
  Target,
  TrendingUp,
  Upload
} from 'lucide-react';
import { GameList } from './components/GameList';
import { MonitoringDashboard } from './components/MonitoringDashboard';
import type { CoachAnalysis, Platform } from './lib/types';
import { analyzedGamesKey, useWorkspace } from './workspace/WorkspaceContext';
import { HomePage } from './pages/HomePage';
import { ProgressPage } from './pages/ProgressPage';
import { InsightsPage } from './pages/InsightsPage';
import { PracticePage } from './pages/PracticePage';
import { GameReviewPage } from './pages/GameReviewPage';
import { AnalysisBoardPage } from './pages/AnalysisBoardPage';
import { SetupPositionPage } from './pages/SetupPositionPage';
import { ScanLine } from 'lucide-react';
import { PlayPage } from './pages/PlayPage';
import { RepertoirePage } from './pages/RepertoirePage';
import { BookMarked } from 'lucide-react';
import { PageHeader } from './components/PageHeader';
import { AccountButton } from './components/AccountButton';
import { getAnalyzedGames } from './lib/api';

function AppShell() {
  const { analyses } = useWorkspace();
  return (
    <div className="app-frame">
      <aside className="app-sidebar">
        <Link className="brand" to="/">
          <Activity size={19} />
          <span>Chess Coach</span>
        </Link>
        <nav aria-label="Primary navigation">
          <Link to="/" activeProps={{ className: 'active' }} activeOptions={{ exact: true }}>
            <Home size={18} /><span>Home</span>
          </Link>
          <Link to="/games" search={{ import: false }} activeProps={{ className: 'active' }}>
            <Library size={18} /><span>Games</span>
            {analyses.length > 0 && <small>{analyses.length}</small>}
          </Link>
          <Link to="/practice" activeProps={{ className: 'active' }}>
            <Target size={18} /><span>Practice</span>
          </Link>
          <Link to="/progress" activeProps={{ className: 'active' }}>
            <TrendingUp size={18} /><span>Progress</span>
          </Link>
          <Link to="/insights" activeProps={{ className: 'active' }}>
            <Lightbulb size={18} /><span>Insights</span>
          </Link>
          <Link to="/analysis" search={{ fen: undefined }} activeProps={{ className: 'active' }}>
            <Microscope size={18} /><span>Analysis</span>
          </Link>
          <Link to="/setup" activeProps={{ className: 'active' }}>
            <ScanLine size={18} /><span>Set up position</span>
          </Link>
          <Link to="/play" search={{ fen: undefined }} activeProps={{ className: 'active' }}>
            <Swords size={18} /><span>Play</span>
          </Link>
          <Link to="/repertoire" activeProps={{ className: 'active' }}>
            <BookMarked size={18} /><span>Repertoire</span>
          </Link>
        </nav>
        <AccountButton />
      </aside>
      <div className="app-content"><Outlet /></div>
    </div>
  );
}

function GameReviewRoutePage() {
  const { gameId } = gameRoute.useParams();
  const search = gameRoute.useSearch();
  return <GameReviewPage key={gameId} gameId={gameId} momentId={search.moment} />;
}

function GameIntake({ onAnalyzed }: { onAnalyzed: (analysis: CoachAnalysis) => void }) {
  const workspace = useWorkspace();

  async function analyze() {
    const first = await workspace.runAnalysis();
    if (first) onAnalyzed(first);
  }

  async function syncAll() {
    // Stay on the library: the refreshed list and the sync summary show the result.
    await workspace.syncAllGames();
  }

  return (
    <section className="game-intake">
      <section className="intake-workspace">
        <div className="intake-section online-import">
          <div className="section-heading">
            <Database size={18} />
            <div><strong>Player history</strong><span>Automatically sync new Chess.com or Lichess games</span></div>
          </div>
          <div className="intake-fields">
            <label>
              Player username
              <input value={workspace.player} onChange={(event) => workspace.setPlayer(event.target.value)} />
            </label>
            <label>
              Source
              <select value={workspace.platform} onChange={(event) => workspace.setPlatform(event.target.value as Platform)}>
                <option value="chess.com">Chess.com</option>
                <option value="lichess">Lichess</option>
              </select>
            </label>
          </div>
          <button className="primary" onClick={syncAll} disabled={workspace.loading || !workspace.player.trim()}>
            {workspace.loading ? <Loader2 className="spin" size={17} /> : <Database size={17} />}
            Sync full history
          </button>
        </div>

        <div className="intake-divider"><span>or</span></div>

        <div className="intake-section pgn-import">
          <div className="section-heading">
            <Upload size={18} />
            <div><strong>PGN review</strong><span>Paste one or more games</span></div>
          </div>
          <label>
            PGN
            <textarea value={workspace.pgn} onChange={(event) => workspace.setPgn(event.target.value)} rows={9} />
          </label>
          <button className="secondary" onClick={analyze} disabled={workspace.loading || !workspace.pgn.trim()}>
            {workspace.loading ? <Loader2 className="spin" size={17} /> : <Upload size={17} />}
            Analyze pasted PGN
          </button>
        </div>
      </section>
      <div className={workspace.error ? 'route-status error' : 'route-status'}>
        {workspace.error ? <AlertCircle size={16} /> : <Activity size={16} />}
        {workspace.error || workspace.status}
      </div>
    </section>
  );
}

function GamesPage() {
  const workspace = useWorkspace();
  const { analyses, activeGameId, openGame } = workspace;
  const navigate = gamesRoute.useNavigate();
  const search = gamesRoute.useSearch();
  // Wait for typing to settle before loading a (possibly very large) game library.
  const [libraryPlayer, setLibraryPlayer] = useState(workspace.player);
  useEffect(() => {
    const timer = window.setTimeout(() => setLibraryPlayer(workspace.player), 400);
    return () => window.clearTimeout(timer);
  }, [workspace.player]);
  const persisted = useQuery({
    queryKey: analyzedGamesKey(workspace.platform, libraryPlayer),
    queryFn: () => getAnalyzedGames(libraryPlayer, workspace.platform),
    enabled: libraryPlayer.trim().length > 0 && !workspace.loading,
    staleTime: 60_000
  });
  useEffect(() => {
    // The server library is authoritative: it includes synced and pasted games for this player.
    if (persisted.data) workspace.restoreAnalyses(persisted.data.analyses);
  }, [persisted.data]);
  const showImport = search.import || (analyses.length === 0 && !persisted.isFetching);
  const activeIndex = Math.max(0, analyses.findIndex((item) => item.game.game_id === activeGameId));

  function selectGame(index: number) {
    const game = analyses[index];
    if (!game) return;
    openGame(game.game.game_id);
    void navigate({ to: '/games/$gameId', params: { gameId: game.game.game_id }, search: { moment: undefined } });
  }

  function openAnalyzedGame(analysis: CoachAnalysis) {
    void navigate({
      to: '/games/$gameId',
      params: { gameId: analysis.game.game_id },
      search: { moment: undefined }
    });
  }

  return (
    <main className="route-page games-page">
      <PageHeader
        eyebrow="Game library"
        title="Your analyzed games"
        detail={analyses.length
          ? `${analyses.length} games ready for review.`
          : persisted.isFetching ? 'Loading your game library...' : 'No analyzed games yet.'}
        actions={<button
          className="secondary route-action"
          onClick={() => navigate({ search: { import: !showImport } })}
        ><Upload size={16} /> {showImport ? 'Close import' : 'Import games'}</button>}
      />
      {showImport && <GameIntake onAnalyzed={openAnalyzedGame} />}
      {analyses.length ? (
        <GameList analyses={analyses} activeIndex={activeIndex} onSelect={selectGame} />
      ) : !showImport ? (
        <section className="empty-route">
          <Library size={28} />
          <h2>No games yet</h2>
          <button className="primary" onClick={() => navigate({ search: { import: true } })}>
            Import games
          </button>
        </section>
      ) : null}
    </main>
  );
}

function PracticeSessionRoutePage() {
  const { sessionId } = practiceSessionRoute.useParams();
  return <PracticePage sessionId={sessionId} />;
}

function QualityPage() {
  const { monitoringRefresh } = useWorkspace();
  return (
    <main className="route-page quality-page">
      <PageHeader
        eyebrow="Agent operations"
        title="Quality monitoring"
        detail="Analyses, model usage, and coaching feedback."
      />
      <MonitoringDashboard refreshKey={monitoringRefresh} />
    </main>
  );
}

const rootRoute = createRootRoute({ component: AppShell });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage
});

const analyzeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/analyze',
  beforeLoad: () => {
    throw redirect({ to: '/games', search: { import: true } });
  }
});
const gamesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/games',
  validateSearch: (search: Record<string, unknown>) => ({ import: search.import === true }),
  component: GamesPage
});
const gameRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/games/$gameId',
  validateSearch: (search: Record<string, unknown>) => ({
    moment: typeof search.moment === 'string' ? search.moment : undefined
  }),
  component: GameReviewRoutePage
});
const practiceRoute = createRoute({ getParentRoute: () => rootRoute, path: '/practice', component: PracticePage });
const practiceSessionRoute = createRoute({ getParentRoute: () => rootRoute, path: '/practice/$sessionId', component: PracticeSessionRoutePage });
const retiredCoachRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/coach',
  beforeLoad: () => { throw redirect({ to: '/practice' }); }
});
const retiredCoachSessionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/coach/$sessionId',
  beforeLoad: () => { throw redirect({ to: '/practice' }); }
});
const progressRoute = createRoute({ getParentRoute: () => rootRoute, path: '/progress', component: ProgressPage });
const insightsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/insights', component: InsightsPage });
const analysisRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/analysis',
  validateSearch: (search: Record<string, unknown>) => ({ fen: typeof search.fen === 'string' ? search.fen : undefined }),
  component: function AnalysisRoutePage() {
    const { fen } = analysisRoute.useSearch();
    return <AnalysisBoardPage key={fen ?? 'start'} initialFen={fen} />;
  }
});
const playRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/play',
  validateSearch: (search: Record<string, unknown>) => ({ fen: typeof search.fen === 'string' ? search.fen : undefined }),
  component: function PlayRoutePage() {
    const { fen } = playRoute.useSearch();
    return <PlayPage key={fen ?? 'start'} initialFen={fen} />;
  }
});
const qualityRoute = createRoute({ getParentRoute: () => rootRoute, path: '/quality', component: QualityPage });

const repertoireRoute = createRoute({ getParentRoute: () => rootRoute, path: '/repertoire', component: RepertoirePage });
const setupRoute = createRoute({ getParentRoute: () => rootRoute, path: '/setup', component: SetupPositionPage });
const routeTree = rootRoute.addChildren([
  setupRoute,
  repertoireRoute,
  indexRoute, analyzeRoute, gamesRoute, gameRoute, practiceRoute, practiceSessionRoute,
  retiredCoachRoute, retiredCoachSessionRoute, progressRoute, insightsRoute, qualityRoute, analysisRoute, playRoute
]);

export const router = createRouter({ routeTree, defaultPreload: 'intent', scrollRestoration: true });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
