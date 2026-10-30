import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from '@tanstack/react-router';
import { BookOpenCheck, Download, ExternalLink, Library, MoreHorizontal } from 'lucide-react';
import { AnalysisPanel } from '../components/AnalysisPanel';
import { CoachPanel } from '../components/CoachPanel';
import { EmptyState } from '../components/EmptyState';
import { GamePanel } from '../components/GamePanel';
import { PageHeader } from '../components/PageHeader';
import { ReviewSummary } from '../components/ReviewSummary';
import { Skeleton } from '../components/Skeleton';
import '../components/GameReview.css';
import { createTrainingSession, getAnalyzedGames } from '../lib/api';
import { useCoachMarks } from '../lib/coachMarks';
import { pgnDownloadUrl } from '../lib/exportApi';
import { boardFenAt } from '../lib/reviewApi';
import { recordGameRetry } from '../lib/studyPlanApi';
import type { CoachAnalysis, CriticalMoment } from '../lib/types';
import { useWorkspace } from '../workspace/WorkspaceContext';

declare module '@tanstack/history' {
  interface HistoryState {
    /** Set by the analysis board's "Back to game" so the review reopens on the same move. */
    reviewPly?: number;
  }
}

type Tab = 'moments' | 'moves' | 'coach' | 'summary';
const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'moments', label: 'Moments' },
  { id: 'moves', label: 'Moves' },
  { id: 'coach', label: 'Coach' },
  { id: 'summary', label: 'Summary' }
];

const RESULT: Record<string, string> = { win: 'Win', loss: 'Loss', draw: 'Draw' };
const PGN_DATE = /^(\d{4})\.(\d{2})\.(\d{2})$/;

/** "2026.06.22" -> "22 Jun 2026"; unknown dates give an empty string. */
function formatDate(value: string): string {
  const match = PGN_DATE.exec(value || '');
  if (!match) return '';
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date);
}

/** "180+2" -> "Blitz 3+2", "1/86400" -> "Daily". */
function formatTimeControl(value: string): string {
  if (!value || value === '-' || value === '?') return '';
  if (value.includes('/')) return 'Daily';
  const [baseText, incText] = value.split('+');
  const base = Number(baseText);
  const inc = Number(incText || 0);
  if (!Number.isFinite(base) || base <= 0) return '';
  const total = base + 40 * inc;
  const kind = total < 180 ? 'Bullet' : total < 480 ? 'Blitz' : total < 1500 ? 'Rapid' : 'Classical';
  const minutes = base % 60 === 0 ? String(base / 60) : (base / 60).toFixed(1).replace(/\.0$/, '');
  return `${kind} ${minutes}+${inc}`;
}

function eyebrow(analysis: CoachAnalysis): string {
  const game = analysis.game;
  return [RESULT[game.player_result] ?? '', formatDate(game.date), formatTimeControl(game.time_control)]
    .filter(Boolean)
    .join(' · ') || 'Game review';
}

function detail(analysis: CoachAnalysis): string {
  const game = analysis.game;
  const moves = Math.ceil(analysis.moves.length / 2);
  const parts = [`${moves} ${moves === 1 ? 'move' : 'moves'}`];
  const color = game.player_color === 'white' ? 'White' : game.player_color === 'black' ? 'Black' : '';
  const verb = { win: 'Won', loss: 'Lost', draw: 'Drew' }[game.player_result];
  if (verb && color) parts.push(`${verb} as ${color}`);
  if (game.player_elo) parts.push(`${game.player_elo} rating`);
  return parts.join(' · ');
}

function siteName(link: string): string | null {
  if (/chess\.com/i.test(link)) return 'Chess.com';
  if (/lichess\.org/i.test(link)) return 'Lichess';
  return null;
}

