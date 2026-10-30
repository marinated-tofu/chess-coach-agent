import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation } from '@tanstack/react-router';
import { AlertTriangle, BookMarked, Check, ChevronLeft, ChevronsLeft, Loader2, Microscope, RotateCcw, Trash2, X } from 'lucide-react';
import { ARROW_COLORS, ChessBoard, type BoardArrow } from '../components/ChessBoard';
import { PageHeader } from '../components/PageHeader';
import { playMove, type BoardMove } from '../lib/chessRules';
import {
  addRepertoireMove,
  answerDrill,
  createRepertoire,
  getDrill,
  getRepertoire,
  listRepertoires,
  removeRepertoireMove,
  seedRepertoire,
  type DrillItem,
  type DrillResult,
  type Repertoire,
  type RepertoireColor,
  type RepertoireNode,
  type SeedResult
} from '../lib/repertoireApi';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './RepertoirePage.css';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const PLAYER_ARROW = 'rgba(21, 120, 75, 0.7)';
const OPPONENT_ARROW = 'rgba(32, 98, 196, 0.55)';

type Mode = 'edit' | 'drill';

function squares(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4) };
}

function moveLabel(node: RepertoireNode, forceNumber: boolean) {
  const number = Math.ceil(node.ply / 2);
  if (node.ply % 2 === 1) return `${number}. ${node.san}`;
  return forceNumber ? `${number}… ${node.san}` : node.san;
}

function lineText(line: string[]) {
  return line.map((san, index) => (index % 2 === 0 ? `${index / 2 + 1}. ${san}` : san)).join(' ');
}

/** Resolve a list of node ids against the current tree, dropping anything that no longer exists. */
function resolvePath(tree: RepertoireNode[], ids: string[]): RepertoireNode[] {
  const path: RepertoireNode[] = [];
  let children = tree;
  for (const id of ids) {
    const node = children.find((child) => child.id === id);
    if (!node) break;
    path.push(node);
    children = node.children;
  }
  return path;
}

/** Board, side to move, castling and en passant: the parts that identify a position. */
function positionKey(fen: string) {
  return fen.trim().split(/\s+/).slice(0, 4).join(' ');
}

/** Node ids of the first line in the tree that reaches `fen`, or null. */
function findPath(tree: RepertoireNode[], fen: string): string[] | null {
  const target = positionKey(fen);
  if (positionKey(START_FEN) === target) return [];
  const seen = new Set<string>();
  function walk(nodes: RepertoireNode[], before: string, ids: string[]): string[] | null {
    for (const node of nodes) {
      const result = playMove(before, { ...squares(node.uci), promotion: node.uci[4] as 'q' | undefined });
      if (!result) continue;
      const key = positionKey(result.fen);
      const path = [...ids, node.id];
      if (key === target) return path;
      if (seen.has(key)) continue;
      seen.add(key);
      const found = walk(node.children, result.fen, path);
      if (found) return found;
    }
    return null;
  }
  return walk(tree, START_FEN, []);
}

function fenAfter(path: RepertoireNode[]) {
  let fen = START_FEN;
  for (const node of path) {
    const result = playMove(fen, { ...squares(node.uci), promotion: node.uci[4] as 'q' | undefined });
    if (!result) break;
    fen = result.fen;
  }
  return fen;
}

