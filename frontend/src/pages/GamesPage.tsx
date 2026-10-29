import { useEffect, useRef, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { Activity, AlertCircle, Database, Library, Loader2, Search, SearchX, Upload, X } from 'lucide-react';
import { EmptyState } from '../components/EmptyState';
import { GameList } from '../components/GameList';
import { PageHeader } from '../components/PageHeader';
import {
  getLibraryPage,
  LIBRARY_PAGE_SIZE,
  TIME_CLASSES,
  themeLabel,
  timeClassLabel,
  type LibraryFilters
} from '../lib/libraryApi';
import type { CoachAnalysis, Platform } from '../lib/types';
import { useWorkspace } from '../workspace/WorkspaceContext';

function GameIntake({ onAnalyzed }: { onAnalyzed: (analysis: CoachAnalysis) => void }) {
  const workspace = useWorkspace();

  async function analyze() {
    const first = await workspace.runAnalysis();
    if (first) onAnalyzed(first);
  }

  async function syncAll() {
    // Stay on the library: the refreshed list and the sync summary show the result.
    await workspace.syncAllGames();
  }

  return (
    <section className="game-intake">
      <section className="intake-workspace">
        <div className="intake-section online-import">
          <div className="section-heading">
            <Database size={18} />
            <div><strong>Player history</strong><span>Automatically sync new Chess.com or Lichess games</span></div>
          </div>
          <div className="intake-fields">
            <label>
              Player username
              <input value={workspace.player} onChange={(event) => workspace.setPlayer(event.target.value)} />
            </label>
            <label>
              Source
              <select value={workspace.platform} onChange={(event) => workspace.setPlatform(event.target.value as Platform)}>
                <option value="chess.com">Chess.com</option>
                <option value="lichess">Lichess</option>
              </select>
            </label>
          </div>
          <button className="primary" onClick={syncAll} disabled={workspace.loading || !workspace.player.trim()}>
            {workspace.loading ? <Loader2 className="spin" size={17} /> : <Database size={17} />}
            Sync full history
          </button>
        </div>

        <div className="intake-divider"><span>or</span></div>

        <div className="intake-section pgn-import">
          <div className="section-heading">
            <Upload size={18} />
            <div><strong>PGN review</strong><span>Paste one or more games</span></div>
          </div>
          <label>
            PGN
            <textarea
              value={workspace.pgn}
              onChange={(event) => workspace.setPgn(event.target.value)}
              rows={9}
              placeholder={'[Event "Casual game"]\n1. e4 e5 2. Nf3 Nc6 ...'}
            />
          </label>
          <button className="secondary" onClick={analyze} disabled={workspace.loading || !workspace.pgn.trim()}>
            {workspace.loading ? <Loader2 className="spin" size={17} /> : <Upload size={17} />}
            Analyze pasted PGN
          </button>
        </div>
      </section>
      <div className={workspace.error ? 'route-status error' : 'route-status'}>
        {workspace.error ? <AlertCircle size={16} /> : <Activity size={16} />}
        {workspace.error || workspace.status}
      </div>
    </section>
  );
}


const FILTER_STORAGE_KEY = 'chess-coach-library-filters';

function loadFilters(): LibraryFilters {
  try {
    const raw = sessionStorage.getItem(FILTER_STORAGE_KEY);
    return raw ? JSON.parse(raw) as LibraryFilters : {};
  } catch {
    return {};
  }
}

/** True once `active` has stayed true for `delay` ms, so quick loads never flash a skeleton. */
function useDelayed(active: boolean, delay = 150) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!active) {
      setShown(false);
      return;
    }
    const timer = window.setTimeout(() => setShown(true), delay);
    return () => window.clearTimeout(timer);
  }, [active, delay]);
  return shown;
}

type ChipOption<T extends string> = { value: T | undefined; label: string; count?: number };

function ChipGroup<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T | undefined;
  options: ChipOption<T>[];
  onChange: (value: T | undefined) => void;
}) {
  return (
    <div className="library-chips" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.label}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.count != null && <span>{option.count.toLocaleString()}</span>}
        </button>
      ))}
    </div>
  );
}

