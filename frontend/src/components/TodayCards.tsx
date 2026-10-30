import { useEffect, useState, type ReactNode } from 'react';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { AlertCircle, ArrowRight, BookOpen, Loader2, Swords, Target, TrendingDown } from 'lucide-react';
import { createTrainingSession } from '../lib/api';
import { getInsights } from '../lib/insightsApi';
import { getRepertoire, listRepertoires, type RepertoireNode } from '../lib/repertoireApi';
import { formatPgnDate, type TodaySummary } from '../lib/todayApi';
import type { Platform } from '../lib/types';
import { ChessBoard } from './ChessBoard';
import { Skeleton } from './Skeleton';

type CardProps = { player: string; platform: Platform; primary: boolean };

const RESULT_LABEL: Record<string, string> = { win: 'Won', loss: 'Lost', draw: 'Drew' };

function themeLabel(theme: string) {
  const text = theme.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Skeletons wait 150 ms so fast responses do not flash a placeholder. */
function DelayedSkeleton({ label, variant }: { label: string; variant?: 'card' }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setShow(true), 150);
    return () => window.clearTimeout(timer);
  }, []);
  return show ? <Skeleton lines={3} variant={variant} label={label} /> : <div className="today-card-pending" aria-busy="true" />;
}

function TodayCard({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <article className="today-card">
      <header className="today-card-title">
        <span aria-hidden="true">{icon}</span>
        <h2>{title}</h2>
      </header>
      {children}
    </article>
  );
}

function CardState({ query, label, children }: {
  query: UseQueryResult<unknown>;
  label: string;
  children: () => ReactNode;
}) {
  if (query.isPending) return <DelayedSkeleton label={`Loading ${label}`} />;
  if (query.isError) {
    return (
      <p className="today-card-error" role="alert">
        <AlertCircle size={15} /> Could not load {label}.
        <button type="button" className="today-text-button" onClick={() => void query.refetch()}>Retry</button>
      </p>
    );
  }
  return <>{children()}</>;
}

export function DueCard({ summary, primary }: { summary: UseQueryResult<TodaySummary>; primary: boolean }) {
  const navigate = useNavigate();
  return (
    <TodayCard icon={<Target size={17} />} title="Due reviews">
      <CardState query={summary} label="due reviews">
        {() => {
          const due = summary.data!.due;
          if (summary.data!.private) {
            return <p className="today-card-body">This player's reviews are private.</p>;
          }
          if (!due.count) {
            return (
              <p className="today-card-body">
                Nothing due. {due.next_due_at ? `Next review ${relativeDay(due.next_due_at)}.` : 'Practice a game moment to start a review queue.'}
              </p>
            );
          }
          return (
            <>
              <p className="today-card-stat num">
                {due.count.toLocaleString()} {due.count === 1 ? 'position' : 'positions'} due
              </p>
              <ul className="today-chips" aria-label="Themes">
                {due.themes.slice(0, 4).map((item) => (
                  <li key={item.theme}>{themeLabel(item.theme)} <span className="num">{item.count}</span></li>
                ))}
              </ul>
              <div className="today-card-action">
                <button className={primary ? 'primary' : 'secondary'} onClick={() => navigate({ to: '/practice' })}>
                  Start review <ArrowRight size={16} />
                </button>
              </div>
            </>
          );
        }}
      </CardState>
    </TodayCard>
  );
}

export function LatestGameCard({ summary, primary }: { summary: UseQueryResult<TodaySummary>; primary: boolean }) {
  const navigate = useNavigate();
  return (
    <TodayCard icon={<Swords size={17} />} title="Latest game">
      <CardState query={summary} label="your latest game">
        {() => {
          const game = summary.data!.latest_game;
          if (!game) return <p className="today-card-body">No dated games yet.</p>;
          const moment = game.first_moment;
          const facts = [
            formatPgnDate(game.date),
            game.accuracy != null ? `${game.accuracy.toFixed(0)}% accuracy` : '',
            `${game.blunders} ${game.blunders === 1 ? 'blunder' : 'blunders'}`
          ].filter(Boolean);
          return (
            <div className="today-latest">
              {moment && (
                <div className="today-mini-board">
                  <ChessBoard fen={moment.fen_before} orientation={game.player_color === 'black' ? 'black' : 'white'} />
                </div>
              )}
              <div className="today-latest-copy">
                <p className="today-card-stat">
                  <span className={`today-result ${game.player_result}`}>{RESULT_LABEL[game.player_result] || 'Played'}</span>
                  {' '}vs {game.opponent}
                </p>
                <p className="today-card-body num">{facts.join(' · ')}</p>
                {moment && (
                  <p className="today-card-body">
                    Move {moment.move_number}: you played {moment.played_san}
                    {moment.best_san ? `, ${moment.best_san} was better` : ''}.
                  </p>
                )}
                <div className="today-card-action">
                  <button
                    className={primary ? 'primary' : 'secondary'}
                    onClick={() => navigate({
                      to: '/games/$gameId',
                      params: { gameId: game.game_id },
                      search: { moment: moment?.id }
                    })}
                  >
                    Review game <ArrowRight size={16} />
                  </button>
                </div>
              </div>
            </div>
          );
        }}
      </CardState>
    </TodayCard>
  );
}

