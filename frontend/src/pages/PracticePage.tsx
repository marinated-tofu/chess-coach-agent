import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { ArrowRight, CheckCircle2, FlipVertical2, Home, Loader2, RotateCcw, Target } from 'lucide-react';
import { ARROW_COLORS, ChessBoard, type BoardArrow } from '../components/ChessBoard';
import { CoachPanel } from '../components/CoachPanel';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { PuzzleModeButton } from '../components/PuzzleModeButton';
import { Skeleton } from '../components/Skeleton';
import { formatGameDate, getPracticeQueue, themeLabel, type PracticeQueue } from '../lib/libraryApi';
import {
  createTrainingSession,
  getTrainingSession,
  submitTrainingAttempt
} from '../lib/api';
import { parseMove, playMove, type BoardMove } from '../lib/chessRules';
import { useCoachMarks } from '../lib/coachMarks';
import type { EvaluationPanel } from '../lib/types';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './PracticePage.css';

function QueuePanel({ queue, busy, onStart, onPuzzles }: {
  queue: PracticeQueue | undefined;
  busy: boolean;
  onStart: () => void;
  onPuzzles: (sessionId: string) => void;
}) {
  const workspace = useWorkspace();
  const preview = queue?.preview;
  const themes = queue?.due_count ? queue.due_themes : queue?.candidate_themes ?? [];
  const sideToMove = preview?.fen.split(' ')[1] === 'b' ? 'black' : 'white';
  return (
    <section className="practice-queue">
      <div className="practice-queue-preview">
        {preview ? (
          <ChessBoard fen={preview.fen} orientation={sideToMove} />
        ) : queue ? (
          <div className="practice-queue-placeholder"><Target size={28} /></div>
        ) : (
          <Skeleton variant="board" label="Loading the first position" />
        )}
      </div>
      <div className="practice-queue-body">
        <div className="practice-queue-counts">
          <div>
            <strong>{queue ? queue.due_count.toLocaleString() : '–'}</strong>
            <span>Due for review</span>
          </div>
          <div>
            <strong>{queue ? queue.candidate_count.toLocaleString() : '–'}</strong>
            <span>Positions from your games</span>
          </div>
        </div>
        {themes.length > 0 && (
          <ul className="practice-queue-themes" aria-label={queue?.due_count ? 'Themes due today' : 'Themes in your queue'}>
            {themes.slice(0, 5).map((theme) => (
              <li key={theme.name}>{themeLabel(theme.name)} <span>{theme.count.toLocaleString()}</span></li>
            ))}
          </ul>
        )}
        {preview ? (
          <p className="practice-queue-first">
            First up: move {preview.move_number} against {preview.opponent || 'your opponent'}
            {preview.date ? `, ${formatGameDate(preview.date)}` : ''}. You played {preview.played_san}; find the stronger move.
          </p>
        ) : queue ? (
          <p className="practice-queue-first">No positions from your games yet. Themed puzzles still work.</p>
        ) : (
          <Skeleton lines={2} label="Loading your queue" />
        )}
        <div className="practice-start-actions">
          <button className="primary" disabled={busy} onClick={onStart}>
            {busy ? <Loader2 className="spin" size={17} /> : <ArrowRight size={17} />} Start practice
          </button>
          <PuzzleModeButton
            username={workspace.player}
            platform={workspace.platform}
            onStarted={(session) => onPuzzles(session.id)}
          />
        </div>
        <p className="practice-start-note">Sessions hold five positions. Themed puzzles come from the Lichess library and target your most common weakness.</p>
      </div>
    </section>
  );
}

