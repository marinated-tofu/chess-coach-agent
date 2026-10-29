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
  Library,
  Lightbulb,
  Home,
  Microscope,
  Swords,
  Target,
  TrendingUp
} from 'lucide-react';
import { MonitoringDashboard } from './components/MonitoringDashboard';
import { useWorkspace } from './workspace/WorkspaceContext';
import { GamesPage } from './pages/GamesPage';
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