export function GamesPage() {
  const workspace = useWorkspace();
  const navigate = useNavigate({ from: '/games' });
  const search = useSearch({ from: '/games' });
  // Wait for typing to settle before reloading the library.
  const [libraryPlayer, setLibraryPlayer] = useState(workspace.player);
  useEffect(() => {
    const timer = window.setTimeout(() => setLibraryPlayer(workspace.player), 400);
    return () => window.clearTimeout(timer);
  }, [workspace.player]);
  const [filters, setFilters] = useState<LibraryFilters>(loadFilters);
  const [query, setQuery] = useState(filters.q ?? '');
  useEffect(() => {
    const timer = window.setTimeout(() => setFilters((current) => ({ ...current, q: query.trim() || undefined })), 300);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    try {
      sessionStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(filters));
    } catch {
      // Storage can be unavailable (private mode); filters then reset on reload.
    }
  }, [filters]);

  // The theme filter lives in the URL (Insights links here with ?theme=missed_tactic).
  const theme = search.theme;
  const queryFilters: LibraryFilters = { ...filters, theme };
  const library = useInfiniteQuery({
    queryKey: ['library', workspace.platform, libraryPlayer.trim().toLowerCase(), queryFilters],
    queryFn: ({ pageParam }) => getLibraryPage(libraryPlayer, workspace.platform, queryFilters, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.has_more ? last.offset + last.items.length : undefined),
    enabled: libraryPlayer.trim().length > 0,
    staleTime: 60_000,
    placeholderData: (previous) => previous
  });
  // Refresh the list when a sync or PGN import finishes.
  const wasLoading = useRef(workspace.loading);
  useEffect(() => {
    if (wasLoading.current && !workspace.loading) void library.refetch();
    wasLoading.current = workspace.loading;
  }, [workspace.loading]);

  const pages = library.data?.pages ?? [];
  const first = pages[0];
  const games = pages.flatMap((page) => page.items);
  const libraryTotal = first?.library_total ?? 0;
  const matching = first?.total ?? 0;
  const facets = first?.facets;
  const filtered = Boolean(filters.result || filters.color || filters.time_class || filters.opening || filters.q || theme);
  const firstLoad = library.isPending && library.fetchStatus !== 'idle';
  const refiltering = library.isPlaceholderData && library.isFetching;
  const showSkeleton = useDelayed(firstLoad || refiltering);
  const libraryEmpty = Boolean(first) && libraryTotal === 0 && !library.isFetching;
  const showImport = search.import || libraryEmpty;

  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !library.hasNextPage) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting) && !library.isFetchingNextPage) void library.fetchNextPage();
    }, { rootMargin: '600px 0px' });
    observer.observe(node);
    return () => observer.disconnect();
  }, [library.hasNextPage, library.isFetchingNextPage, games.length]);

  function update(patch: Partial<LibraryFilters>) {
    setFilters((current) => ({ ...current, ...patch }));
  }

  function clearTheme() {
    void navigate({ search: (previous) => ({ ...previous, theme: undefined }) });
  }

  function clearFilters() {
    setQuery('');
    setFilters({ sort: filters.sort });
    if (theme) clearTheme();
  }

  function openAnalyzedGame(analysis: CoachAnalysis) {
    void navigate({
      to: '/games/$gameId',
      params: { gameId: analysis.game.game_id },
      search: { moment: undefined }
    });
  }

  let detail = 'Loading your games…';
  if (first) {
    detail = libraryTotal
      ? filtered
        ? `${matching.toLocaleString()} of ${libraryTotal.toLocaleString()} games match.`
        : `${libraryTotal.toLocaleString()} games ready for review.`
      : 'No analyzed games yet.';
  } else if (!libraryPlayer.trim()) {
    detail = 'Add your username to load your games.';
  } else if (library.isError) {
    detail = 'Your games didn’t load.';
  }

  const results = facets?.results ?? {};
  const timeClasses = facets?.time_classes ?? {};
  const colors = facets?.colors ?? {};
  // No counts until the first page arrives, so chips never read "Wins 0" while loading.
  const tally = (value: number | undefined) => (facets ? value ?? 0 : undefined);

  return (
    <main className="route-page games-page">
      <PageHeader
        eyebrow="Game library"
        title="Your analyzed games"
        detail={detail}
        actions={<button
          className="secondary route-action"
          onClick={() => navigate({ search: (previous) => ({ ...previous, import: !showImport }) })}
        ><Upload size={16} /> {showImport ? 'Close import' : 'Import games'}</button>}
      />
      {showImport && <GameIntake onAnalyzed={openAnalyzedGame} />}

      {library.isError && !first && (
        <p className="route-status error" role="alert">
          <AlertCircle size={16} /> Your games didn’t load.{' '}
          <button type="button" className="secondary" onClick={() => void library.refetch()}>Try again</button>
        </p>
      )}

      {(libraryTotal > 0 || firstLoad) && (
        <section className="library-toolbar" aria-label="Filter games">
          <div className="library-toolbar-row">
          <label className="library-search">
            <Search size={16} aria-hidden="true" />
            <span className="library-visually-hidden">Search by opponent</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by opponent"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <div className="library-selects">
            <label>
              <span>Opening</span>
              <select
                value={filters.opening ?? ''}
                onChange={(event) => update({ opening: event.target.value || undefined })}
                disabled={!facets?.openings_ready && !filters.opening}
              >
                <option value="">{facets?.openings_ready === false ? 'Naming openings…' : 'All openings'}</option>
                {filters.opening && !facets?.openings.some((item) => item.name === filters.opening) && (
                  <option value={filters.opening}>{filters.opening}</option>
                )}
                {facets?.openings.map((item) => (
                  <option key={item.name} value={item.name}>{item.name} ({item.count.toLocaleString()})</option>
                ))}
              </select>
            </label>
            <label>
              <span>Sort</span>
              <select
                value={filters.sort ?? 'date'}
                onChange={(event) => update({ sort: event.target.value === 'blunders' ? 'blunders' : undefined })}
              >
                <option value="date">Newest first</option>
                <option value="blunders">Most blunders</option>
              </select>
            </label>
            {filtered && <button type="button" className="ghost library-clear" onClick={clearFilters}>Clear filters</button>}
          </div>
          </div>
          <div className="library-toolbar-row">
          {theme && (
            <button
              type="button"
              className="library-active-filter"
              onClick={clearTheme}
              aria-label={`Remove filter: ${themeLabel(theme)}`}
            >
              {themeLabel(theme)} <X size={14} aria-hidden="true" />
            </button>
          )}
          <ChipGroup
            label="Result"
            value={filters.result}
            onChange={(result) => update({ result })}
            options={[
              { value: undefined, label: 'All results' },
              { value: 'win', label: 'Wins', count: tally(results.win) },
              { value: 'loss', label: 'Losses', count: tally(results.loss) },
              { value: 'draw', label: 'Draws', count: tally(results.draw) }
            ]}
          />
          <ChipGroup
            label="Time control"
            value={filters.time_class}
            onChange={(time_class) => update({ time_class })}
            options={[
              { value: undefined, label: 'All speeds' },
              ...TIME_CLASSES.filter((name) => timeClasses[name]).map((name) => ({
                value: name, label: timeClassLabel(name), count: timeClasses[name]
              }))
            ]}
          />
          <ChipGroup
            label="Color"
            value={filters.color}
            onChange={(color) => update({ color })}
            options={[
              { value: undefined, label: 'Both colors' },
              { value: 'white', label: 'As White', count: tally(colors.white) },
              { value: 'black', label: 'As Black', count: tally(colors.black) }
            ]}
          />
          </div>
        </section>
      )}

      {showSkeleton && !games.length ? (
        <GameList games={[]} loadingRows={8} />
      ) : games.length ? (
        <div className={refiltering ? 'library-results is-refreshing' : 'library-results'} aria-busy={library.isFetching}>
          <GameList
            games={games}
            loadingRows={library.isFetchingNextPage ? 3 : 0}
            onOpen={(gameId) => workspace.openGame(gameId)}
          />
          {library.hasNextPage && (
            <div ref={sentinel} className="library-more">
              <button
                type="button"
                className="secondary"
                disabled={library.isFetchingNextPage}
                onClick={() => void library.fetchNextPage()}
              >
                {library.isFetchingNextPage && <Loader2 className="spin" size={16} />}
                Load {Math.min(LIBRARY_PAGE_SIZE, matching - games.length).toLocaleString()} more
              </button>
              <span>{games.length.toLocaleString()} of {matching.toLocaleString()} shown</span>
            </div>
          )}
        </div>
      ) : first && filtered && libraryTotal > 0 && !library.isFetching ? (
        <EmptyState
          icon={<SearchX size={22} />}
          title="No games match these filters"
          body="Try a different opponent name, or clear the filters to see every game."
          action={<button type="button" className="secondary" onClick={clearFilters}>Clear filters</button>}
        />
      ) : libraryEmpty && !search.import ? (
        <EmptyState
          icon={<Library size={22} />}
          title="No games yet"
          body="Sync your Chess.com or Lichess history, or paste a PGN, and your games show up here."
        />
      ) : null}
    </main>
  );
}