export function GameReviewPage({ gameId, momentId }: { gameId: string; momentId?: string }) {
  const navigate = useNavigate();
  const workspace = useWorkspace();
  const returnPly = useLocation({ select: (location) => location.state.reviewPly });
  const sessionAnalysis = workspace.analyses.find((item) => item.game.game_id === gameId) || null;
  const stored = useQuery({
    queryKey: ['analyzed-game', workspace.platform, workspace.player.trim().toLowerCase(), gameId],
    queryFn: async () => {
      // Pasted games used to be stored under the "pgn" platform, so check there as well.
      for (const platform of [workspace.platform, 'pgn'] as const) {
        const result = await getAnalyzedGames(workspace.player, platform, gameId);
        if (result.analyses[0]) return result.analyses[0];
      }
      return null;
    },
    enabled: !sessionAnalysis && workspace.player.trim().length > 0,
    staleTime: 60_000
  });
  const analysis = sessionAnalysis || stored.data || null;
  const selectedMoment = analysis?.moments.find((moment) => moment.id === momentId) || analysis?.moments[0] || null;
  const [currentPly, setCurrentPly] = useState(returnPly ?? selectedMoment?.ply ?? 0);
  const [tab, setTab] = useState<Tab>(analysis && !analysis.moments.length ? 'moves' : 'moments');
  const [practice, setPractice] = useState<{ pending: boolean; error: string }>({ pending: false, error: '' });
  const [retryRequest, setRetryRequest] = useState<{ ply: number; nonce: number } | null>(null);
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | null>(null);
  const tabsRef = useRef<HTMLDivElement>(null);
  // The moment whose ply the board already shows; coming back from analysis keeps that move instead.
  const syncedMoment = useRef<string | undefined>(returnPly != null ? 'returned' : undefined);
  const currentFen = (analysis && boardFenAt(analysis.moves, currentPly)) || '';
  const coachMarks = useCoachMarks(currentFen);

  useEffect(() => {
    if (analysis) workspace.openGame(analysis.game.game_id);
  }, [analysis?.game.game_id]);

  useEffect(() => {
    if (syncedMoment.current === 'returned') {
      if (selectedMoment) syncedMoment.current = selectedMoment.id;
      return;
    }
    if (syncedMoment.current === (selectedMoment?.id ?? '')) return;
    syncedMoment.current = selectedMoment?.id ?? '';
    setCurrentPly(selectedMoment?.ply || 0);
    workspace.clearFeedbackStatus();
  }, [selectedMoment?.id]);

  function selectMoment(moment: CriticalMoment) {
    setCurrentPly(moment.ply);
    workspace.clearFeedbackStatus();
    void navigate({ to: '/games/$gameId', params: { gameId }, search: { moment: moment.id }, replace: true });
  }

  function retryMoment(moment: CriticalMoment) {
    setRetryRequest((current) => ({ ply: moment.ply, nonce: (current?.nonce ?? 0) + 1 }));
  }

  async function practiceMoment(moment: CriticalMoment) {
    setPractice({ pending: true, error: '' });
    try {
      const created = await createTrainingSession(workspace.player, workspace.platform, moment.theme, moment.id);
      await navigate({ to: '/practice/$sessionId', params: { sessionId: created.id } });
    } catch (caught) {
      setPractice({ pending: false, error: caught instanceof Error ? caught.message : 'Could not start practice. Try again.' });
    }
  }

  function openCoach(text?: string) {
    setTab('coach');
    if (text) setPrefill((current) => ({ text, nonce: (current?.nonce ?? 0) + 1 }));
    // Small screens: bring the tabs up under the pinned board.
    requestAnimationFrame(() => {
      const tabs = tabsRef.current;
      if (tabs && tabs.getBoundingClientRect().top > window.innerHeight * 0.6) tabs.scrollIntoView({ block: 'start', behavior: 'smooth' });
      if (!text) document.getElementById('coach-question')?.focus({ preventScroll: true });
    });
  }

  function askAboutMoment(moment: CriticalMoment) {
    openCoach(
      moment.best_san
        ? `Why is ${moment.best_san} better than ${moment.played_san}?`
        : `What was wrong with ${moment.played_san}?`
    );
  }

  // n / p step through the key moments; / opens the coach. Ignored while typing, and "g p" belongs to the nav.
  const lastKey = useRef({ key: '', at: 0 });
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const previous = lastKey.current;
      lastKey.current = { key: event.key, at: event.timeStamp };
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"]')) return;
      if (previous.key === 'g' && event.timeStamp - previous.at < 1000) return;
      if (!analysis) return;
      if (event.key === '/') {
        event.preventDefault();
        openCoach();
        return;
      }
      if (event.key !== 'n' && event.key !== 'p') return;
      const moments = analysis.moments;
      if (!moments.length) return;
      const index = selectedMoment ? moments.findIndex((moment) => moment.id === selectedMoment.id) : -1;
      const next = event.key === 'n' ? Math.min(moments.length - 1, index + 1) : Math.max(0, index - 1);
      event.preventDefault();
      setTab('moments');
      selectMoment(moments[next]);
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  if (!analysis && stored.isPending && stored.fetchStatus !== 'idle') {
    return (
      <main className="route-page review-page" aria-busy="true">
        <div className="rv-loading">
          <Skeleton variant="board" label="Loading game" />
          <Skeleton lines={6} label="Loading review" />
        </div>
      </main>
    );
  }

  if (!analysis) {
    return (
      <main className="route-page">
        <EmptyState
          icon={<BookOpenCheck size={28} />}
          title="Review unavailable"
          body={stored.isError
            ? 'The game could not be loaded. Check that the backend is running and try again.'
            : `This game was not found in ${workspace.player}'s ${workspace.platform} library.`}
          action={stored.isError
            ? <button className="primary" type="button" onClick={() => stored.refetch()}>Try again</button>
            : <Link className="primary" to="/games" search={{ import: false }}>Back to games</Link>}
        />
      </main>
    );
  }

  const site = analysis.game.link ? siteName(analysis.game.link) : null;

  return (
    <main className="route-page review-page">
      <PageHeader
        eyebrow={eyebrow(analysis)}
        title={`${analysis.game.white} vs ${analysis.game.black}`}
        detail={detail(analysis)}
        actions={<>
          <Link className="secondary route-action" to="/games" search={{ import: false }}><Library size={16} /> All games</Link>
          <details className="rv-more">
            <summary className="secondary route-action" aria-label="More actions"><MoreHorizontal size={16} /> More</summary>
            <div className="rv-more-menu" role="menu">
              <a role="menuitem" href={pgnDownloadUrl(workspace.platform, workspace.player, analysis.game.game_id)} download>
                <Download size={15} aria-hidden="true" /> Export PGN
              </a>
              {site && (
                <a role="menuitem" href={analysis.game.link} target="_blank" rel="noreferrer">
                  <ExternalLink size={15} aria-hidden="true" /> Open on {site}
                </a>
              )}
            </div>
          </details>
        </>}
      />
      <GamePanel
        analysis={analysis}
        currentPly={currentPly}
        setCurrentPly={setCurrentPly}
        coachArrows={coachMarks.arrows}
        coachHighlights={coachMarks.highlights}
        retryRequest={retryRequest}
        onRetryFinished={(ply) => recordGameRetry(workspace.player, workspace.platform, analysis.game.game_id, ply)}
        compactBoard={tab === 'coach'}
        renderSide={(movesPanel) => (
          <div className="rv-side-inner" data-tab={tab}>
            <div className="rv-summary-slot">
              <ReviewSummary analysis={analysis} username={workspace.player} platform={workspace.platform} />
            </div>
            <div className="rv-tabs" role="tablist" aria-label="Review sections" ref={tabsRef}>
              {TABS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  id={`rv-tab-${item.id}`}
                  aria-controls={`rv-panel-${item.id}`}
                  aria-selected={tab === item.id}
                  data-tab={item.id}
                  onClick={() => setTab(item.id)}
                >
                  {item.label}
                  {item.id === 'moments' && analysis.moments.length > 0 && <small className="tnum">{analysis.moments.length}</small>}
                </button>
              ))}
            </div>
            <div className="rv-panel" role="tabpanel" id="rv-panel-moments" aria-labelledby="rv-tab-moments" data-panel="moments" hidden={tab !== 'moments'}>
              <AnalysisPanel
                analysis={analysis}
                selectedMoment={selectedMoment}
                onSelectMoment={selectMoment}
                onRetry={retryMoment}
                onPractice={practiceMoment}
                practicePending={practice.pending}
                practiceError={practice.error}
                onAskCoach={askAboutMoment}
                onFeedback={workspace.recordFeedback}
                feedbackStatus={workspace.feedbackStatus}
              />
            </div>
            <div className="rv-panel" role="tabpanel" id="rv-panel-moves" aria-labelledby="rv-tab-moves" data-panel="moves" hidden={tab !== 'moves'}>
              <h2 className="rv-sr-only">Moves</h2>
              {movesPanel}
            </div>
            <div className="rv-panel" role="tabpanel" id="rv-panel-coach" aria-labelledby="rv-tab-coach" data-panel="coach" hidden={tab !== 'coach'}>
              <CoachPanel
                key={analysis.game.game_id}
                gameId={analysis.game.game_id}
                fen={currentFen || undefined}
                onAnnotations={coachMarks.onAnnotations}
                prefill={prefill}
                suggestions={[
                  'What was my biggest mistake in this game?',
                  'Explain the position on the board',
                  'Give me a drill for this weakness'
                ]}
              />
            </div>
            <div className="rv-panel" role="tabpanel" id="rv-panel-summary" aria-labelledby="rv-tab-summary" data-panel="summary" hidden={tab !== 'summary'}>
              <section className="rv-game-summary" aria-labelledby="rv-summary-title">
                <h2 id="rv-summary-title" className="rv-section-title">Coach's summary</h2>
                <p>{analysis.summary}</p>
                {analysis.training_plan.length > 0 && (
                  <>
                    <h3>Training plan</h3>
                    <ul className="training-list">
                      {analysis.training_plan.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </>
                )}
              </section>
            </div>
          </div>
        )}
      />
    </main>
  );
}
