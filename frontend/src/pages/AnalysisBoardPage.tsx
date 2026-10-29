import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Chess } from 'chess.js';
import { Link } from '@tanstack/react-router';
import {
  ArrowLeft,
  Bot,
  Check,
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
  Copy,
  FlipVertical2,
  Loader2,
  RotateCcw,
  Square
} from 'lucide-react';
import { ARROW_COLORS, ChessBoard, type BoardArrow } from '../components/ChessBoard';
import { CoachPanel } from '../components/CoachPanel';
import { PageHeader } from '../components/PageHeader';
import { playMove, sideToMove, type BoardMove } from '../lib/chessRules';
import { useCoachMarks } from '../lib/coachMarks';
import {
  analyzePosition,
  formatEval,
  requestBotMove,
  whiteWinPercent,
  type EngineAnalysis
} from '../lib/engineApi';
import type { PieceColor } from '../lib/squareControl';
import './AnalysisBoardPage.css';
import { OpeningExplorer } from '../components/OpeningExplorer';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const ROOT = 'root';
const ENGINE_DEBOUNCE_MS = 250;
const LEVEL_ELO = [800, 1000, 1200, 1400, 1600, 1800, 2100, 2400];

/* ---------- Move tree ---------- */

type TreeNode = {
  id: string;
  fen: string;
  parent: string | null;
  /** children[0] continues the line; the rest are variations. */
  children: string[];
  move?: BoardMove;
};

type Tree = { nodes: Record<string, TreeNode>; nextId: number };

function newTree(fen: string): Tree {
  return { nodes: { [ROOT]: { id: ROOT, fen, parent: null, children: [] } }, nextId: 1 };
}

/** Adds `move` after `parentId`, reusing an existing child with the same move. */
function addMove(tree: Tree, parentId: string, move: BoardMove, fen: string): { tree: Tree; id: string } {
  const parent = tree.nodes[parentId];
  const existing = parent.children.find((childId) => tree.nodes[childId].move?.uci === move.uci);
  if (existing) return { tree, id: existing };
  const id = `n${tree.nextId}`;
  return {
    id,
    tree: {
      nextId: tree.nextId + 1,
      nodes: {
        ...tree.nodes,
        [parentId]: { ...parent, children: [...parent.children, id] },
        [id]: { id, fen, parent: parentId, children: [], move }
      }
    }
  };
}

function pathTo(tree: Tree, id: string): TreeNode[] {
  const path: TreeNode[] = [];
  for (let node: TreeNode | undefined = tree.nodes[id]; node; node = node.parent ? tree.nodes[node.parent] : undefined) {
    path.unshift(node);
  }
  return path;
}

function lineEnd(tree: Tree, id: string): string {
  let node = tree.nodes[id];
  while (node.children.length) node = tree.nodes[node.children[0]];
  return node.id;
}

/* ---------- Game state ---------- */

type GameOver = { kind: 'checkmate' | 'stalemate' | 'repetition' | 'insufficient' | 'fifty'; winner: PieceColor | null };

/** Replays the path from the root so threefold repetition sees the whole history. */
function gameOverAt(tree: Tree, id: string): GameOver | null {
  const path = pathTo(tree, id);
  let game: Chess;
  try {
    game = new Chess(path[0].fen);
    for (const node of path.slice(1)) if (node.move) game.move(node.move.san);
  } catch {
    return null;
  }
  if (game.isCheckmate()) return { kind: 'checkmate', winner: game.turn() === 'w' ? 'black' : 'white' };
  if (game.isStalemate()) return { kind: 'stalemate', winner: null };
  if (game.isThreefoldRepetition()) return { kind: 'repetition', winner: null };
  if (game.isInsufficientMaterial()) return { kind: 'insufficient', winner: null };
  if (game.isDrawByFiftyMoves()) return { kind: 'fifty', winner: null };
  return null;
}

const DRAW_REASON: Record<Exclude<GameOver['kind'], 'checkmate'>, string> = {
  stalemate: 'stalemate',
  repetition: 'threefold repetition',
  insufficient: 'insufficient material',
  fifty: 'the fifty-move rule'
};

function resultText(over: GameOver, you: PieceColor | null): string {
  if (over.kind !== 'checkmate') return `Draw by ${DRAW_REASON[over.kind]}`;
  if (!you) return `Checkmate. ${over.winner === 'white' ? 'White' : 'Black'} wins`;
  return over.winner === you ? 'Checkmate. You win' : 'Checkmate. The computer wins';
}

