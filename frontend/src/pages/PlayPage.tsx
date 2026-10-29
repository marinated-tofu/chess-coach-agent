import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { Chess } from 'chess.js';
import { AlertCircle, ArrowRight, Check, Copy, Flag, Loader2, MessageSquare, Microscope, RotateCcw, Swords, Undo2 } from 'lucide-react';
import { ChessBoard, type BoardMove } from '../components/ChessBoard';
import { CoachPanel } from '../components/CoachPanel';
import { PageHeader } from '../components/PageHeader';
import { analyzeGames } from '../lib/api';
import { getBots, requestBotMove, type BotPersona } from '../lib/botsApi';
import { loadGame } from '../lib/chessRules';
import { useCoachMarks } from '../lib/coachMarks';
import { useWorkspace } from '../workspace/WorkspaceContext';
import './PlayPage.css';

type Side = 'white' | 'black';
type ColorChoice = Side | 'random';
type PlayedMove = { san: string; uci: string; fen: string; from: string; to: string };
type GameEnd = { result: '1-0' | '0-1' | '1/2-1/2'; title: string; detail: string };
type Review = { state: 'idle' } | { state: 'analyzing' } | { state: 'ready'; gameId: string | null } | { state: 'failed'; message: string };

type Game = {
  id: number;
  bot: BotPersona;
  playerColor: Side;
  startFen: string;
  moves: PlayedMove[];
  resigned: boolean;
  takebackUsed: boolean;
  botNote: string | null;
};

const START_FEN = new Chess().fen();

const STYLE_LABELS: Record<BotPersona['style'], string> = {
  solid: 'Solid',
  aggressive: 'Aggressive',
  tricky: 'Tricky',
  sparring: 'Your opponents'
};

function sideOf(fen: string): Side {
  return fen.split(' ')[1] === 'b' ? 'black' : 'white';
}

function gameEnd(game: Game, fen: string): GameEnd | null {
  const you = game.playerColor;
  if (game.resigned) {
    return { result: you === 'white' ? '0-1' : '1-0', title: `${game.bot.name} wins`, detail: 'You resigned.' };
  }
  const board = replay(game);
  if (board.isCheckmate()) {
    const loser = sideOf(fen);
    return loser === you
      ? { result: loser === 'white' ? '0-1' : '1-0', title: `${game.bot.name} wins`, detail: 'Checkmate.' }
      : { result: loser === 'white' ? '0-1' : '1-0', title: 'You win', detail: 'Checkmate.' };
  }
  const draw = (detail: string): GameEnd => ({ result: '1/2-1/2', title: 'Draw', detail });
  if (board.isStalemate()) return draw('Stalemate.');
  if (board.isThreefoldRepetition()) return draw('Threefold repetition.');
  if (board.isInsufficientMaterial()) return draw('Insufficient material.');
  if (board.isDrawByFiftyMoves()) return draw('Fifty moves without a capture or pawn move.');
  return null;
}

function replay(game: Game): Chess {
  const board = new Chess(game.startFen);
  for (const move of game.moves) board.move(move.san);
  return board;
}

/** The bot is named "<name> (bot)" so the sparring book can skip these games (bots.py BOT_SUFFIX). */
function buildPgn(game: Game, end: GameEnd | null, you = 'You'): string {
  const board = replay(game);
  board.setHeader('Event', `Chess Coach vs ${game.bot.name}`);
  const started = new Date(game.id);
  board.setHeader('Date', started.toISOString().slice(0, 10).replace(/-/g, '.'));
  board.setHeader('UTCTime', started.toISOString().slice(11, 19));
  board.setHeader('White', game.playerColor === 'white' ? you : `${game.bot.name} (bot)`);
  board.setHeader('Black', game.playerColor === 'black' ? you : `${game.bot.name} (bot)`);
  board.setHeader(game.playerColor === 'white' ? 'BlackElo' : 'WhiteElo', String(game.bot.rating));
  board.setHeader('Result', end?.result ?? '*');
  if (game.startFen !== START_FEN) {
    board.setHeader('SetUp', '1');
    board.setHeader('FEN', game.startFen);
  }
  return board.pgn();
}