export function PracticePage({ sessionId }: { sessionId?: string }) {
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const [index, setIndex] = useState(0);
  const [move, setMove] = useState('');
  const [evaluation, setEvaluation] = useState<EvaluationPanel | null>(null);
  const [busy, setBusy] = useState(false);
  const [hintOpen, setHintOpen] = useState(false);
  const [played, setPlayed] = useState<{ move: BoardMove; fen: string } | null>(null);
  const [flipState, setFlipState] = useState({ positionId: '', flipped: false });
  const started = useMemo(() => Date.now(), [index, sessionId]);
  useEffect(() => {
    // "Practice more" opens a new session in this same component; start it from the top.
    setIndex(0);
    setMove('');
    setEvaluation(null);
    setPlayed(null);
    setHintOpen(false);
  }, [sessionId]);
  const queue = useQuery({
    queryKey: ['practice-queue', workspace.platform, workspace.player],
    queryFn: () => getPracticeQueue(workspace.player, workspace.platform),
    enabled: !sessionId && workspace.player.trim().length > 0
  });
  const training = useQuery({
    queryKey: ['training-session', sessionId],
    queryFn: () => getTrainingSession(sessionId!),
    enabled: Boolean(sessionId)
  });
  const position = training.data?.positions[index];
  const sideToMove = position?.fen.split(' ')[1] === 'b' ? 'black' : 'white';
  const flipped = Boolean(position && flipState.positionId === position.id && flipState.flipped);
  const orientation = flipped ? (sideToMove === 'black' ? 'white' : 'black') : sideToMove;
  const grading = Boolean(played) && !evaluation;
  const bestMove = useMemo(
    () => (position && evaluation ? parseMove(position.fen, evaluation.best_move) : null),
    [position, evaluation]
  );
  const reviewArrows: BoardArrow[] = [];
  if (evaluation && bestMove) reviewArrows.push({ from: bestMove.from, to: bestMove.to, color: ARROW_COLORS.best });
  if (evaluation && played && !evaluation.correct && played.move.uci !== bestMove?.uci) {
    reviewArrows.push({ from: played.move.from, to: played.move.to, color: ARROW_COLORS.mistake });
  }
  const boardFen = evaluation || !played ? position?.fen ?? '' : played.fen;
  const coachMarks = useCoachMarks(boardFen);

  async function start() {
    setBusy(true);
    try {
      const created = await createTrainingSession(workspace.player, workspace.platform);
      await navigate({ to: '/practice/$sessionId', params: { sessionId: created.id } });
    } finally {
      setBusy(false);
    }
  }

  async function submit(selected: string) {
    if (!sessionId || !position || busy) return;
    const parsed = parseMove(position.fen, selected);
    const result = parsed ? playMove(position.fen, parsed) : null;
    setPlayed(result);
    setBusy(true);
    try {
      const result = await submitTrainingAttempt(
        sessionId,
        position.id,
        selected,
        hintOpen ? 1 : 0,
        Date.now() - started
      );
      setEvaluation(result);
    } catch (error) {
      setPlayed(null);
      throw error;
    } finally {
      setBusy(false);
    }
  }

  function next() {
    if (!training.data || index + 1 >= training.data.positions.length) {
      void navigate({ to: '/' });
      return;
    }
    setIndex((value) => value + 1);
    setMove('');
    setEvaluation(null);
    setPlayed(null);
    setHintOpen(false);
  }

  function retry() {
    setEvaluation(null);
    setPlayed(null);
  }

  function handleBoardMove(boardMove: BoardMove) {
    if (busy || evaluation || played) return false;
    void submit(boardMove.san);
    return true;
  }

  if (!sessionId) return <main className="route-page practice-home">
    <PageHeader eyebrow="Practice" title="Train mistakes from your games" detail="Real positions from your games, graded by Stockfish and scheduled for review." />
    <QueuePanel
      queue={queue.data}
      busy={busy}
      onStart={start}
      onPuzzles={(id) => void navigate({ to: '/practice/$sessionId', params: { sessionId: id } })}
    />
    {queue.isError && <p className="route-status error" role="alert">Your practice queue didn’t load. You can still start a session.</p>}
  </main>;

  if (training.isLoading) return <main className="route-page practice-page">
    <section className="practice-workspace practice-loading">
      <div className="practice-board"><Skeleton variant="board" label="Loading positions" /></div>
      <div className="practice-controls"><Skeleton lines={4} /></div>
    </section>
  </main>;
  if (!position) return <main className="route-page">
    <EmptyState
      icon={<CheckCircle2 size={22} />}
      title="No positions due"
      body="Review a game to add its mistakes to your practice queue."
      action={<button className="primary" onClick={() => navigate({ to: '/games', search: { import: false } })}>Review games</button>}
    />
  </main>;

  const total = training.data?.positions.length || 0;
  const isLast = index + 1 >= total;

  return <main className="route-page practice-page">
    <header className="page-header"><div><span className="page-eyebrow">Practice · {index + 1} of {total}</span><h1>{themeLabel(position.theme)}</h1><p>{themeLabel(position.difficulty)} · {position.source === 'puzzle' ? <span className="puzzle-badge">Puzzle{position.rating ? ` · ${position.rating}` : ''}</span> : 'Position from your games'}</p></div></header>
    <section className="practice-workspace">
      <div className="practice-board">
        <ChessBoard
          fen={boardFen}
          orientation={orientation}
          onMove={evaluation || played || busy ? undefined : handleBoardMove}
          lastMove={evaluation || !played ? undefined : { from: played.move.from, to: played.move.to }}
          arrows={[...reviewArrows, ...coachMarks.arrows]}
          highlights={coachMarks.highlights}
        />
        <button
          className="secondary"
          type="button"
          aria-label="Flip board"
          aria-pressed={flipped}
          onClick={() => setFlipState({ positionId: position.id, flipped: !flipped })}
        >
          <FlipVertical2 size={16} /> Flip board
        </button>
      </div>
      <div className="practice-controls">
        {evaluation ? <>
          <div className={`evaluation-status ${evaluation.correct ? 'correct' : 'incorrect'}`}><strong>{evaluation.correct ? 'Strong move' : evaluation.legal ? 'Try this again' : 'Illegal move'}</strong><span className="practice-best">Best move: {evaluation.best_move}{evaluation.cp_loss == null ? '' : ` · ${evaluation.cp_loss.toFixed(2)} pawn loss`}</span></div>
          <p>{evaluation.explanation}</p>
          <small>Next review {formatGameDate(evaluation.next_review_at)}</small>
          {isLast ? <>
            <button className="primary" onClick={next}><Home size={17} /> Back to Today</button>
            <button className="secondary" disabled={busy} onClick={start}>{busy ? <Loader2 className="spin" size={16} /> : <ArrowRight size={16} />} Practice more</button>
          </> : (
            <button className="primary" onClick={next}>Next position <ArrowRight size={17} /></button>
          )}
          <button className="secondary" onClick={retry}><RotateCcw size={16} /> Try again</button>
          <button className="secondary" type="button" onClick={() => navigate({ to: '/analysis', search: { fen: position.fen } })}>Open in analysis board</button>
        </> : <>
          <span className="page-eyebrow">Your move</span>
          <h2 data-testid="practice-prompt">{position.prompt || 'What would you play?'}</h2>
          <p className="practice-instructions">Play it on the board, or {position.choices.length ? 'pick one of these moves.' : 'type it below.'}</p>
          {grading && <p className="practice-grading" role="status"><Loader2 className="spin" size={15} /> Checking {played?.move.san}…</p>}
          {position.choices.length ? <div className="move-choices" role="group" aria-label="Candidate moves">{position.choices.map((choice) => <button disabled={busy} key={choice} onClick={() => submit(choice)}>{choice}</button>)}</div> : <form className="move-entry" onSubmit={(event) => { event.preventDefault(); if (move) void submit(move); }}><input value={move} onChange={(event) => setMove(event.target.value)} placeholder="Enter SAN or UCI" aria-label="Your move in SAN or UCI" autoComplete="off" spellCheck={false} /><button className="primary" type="submit" disabled={!move || busy}>Submit</button></form>}
          {position.difficulty === 'beginner' && !hintOpen && <button className="text-action" onClick={() => setHintOpen(true)}>Show hint</button>}
          {hintOpen && <p className="quiz-hint">{position.hint || 'Start with checks and captures, then inspect every loose piece.'}</p>}
        </>}
      </div>
    </section>
    <CoachPanel
      key={position.id}
      fen={position.fen}
      onAnnotations={coachMarks.onAnnotations}
      suggestions={[
        'Give me a hint without telling me the move',
        'What should I look for in this position?',
        'Why was my answer wrong?'
      ]}
    />
  </main>;
}