export function RepertoirePage() {
  const { player, platform } = useWorkspace();
  const queryClient = useQueryClient();
  // The explorer links here with ?fen=&color= to open that position in the matching repertoire.
  const linked = useLocation({
    select: (location) => {
      const search = location.search as Record<string, unknown>;
      return {
        fen: typeof search.fen === 'string' ? search.fen : undefined,
        color: search.color === 'black' || search.color === 'white' ? (search.color as RepertoireColor) : undefined,
        // The study plan links here with ?drill=true to open the drill directly.
        drill: search.drill === true || search.drill === 'true'
      };
    },
    structuralSharing: true
  });
  const [color, setColor] = useState<RepertoireColor>(linked.color ?? 'white');
  const [mode, setMode] = useState<Mode>(linked.drill ? 'drill' : 'edit');
  const [seedNote, setSeedNote] = useState<SeedResult | null>(null);

  const listKey = ['repertoires', platform, player.trim().toLowerCase()];
  const list = useQuery({
    queryKey: listKey,
    queryFn: () => listRepertoires(player, platform),
    enabled: Boolean(player.trim())
  });
  const summary = list.data?.find((rep) => rep.color === color);
  const repertoire = useQuery({
    queryKey: ['repertoire', summary?.id],
    queryFn: () => getRepertoire(summary!.id),
    enabled: Boolean(summary)
  });

  const storeRepertoire = (rep: Repertoire) => {
    queryClient.setQueryData(['repertoire', rep.id], rep);
    queryClient.invalidateQueries({ queryKey: listKey });
  };

  const build = useMutation({
    mutationFn: async () => {
      const id = summary?.id ?? (await createRepertoire(player, platform, color)).id;
      return seedRepertoire(id);
    },
    onSuccess: (result) => {
      setSeedNote(result);
      storeRepertoire(result);
    }
  });

  const rep = repertoire.data;
  const empty = !summary || (rep && rep.tree.length === 0);
  const loading = list.isLoading || (summary && repertoire.isLoading);

  return (
    <main className="route-page repertoire-page">
      <PageHeader
        eyebrow="Openings"
        title="Repertoire"
        detail="Lines built from the openings you actually play, with the moves you keep getting wrong swapped for better ones."
        actions={
          rep && rep.tree.length > 0 ? (
            <button className="secondary" type="button" onClick={() => build.mutate()} disabled={build.isPending}>
              {build.isPending ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
              Rebuild from my games
            </button>
          ) : undefined
        }
      />

      <div className="rep-toolbar">
        <div className="rep-segmented" role="group" aria-label="Repertoire color">
          {(['white', 'black'] as const).map((side) => (
            <button
              key={side}
              type="button"
              aria-pressed={color === side}
              onClick={() => { setColor(side); setSeedNote(null); }}
            >
              <span className={`rep-swatch ${side}`} aria-hidden="true" />
              {side === 'white' ? 'White' : 'Black'}
            </button>
          ))}
        </div>
        {!empty && rep && (
          <div className="rep-segmented" role="group" aria-label="Mode">
            <button type="button" aria-pressed={mode === 'edit'} onClick={() => setMode('edit')}>Edit</button>
            <button type="button" aria-pressed={mode === 'drill'} onClick={() => setMode('drill')}>
              Drill
              {rep.due_count > 0 && <span className="rep-badge">{rep.due_count}</span>}
            </button>
          </div>
        )}
      </div>

      {seedNote && <SeedSummary result={seedNote} onClose={() => setSeedNote(null)} />}
      {build.isError && <p className="rep-error" role="alert">{(build.error as Error).message}</p>}

      {!player.trim() ? (
        <div className="empty-route"><h2>Pick a player first</h2><p>Load your games from the Games page.</p></div>
      ) : list.isError ? (
        <div className="empty-route"><h2>No games yet</h2><p>{(list.error as Error).message}</p></div>
      ) : loading ? (
        <div className="rep-skeleton" aria-busy="true"><div /><div /></div>
      ) : empty ? (
        <div className="empty-route rep-empty">
          <BookMarked size={28} aria-hidden="true" />
          <h2>No {color} repertoire yet</h2>
          <p>We'll read your games as {color}, keep the lines you play most and score best with, and fix the moves you keep getting wrong.</p>
          <button className="primary" type="button" onClick={() => build.mutate()} disabled={build.isPending}>
            {build.isPending ? <Loader2 className="spin" size={16} /> : <BookMarked size={16} />}
            {build.isPending ? 'Reading your games…' : 'Build from my games'}
          </button>
        </div>
      ) : rep && mode === 'edit' ? (
        <EditMode key={rep.id} rep={rep} onChange={storeRepertoire} targetFen={rep.color === linked.color ? linked.fen : undefined} />
      ) : rep ? (
        <DrillMode key={rep.id} rep={rep} onAnswered={() => queryClient.invalidateQueries({ queryKey: ['repertoire', rep.id] })} />
      ) : null}
    </main>
  );
}

function SeedSummary({ result, onClose }: { result: SeedResult; onClose: () => void }) {
  return (
    <div className="rep-notice" role="status">
      <div>
        <strong>
          {result.added === 0 ? 'Nothing new to add' : `Added ${result.added} moves`} from {result.games_used} games.
        </strong>
        {result.flagged.length > 0 && (
          <span>
            {' '}{result.flagged.length} {result.flagged.length === 1 ? 'line uses' : 'lines use'} the engine's move where yours kept going wrong
            ({result.flagged.map((flag) => `${flag.played_san} → ${flag.best_san}`).join(', ')}).
          </span>
        )}
        {result.games_used === 0 && <span> Sync some games as this color first.</span>}
      </div>
      <button className="rep-icon-button" type="button" aria-label="Dismiss" onClick={onClose}><X size={16} /></button>
    </div>
  );
}

/* ------------------------------------------------------------------ edit mode */

function EditMode({ rep, onChange, targetFen }: { rep: Repertoire; onChange: (rep: Repertoire) => void; targetFen?: string }) {
  const [target] = useState(() => (targetFen ? { fen: targetFen, path: findPath(rep.tree, targetFen) } : null));
  const [pathIds, setPathIds] = useState<string[]>(target?.path ?? []);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const path = useMemo(() => resolvePath(rep.tree, pathIds), [rep.tree, pathIds]);
  const current = path[path.length - 1];
  const fen = useMemo(() => fenAfter(path), [path]);
  const children = current ? current.children : rep.tree;

  const add = useMutation({
    mutationFn: (move: BoardMove) => addRepertoireMove(rep.id, fen, move.uci),
    onSuccess: (result) => {
      onChange(result);
      setPathIds([...path.map((node) => node.id), result.move_id]);
    }
  });
  const remove = useMutation({
    mutationFn: (moveId: string) => removeRepertoireMove(rep.id, moveId),
    onSuccess: (result) => {
      onChange(result);
      setPathIds(path.slice(0, -1).map((node) => node.id));
      setConfirmRemove(false);
    }
  });

  const goTo = (ids: string[]) => { setPathIds(ids); setConfirmRemove(false); };

  const onMove = (move: BoardMove) => {
    if (add.isPending) return false;
    const existing = children.find((child) => child.uci === move.uci);
    if (existing) {
      goTo([...path.map((node) => node.id), existing.id]);
      return true;
    }
    add.mutate(move);
    return true;
  };

  const arrows: BoardArrow[] = children.map((child) => ({
    ...squares(child.uci),
    color: child.is_player_move ? PLAYER_ARROW : OPPONENT_ARROW
  }));
  const yourTurn = (fen.split(' ')[1] === 'w') === (rep.color === 'white');

  return (
    <div className="rep-workspace">
      <section className="rep-board-column">
        <ChessBoard
          fen={fen}
          orientation={rep.color}
          onMove={onMove}
          arrows={arrows}
          lastMove={current ? squares(current.uci) : undefined}
        />
        <div className="rep-board-bar">
          <button className="secondary icon" type="button" aria-label="Back to start" onClick={() => goTo([])} disabled={!current}>
            <ChevronsLeft size={18} />
          </button>
          <button className="secondary icon" type="button" aria-label="Previous move" onClick={() => goTo(pathIds.slice(0, path.length - 1))} disabled={!current}>
            <ChevronLeft size={18} />
          </button>
          <p className="rep-hint">
            {add.isPending ? 'Saving…' : children.length
              ? (yourTurn ? 'Play a move to follow your line or add a new one.' : 'Play a reply to follow it or add it.')
              : (yourTurn ? 'Your move: play it to add it.' : 'Add a reply you expect from opponents.')}
          </p>
          {current && (
            confirmRemove ? (
              <span className="rep-confirm">
                <button className="rep-danger" type="button" onClick={() => remove.mutate(current.id)} disabled={remove.isPending}>
                  Remove {current.san} and what follows
                </button>
                <button className="secondary" type="button" onClick={() => setConfirmRemove(false)}>Cancel</button>
              </span>
            ) : (
              <button className="secondary icon" type="button" aria-label={`Remove ${current.san}`} onClick={() => setConfirmRemove(true)}>
                <Trash2 size={16} />
              </button>
            )
          )}
        </div>
        {target && !target.path && (
          <p className="rep-comment" role="status">
            That position isn't in your {rep.color} repertoire yet. Play the moves from the start to add the line.
          </p>
        )}
        {(add.isError || remove.isError) && (
          <p className="rep-error" role="alert">{((add.error ?? remove.error) as Error).message}</p>
        )}
        {current?.comment && (
          <p className={`rep-comment ${current.mistake_count ? 'is-fix' : ''}`}>
            {current.mistake_count > 0 && <AlertTriangle size={16} aria-hidden="true" />}
            {current.comment}
          </p>
        )}
      </section>

      <section className="rep-tree-panel" aria-label="Repertoire lines">
        <header>
          <h2>{rep.name}</h2>
          <span className="rep-legend">
            <i className="you" /> your moves <i className="them" /> replies
          </span>
        </header>
        <div className="rep-tree">
          <Branch nodes={rep.tree} prefix={[]} activeIds={pathIds} onSelect={goTo} />
        </div>
      </section>
    </div>
  );
}

/**
 * One line of play: moves continue inline while each position has a single follow-up;
 * where there are several, every option opens its own indented branch.
 */
function Branch({ nodes, prefix, activeIds, onSelect }: {
  nodes: RepertoireNode[];
  prefix: string[];
  activeIds: string[];
  onSelect: (ids: string[]) => void;
}) {
  if (nodes.length === 0) return null;
  if (nodes.length > 1) {
    return (
      <div className="rep-branches">
        {nodes.map((node) => (
          <div className="rep-branch" key={node.id}>
            <Line start={node} prefix={prefix} activeIds={activeIds} onSelect={onSelect} />
          </div>
        ))}
      </div>
    );
  }
  return <Line start={nodes[0]} prefix={prefix} activeIds={activeIds} onSelect={onSelect} />;
}

function Line({ start, prefix, activeIds, onSelect }: {
  start: RepertoireNode;
  prefix: string[];
  activeIds: string[];
  onSelect: (ids: string[]) => void;
}) {
  const run: Array<{ node: RepertoireNode; ids: string[] }> = [];
  let node: RepertoireNode | undefined = start;
  let ids = prefix;
  while (node) {
    ids = [...ids, node.id];
    run.push({ node, ids });
    node = node.children.length === 1 ? node.children[0] : undefined;
  }
  const last = run[run.length - 1];
  const activeId = activeIds[activeIds.length - 1];
  return (
    <>
      <div className="rep-line">
        {run.map(({ node: item, ids: itemIds }, index) => (
          <Fragment key={item.id}>
            <button
              type="button"
              className={[
                'rep-move',
                item.is_player_move ? 'you' : 'them',
                item.id === activeId && itemIds.length === activeIds.length ? 'active' : '',
                item.mistake_count ? 'fixed' : ''
              ].join(' ')}
              onClick={() => onSelect(itemIds)}
            >
              {moveLabel(item, index === 0)}
              {item.mistake_count > 0 && <AlertTriangle size={12} aria-label="Replaced a repeated mistake" />}
              {item.transposition && <span className="rep-transpose" title="Transposes to a position listed elsewhere">⇄</span>}
            </button>
            {item.comment && <span className="rep-inline-comment">{item.comment}</span>}
          </Fragment>
        ))}
      </div>
      <Branch nodes={last.node.children} prefix={last.ids} activeIds={activeIds} onSelect={onSelect} />
    </>
  );
}

/* ------------------------------------------------------------------ drill mode */

type Feedback = { result: DrillResult; fen: string; lastMove?: { from: string; to: string } };

function DrillMode({ rep, onAnswered }: { rep: Repertoire; onAnswered: () => void }) {
  const [includeAll, setIncludeAll] = useState(false);
  const [round, setRound] = useState(0);
  const [queue, setQueue] = useState<DrillItem[] | null>(null);
  const [done, setDone] = useState(0);
  const [correct, setCorrect] = useState(0);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const advanceTimer = useRef<number | undefined>(undefined);

  const drill = useQuery({
    queryKey: ['repertoire-drill', rep.id, includeAll, round],
    queryFn: () => getDrill(rep.id, 10, includeAll),
    staleTime: Infinity,
    gcTime: 0
  });
  const items = queue ?? drill.data?.items ?? [];
  const item = items[0];
  const total = done + items.length;

  useEffect(() => () => window.clearTimeout(advanceTimer.current), []);

  const next = (repeat: boolean) => {
    setFeedback(null);
    setQueue((previous) => {
      const [first, ...rest] = previous ?? drill.data?.items ?? [];
      return repeat && first ? [...rest, first] : rest;
    });
  };

  const answer = useMutation({
    mutationFn: (move: BoardMove) => answerDrill(rep.id, item.move_id, move.uci),
    onSuccess: (result, move) => {
      onAnswered();
      if (result.correct) {
        const after = playMove(item.fen, move.uci);
        setFeedback({ result, fen: after?.fen ?? item.fen, lastMove: { from: move.from, to: move.to } });
        setDone((count) => count + 1);
        setCorrect((count) => count + 1);
        advanceTimer.current = window.setTimeout(() => next(false), 700);
      } else {
        setFeedback({ result, fen: item.fen, lastMove: item.last_move ? squares(item.last_move) : undefined });
      }
    }
  });

  const restart = (all: boolean) => {
    setQueue(null); setDone(0); setCorrect(0); setFeedback(null);
    setIncludeAll(all);
    setRound((value) => value + 1);
  };

  if (drill.isLoading) return <div className="rep-skeleton" aria-busy="true"><div /><div /></div>;
  if (drill.isError) return <p className="rep-error" role="alert">{(drill.error as Error).message}</p>;

  if (!item) {
    const finished = done > 0;
    return (
      <div className="empty-route rep-empty">
        <Check size={28} aria-hidden="true" />
        <h2>{finished ? `Done: ${correct} of ${done} first try` : 'Nothing due right now'}</h2>
        <p>{finished ? 'Missed moves come back in ten minutes; the rest are spaced out over the next days.' : 'Every line is scheduled for later. You can still run through them now.'}</p>
        <button className="primary" type="button" onClick={() => restart(true)}>Practice anyway</button>
      </div>
    );
  }

  const wrong = feedback && !feedback.result.correct;
  const arrows: BoardArrow[] = wrong ? [{ ...squares(feedback.result.expected_uci), color: ARROW_COLORS.best }] : [];
  const boardFen = feedback?.fen ?? item.fen;
  const lastMove = feedback?.lastMove ?? (item.last_move ? squares(item.last_move) : undefined);

  return (
    <div className="rep-workspace">
      <section className="rep-board-column">
        <ChessBoard
          key={item.move_id + done}
          fen={boardFen}
          orientation={rep.color}
          onMove={feedback || answer.isPending ? undefined : (move) => { answer.mutate(move); return true; }}
          arrows={arrows}
          lastMove={lastMove}
        />
      </section>
      <section className="rep-drill-panel" aria-live="polite">
        <div className="rep-progress">
          <span className="rep-progress-count">{Math.min(done + 1, total)} / {total}</span>
          <div className="rep-progress-track" aria-hidden="true">
            <div style={{ transform: `scaleX(${total ? done / total : 0})` }} />
          </div>
        </div>
        <p className="rep-drill-line">{item.line.length ? lineText(item.line) : 'Starting position'}</p>
        {!feedback && <p className="rep-drill-prompt">Your move as {rep.color}. What does your repertoire play here?</p>}
        {feedback?.result.correct && (
          <p className="rep-verdict good"><Check size={18} aria-hidden="true" /> {feedback.result.expected_san === feedback.result.played_san ? 'Correct' : `Also in your repertoire (${feedback.result.played_san})`}</p>
        )}
        {wrong && (
          <>
            <p className="rep-verdict bad">
              <X size={18} aria-hidden="true" />
              {feedback.result.played_san ?? 'That move'} isn't your line. Play {feedback.result.expected_san}.
            </p>
            {feedback.result.comment && <p className="rep-comment is-fix"><AlertTriangle size={16} aria-hidden="true" />{feedback.result.comment}</p>}
            <p className="rep-drill-note">It comes back later in this session.</p>
            <div className="rep-drill-actions">
              <button className="primary" type="button" onClick={() => next(true)}>Continue</button>
              <Link className="secondary" to="/analysis" search={{ fen: item.fen, tab: 'explorer' }}>
                <Microscope size={16} /> Open in explorer
              </Link>
            </div>
          </>
        )}
        {answer.isError && <p className="rep-error" role="alert">{(answer.error as Error).message}</p>}
        <p className="rep-drill-score">{correct} correct · {rep.due_count} due</p>
      </section>
    </div>
  );
}