export function PlayPage({ initialFen }: { initialFen?: string }) {
  const startFen = useMemo(() => (initialFen && loadGame(initialFen) ? initialFen : START_FEN), [initialFen]);
  const badFen = Boolean(initialFen) && startFen !== initialFen;
  const bots = useQuery({ queryKey: ['bots'], queryFn: getBots, staleTime: Infinity });
  const [botId, setBotId] = useState('kit');
  const [colorChoice, setColorChoice] = useState<ColorChoice>(() => (initialFen ? sideOf(startFen) : 'white'));
  const [game, setGame] = useState<Game | null>(null);

  const selected = bots.data?.find((bot) => bot.id === botId) ?? null;

  function start() {
    if (!selected) return;
    const playerColor: Side = colorChoice === 'random' ? (Math.random() < 0.5 ? 'white' : 'black') : colorChoice;
    setGame({ id: Date.now(), bot: selected, playerColor, startFen, moves: [], resigned: false, takebackUsed: false, botNote: null });
  }

  if (game) {
    return (
      <GameScreen
        key={game.id}
        game={game}
        setGame={setGame}
        onRematch={() => setGame({ ...game, id: Date.now(), moves: [], resigned: false, takebackUsed: false, botNote: null })}
        onExit={() => setGame(null)}
      />
    );
  }

  return (
    <main className="route-page play-page">
      <PageHeader
        eyebrow="Play"
        title="Play a bot"
        detail="The bots play like people at their rating: book moves early, plausible choices later, and more mistakes in sharp positions."
      />
      {startFen !== START_FEN && (
        <p className="play-start-note">Starting from a custom position, {sideOf(startFen)} to move.</p>
      )}
      {badFen && <p className="play-error"><AlertCircle size={16} /> That FEN isn't a legal position, so the game starts from the initial position.</p>}
      {bots.isError && <p className="play-error"><AlertCircle size={16} /> {(bots.error as Error).message}</p>}

      <section className="play-bots" aria-label="Choose a bot">
        {bots.isPending && Array.from({ length: 8 }, (_, index) => <div key={index} className="play-bot-card skeleton" />)}
        {bots.data?.map((bot) => (
          <button
            key={bot.id}
            type="button"
            className={bot.id === botId ? 'play-bot-card selected' : 'play-bot-card'}
            aria-pressed={bot.id === botId}
            onClick={() => setBotId(bot.id)}
          >
            <span className="play-avatar" style={{ background: bot.color }} aria-hidden>{bot.initial}</span>
            <span className="play-bot-text">
              <span className="play-bot-name">
                <strong>{bot.name}</strong>
                <span className="play-rating">{bot.style === 'sparring' ? 'Your level' : bot.rating}</span>
              </span>
              <span className={`play-style style-${bot.style}`}>{STYLE_LABELS[bot.style]}</span>
              <span className="play-blurb">{bot.blurb}</span>
            </span>
          </button>
        ))}
      </section>

      <section className="play-setup">
        <div className="play-color" role="radiogroup" aria-label="Your color">
          {(['white', 'random', 'black'] as const).map((choice) => (
            <button
              key={choice}
              type="button"
              role="radio"
              aria-checked={colorChoice === choice}
              className={colorChoice === choice ? 'active' : ''}
              onClick={() => setColorChoice(choice)}
            >
              <span className={`play-color-swatch ${choice}`} aria-hidden />
              {choice === 'random' ? 'Random' : choice === 'white' ? 'White' : 'Black'}
            </button>
          ))}
        </div>
        <SparringHint bot={selected} />
        <button className="primary play-start" onClick={start} disabled={!selected}>
          <Swords size={17} /> Play {selected?.name ?? ''}
        </button>
      </section>
    </main>
  );
}

function SparringHint({ bot }: { bot: BotPersona | null }) {
  const { player, platform } = useWorkspace();
  if (bot?.style !== 'sparring') return null;
  return (
    <p className="play-sparring-hint">
      {player.trim()
        ? <>Opens like the opponents in <strong>{player}</strong>'s {platform === 'lichess' ? 'Lichess' : 'Chess.com'} games, at your rating.</>
        : <>Set a player on the <Link to="/games" search={{ import: true }}>Games</Link> page so this bot can copy your opponents.</>}
    </p>
  );
}

function GameScreen({
  game,
  setGame,
  onRematch,
  onExit
}: {
  game: Game;
  setGame: (update: (current: Game | null) => Game | null) => void;
  onRematch: () => void;
  onExit: () => void;
}) {
  const { player, platform } = useWorkspace();
  const navigate = useNavigate();
  const fen = game.moves[game.moves.length - 1]?.fen ?? game.startFen;
  const end = useMemo(() => gameEnd(game, fen), [game, fen]);
  const botToMove = !end && sideOf(fen) !== game.playerColor;
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [review, setReview] = useState<Review>({ state: 'idle' });
  const [copied, setCopied] = useState(false);
  const [confirmResign, setConfirmResign] = useState(false);
  const coachMarks = useCoachMarks(fen);
  const movesRef = useRef<HTMLOListElement>(null);

  // The bot's turn: ask the server, then wait out the rest of its "thinking" time.
  useEffect(() => {
    if (!botToMove) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const started = performance.now();
    setThinking(true);
    setError('');
    requestBotMove(
      {
        fen,
        bot_id: game.bot.id,
        moves_uci: game.moves.map((move) => move.uci),
        ...(game.bot.style === 'sparring' && player.trim() ? { platform, username: player.trim() } : {})
      },
      controller.signal
    )
      .then((result) => {
        const wait = Math.max(0, result.thinking_ms - (performance.now() - started));
        timer = window.setTimeout(() => {
          setThinking(false);
          setGame((current) => {
            if (!current || (current.moves[current.moves.length - 1]?.fen ?? current.startFen) !== fen) return current;
            const uci = result.move_uci;
            return {
              ...current,
              botNote: result.comment,
              moves: [...current.moves, { san: result.move_san, uci, fen: result.fen_after, from: uci.slice(0, 2), to: uci.slice(2, 4) }]
            };
          });
        }, wait);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setThinking(false);
        setError(reason instanceof Error ? reason.message : 'The bot could not move.');
      });
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      setThinking(false);
    };
    // game.moves is captured through fen; re-running on every render would re-request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [botToMove, fen, retry]);

  useEffect(() => {
    const list = movesRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [game.moves.length]);

  function onMove(move: BoardMove): boolean {
    if (end || botToMove) return false;
    const board = replay(game);
    const played = board.move({ from: move.from, to: move.to, promotion: move.promotion });
    if (!played) return false;
    setGame((current) =>
      current && {
        ...current,
        moves: [...current.moves, { san: played.san, uci: move.uci, fen: board.fen(), from: move.from, to: move.to }]
      }
    );
    return true;
  }

  // One takeback per game: removes your last move and the bot's reply to it.
  let lastOwnIndex = -1;
  game.moves.forEach((_, index) => {
    const moverFen = index === 0 ? game.startFen : game.moves[index - 1].fen;
    if (sideOf(moverFen) === game.playerColor) lastOwnIndex = index;
  });
  const canTakeback = !game.takebackUsed && !game.resigned && lastOwnIndex >= 0;

  function takeback() {
    if (!canTakeback) return;
    setGame((current) => current && { ...current, moves: current.moves.slice(0, lastOwnIndex), takebackUsed: true, botNote: null });
  }

  // Run the finished game through the normal PGN analysis so it lands in the library and the
  // coach can see every move. Without a player name there is nothing to file it under, so the
  // coach only gets the final position.
  async function startReview() {
    if (!end) return;
    const username = player.trim();
    if (!username) {
      setReview({ state: 'ready', gameId: null });
      return;
    }
    setReview({ state: 'analyzing' });
    try {
      const result = await analyzeGames(buildPgn(game, end, username), username, 1, platform);
      const gameId = result.analyses[0]?.game.game_id ?? null;
      if (gameId) {
        // The game is in the library now; review it like any other game.
        await navigate({ to: '/games/$gameId', params: { gameId }, search: { moment: undefined } });
        return;
      }
      setReview({ state: 'ready', gameId: null });
    } catch (reason) {
      setReview({ state: 'failed', message: reason instanceof Error ? reason.message : 'The analysis failed.' });
    }
  }

  async function copyPgn() {
    try {
      await navigator.clipboard.writeText(buildPgn(game, end));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setError('Copying failed. Your browser blocked clipboard access.');
    }
  }

  const rows = useMemo(() => {
    const blackFirst = sideOf(game.startFen) === 'black';
    const firstNumber = Number(game.startFen.split(' ')[5]) || 1;
    const cells: Array<string | null> = blackFirst ? [null, ...game.moves.map((m) => m.san)] : game.moves.map((m) => m.san);
    const out: Array<{ number: number; white: string | null; black: string | null }> = [];
    for (let index = 0; index < cells.length; index += 2) {
      out.push({ number: firstNumber + index / 2, white: cells[index], black: cells[index + 1] ?? null });
    }
    return out;
  }, [game.moves, game.startFen]);

  const last = game.moves[game.moves.length - 1];
  const botLabel = game.bot.style === 'sparring' ? 'Sparring partner' : `${game.bot.name} · ${game.bot.rating}`;

  return (
    <main className="route-page play-page">
      <div className="play-game">
        <section className="play-board-column">
          <PlayerStrip
            avatar={<span className="play-avatar small" style={{ background: game.bot.color }} aria-hidden>{game.bot.initial}</span>}
            name={botLabel}
            status={thinking ? 'Thinking' : null}
          />
          <div className="play-board">
            <ChessBoard
              fen={fen}
              orientation={game.playerColor}
              youColor={game.playerColor}
              onMove={end ? undefined : onMove}
              lastMove={last ? { from: last.from, to: last.to } : undefined}
              arrows={coachMarks.arrows}
              highlights={coachMarks.highlights}
            />
          </div>
          <PlayerStrip
            avatar={<span className={`play-avatar small you ${game.playerColor}`} aria-hidden>Y</span>}
            name="You"
            status={!end && !botToMove ? 'Your move' : null}
          />
        </section>

        <aside className="play-side">
          {end && (
            <div className="play-result" role="status">
              <div>
                <strong>{end.title}</strong>
                <span>{end.detail} <span className="play-score">{end.result.replace('1/2', '½').replace('1/2', '½')}</span></span>
              </div>
              <div className="play-result-actions">
                <button className="primary" onClick={startReview} disabled={review.state !== 'idle' && review.state !== 'failed'}>
                  {review.state === 'analyzing' ? <Loader2 className="spin" size={16} /> : <MessageSquare size={16} />}
                  {review.state === 'analyzing' ? 'Analyzing game' : 'Review with coach'}
                </button>
                <button className="secondary" onClick={onRematch}><RotateCcw size={16} /> Rematch</button>
              </div>
              {review.state === 'failed' && <p className="play-error" role="alert"><AlertCircle size={16} /> {review.message}</p>}
            </div>
          )}

          <div className="play-moves-card">
            <div className="play-moves-head">
              <strong>Moves</strong>
              <span>{game.moves.length ? `${Math.ceil(game.moves.length / 2)} ${Math.ceil(game.moves.length / 2) === 1 ? 'move' : 'moves'}` : 'No moves yet'}</span>
            </div>
            <ol className="play-moves" ref={movesRef}>
              {rows.map((row) => (
                <li key={row.number}>
                  <span className="play-move-number">{row.number}.</span>
                  <span>{row.white ?? '…'}</span>
                  <span>{row.black ?? ''}</span>
                </li>
              ))}
            </ol>
            {game.botNote && <p className="play-bot-note">{game.botNote}</p>}
            {error && (
              <p className="play-error">
                <AlertCircle size={16} /> {error}
                {botToMove && <button className="play-link" onClick={() => setRetry((n) => n + 1)}>Try again</button>}
              </p>
            )}
          </div>

          <div className="play-controls">
            <button className="secondary" onClick={takeback} disabled={!canTakeback}>
              <Undo2 size={16} /> {game.takebackUsed ? 'Takeback used' : 'Takeback'}
            </button>
            <button
              className={confirmResign ? 'secondary play-danger' : 'secondary'}
              onClick={() => {
                if (!confirmResign) {
                  setConfirmResign(true);
                  return;
                }
                setGame((current) => current && { ...current, resigned: true });
              }}
              onBlur={() => setConfirmResign(false)}
              disabled={Boolean(end) || game.moves.length === 0}
            >
              <Flag size={16} /> {confirmResign ? 'Confirm resign' : 'Resign'}
            </button>
            <button className="secondary" onClick={copyPgn} disabled={game.moves.length === 0}>
              {copied ? <Check size={16} /> : <Copy size={16} />} {copied ? 'Copied' : 'Copy PGN'}
            </button>
            <Link className="secondary" to="/analysis" search={{ fen }}>
              <Microscope size={16} /> Analyze
            </Link>
            <button className="secondary" onClick={onExit}><Swords size={16} /> New game</button>
          </div>

          {review.state === 'ready' && end && (
            <>
              {review.gameId && (
                <Link className="play-review-link" to="/games/$gameId" params={{ gameId: review.gameId }} search={{ moment: undefined }}>
                  Open the full game review <ArrowRight size={15} />
                </Link>
              )}
              <CoachPanel
                gameId={review.gameId ?? undefined}
                fen={fen}
                onAnnotations={coachMarks.onAnnotations}
                suggestions={[
                  'What was the turning point?',
                  'Where did I go wrong?',
                  'What should I practice after this game?'
                ]}
              />
            </>
          )}
        </aside>
      </div>
    </main>
  );
}

function PlayerStrip({ avatar, name, status }: { avatar: ReactNode; name: string; status: string | null }) {
  return (
    <div className="play-strip">
      {avatar}
      <strong>{name}</strong>
      {status && (
        <span className="play-strip-status">
          {status === 'Thinking' && <Loader2 className="spin" size={14} />}
          {status}
        </span>
      )}
    </div>
  );
}
