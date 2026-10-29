import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { Activity, AlertCircle, Database, Library, Loader2, Upload } from 'lucide-react';
import { GameList } from '../components/GameList';
import { PageHeader } from '../components/PageHeader';
import { getAnalyzedGames } from '../lib/api';
import type { CoachAnalysis, Platform } from '../lib/types';
import { analyzedGamesKey, useWorkspace } from '../workspace/WorkspaceContext';

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
            <textarea value={workspace.pgn} onChange={(event) => workspace.setPgn(event.target.value)} rows={9} />
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

export function GamesPage() {
  const workspace = useWorkspace();
  const { analyses, activeGameId, openGame } = workspace;
  const navigate = useNavigate({ from: '/games' });
  const search = useSearch({ from: '/games' });
  // Wait for typing to settle before loading a (possibly very large) game library.
  const [libraryPlayer, setLibraryPlayer] = useState(workspace.player);
  useEffect(() => {
    const timer = window.setTimeout(() => setLibraryPlayer(workspace.player), 400);
    return () => window.clearTimeout(timer);
  }, [workspace.player]);
  const persisted = useQuery({
    queryKey: analyzedGamesKey(workspace.platform, libraryPlayer),
    queryFn: () => getAnalyzedGames(libraryPlayer, workspace.platform),
    enabled: libraryPlayer.trim().length > 0 && !workspace.loading,
    staleTime: 60_000
  });
  useEffect(() => {
    // The server library is authoritative: it includes synced and pasted games for this player.
    if (persisted.data) workspace.restoreAnalyses(persisted.data.analyses);
  }, [persisted.data]);
  const showImport = search.import || (analyses.length === 0 && !persisted.isFetching);
  const activeIndex = Math.max(0, analyses.findIndex((item) => item.game.game_id === activeGameId));

  function selectGame(index: number) {
    const game = analyses[index];
    if (!game) return;
    openGame(game.game.game_id);
    void navigate({ to: '/games/$gameId', params: { gameId: game.game.game_id }, search: { moment: undefined } });
  }

  function openAnalyzedGame(analysis: CoachAnalysis) {
    void navigate({
      to: '/games/$gameId',
      params: { gameId: analysis.game.game_id },
      search: { moment: undefined }
    });
  }

  return (
    <main className="route-page games-page">
      <PageHeader
        eyebrow="Game library"
        title="Your analyzed games"
        detail={analyses.length
          ? `${analyses.length} games ready for review.`
          : persisted.isFetching ? 'Loading your game library...' : 'No analyzed games yet.'}
        actions={<button
          className="secondary route-action"
          onClick={() => navigate({ search: { import: !showImport } })}
        ><Upload size={16} /> {showImport ? 'Close import' : 'Import games'}</button>}
      />
      {showImport && <GameIntake onAnalyzed={openAnalyzedGame} />}
      {analyses.length ? (
        <GameList analyses={analyses} activeIndex={activeIndex} onSelect={selectGame} />
      ) : !showImport ? (
        <section className="empty-route">
          <Library size={28} />
          <h2>No games yet</h2>
          <button className="primary" onClick={() => navigate({ search: { import: true } })}>
            Import games
          </button>
        </section>
      ) : null}
    </main>
  );
}
