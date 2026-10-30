import { useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { AlertCircle, ArrowLeft, ArrowRight, Check, Flag, Lightbulb, Loader2, RotateCcw, Swords, X } from 'lucide-react';
import { ChessBoard, type BoardMove } from '../components/ChessBoard';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
import { loadGame } from '../lib/chessRules';
import {
  endgamesKey,
  getEndgameDrills,
  takeEndgameTurn,
  type EndgameDrill,
  type EndgameTurn
} from '../lib/endgamesApi';
import { formatGameDate } from '../lib/libraryApi';
import { todayKey } from '../lib/todayApi';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './PlayPage.css';
import './EndgamesPage.css';

type PlayedMove = { san: string; uci: string; fen: string; from: string; to: string };

const REPLY_DELAY_MS = 350;

function goalLabel(drill: EndgameDrill) {
  if (drill.goal === 'draw') return 'Hold the draw';
  return drill.finish === 'mate' ? 'Deliver mate' : 'Convert the win';
}

function drillStatus(drill: EndgameDrill) {
  if (drill.due) return { label: 'Due', tone: 'due' };
  if (drill.last_passed === true) return { label: 'Passed', tone: 'passed' };
  if (drill.last_passed === false) return { label: 'Missed', tone: 'missed' };
  return null;
}

function reviewNote(turn: EndgameTurn) {
  if (!turn.recorded) return 'Set a player on the Games page to save results and schedule reviews.';
  const days = turn.interval_days ?? 1;
  return `Next review in ${days} ${days === 1 ? 'day' : 'days'}.`;
}

function groupDrills(drills: EndgameDrill[]) {
  const groups = new Map<string, EndgameDrill[]>();
  for (const drill of drills) groups.set(drill.category, [...(groups.get(drill.category) ?? []), drill]);
  return [...groups.entries()];
}

export function EndgamesPage() {
  const { player, platform } = useWorkspace();
  const drills = useQuery({
    queryKey: endgamesKey(platform, player),
    queryFn: () => getEndgameDrills(player, platform)
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<{ id: number; drill: EndgameDrill } | null>(null);

  const list = drills.data ?? [];
  const selected = list.find((drill) => drill.id === selectedId) ?? list.find((drill) => drill.due) ?? list[0] ?? null;
  const dueCount = list.filter((drill) => drill.due).length;
  const gameCount = list.filter((drill) => drill.kind === 'game').length;

  function start(drill: EndgameDrill) {
    setSelectedId(drill.id);
    setRun({ id: Date.now(), drill });
  }

  if (run) {
    const index = list.findIndex((drill) => drill.id === run.drill.id);
    const next = list.slice(index + 1).find((drill) => drill.due) ?? list[index + 1] ?? null;
    return (
      <DrillScreen
        key={run.id}
        drill={run.drill}
        onRetry={() => start(run.drill)}
        onNext={next ? () => start(next) : null}
        onExit={() => setRun(null)}
      />
    );
  }

  return (
    <main className="route-page play-page">
      <PageHeader
        eyebrow="Train"
        title="Endgames"
        detail="Play each position out against Stockfish at full strength. You pass by converting the win or holding the draw, and the engine judges the result."
      />
      {drills.isError && <p className="play-error" role="alert"><AlertCircle size={16} /> {(drills.error as Error).message}</p>}
      {drills.isSuccess && !list.length && (
        <EmptyState icon={<Swords size={22} />} title="No endgames loaded" body="The essential positions are missing from this server." />
      )}
      {(drills.isPending || list.length > 0) && (
        <div className="endgames-layout">
          <section className="endgames-list" aria-label="Endgame drills">
            <p className="endgames-counts">
              {drills.isPending ? 'Loading drills' : (
                <>
                  <strong>{dueCount}</strong> due · <strong>{gameCount}</strong> from your games
                </>
              )}
            </p>
            {drills.isPending && <Skeleton lines={6} label="Loading drills" />}
            {groupDrills(list).map(([category, items]) => (
              <div key={category} className="endgames-group" role="group" aria-label={category}>
                <h2>{category}</h2>
                {items.map((drill) => {
                  const status = drillStatus(drill);
                  return (
                    <button
                      key={drill.id}
                      type="button"
                      className={drill.id === selected?.id ? 'endgames-row selected' : 'endgames-row'}
                      aria-pressed={drill.id === selected?.id}
                      onClick={() => setSelectedId(drill.id)}
                    >
                      <span className="endgames-row-title">{drill.title}</span>
                      <span className="endgames-row-goal">{goalLabel(drill)}</span>
                      {status && <span className={`endgames-chip ${status.tone}`}>{status.label}</span>}
                    </button>
                  );
                })}
              </div>
            ))}
            {drills.isSuccess && !gameCount && (
              <p className="endgames-note">
                {player.trim()
                  ? 'No thrown endgames in your analyzed games yet. Lost wins and lost draws appear here after a sync.'
                  : <>Set a player on the <Link to="/games" search={{ import: true }}>Games</Link> page to add endgames you let slip and save your results.</>}
              </p>
            )}
          </section>

          <section className="endgames-preview" aria-label="Selected drill">
            {selected ? (
              <>
                <div className="endgames-preview-board">
                  <ChessBoard fen={selected.fen} orientation={selected.player_color} youColor={selected.player_color} />
                </div>
                <div className="endgames-preview-body">
                  <span className="page-eyebrow">{selected.category}</span>
                  <h2>{selected.title}</h2>
                  <p>{selected.summary}</p>
                  {selected.kind === 'game' && selected.played_at && (
                    <p className="endgames-meta">Move {selected.move_number}, {formatGameDate(selected.played_at)}</p>
                  )}
                  <p className="endgames-meta">
                    You play {selected.player_color}. {goalLabel(selected)} within {selected.move_limit} moves.
                    {selected.attempts > 0 && ` ${selected.passes} of ${selected.attempts} passed so far.`}
                  </p>
                  <button className="primary" onClick={() => start(selected)}>
                    <Swords size={17} /> {selected.attempts > 0 ? 'Play again' : 'Start drill'}
                  </button>
                </div>
              </>
            ) : (
              <Skeleton variant="board" label="Loading the first position" />
            )}
          </section>
        </div>
      )}
    </main>
  );
}

function DrillScreen({ drill, onRetry, onNext, onExit }: {
  drill: EndgameDrill;
  onRetry: () => void;
  onNext: (() => void) | null;
  onExit: () => void;
}) {
  const { player, platform } = useWorkspace();
  const queryClient = useQueryClient();
  const [moves, setMoves] = useState<PlayedMove[]>([]);
  const [strikes, setStrikes] = useState(0);
  const [thinking, setThinking] = useState(false);
  const [finished, setFinished] = useState<EndgameTurn | null>(null);
  const [error, setError] = useState('');
  const [failedLine, setFailedLine] = useState<PlayedMove[] | null>(null);
  const [hintOpen, setHintOpen] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const startedAt = useRef(Date.now());

  const fen = moves[moves.length - 1]?.fen ?? drill.fen;
  const last = moves[moves.length - 1];
  const yourTurn = !finished && !thinking && !failedLine;
  const movesPlayed = Math.ceil(moves.length / 2);

  function finish(turn: EndgameTurn) {
    setFinished(turn);
    if (!turn.recorded) return;
    void queryClient.invalidateQueries({ queryKey: endgamesKey(platform, player) });
    void queryClient.invalidateQueries({ queryKey: ['progress', platform, player] });
    void queryClient.invalidateQueries({ queryKey: todayKey(platform, player) });
  }

  // Sent only from a move or a button, never an effect: a finished line records one attempt.
  async function send(line: PlayedMove[], resign = false) {
    setThinking(true);
    setError('');
    setFailedLine(null);
    const asked = performance.now();
    try {
      const turn = await takeEndgameTurn({
        drill_id: drill.id,
        moves_uci: line.map((move) => move.uci),
        strikes,
        resign,
        hints_used: hintOpen ? 1 : 0,
        elapsed_ms: Date.now() - startedAt.current,
        ...(player.trim() ? { platform, username: player.trim() } : {})
      });
      setStrikes(turn.strikes);
      if (turn.reply_uci && turn.reply_san) {
        const wait = REPLY_DELAY_MS - (performance.now() - asked);
        if (wait > 0) await new Promise((resolve) => window.setTimeout(resolve, wait));
        const { reply_uci: uci, reply_san: san } = turn;
        setMoves([...line, { san, uci, fen: turn.fen, from: uci.slice(0, 2), to: uci.slice(2, 4) }]);
      }
      if (turn.status !== 'playing') finish(turn);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Stockfish could not reply.');
      if (!resign) setFailedLine(line);
    } finally {
      setThinking(false);
    }
  }

  function onMove(move: BoardMove): boolean {
    if (!yourTurn) return false;
    const board = loadGame(fen);
    const played = board?.move({ from: move.from, to: move.to, promotion: move.promotion });
    if (!board || !played) return false;
    const line = [...moves, { san: played.san, uci: move.uci, fen: board.fen(), from: move.from, to: move.to }];
    setMoves(line);
    void send(line);
    return true;
  }

  const rows = useMemo(() => {
    if (!moves.length) return [];
    const blackFirst = drill.player_color === 'black';
    const firstNumber = Number(drill.fen.split(' ')[5]) || 1;
    const cells: Array<string | null> = blackFirst ? [null, ...moves.map((m) => m.san)] : moves.map((m) => m.san);
    const out: Array<{ number: number; white: string | null; black: string | null }> = [];
    for (let index = 0; index < cells.length; index += 2) {
      out.push({ number: firstNumber + index / 2, white: cells[index], black: cells[index + 1] ?? null });
    }
    return out;
  }, [moves, drill]);

  const passed = finished?.status === 'passed';

  return (
    <main className="route-page play-page">
      <button className="ghost endgames-back" onClick={onExit}><ArrowLeft size={16} /> All endgames</button>
      <div className="play-game">
        <section className="play-board-column">
          <div className="play-strip">
            <span className="play-avatar small endgames-engine" aria-hidden>S</span>
            <strong>Stockfish</strong>
            {thinking && <span className="play-strip-status"><Loader2 className="spin" size={14} /> Thinking</span>}
          </div>
          <div className="play-board">
            <ChessBoard
              fen={fen}
              orientation={drill.player_color}
              youColor={drill.player_color}
              onMove={finished ? undefined : onMove}
              lastMove={last ? { from: last.from, to: last.to } : undefined}
            />
          </div>
          <div className="play-strip">
            <span className={`play-avatar small you ${drill.player_color}`} aria-hidden>Y</span>
            <strong>You</strong>
            {yourTurn && <span className="play-strip-status">Your move</span>}
          </div>
        </section>

        <aside className="play-side">
          {finished ? (
            <div className={passed ? 'play-result' : 'play-result endgames-failed'} role="status">
              <div>
                <strong className="endgames-result-title">
                  {passed ? <Check size={20} aria-hidden /> : <X size={20} aria-hidden />}
                  {passed ? 'Passed' : 'Not this time'}
                </strong>
                <span>{finished.reason}</span>
                <span>{reviewNote(finished)}</span>
              </div>
              <div className="play-result-actions">
                {onNext && (
                  <button className={passed ? 'primary' : 'secondary'} onClick={onNext}><ArrowRight size={16} /> Next drill</button>
                )}
                <button className={passed || !onNext ? 'secondary' : 'primary'} onClick={onRetry}><RotateCcw size={16} /> Try again</button>
              </div>
            </div>
          ) : (
            <div className="endgames-goal">
              <span className="page-eyebrow">{drill.title}</span>
              <strong>{goalLabel(drill)}</strong>
              <p>{drill.summary}</p>
              <span className="endgames-meta">{Math.max(0, drill.move_limit - movesPlayed)} of {drill.move_limit} moves left</span>
            </div>
          )}

          {drill.hint && (hintOpen ? (
            <p className="endgames-hint"><Lightbulb size={16} aria-hidden /> {drill.hint}</p>
          ) : !finished && (
            <button className="secondary" onClick={() => setHintOpen(true)}>
              <Lightbulb size={16} /> Show the idea (shortens the next review)
            </button>
          ))}

          <div className="play-moves-card">
            <div className="play-moves-head">
              <strong>Moves</strong>
              <span>{moves.length ? `${movesPlayed} ${movesPlayed === 1 ? 'move' : 'moves'}` : 'No moves yet'}</span>
            </div>
            <ol className="play-moves">
              {rows.map((row) => (
                <li key={row.number}>
                  <span className="play-move-number">{row.number}.</span>
                  <span>{row.white ?? '…'}</span>
                  <span>{row.black ?? ''}</span>
                </li>
              ))}
            </ol>
            {error && (
              <p className="play-error" role="alert">
                <AlertCircle size={16} /> {error}
                {failedLine && <button className="play-link" onClick={() => void send(failedLine)}>Try again</button>}
              </p>
            )}
          </div>

          {!finished && (
            <div className="play-controls">
              <button
                className={confirmStop ? 'secondary play-danger' : 'secondary'}
                disabled={thinking}
                onBlur={() => setConfirmStop(false)}
                onClick={() => {
                  if (!confirmStop) {
                    setConfirmStop(true);
                    return;
                  }
                  void send(moves, true);
                }}
              >
                <Flag size={16} /> {confirmStop ? 'Confirm: count as missed' : 'Give up'}
              </button>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}
