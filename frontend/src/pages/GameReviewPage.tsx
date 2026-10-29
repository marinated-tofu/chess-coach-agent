import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { BookOpenCheck, Download, Library, Loader2, Target } from 'lucide-react';
import { AnalysisPanel } from '../components/AnalysisPanel';
import { CoachPanel } from '../components/CoachPanel';
import { GamePanel } from '../components/GamePanel';
import { PageHeader } from '../components/PageHeader';
import { ReviewSummary } from '../components/ReviewSummary';
import '../components/GameReview.css';
import { createTrainingSession, getAnalyzedGames } from '../lib/api';
import { useCoachMarks } from '../lib/coachMarks';
import { pgnDownloadUrl } from '../lib/exportApi';
import { boardFenAt } from '../lib/reviewApi';
import type { CoachAnalysis, CriticalMoment } from '../lib/types';
import { useWorkspace } from '../workspace/WorkspaceContext';

function gameStats(analysis: CoachAnalysis) {
  const side = analysis.game.player_color === 'unknown' ? 'player' : analysis.game.player_color;
  return [
    `${analysis.moves.length} plies`,
    `${analysis.moments.length} moments`,
    `${analysis.game.player_result} as ${side}`,
    analysis.game.player_elo ? `${analysis.game.player_elo} Elo` : analysis.game.time_control || 'PGN'
  ];
}

export function GameReviewPage({ gameId, momentId }: { gameId: string; momentId?: string }) {
  const navigate = useNavigate();
  const workspace = useWorkspace();
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
  const [currentPly, setCurrentPly] = useState(selectedMoment?.ply || 0);
  const [startingPractice, setStartingPractice] = useState(false);
  const currentFen = (analysis && boardFenAt(analysis.moves, currentPly)) || '';
  const coachMarks = useCoachMarks(currentFen);

  useEffect(() => {
    if (analysis) workspace.openGame(analysis.game.game_id);
  }, [analysis?.game.game_id]);

  useEffect(() => {
    setCurrentPly(selectedMoment?.ply || 0);
    workspace.clearFeedbackStatus();
  }, [selectedMoment?.id]);

  function selectMoment(moment: CriticalMoment) {
    setCurrentPly(moment.ply);
    workspace.clearFeedbackStatus();
    void navigate({ to: '/games/$gameId', params: { gameId }, search: { moment: moment.id }, replace: true });
  }

  async function openPractice() {
    if (!analysis || !selectedMoment) return;
    setStartingPractice(true);
    try {
      const created = await createTrainingSession(
        workspace.player,
        workspace.platform,
        selectedMoment.theme,
        selectedMoment.id
      );
      await navigate({ to: '/practice/$sessionId', params: { sessionId: created.id } });
    } finally {
      setStartingPractice(false);
    }
  }

  if (!analysis && stored.isPending && stored.fetchStatus !== 'idle') {
    return (
      <main className="route-page">
        <section className="empty-route">
          <Loader2 className="spin" size={28} />
          <h2>Loading game</h2>
        </section>
      </main>
    );
  }

  if (!analysis) {
    return (
      <main className="route-page">
        <section className="empty-route">
          <BookOpenCheck size={28} />
          <h2>Review unavailable</h2>
          <p>
            {stored.isError
              ? 'The game could not be loaded. Check that the backend is running and try again.'
              : `This game was not found in ${workspace.player}'s ${workspace.platform} library.`}
          </p>
          <Link className="primary" to="/games" search={{ import: false }}>Back to games</Link>
        </section>
      </main>
    );
  }

  return (
    <main className="route-page review-page">
      <PageHeader
        eyebrow={`${analysis.game.date} · ${analysis.game.player_result}`}
        title={`${analysis.game.white} vs ${analysis.game.black}`}
        actions={<>
          <button className="secondary route-action" disabled={startingPractice} onClick={openPractice}>
            <Target size={16} /> Train this position
          </button>
          <a className="secondary route-action" href={pgnDownloadUrl(workspace.platform, workspace.player, analysis.game.game_id)} download>
            <Download size={16} /> Download PGN
          </a>
          <Link className="secondary route-action" to="/games" search={{ import: false }}><Library size={16} /> All games</Link>
        </>}
      />
      <div className="stat-row">{gameStats(analysis).map((stat) => <span key={stat}>{stat}</span>)}</div>
      <ReviewSummary analysis={analysis} username={workspace.player} platform={workspace.platform} />
      <div className="layout review-layout">
        <GamePanel
          analysis={analysis}
          currentPly={currentPly}
          setCurrentPly={setCurrentPly}
          coachArrows={coachMarks.arrows}
          coachHighlights={coachMarks.highlights}
        />
        <div className="review-main">
          <AnalysisPanel
            analysis={analysis}
            selectedMoment={selectedMoment}
            onSelectMoment={selectMoment}
            onFeedback={workspace.recordFeedback}
            feedbackStatus={workspace.feedbackStatus}
          />
          <CoachPanel
            key={analysis.game.game_id}
            gameId={analysis.game.game_id}
            fen={currentFen || undefined}
            onAnnotations={coachMarks.onAnnotations}
            suggestions={[
              'What was my biggest mistake in this game?',
              'Explain the position on the board',
              'Give me a drill for this weakness'
            ]}
          />
        </div>
      </div>
    </main>
  );
}
