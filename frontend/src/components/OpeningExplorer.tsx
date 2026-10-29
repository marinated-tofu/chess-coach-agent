import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Link } from '@tanstack/react-router';
import { useWorkspace } from '../workspace/WorkspaceContext';
import {
  getLichessExplorer,
  getPlayerExplorer,
  type ExplorerColor,
  type ExplorerOpening,
  type LichessExplorerGame,
  type LichessExplorerResponse,
  type PlayerExplorerResponse
} from '../lib/explorerApi';
import './OpeningExplorer.css';

type Tab = 'player' | 'masters' | 'lichess';
type Result = { kind: 'player'; data: PlayerExplorerResponse } | { kind: 'lichess'; data: LichessExplorerResponse };
type FetchState = { key: string; result: Result | null; error: string };

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'player', label: 'Your games' },
  { id: 'masters', label: 'Masters' },
  { id: 'lichess', label: 'Lichess' }
];
const COLORS: Array<{ id: ExplorerColor; label: string }> = [
  { id: 'both', label: 'Both' },
  { id: 'white', label: 'White' },
  { id: 'black', label: 'Black' }
];
const START_BOARD = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR ';
const TAB_STORAGE_KEY = 'chess-coach-explorer-tab';
const DEBOUNCE_MS = 250;
const CACHE_LIMIT = 300;
const numberFormat = new Intl.NumberFormat();

// Session cache so stepping back and forth through a line never refetches.
const responseCache = new Map<string, Result>();
function remember(key: string, result: Result) {
  responseCache.set(key, result);
  if (responseCache.size > CACHE_LIMIT) {
    const oldest = responseCache.keys().next().value;
    if (oldest !== undefined) responseCache.delete(oldest);
  }
}

function readStoredTab(): Tab | null {
  try {
    const value = localStorage.getItem(TAB_STORAGE_KEY);
    return value === 'player' || value === 'masters' || value === 'lichess' ? value : null;
  } catch {
    return null;
  }
}

function storeTab(tab: Tab) {
  try {
    localStorage.setItem(TAB_STORAGE_KEY, tab);
  } catch {
    // per-viewer convenience only
  }
}

function pct(part: number, total: number) {
  return total ? (part / total) * 100 : 0;
}

export type OpeningExplorerProps = {
  fen: string;
  onPlayMove: (san: string) => void;
};

