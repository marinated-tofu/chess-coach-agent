import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  redirect
} from '@tanstack/react-router';
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
import { PlayPage } from './pages/PlayPage';
import { RepertoirePage } from './pages/RepertoirePage';
import { EndgamesPage } from './pages/EndgamesPage';
import { PageHeader } from './components/PageHeader';
import { AppNav } from './components/AppNav';
import { SyncToast } from './components/SyncToast';

function AppShell() {
  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <AppNav />
      <div className="app-content" id="main-content" tabIndex={-1}><Outlet /></div>
      <SyncToast />
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
  validateSearch: (search: Record<string, unknown>): { import: boolean; theme?: string } => ({
    import: search.import === true || search.import === 'true',
    ...(typeof search.theme === 'string' && search.theme ? { theme: search.theme } : {})
  }),
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
  // fen: position to open; from: "game:<id>:<ply>" adds "Back to game"; tab=explorer and coach=true open those panels.
  validateSearch: (search: Record<string, unknown>): { fen?: string; from?: string; tab?: 'explorer'; coach?: boolean } => ({
    fen: typeof search.fen === 'string' ? search.fen : undefined,
    from: typeof search.from === 'string' ? search.from : undefined,
    tab: search.tab === 'explorer' ? 'explorer' : undefined,
    coach: search.coach === true || search.coach === 'true' || search.coach === 1 ? true : undefined
  }),
  component: function AnalysisRoutePage() {
    const { fen, from, tab, coach } = analysisRoute.useSearch();
    return <AnalysisBoardPage key={fen ?? 'start'} initialFen={fen} from={from} focus={coach ? 'coach' : tab} />;
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
const endgamesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/endgames', component: EndgamesPage });
const setupRoute = createRoute({ getParentRoute: () => rootRoute, path: '/setup', component: SetupPositionPage });
const routeTree = rootRoute.addChildren([
  setupRoute,
  repertoireRoute,
  endgamesRoute,
  indexRoute, analyzeRoute, gamesRoute, gameRoute, practiceRoute, practiceSessionRoute,
  retiredCoachRoute, retiredCoachSessionRoute, progressRoute, insightsRoute, qualityRoute, analysisRoute, playRoute
]);

export const router = createRouter({ routeTree, defaultPreload: 'intent', scrollRestoration: true });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
