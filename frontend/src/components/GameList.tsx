import { Link } from '@tanstack/react-router';
import { Skeleton } from './Skeleton';
import {
  formatGameDate,
  resultLabel,
  themeLabel,
  timeClassLabel,
  type LibraryGame
} from '../lib/libraryApi';
import './GameList.css';

function GameRow({ game, onOpen }: { game: LibraryGame; onOpen?: (gameId: string) => void }) {
  const date = formatGameDate(game.date);
  const opponent = game.opponent || 'Unknown opponent';
  const meta = [
    timeClassLabel(game.time_class) || game.time_control,
    date,
    game.move_count ? `${game.move_count.toLocaleString()} moves` : ''
  ].filter(Boolean);
  const slips = [
    game.blunders ? `${game.blunders} ${game.blunders === 1 ? 'blunder' : 'blunders'}` : '',
    game.mistakes ? `${game.mistakes} ${game.mistakes === 1 ? 'mistake' : 'mistakes'}` : ''
  ].filter(Boolean);
  const colorLabel = game.player_color === 'white' ? 'White' : game.player_color === 'black' ? 'Black' : '';

  return (
    <li>
      <Link
        className="library-row"
        to="/games/$gameId"
        params={{ gameId: game.game_id }}
        search={{ moment: undefined }}
        onClick={() => onOpen?.(game.game_id)}
      >
        <span className={`library-result library-result-${game.player_result}`}>
          {resultLabel(game.player_result)}
        </span>
        <span className="library-main">
          <strong>
            {colorLabel && <span className={`library-piece library-piece-${game.player_color}`} aria-label={`You played ${colorLabel}`} />}
            vs {opponent}
            {game.opponent_elo ? <span className="library-elo"> ({game.opponent_elo})</span> : null}
          </strong>
          <span className="library-meta">{meta.join(' · ')}</span>
        </span>
        <span className="library-opening" title={game.opening || undefined}>
          {game.opening || 'Opening not named'}
          {game.top_themes.length > 0 && (
            <span className="library-themes">{game.top_themes.slice(0, 2).map(themeLabel).join(', ')}</span>
          )}
        </span>
        <span className="library-stats">
          <span className="library-accuracy">{game.accuracy == null ? '–' : `${Math.round(game.accuracy)}%`}</span>
          <span className="library-slips">{slips.length ? slips.join(', ') : game.moment_count ? `${game.moment_count} key moments` : 'Clean game'}</span>
        </span>
      </Link>
    </li>
  );
}

/** One line per game. Rows are links, so a game opens in a new tab with a middle click. */
export function GameList({
  games,
  loadingRows = 0,
  onOpen
}: {
  games: LibraryGame[];
  /** Skeleton rows to show after the loaded games (first load or "load more"). */
  loadingRows?: number;
  onOpen?: (gameId: string) => void;
}) {
  return (
    <section className="library-list" aria-label="Games">
      <div className="library-list-head" aria-hidden="true">
        <span>Result</span>
        <span>Opponent</span>
        <span>Opening</span>
        <span>Accuracy</span>
      </div>
      <ul>
        {games.map((game) => <GameRow key={game.game_id} game={game} onOpen={onOpen} />)}
        {Array.from({ length: loadingRows }, (_, index) => (
          <li key={`skeleton-${index}`} className="library-skeleton">
            <Skeleton variant="row" label={index === 0 ? 'Loading games' : 'Loading'} />
          </li>
        ))}
      </ul>
    </section>
  );
}