export function OpeningExplorer({ fen, onPlayMove }: OpeningExplorerProps) {
  const { player, platform } = useWorkspace();
  const username = player.trim();
  const [tab, setTab] = useState<Tab>(() => readStoredTab() ?? (username ? 'player' : 'masters'));
  const [color, setColor] = useState<ExplorerColor>('both');
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<FetchState>({ key: '', result: null, error: '' });
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const needsPlayer = tab === 'player' && !username;
  const key = tab === 'player' ? `player|${platform}|${username.toLowerCase()}|${color}|${fen}` : `${tab}|${fen}`;

  useEffect(() => {
    if (needsPlayer) return;
    const cached = responseCache.get(key);
    if (cached) {
      setState({ key, result: cached, error: '' });
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const result: Result =
          tab === 'player'
            ? { kind: 'player', data: await getPlayerExplorer({ platform, username, fen, color }, controller.signal) }
            : { kind: 'lichess', data: await getLichessExplorer({ fen, db: tab }, controller.signal) };
        remember(key, result);
        setState({ key, result, error: '' });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({ key, result: null, error: error instanceof Error ? error.message : 'Could not load the explorer.' });
      }
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [key, tab, platform, username, fen, color, needsPlayer, retry]);

  function selectTab(next: Tab) {
    setTab(next);
    storeTab(next);
  }

  function onTabKey(event: KeyboardEvent, index: number) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (index + step + TABS.length) % TABS.length;
    selectTab(TABS[next].id);
    tabRefs.current[next]?.focus();
  }

  const loading = !needsPlayer && state.key !== key;
  // While the next position loads, keep the previous table from the same tab on screen, dimmed.
  const sameTab = state.key.split('|')[0] === key.split('|')[0];
  const stale = loading && sameTab && Boolean(state.result);
  const result = !loading || stale ? state.result : null;
  const error = !loading ? state.error : '';
  const opening: ExplorerOpening | null = result?.data.opening ?? null;

  return (
    <section className="explorer" aria-label="Opening explorer">
      <div className="explorer-head">
        <h2>Opening explorer</h2>
        <p className="explorer-opening" title={opening ? `${opening.eco} ${opening.name}` : undefined}>
          {opening ? (
            <>
              <span className="explorer-eco">{opening.eco}</span> {opening.name}
            </>
          ) : (
            <span className="explorer-muted">{loading && !result ? ' ' : 'No named opening'}</span>
          )}
        </p>
      </div>

      <div className="explorer-tabs" role="tablist" aria-label="Explorer database">
        {TABS.map((item, index) => (
          <button
            key={item.id}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            id={`explorer-tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            aria-controls="explorer-panel"
            tabIndex={tab === item.id ? 0 : -1}
            onClick={() => selectTab(item.id)}
            onKeyDown={(event) => onTabKey(event, index)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div id="explorer-panel" role="tabpanel" aria-labelledby={`explorer-tab-${tab}`} className="explorer-panel">
        {tab === 'player' && username && (
          <div className="explorer-colors" role="radiogroup" aria-label="Games where you played">
            <span>You played</span>
            {COLORS.map((item) => (
              <button key={item.id} type="button" role="radio" aria-checked={color === item.id} onClick={() => setColor(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
        )}

        {needsPlayer ? (
          <div className="explorer-empty">
            <p>Import your games to see what you play from here and where you tend to go wrong.</p>
            <button type="button" className="explorer-link" onClick={() => selectTab('masters')}>Browse master games instead</button>
          </div>
        ) : error ? (
          <div className="explorer-empty" role="alert">
            <p>{error}</p>
            <button type="button" className="explorer-link" onClick={() => setRetry((count) => count + 1)}>Try again</button>
          </div>
        ) : !result ? (
          <ExplorerSkeleton />
        ) : result.kind === 'player' ? (
          <PlayerTable data={result.data} fen={fen} stale={stale} onPlayMove={onPlayMove} onEmptyAction={() => selectTab('masters')} />
        ) : (
          <LichessTable data={result.data} stale={stale} onPlayMove={onPlayMove} />
        )}
      </div>
    </section>
  );
}

function ExplorerSkeleton() {
  return (
    <div className="explorer-table" aria-busy="true" aria-label="Loading moves">
      {Array.from({ length: 5 }, (_, index) => (
        <div key={index} className="explorer-row explorer-skeleton-row" aria-hidden="true">
          <span className="explorer-skeleton" style={{ width: 28 }} />
          <span className="explorer-skeleton" style={{ width: 40 }} />
          <span className="explorer-skeleton explorer-skeleton-bar" />
          <span className="explorer-skeleton" style={{ width: 30 }} />
        </div>
      ))}
    </div>
  );
}

function ResultBar({ segments, label }: { segments: Array<{ value: number; tone: string; name: string }>; label: string }) {
  const total = segments.reduce((sum, item) => sum + item.value, 0);
  return (
    <span className="explorer-bar" role="img" aria-label={label}>
      {segments.map((item) => {
        const share = pct(item.value, total);
        if (!share) return null;
        return (
          <span key={item.name} className={`explorer-bar-seg ${item.tone}`} style={{ flexGrow: share }} title={`${item.name} ${Math.round(share)}%`}>
            {share >= 18 ? `${Math.round(share)}%` : ''}
          </span>
        );
      })}
    </span>
  );
}

function PlayerTable({
  data,
  fen,
  stale,
  onPlayMove,
  onEmptyAction
}: {
  data: PlayerExplorerResponse;
  fen: string;
  stale: boolean;
  onPlayMove: (san: string) => void;
  onEmptyAction: () => void;
}) {
  if (!data.moves.length) {
    return (
      <div className="explorer-empty">
        <p>No games from this position.</p>
        <button type="button" className="explorer-link" onClick={onEmptyAction}>Try the Masters tab</button>
      </div>
    );
  }
  const mistake = data.common_mistake?.frequent ? data.common_mistake : null;
  return (
    <div data-stale={stale || undefined} className="explorer-body">
      {mistake && (
        <p className="explorer-warning">
          <strong>You often go wrong here.</strong> {mistake.san} went wrong in {mistake.mistakes} of {mistake.player_moves} games,
          {' '}usually as {mistake.label === 'inaccuracy' ? 'an' : 'a'} {mistake.label}
          {mistake.best_san && mistake.best_san !== mistake.san ? <>. The engine prefers <strong>{mistake.best_san}</strong>.</> : '.'}
          {' '}
          <Link
            className="explorer-link explorer-rep-link"
            to="/repertoire"
            search={{ fen, color: fen.split(' ')[1] === 'b' ? 'black' : 'white' } as Record<string, string>}
          >
            Add to repertoire
          </Link>
        </p>
      )}
      <div className="explorer-table" role="table" aria-label="Moves from your games">
        <div className="explorer-row explorer-header" role="row">
          <span role="columnheader">Move</span>
          <span role="columnheader">Games</span>
          <span role="columnheader">Win / draw / loss</span>
          <span role="columnheader">Score</span>
        </div>
        {data.moves.map((move) => {
          const share = Math.round(pct(move.games, data.total));
          const wrongText = move.mistakes ? `wrong in ${move.mistakes} of ${move.player_moves} games` : '';
          return (
            <button
              key={move.uci}
              type="button"
              role="row"
              className="explorer-row explorer-move"
              data-wrong={move.frequent_mistake || undefined}
              onClick={() => onPlayMove(move.san)}
              aria-label={`Play ${move.san}: ${move.games} games, ${move.wins} wins, ${move.draws} draws, ${move.losses} losses${move.frequent_mistake ? `, you often go wrong here (${wrongText})` : ''}`}
              title={move.frequent_mistake ? `You often go wrong with ${move.san}: ${wrongText}` : `Last played ${move.last_played || 'unknown'}`}
            >
              <span role="cell" className="explorer-san">
                {move.san}
                {move.frequent_mistake && <span className="explorer-wrong-dot" aria-hidden="true" />}
              </span>
              <span role="cell" className="explorer-num">
                {numberFormat.format(move.games)} <span className="explorer-muted">{share}%</span>
              </span>
              <span role="cell">
                <ResultBar
                  label={`${move.wins} wins, ${move.draws} draws, ${move.losses} losses`}
                  segments={[
                    { value: move.wins, tone: 'win', name: 'Win' },
                    { value: move.draws, tone: 'draw', name: 'Draw' },
                    { value: move.losses, tone: 'loss', name: 'Loss' }
                  ]}
                />
              </span>
              <span role="cell" className="explorer-num">{move.score_pct === null ? '–' : `${Math.round(move.score_pct)}%`}</span>
            </button>
          );
        })}
      </div>
      <p className="explorer-foot">
        {numberFormat.format(data.total)} of your games reached this position
        {data.moves.some((move) => move.frequent_mistake) && (
          <>
            {' · '}
            <span className="explorer-wrong-dot inline" aria-hidden="true" /> you often go wrong
          </>
        )}
      </p>
    </div>
  );
}

function LichessTable({ data, stale, onPlayMove }: { data: LichessExplorerResponse; stale: boolean; onPlayMove: (san: string) => void }) {
  if (!data.moves.length) {
    return (
      <div className="explorer-empty">
        <p>{data.db === 'masters' ? 'No master games reached this position.' : 'No Lichess games reached this position.'}</p>
      </div>
    );
  }
  return (
    <div data-stale={stale || undefined} className="explorer-body">
      <div className="explorer-table" role="table" aria-label={data.db === 'masters' ? 'Moves from master games' : 'Moves from Lichess games'}>
        <div className="explorer-row explorer-header" role="row">
          <span role="columnheader">Move</span>
          <span role="columnheader">Games</span>
          <span role="columnheader">White / draw / black</span>
          <span role="columnheader">Avg</span>
        </div>
        {data.moves.map((move) => (
          <button
            key={move.uci}
            type="button"
            role="row"
            className="explorer-row explorer-move"
            onClick={() => onPlayMove(move.san)}
            title={move.opening ? `${move.opening.eco} ${move.opening.name}` : undefined}
            aria-label={`Play ${move.san}: ${move.games} games, white ${Math.round(move.white_pct)}%, draws ${Math.round(move.draw_pct)}%, black ${Math.round(move.black_pct)}%`}
          >
            <span role="cell" className="explorer-san">{move.san}</span>
            <span role="cell" className="explorer-num">
              {compact(move.games)} <span className="explorer-muted">{Math.round(pct(move.games, data.total))}%</span>
            </span>
            <span role="cell">
              <ResultBar
                label={`White ${Math.round(move.white_pct)}%, draws ${Math.round(move.draw_pct)}%, black ${Math.round(move.black_pct)}%`}
                segments={[
                  { value: move.white, tone: 'white', name: 'White wins' },
                  { value: move.draws, tone: 'draw', name: 'Draws' },
                  { value: move.black, tone: 'black', name: 'Black wins' }
                ]}
              />
            </span>
            <span role="cell" className="explorer-num">{move.avg_rating ?? '–'}</span>
          </button>
        ))}
      </div>
      <p className="explorer-foot">{numberFormat.format(data.total)} {data.db === 'masters' ? 'master' : 'Lichess'} games</p>
      {data.top_games.length > 0 && <TopGames games={data.top_games.slice(0, 5)} />}
    </div>
  );
}

function TopGames({ games }: { games: LichessExplorerGame[] }) {
  return (
    <div className="explorer-games">
      <h3>Top games</h3>
      <ul>
        {games.map((game) => (
          <li key={game.id}>
            <a href={game.url ?? undefined} target="_blank" rel="noreferrer">
              <span className="explorer-players">
                <span>{game.white} <span className="explorer-muted">{game.white_rating ?? ''}</span></span>
                <span>{game.black} <span className="explorer-muted">{game.black_rating ?? ''}</span></span>
              </span>
              <span className={`explorer-result ${game.winner ?? 'draw'}`}>
                {game.winner === 'white' ? '1-0' : game.winner === 'black' ? '0-1' : '½-½'}
              </span>
              <span className="explorer-muted explorer-num">{game.year ?? ''}</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function compact(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${Math.round(value / 1000)}k`;
  return numberFormat.format(value);
}
