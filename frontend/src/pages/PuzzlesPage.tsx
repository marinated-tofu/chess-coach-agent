import { useEffect, useRef, useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { ArrowLeft, ArrowRight, Check, Eye, FlipVertical2, Loader2, Puzzle as PuzzleIcon, RotateCcw, X } from 'lucide-react';
import { ARROW_COLORS, ChessBoard, type BoardArrow, type BoardHighlight } from '../components/ChessBoard';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { Skeleton } from '../components/Skeleton';
import { playMove, sideToMove, type BoardMove } from '../lib/chessRules';
import { formatGameDate } from '../lib/libraryApi';
import {
  getPuzzleCatalog,
  getPuzzles,
  revealPuzzle,
  submitPuzzleMove,
  type PuzzleFinish,
  type PuzzleSummary
} from '../lib/puzzlesApi';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './PuzzlesPage.css';

const PAGE_SIZE = 24;
const RATING_STEP = 200;
const RATING_FLOOR = 600;
const RATING_CEILING = 2200;
const RATINGS = Array.from(
  { length: (RATING_CEILING - RATING_FLOOR) / RATING_STEP + 1 },
  (_, index) => RATING_FLOOR + index * RATING_STEP
);
/** Long enough to see your own move land before the opponent answers. */
const REPLY_DELAY_MS = 350;
const WRONG_SQUARE = 'rgba(180, 38, 46, 0.42)';

export type PuzzleSearch = { theme?: string; tag?: string; min?: number; max?: number; page?: number };

/** Lichess tags that Insights links to. Anything else is ignored, not shown as a raw tag. */
const TAG_LABELS: Record<string, string> = {
  fork: 'Forks',
  pin: 'Pins',
  skewer: 'Skewers',
  mate: 'Mates',
  mateIn1: 'Mate in 1',
  mateIn2: 'Mate in 2'
};

function ratingParam(value: unknown): number | undefined {
  const number = Number(value);
  return RATINGS.includes(number) ? number : undefined;
}

export function parsePuzzleSearch(search: Record<string, unknown>): PuzzleSearch {
  const page = Number(search.page);
  return {
    ...(typeof search.theme === 'string' && search.theme ? { theme: search.theme } : {}),
    ...(typeof search.tag === 'string' && TAG_LABELS[search.tag] ? { tag: search.tag } : {}),
    ...(ratingParam(search.min) != null ? { min: ratingParam(search.min) } : {}),
    ...(ratingParam(search.max) != null ? { max: ratingParam(search.max) } : {}),
    ...(Number.isInteger(page) && page > 0 ? { page } : {})
  };
}

type Status = 'playing' | 'checking' | 'reply' | 'wrong' | 'solved' | 'revealed';

function Solver({ puzzle, onNext, hasNext, privatePlayer }: {
  puzzle: PuzzleSummary;
  onNext: () => void;
  hasNext: boolean;
  /** The current player belongs to someone else, so results are not sent for them. */
  privatePlayer: boolean;
}) {
  const { player, platform } = useWorkspace();
  const recordFor = privatePlayer ? '' : player.trim();
  const queryClient = useQueryClient();
  const side = sideToMove(puzzle.fen);
  const [fen, setFen] = useState(puzzle.fen);
  const [line, setLine] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>('playing');
  const [lastMove, setLastMove] = useState<{ from: string; to: string }>();
  const [wrongSan, setWrongSan] = useState('');
  const [finish, setFinish] = useState<PuzzleFinish | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [error, setError] = useState('');
  const counted = useRef(false);
  const startedAt = useRef(Date.now());
  const replyTimer = useRef<number>(undefined);

  useEffect(() => () => window.clearTimeout(replyTimer.current), []);

  function playerFields() {
    return {
      username: recordFor || undefined,
      platform: recordFor ? platform : undefined,
      record: !counted.current,
      elapsed_ms: Date.now() - startedAt.current
    };
  }

  function settle(result: PuzzleFinish) {
    setFinish(result);
    counted.current = true;
    if (result.recorded) {
      void queryClient.invalidateQueries({ queryKey: ['puzzles'] });
      void queryClient.invalidateQueries({ queryKey: ['progress', platform, player] });
    }
  }

  async function handleMove(move: BoardMove) {
    const played = playMove(fen, { from: move.from, to: move.to, promotion: move.promotion });
    if (!played) return;
    const before = fen;
    const nextLine = [...line, move.uci];
    setFen(played.fen);
    setLastMove({ from: move.from, to: move.to });
    setStatus('checking');
    setError('');
    try {
      const result = await submitPuzzleMove(puzzle.id, nextLine, playerFields());
      if (result.finish) settle(result.finish);
      if (result.status === 'solved') {
        setLine(nextLine);
        setStatus('solved');
      } else if (result.status === 'wrong') {
        setWrongSan(move.san);
        setStatus('wrong');
      } else if (result.reply) {
        const reply = playMove(played.fen, result.reply);
        setLine([...nextLine, result.reply]);
        setStatus('reply');
        replyTimer.current = window.setTimeout(() => {
          if (reply) {
            setFen(reply.fen);
            setLastMove({ from: reply.move.from, to: reply.move.to });
          }
          setStatus('playing');
        }, REPLY_DELAY_MS);
      }
    } catch (err) {
      setFen(before);
      setLastMove(undefined);
      setStatus('playing');
      setError(err instanceof Error ? err.message : 'Could not check that move');
    }
  }

  function undoWrongMove() {
    // Back to the position before the miss. `line` never includes the wrong move.
    let position = puzzle.fen;
    for (const uci of line) position = playMove(position, uci)?.fen ?? position;
    setFen(position);
    setLastMove(undefined);
    setWrongSan('');
    setStatus('playing');
  }

  function restart() {
    setFen(puzzle.fen);
    setLine([]);
    setLastMove(undefined);
    setWrongSan('');
    setStatus('playing');
  }

  async function reveal() {
    setError('');
    try {
      const result = finish ?? (await revealPuzzle(puzzle.id, playerFields()));
      settle(result);
      if (status === 'wrong') undoWrongMove();
      setStatus('revealed');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the solution');
    }
  }

  const answer = status === 'revealed' && finish ? playMove(fen, finish.solution[line.length] ?? '') : null;
  const arrows: BoardArrow[] = answer ? [{ from: answer.move.from, to: answer.move.to, color: ARROW_COLORS.best }] : [];
  const highlights: BoardHighlight[] = status === 'wrong' && lastMove ? [{ square: lastMove.to, color: WRONG_SQUARE }] : [];
  const remaining = finish?.solution_san.slice(line.length) ?? [];
  const sideName = side === 'white' ? 'White' : 'Black';

  return (
    <section className="practice-workspace puzzle-workspace">
      <div className="practice-board">
        <ChessBoard
          fen={fen}
          orientation={flipped ? (side === 'white' ? 'black' : 'white') : side}
          onMove={status === 'playing' ? (move) => void handleMove(move) : undefined}
          lastMove={lastMove}
          arrows={arrows}
          highlights={highlights}
        />
        <button className="secondary" type="button" aria-pressed={flipped} onClick={() => setFlipped((value) => !value)}>
          <FlipVertical2 size={16} /> Flip board
        </button>
      </div>
      <div className="practice-controls">
        <span className="page-eyebrow">{puzzle.theme_label} · {puzzle.rating}</span>
        <div role="status" aria-live="polite">
          {(status === 'playing' || status === 'checking' || status === 'reply') && (
            <>
              <h2>{line.length ? 'Keep going' : `${sideName} to move`}</h2>
              <p>{status === 'checking'
                ? <><Loader2 className="spin" size={15} /> Checking your move…</>
                : status === 'reply' ? 'Correct. Watch the reply.' : line.length ? `Find the next move for ${sideName}.` : 'Find the best move and play it on the board.'}</p>
            </>
          )}
          {status === 'wrong' && (
            <div className="evaluation-status incorrect">
              <strong><X size={16} aria-hidden="true" /> {wrongSan} is not the move</strong>
              <span>Try again, or look at the solution.</span>
            </div>
          )}
          {status === 'solved' && (
            <div className="evaluation-status correct">
              <strong><Check size={16} aria-hidden="true" /> {finish?.recorded ? 'Solved' : 'Solved on a retry'}</strong>
              <span>{finish?.solution_san.join(' ')}</span>
            </div>
          )}
          {status === 'revealed' && (
            <div className="evaluation-status incorrect">
              <strong><Eye size={16} aria-hidden="true" /> Solution</strong>
              <span>{remaining.join(' ') || finish?.solution_san.join(' ')}</span>
            </div>
          )}
        </div>
        {error && <p className="route-status error" role="alert">{error}</p>}
        {finish && (status === 'solved' || status === 'revealed') && (
          <p className="puzzle-record">
            {finish.tags.length > 0 && <span>Ideas: {finish.tags.join(', ').replace(/([A-Z0-9])/g, ' $1').toLowerCase()}. </span>}
            {finish.recorded && finish.next_review_at
              ? `Counted toward your mastery. Next review ${formatGameDate(finish.next_review_at)}.`
              : privatePlayer
                ? "This player's practice is private, so this result isn't saved."
                : player.trim() ? 'Only your first try counts toward mastery.' : 'Connect an account to count puzzles toward mastery.'}
          </p>
        )}
        <div className="puzzle-actions">
          {(status === 'solved' || status === 'revealed') && hasNext && (
            <button className="primary" type="button" onClick={onNext}>Next puzzle <ArrowRight size={17} /></button>
          )}
          {status === 'wrong' && <button className="primary" type="button" onClick={undoWrongMove}><RotateCcw size={16} /> Try again</button>}
          {(status === 'playing' || status === 'wrong') && (
            <button className="secondary" type="button" onClick={() => void reveal()}><Eye size={16} /> Show solution</button>
          )}
          {(status === 'solved' || status === 'revealed') && (
            <button className="secondary" type="button" onClick={restart}><RotateCcw size={16} /> Play it again</button>
          )}
          {status !== 'solved' && status !== 'revealed' && hasNext && (
            <button className="secondary" type="button" onClick={onNext}>Skip <ArrowRight size={16} /></button>
          )}
        </div>
        {finish && (status === 'solved' || status === 'revealed') && (
          <a className="puzzle-source" href={finish.url} target="_blank" rel="noreferrer">Puzzle from Lichess</a>
        )}
      </div>
    </section>
  );
}

export function PuzzlesPage({ search }: { search: PuzzleSearch }) {
  const { player, platform } = useWorkspace();
  const navigate = useNavigate();
  const { theme, tag, min, max, page = 1 } = search;
  const offset = (page - 1) * PAGE_SIZE;
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const catalog = useQuery({ queryKey: ['puzzle-catalog'], queryFn: getPuzzleCatalog, staleTime: Infinity });
  const username = player.trim() || undefined;
  const list = useQuery({
    queryKey: ['puzzles', theme, tag, min, max, page, username, platform],
    queryFn: () => getPuzzles({ theme, tag, minRating: min, maxRating: max }, offset, PAGE_SIZE, { username, platform }),
    placeholderData: keepPreviousData
  });

  function setSearch(next: PuzzleSearch) {
    setSelectedId(null);
    void navigate({ to: '/puzzles', search: { ...next, tag }, replace: true });
  }

  function clearTag() {
    setSelectedId(null);
    void navigate({ to: '/puzzles', search: { theme, min, max }, replace: true });
  }

  const puzzles = list.data?.puzzles ?? [];
  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // Pinned once chosen: finishing a puzzle changes its status in the list, and the open puzzle
  // must not jump to the next unsolved one underneath the player.
  const current = list.isPlaceholderData
    ? undefined
    : puzzles.find((item) => item.id === selectedId) ?? puzzles.find((item) => !item.status) ?? puzzles[0];
  const currentId = current?.id ?? null;
  const currentIndex = current ? puzzles.indexOf(current) : -1;
  const hasNext = currentIndex + 1 < puzzles.length || page < pages;

  useEffect(() => {
    if (currentId) setSelectedId(currentId);
  }, [currentId]);

  function goToPage(next: number) {
    setSelectedId(null);
    void navigate({ to: '/puzzles', search: { ...search, page: next > 1 ? next : undefined }, replace: true });
  }

  function next() {
    if (currentIndex + 1 < puzzles.length) setSelectedId(puzzles[currentIndex + 1].id);
    else if (page < pages) goToPage(page + 1);
  }

  return (
    <main className="route-page puzzles-page">
      <PageHeader
        eyebrow="Puzzles"
        title="Solve by theme and rating"
        detail={catalog.data ? `${catalog.data.total.toLocaleString('en-US')} puzzles from the Lichess database.` : undefined}
      />

      <section className="puzzle-filters" aria-label="Puzzle filters">
        <div className="puzzle-themes" role="group" aria-label="Theme">
          <button type="button" aria-pressed={!theme} onClick={() => setSearch({ min, max })}>All themes</button>
          {catalog.data?.themes.map((option) => (
            <button
              key={option.theme}
              type="button"
              aria-pressed={theme === option.theme}
              onClick={() => setSearch({ theme: option.theme, min, max })}
            >
              {option.label}
            </button>
          ))}
        </div>
        {tag && (
          <button className="puzzle-tag" type="button" onClick={clearTag} aria-label={`Stop showing only ${TAG_LABELS[tag]}`}>
            {TAG_LABELS[tag]} <X size={14} aria-hidden="true" />
          </button>
        )}
        <div className="puzzle-range">
          <label>
            From
            <select
              value={min ?? RATING_FLOOR}
              onChange={(event) => {
                const value = Number(event.target.value);
                setSearch({ theme, min: value > RATING_FLOOR ? value : undefined, max: max != null && max <= value ? undefined : max });
              }}
            >
              {RATINGS.slice(0, -1).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            to
            <select
              value={max ?? RATING_CEILING}
              onChange={(event) => {
                const value = Number(event.target.value);
                setSearch({ theme, min: min != null && min >= value ? undefined : min, max: value < RATING_CEILING ? value : undefined });
              }}
            >
              {RATINGS.slice(1).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          {list.data && <span className="puzzle-count">{total.toLocaleString('en-US')} match{total === 1 ? '' : 'es'}</span>}
        </div>
      </section>

      {list.isError && (
        <EmptyState
          icon={<PuzzleIcon size={22} />}
          title="Puzzles didn't load"
          action={<button className="primary" onClick={() => list.refetch()}>Try again</button>}
        />
      )}
      {list.data && total === 0 && (
        <EmptyState
          icon={<PuzzleIcon size={22} />}
          title="No puzzles in this range"
          body="Widen the rating range or pick another theme."
          action={<Link className="primary" to="/puzzles" search={{}} onClick={() => setSelectedId(null)}>Clear filters</Link>}
        />
      )}
      {!list.isError && total > 0 && current ? (
        <Solver key={current.id} puzzle={current} onNext={next} hasNext={hasNext} privatePlayer={Boolean(list.data?.private)} />
      ) : !list.isError && !(list.data && total === 0) && (
        <section className="practice-workspace practice-loading">
          <div className="practice-board"><Skeleton variant="board" label="Loading puzzle" /></div>
          <div className="practice-controls"><Skeleton lines={4} /></div>
        </section>
      )}

      {total > 0 && (
        <section className="puzzle-browser" aria-label="Browse puzzles">
          <ol className="puzzle-list">
            {puzzles.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={item.status ?? undefined}
                  aria-current={item === current ? 'true' : undefined}
                  aria-label={`Puzzle rated ${item.rating}, ${item.theme_label}${item.status ? `, ${item.status}` : ''}`}
                  onClick={() => setSelectedId(item.id)}
                >
                  {item.rating}
                  {item.status === 'solved' && <Check size={13} aria-hidden="true" />}
                  {item.status === 'failed' && <X size={13} aria-hidden="true" />}
                </button>
              </li>
            ))}
          </ol>
          {pages > 1 && (
            <nav className="puzzle-pages" aria-label="Puzzle pages">
              <button className="secondary" type="button" disabled={page <= 1} onClick={() => goToPage(page - 1)}><ArrowLeft size={16} /> Easier</button>
              <span>Page {page.toLocaleString('en-US')} of {pages.toLocaleString('en-US')}</span>
              <button className="secondary" type="button" disabled={page >= pages} onClick={() => goToPage(page + 1)}>Harder <ArrowRight size={16} /></button>
            </nav>
          )}
        </section>
      )}
    </main>
  );
}