function validateFen(fen: string): string | null {
  if (!fen.trim()) return 'Paste a FEN first.';
  try {
    new Chess(fen.trim());
    return null;
  } catch (error) {
    const reason = error instanceof Error ? error.message.replace(/^Invalid FEN: /i, '') : '';
    return reason ? `That FEN is not valid: ${reason}.` : 'That FEN is not valid.';
  }
}

function moveNumber(fen: string): number {
  return Number(fen.split(' ')[5]) || 1;
}

/* ---------- Page ---------- */

type PlayState = { color: PieceColor; level: number };

/** "game:<id>:<ply>" from the review page's "Open in analysis". */
function parseFrom(from: string | undefined): { gameId: string; ply: number } | null {
  const match = /^game:([^:]+):(\d+)$/.exec(from ?? '');
  return match ? { gameId: match[1], ply: Number(match[2]) } : null;
}

export function AnalysisBoardPage({
  initialFen,
  from,
  focus
}: {
  initialFen?: string;
  from?: string;
  /** Scroll to and open a panel on arrival: the opening explorer or the coach. */
  focus?: 'explorer' | 'coach';
}) {
  const origin = parseFrom(from);
  const startFen = initialFen && !validateFen(initialFen) ? initialFen.trim() : START_FEN;
  const [tree, setTree] = useState(() => newTree(startFen));
  const [currentId, setCurrentId] = useState(ROOT);
  const [orientation, setOrientation] = useState<PieceColor>(() => sideToMove(startFen));
  const [engineOn, setEngineOn] = useState(true);
  const [analysis, setAnalysis] = useState<EngineAnalysis | null>(null);
  const [engineError, setEngineError] = useState('');
  const [fenDraft, setFenDraft] = useState('');
  const [fenError, setFenError] = useState(initialFen && validateFen(initialFen) ? 'The linked FEN was not valid, so the board starts from the initial position.' : '');
  const [copied, setCopied] = useState(false);
  const [play, setPlay] = useState<PlayState | null>(null);
  const [playColor, setPlayColor] = useState<PieceColor | null>(null);
  const [playLevel, setPlayLevel] = useState(3);
  const [thinking, setThinking] = useState(false);
  const [botError, setBotError] = useState('');

  const current = tree.nodes[currentId];
  const fen = current.fen;
  const turn = sideToMove(fen);
  const over = useMemo(() => gameOverAt(tree, currentId), [tree, currentId]);
  const coachMarks = useCoachMarks(fen);
  const treeRef = useRef(tree);
  treeRef.current = tree;

  useEffect(() => {
    if (!focus) return;
    // Wait a frame: the router restores scroll to the top after the page mounts.
    const id = window.setTimeout(() => {
      document.getElementById(focus === 'coach' ? 'analysis-coach' : 'analysis-explorer')?.scrollIntoView({ block: 'start' });
    }, 60);
    return () => window.clearTimeout(id);
  }, [focus]);

  const playBoardMove = useCallback((parentId: string, move: BoardMove, fenAfter: string) => {
    const result = addMove(treeRef.current, parentId, move, fenAfter);
    treeRef.current = result.tree;
    setTree(result.tree);
    setCurrentId(result.id);
  }, []);

  function handleBoardMove(move: BoardMove) {
    if (play && (turn !== play.color || thinking)) return false;
    if (over) return false;
    const result = playMove(fen, { from: move.from, to: move.to, promotion: move.promotion });
    if (!result) return false;
    playBoardMove(currentId, result.move, result.fen);
    return true;
  }

  function playSan(san: string) {
    const result = playMove(fen, san);
    if (result) playBoardMove(currentId, result.move, result.fen);
  }

  /* Navigation */
  const goBack = useCallback(() => setCurrentId((id) => treeRef.current.nodes[id].parent ?? id), []);
  const goForward = useCallback(() => setCurrentId((id) => treeRef.current.nodes[id].children[0] ?? id), []);
  const goStart = useCallback(() => setCurrentId(ROOT), []);
  const goEnd = useCallback(() => setCurrentId((id) => lineEnd(treeRef.current, id)), []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const action = { ArrowLeft: goBack, ArrowRight: goForward, Home: goStart, End: goEnd }[event.key];
      if (!action) return;
      event.preventDefault();
      action();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goBack, goForward, goStart, goEnd]);

  /* Engine: debounced, stale requests aborted. Paused while playing the computer. */
  const engineActive = engineOn && !play;
  useEffect(() => {
    if (!engineActive) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      analyzePosition(fen, { multipv: 3, depth: 14, signal: controller.signal })
        .then((result) => {
          setAnalysis({ ...result, fen });
          setEngineError('');
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setEngineError(error instanceof Error ? error.message : 'The engine is not responding.');
        });
    }, ENGINE_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [fen, engineActive]);

  const liveAnalysis = engineActive && analysis?.fen === fen ? analysis : null;
  // Keep the previous lines on screen (dimmed, not clickable) while the new ones load.
  const shownAnalysis = engineActive ? analysis : null;
  const stale = Boolean(shownAnalysis && !liveAnalysis);
  const bestLine = liveAnalysis?.lines[0] ?? null;

  /* Bot: replies whenever it is its turn at the end of a line. */
  const botToMove = Boolean(play && !over && turn !== play.color && current.children.length === 0);
  useEffect(() => {
    if (!play || !botToMove) return;
    const controller = new AbortController();
    const fromId = currentId;
    setThinking(true);
    setBotError('');
    requestBotMove(fen, play.level, controller.signal)
      .then((reply) => {
        const result = playMove(fen, reply.move_uci);
        if (result) playBoardMove(fromId, result.move, result.fen);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setBotError(error instanceof Error ? error.message : 'The computer could not move.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setThinking(false);
      });
    return () => {
      controller.abort();
      setThinking(false);
    };
  }, [play, botToMove, fen, currentId, playBoardMove]);

  function startPlaying() {
    const color = playColor ?? turn;
    setPlay({ color, level: playLevel });
    setOrientation(color);
    setBotError('');
  }

  function stopPlaying() {
    setPlay(null);
    setThinking(false);
    setBotError('');
  }

  function loadFen(next: string) {
    stopPlaying();
    const fresh = newTree(next);
    treeRef.current = fresh;
    setTree(fresh);
    setCurrentId(ROOT);
    setOrientation(sideToMove(next));
    setAnalysis(null);
  }

  function submitFen(event: FormEvent) {
    event.preventDefault();
    const error = validateFen(fenDraft);
    setFenError(error ?? '');
    if (error) return;
    loadFen(fenDraft.trim());
    setFenDraft('');
  }

  async function copyFen() {
    try {
      await navigator.clipboard.writeText(fen);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  /* Board marks */
  const arrows: BoardArrow[] = useMemo(() => {
    const marks: BoardArrow[] = [];
    if (bestLine) marks.push({ from: bestLine.move_uci.slice(0, 2), to: bestLine.move_uci.slice(2, 4), color: ARROW_COLORS.best });
    return [...marks, ...coachMarks.arrows];
  }, [bestLine, coachMarks.arrows]);

  let evalSource: { eval_cp: number | null; mate: number | null } | null = bestLine ?? shownAnalysis?.lines[0] ?? null;
  if (over) evalSource = over.kind === 'checkmate' ? { eval_cp: null, mate: over.winner === 'white' ? 1 : -1 } : { eval_cp: 0, mate: null };
  const whitePct = evalSource ? whiteWinPercent(evalSource) : 50;
  const evalLabel = over?.kind === 'checkmate' ? (over.winner === 'white' ? '1-0' : '0-1') : over ? '½-½' : bestLine ? formatEval(bestLine) : '';
  const canMove = !over && !(play && (turn !== play.color || thinking));

  return (
    <main className="route-page analysis-page">
      <PageHeader
        eyebrow="Analysis board"
        title="Explore any position"
        detail="Try your own ideas, see Stockfish's top lines, and ask the coach why they work."
        actions={origin ? (
          <Link
            className="secondary"
            to="/games/$gameId"
            params={{ gameId: origin.gameId }}
            search={{ moment: undefined }}
            state={{ reviewPly: origin.ply }}
          >
            <ArrowLeft size={16} /> Back to game
          </Link>
        ) : undefined}
      />

      <section className="analysis-workspace">
        <div className="analysis-board-column">
          <div className="analysis-board-row">
            <div
              className={`analysis-evalbar${orientation === 'black' ? ' flipped' : ''}`}
              role="img"
              aria-label={evalLabel ? `Evaluation ${evalLabel} from White's side` : 'No evaluation'}
            >
              <div className="analysis-evalbar-fill" style={{ transform: `scaleY(${whitePct / 100})` }} />
            </div>
            <ChessBoard
              fen={fen}
              orientation={orientation}
              onMove={canMove ? handleBoardMove : undefined}
              lastMove={current.move ? { from: current.move.from, to: current.move.to } : undefined}
              arrows={arrows}
              highlights={coachMarks.highlights}
            />
          </div>
          <div className="analysis-nav" role="group" aria-label="Move navigation">
            <button className="secondary icon" type="button" aria-label="First move" onClick={goStart} disabled={currentId === ROOT}><ChevronFirst size={18} /></button>
            <button className="secondary icon" type="button" aria-label="Previous move" onClick={goBack} disabled={currentId === ROOT}><ChevronLeft size={18} /></button>
            <button className="secondary icon" type="button" aria-label="Next move" onClick={goForward} disabled={!current.children.length}><ChevronRight size={18} /></button>
            <button className="secondary icon" type="button" aria-label="Last move" onClick={goEnd} disabled={!current.children.length}><ChevronLast size={18} /></button>
            <button className="secondary" type="button" aria-pressed={orientation === 'black'} onClick={() => setOrientation((side) => (side === 'white' ? 'black' : 'white'))}>
              <FlipVertical2 size={16} /> Flip
            </button>
            <button className="secondary" type="button" onClick={() => { loadFen(START_FEN); setFenError(''); }}>
              <RotateCcw size={16} /> Reset
            </button>
          </div>
          {over && (
            <p className="analysis-result" role="status">
              <strong>{resultText(over, play?.color ?? null)}</strong>
              {play && <button className="text-action" type="button" onClick={stopPlaying}>Back to analysis</button>}
            </p>
          )}
        </div>

        <div className="analysis-side">
          {play ? (
            <section className="analysis-card analysis-play" aria-label="Game against the computer">
              <div className="analysis-card-head">
                <h2>You play {play.color} · level {play.level}</h2>
                <button className="secondary" type="button" onClick={stopPlaying}><Square size={14} /> Stop playing</button>
              </div>
              <p className="analysis-play-status" role="status" aria-live="polite">
                {over ? 'Game over.' : thinking ? <><Loader2 className="spin" size={15} /> Thinking…</> : turn === play.color ? 'Your move.' : current.children.length ? 'Go to the last move to continue the game.' : ''}
              </p>
              {botError && <p className="analysis-error" role="alert">{botError}</p>}
              <p className="analysis-hint">The engine is off during the game. Stop playing to see its lines.</p>
            </section>
          ) : (
            <section className="analysis-card analysis-engine" aria-label="Engine">
              <div className="analysis-card-head">
                <h2>Stockfish{liveAnalysis?.depth ? <span className="analysis-depth"> · depth {liveAnalysis.depth}</span> : null}</h2>
                <label className="analysis-switch">
                  <input type="checkbox" role="switch" checked={engineOn} onChange={(event) => setEngineOn(event.target.checked)} />
                  <span>Engine</span>
                </label>
              </div>
              {!engineOn ? (
                <p className="analysis-hint">Engine is off.</p>
              ) : over ? (
                <p className="analysis-hint">The game is over in this position.</p>
              ) : engineError ? (
                <p className="analysis-error" role="alert">{engineError}</p>
              ) : !shownAnalysis ? (
                <p className="analysis-hint" aria-live="polite"><Loader2 className="spin" size={14} /> Analyzing…</p>
              ) : (
                <div className="analysis-engine-body" data-stale={stale || undefined} aria-busy={stale}>
                  <p className="analysis-eval" aria-live="polite">
                    {shownAnalysis.lines[0] ? formatEval(shownAnalysis.lines[0]) : '–'}
                    {stale && <Loader2 className="spin" size={16} aria-label="Analyzing" />}
                  </p>
                  <ol className="analysis-lines">
                    {shownAnalysis.lines.map((line) => (
                      <li key={line.rank}>
                        <button type="button" disabled={stale} onClick={() => playSan(line.move_san)} aria-label={`Play ${line.move_san}, line evaluated ${formatEval(line)}`}>
                          <span className="analysis-line-eval">{formatEval(line)}</span>
                          <span className="analysis-line-moves">{formatPv(shownAnalysis.fen, line.pv_san.slice(0, 6))}</span>
                        </button>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </section>
          )}

          {!play && (
            <div id="analysis-explorer" className="analysis-anchor">
              <OpeningExplorer fen={fen} onPlayMove={playSan} />
            </div>
          )}

          <section className="analysis-card analysis-moves" aria-label="Moves">
            <h2>Moves</h2>
            {tree.nodes[ROOT].children.length ? (
              <MoveList tree={tree} currentId={currentId} onSelect={setCurrentId} />
            ) : (
              <p className="analysis-hint">Make a move on the board to start a line.</p>
            )}
          </section>

          <div id="analysis-coach" className="analysis-anchor">
            <CoachPanel
              fen={fen}
              autoFocus={focus === 'coach'}
              onAnnotations={coachMarks.onAnnotations}
              suggestions={['Explain this position', 'What is the plan for the side to move?', 'Why is the engine move best?']}
            />
          </div>

          {!play && (
            <section className="analysis-card analysis-play-setup" aria-label="Play against the computer">
              <h2>Play the computer from here</h2>
              <div className="analysis-play-options">
                <div className="analysis-segmented" role="radiogroup" aria-label="Your color">
                  {(['white', 'black'] as const).map((color) => (
                    <button
                      key={color}
                      type="button"
                      role="radio"
                      aria-checked={(playColor ?? turn) === color}
                      onClick={() => setPlayColor(color)}
                    >
                      {color === 'white' ? 'White' : 'Black'}
                    </button>
                  ))}
                </div>
                <label className="analysis-level">
                  <span>Level</span>
                  <select value={playLevel} onChange={(event) => setPlayLevel(Number(event.target.value))}>
                    {LEVEL_ELO.map((elo, index) => (
                      <option key={elo} value={index + 1}>{index + 1} · about {elo}</option>
                    ))}
                  </select>
                </label>
                <button className="primary" type="button" onClick={startPlaying} disabled={Boolean(over)}>
                  <Bot size={16} /> Start game
                </button>
              </div>
            </section>
          )}

          <section className="analysis-card analysis-fen" aria-label="Position">
            <h2>Position</h2>
            <div className="analysis-fen-current">
              <code>{fen}</code>
              <button className="secondary icon" type="button" aria-label={copied ? 'FEN copied' : 'Copy FEN'} onClick={copyFen}>
                {copied ? <Check size={16} /> : <Copy size={16} />}
              </button>
            </div>
            <form className="analysis-fen-form" onSubmit={submitFen} noValidate>
              <input
                value={fenDraft}
                onChange={(event) => { setFenDraft(event.target.value); if (fenError) setFenError(''); }}
                placeholder="Paste a FEN"
                aria-label="FEN to load"
                aria-invalid={Boolean(fenError)}
                aria-describedby={fenError ? 'analysis-fen-error' : undefined}
                autoComplete="off"
                spellCheck={false}
              />
              <button className="secondary" type="submit">Load</button>
            </form>
            {fenError && <p id="analysis-fen-error" className="analysis-error" role="alert">{fenError}</p>}
          </section>
        </div>
      </section>

    </main>
  );
}

/** "12. Nf3 Nc6 13. Bb5" or "12... Nc6 13. Bb5" for a line starting at `fen`. */
function formatPv(fen: string, sans: string[]): string {
  let number = moveNumber(fen);
  let white = sideToMove(fen) === 'white';
  return sans
    .map((san, index) => {
      const prefix = white ? `${number}. ` : index === 0 ? `${number}… ` : '';
      if (!white) number += 1;
      white = !white;
      return `${prefix}${san}`;
    })
    .join(' ');
}

/* ---------- Move list with variations ---------- */

function MoveList({ tree, currentId, onSelect }: { tree: Tree; currentId: string; onSelect: (id: string) => void }) {
  function token(node: TreeNode, showNumber: boolean) {
    const parent = tree.nodes[node.parent ?? ROOT];
    const white = sideToMove(parent.fen) === 'white';
    const number = moveNumber(parent.fen);
    const label = white ? `${number}.` : showNumber ? `${number}…` : '';
    return (
      <button
        key={node.id}
        type="button"
        className="analysis-move"
        aria-current={node.id === currentId ? 'true' : undefined}
        onClick={() => onSelect(node.id)}
      >
        {label && <span className="analysis-move-number">{label}</span>}
        {node.move?.san}
      </button>
    );
  }

  /** Renders the line that starts with `firstId`, inserting sibling variations after each main move. */
  function line(firstId: string): ReactNode[] {
    const out: ReactNode[] = [];
    let node = tree.nodes[firstId];
    let needNumber = true;
    for (;;) {
      out.push(token(node, needNumber));
      needNumber = false;
      const parent = tree.nodes[node.parent ?? ROOT];
      if (parent.children[0] === node.id && parent.children.length > 1) {
        out.push(
          <div className="analysis-variations" key={`${node.id}-vars`}>
            {parent.children.slice(1).map((childId) => (
              <div className="analysis-variation" key={childId}>{line(childId)}</div>
            ))}
          </div>
        );
        needNumber = true;
      }
      if (!node.children.length) break;
      node = tree.nodes[node.children[0]];
    }
    return out;
  }

  return <div className="analysis-movelist">{line(tree.nodes[ROOT].children[0])}</div>;
}
