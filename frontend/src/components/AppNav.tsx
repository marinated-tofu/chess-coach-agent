import { useRef, useState } from 'react';
import { Link, useNavigate, useRouterState } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  BookMarked,
  Compass,
  Crown,
  Home,
  Library,
  Lightbulb,
  Menu,
  Microscope,
  ScanLine,
  Swords,
  Target,
  TrendingUp
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { getProgress } from '../lib/api';
import { useHotkeys } from '../lib/useHotkeys';
import { useWorkspace } from '../workspace/WorkspaceContext';
import { AccountButton } from './AccountButton';
import { MoreSheet } from './MoreSheet';
import { ShortcutSheet } from './ShortcutSheet';
import './AppNav.css';

export type NavPath =
  | '/'
  | '/games'
  | '/insights'
  | '/progress'
  | '/practice'
  | '/repertoire'
  | '/endgames'
  | '/play'
  | '/analysis'
  | '/setup';

export type NavItem = {
  to: NavPath;
  label: string;
  icon: LucideIcon;
  /** Second key of the "g" sequence that opens this page. */
  hotkey: string;
  search?: Record<string, unknown>;
  exact?: boolean;
  /** Active only when the URL carries this item's search params (deep links to a tab). */
  matchSearch?: boolean;
  /** Not active when the URL is another item's deep link (Analysis board vs. its explorer tab). */
  inactiveWhen?: (search: Record<string, unknown>) => boolean;
  badge?: 'games' | 'due';
};

export type NavGroup = { label: string | null; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  { label: null, items: [{ to: '/', label: 'Today', icon: Home, hotkey: 'h', exact: true }] },
  {
    label: 'Review',
    items: [
      { to: '/games', label: 'Games', icon: Library, hotkey: 'g', search: { import: false }, badge: 'games' },
      { to: '/insights', label: 'Insights', icon: Lightbulb, hotkey: 'i' },
      { to: '/progress', label: 'Progress', icon: TrendingUp, hotkey: 'r' }
    ]
  },
  {
    label: 'Train',
    items: [
      { to: '/practice', label: 'Practice', icon: Target, hotkey: 'p', badge: 'due' },
      { to: '/repertoire', label: 'Repertoire', icon: BookMarked, hotkey: 'o' },
      { to: '/endgames', label: 'Endgames', icon: Crown, hotkey: 'n' }
    ]
  },
  {
    label: 'Play',
    items: [{ to: '/play', label: 'Play bots', icon: Swords, hotkey: 'b', search: { fen: undefined } }]
  },
  {
    label: 'Tools',
    items: [
      { to: '/analysis', label: 'Analysis board', icon: Microscope, hotkey: 'a', search: { fen: undefined },
        inactiveWhen: (search) => search.tab === 'explorer' },
      { to: '/analysis', label: 'Opening explorer', icon: Compass, hotkey: 'x', search: { tab: 'explorer' }, matchSearch: true },
      { to: '/setup', label: 'Set up position', icon: ScanLine, hotkey: 'e' }
    ]
  }
];

const ALL_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

/** Phone tab bar: these four plus More. Everything else lives in the More sheet. */
const TAB_PATHS: NavPath[] = ['/', '/games', '/practice', '/play'];
const TAB_LABELS: Partial<Record<NavPath, string>> = { '/practice': 'Train', '/play': 'Play' };

export function isTabPath(path: NavPath) {
  return TAB_PATHS.includes(path);
}

export type NavBadges = { games: number; due: number };

export function NavLink({ item, badges, label, onNavigate }: {
  item: NavItem;
  badges: NavBadges;
  label?: string;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  const search = useRouterState({ select: (state) => state.location.search as Record<string, unknown> });
  const suppressed = item.inactiveWhen?.(search) ?? false;
  const count = item.badge ? badges[item.badge] : 0;
  return (
    <Link
      to={item.to}
      search={item.search as never}
      className="nav-link"
      activeProps={suppressed ? { className: '', 'aria-current': undefined } : { className: 'active' }}
      activeOptions={{ exact: Boolean(item.exact), includeSearch: Boolean(item.matchSearch) }}
      data-label={label ?? item.label}
      onClick={onNavigate}
    >
      <Icon size={20} aria-hidden />
      <span className="nav-label">{label ?? item.label}</span>
      {count > 0 && (
        <small className="nav-badge" aria-label={item.badge === 'due' ? `${count} due` : `${count} games`}>
          {count.toLocaleString()}
        </small>
      )}
    </Link>
  );
}

function useNavBadges(): NavBadges {
  const { analyses, totalGames, player, platform } = useWorkspace();
  // Same key as Today and Progress, so the request is shared with those pages.
  const progress = useQuery({
    queryKey: ['progress', platform, player],
    queryFn: () => getProgress(player, platform),
    enabled: Boolean(player.trim()),
    staleTime: 60_000,
    retry: 1
  });
  // The server count; the loaded list (capped) only stands in until it arrives.
  return { games: totalGames ?? analyses.length, due: progress.data?.player.due_positions ?? 0 };
}

export function AppNav() {
  const badges = useNavBadges();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const [moreOpen, setMoreOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);

  const bindings: Record<string, () => void> = {
    '?': () => setShortcutsOpen(true),
    'g t': () => void navigate({ to: '/' })
  };
  for (const item of ALL_ITEMS) {
    bindings[`g ${item.hotkey}`] = () => void navigate({ to: item.to, search: item.search as never });
  }
  useHotkeys(bindings);

  const moreActive = ALL_ITEMS.some(
    (item) => !isTabPath(item.to) && (pathname === item.to || pathname.startsWith(`${item.to}/`))
  ) || pathname === '/quality';

  return (
    <>
      <aside className="app-sidebar">
        <Link className="brand" to="/" aria-label="Chess Coach, Today">
          <Activity size={20} aria-hidden />
          <span className="nav-label">Chess Coach</span>
        </Link>
        <nav className="sidebar-nav" aria-label="Main">
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group.label ?? 'top'} role="group" aria-label={group.label ?? undefined}>
              {group.label && <span className="nav-group-label" aria-hidden="true">{group.label}</span>}
              {group.items.map((item) => <NavLink key={item.label} item={item} badges={badges} />)}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <AccountButton />
          <Link to="/quality" className="nav-dev-link" activeProps={{ className: 'active' }}>
            Developer: quality
          </Link>
        </div>
      </aside>

      <nav className="tab-bar" aria-label="Main">
        {TAB_PATHS.map((path) => {
          const item = ALL_ITEMS.find((entry) => entry.to === path)!;
          return <NavLink key={path} item={item} badges={badges} label={TAB_LABELS[path]} />;
        })}
        <button
          ref={moreButton}
          type="button"
          className={`nav-link tab-more${moreActive ? ' active' : ''}`}
          aria-haspopup="dialog"
          aria-expanded={moreOpen}
          aria-current={moreActive ? 'page' : undefined}
          onClick={() => setMoreOpen(true)}
        >
          <Menu size={20} aria-hidden />
          <span className="nav-label">More</span>
        </button>
      </nav>

      <MoreSheet
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        groups={NAV_GROUPS}
        badges={badges}
        returnFocus={moreButton}
      />
      <ShortcutSheet
        open={shortcutsOpen}
        onClose={() => setShortcutsOpen(false)}
        pathname={pathname}
        items={ALL_ITEMS}
      />
    </>
  );
}