export function LeakCard({ player, platform, primary }: CardProps) {
  const navigate = useNavigate();
  const insights = useQuery({
    queryKey: ['insights', platform, player, 500],
    queryFn: () => getInsights(player, platform, 500),
    staleTime: 5 * 60_000
  });
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');

  async function practice(theme: string) {
    setStarting(true);
    setError('');
    try {
      const session = await createTrainingSession(player, platform, theme);
      await navigate({ to: '/practice/$sessionId', params: { sessionId: session.id } });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not start practice');
      setStarting(false);
    }
  }

  return (
    <TodayCard icon={<TrendingDown size={17} />} title="Top leak">
      <CardState query={insights} label="your top leak">
        {() => {
          const leak = insights.data!.leaks[0];
          if (!leak) return <p className="today-card-body">Not enough analyzed games to rank leaks yet.</p>;
          return (
            <>
              <p className="today-card-stat">{leak.title}</p>
              <p className="today-card-body num">{leak.points_per_10_games.toFixed(1)} points lost per 10 games</p>
              <div className="today-card-action">
                {leak.action.type === 'practice' && leak.action.theme ? (
                  <button
                    className={primary ? 'primary' : 'secondary'}
                    onClick={() => practice(leak.action.theme!)}
                    disabled={starting}
                  >
                    {starting ? <Loader2 className="spin" size={16} /> : <ArrowRight size={16} />} Practice this
                  </button>
                ) : (
                  <button className={primary ? 'primary' : 'secondary'} onClick={() => navigate({ to: '/insights' })}>
                    See details <ArrowRight size={16} />
                  </button>
                )}
                {error && <p className="today-card-error" role="alert"><AlertCircle size={15} /> {error}</p>}
              </div>
            </>
          );
        }}
      </CardState>
    </TodayCard>
  );
}

function countLines(nodes: RepertoireNode[]): { total: number; learned: number } {
  let total = 0;
  let learned = 0;
  function walk(node: RepertoireNode, ok: boolean) {
    const fine = ok && (!node.is_player_move || ((node.streak ?? 0) > 0 && !node.due));
    if (!node.children.length || node.transposition) {
      total += 1;
      if (fine) learned += 1;
      return;
    }
    node.children.forEach((child) => walk(child, fine));
  }
  nodes.forEach((node) => walk(node, true));
  return { total, learned };
}

/** Hidden until the player has a repertoire with at least one move. */
export function RepertoireCard({ player, platform }: Omit<CardProps, 'primary'>) {
  const navigate = useNavigate();
  const list = useQuery({
    queryKey: ['repertoires', platform, player],
    queryFn: () => listRepertoires(player, platform)
  });
  const chosen = list.data?.length
    ? [...list.data].sort((a, b) => b.due_count - a.due_count)[0]
    : null;
  const detail = useQuery({
    queryKey: ['repertoire', chosen?.id],
    queryFn: () => getRepertoire(chosen!.id),
    enabled: Boolean(chosen)
  });

  if (list.isSuccess && !chosen) return null;
  if (detail.isSuccess && !detail.data.tree.length) return null;
  const query = list.isError || !chosen ? list : detail;

  return (
    <TodayCard icon={<BookOpen size={17} />} title="Repertoire">
      <CardState query={query} label="your repertoire">
        {() => {
          const { total, learned } = countLines(detail.data!.tree);
          const color = chosen!.color === 'white' ? 'White' : 'Black';
          return (
            <>
              <p className="today-card-stat">Continue {chosen!.name} ({color})</p>
              <p className="today-card-body num">
                {learned} of {total} {total === 1 ? 'line' : 'lines'} learned
                {chosen!.due_count ? ` · ${chosen!.due_count} due` : ''}
              </p>
              <div className="today-card-action">
                <button className="secondary" onClick={() => navigate({ to: '/repertoire' })}>
                  Continue drill <ArrowRight size={16} />
                </button>
              </div>
            </>
          );
        }}
      </CardState>
    </TodayCard>
  );
}

export function relativeDay(iso: string) {
  const target = new Date(iso);
  const start = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const days = Math.round((start(target) - start(new Date())) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return 'tomorrow';
  if (days < 7) return `in ${days} days`;
  return `on ${new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' }).format(target)}`;
}

export function relativePast(iso: string) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} ${days === 1 ? 'day' : 'days'} ago`;
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso));
}
