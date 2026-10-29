import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  analyzeGames,
  getAnalyzedGames,
  getGameSync,
  sendMomentFeedback,
  startGameSync
} from '../lib/api';
import { getToday, todayKey } from '../lib/todayApi';
import type { CoachAnalysis, CriticalMoment, Platform, SyncJob } from '../lib/types';

const STORAGE_KEY = 'chess-coach-workspace';
// The player identity also lives in localStorage so links opened in a new tab can load games.
const PLAYER_STORAGE_KEY = 'chess-coach-player';
// An unfinished sync job id, so a reload picks the progress back up instead of losing it.
const SYNC_STORAGE_KEY = 'chess-coach-sync-job';
const POLL_RETRIES = 5;

export type SyncJobState = {
  status: 'idle' | SyncJob['status'];
  /** Games found on the platform (0 until fetching finishes). */
  total: number;
  /** Games checked so far: newly analyzed plus already stored. */
  done: number;
  /** Games newly analyzed in this run. */
  analyzed: number;
  player: string;
  platform: Platform;
  error: string;
};

const IDLE_SYNC: SyncJobState = {
  status: 'idle', total: 0, done: 0, analyzed: 0, player: '', platform: 'chess.com', error: ''
};

function syncState(job: SyncJob, player: string, platform: Platform): SyncJobState {
  return {
    status: job.status,
    total: job.total_games,
    done: job.analyzed_games + job.skipped_games,
    analyzed: job.analyzed_games,
    player,
    platform,
    error: job.error
  };
}

function readStoredSync(): { id: string; player: string; platform: Platform } | null {
  try {
    const raw = localStorage.getItem(SYNC_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeStoredSync(value: { id: string; player: string; platform: Platform } | null) {
  try {
    if (value) localStorage.setItem(SYNC_STORAGE_KEY, JSON.stringify(value));
    else localStorage.removeItem(SYNC_STORAGE_KEY);
  } catch {
    // Optional convenience only.
  }
}

export function analyzedGamesKey(platform: Platform, player: string) {
  return ['analyzed-games', platform, player.trim().toLowerCase()] as const;
}

function mergeAnalyses(first: CoachAnalysis[], rest: CoachAnalysis[]) {
  const seen = new Set(first.map((item) => item.game.game_id));
  return [...first, ...rest.filter((item) => !seen.has(item.game.game_id))];
}

type StoredWorkspace = {
  analyses: CoachAnalysis[];
  activeGameId: string;
  player: string;
  pgn: string;
  platform?: Platform;
};

type WorkspaceContextValue = {
  pgn: string;
  setPgn: (value: string) => void;
  player: string;
  setPlayer: (value: string) => void;
  platform: Platform;
  setPlatform: (value: Platform) => void;
  /** True once a username is set. Without one, pages show the connect card or an empty state. */
  hasIdentity: boolean;
  /** Games stored on the server for the current player; null while unknown. */
  totalGames: number | null;
  /** Progress of the latest history sync started in this browser. */
  syncJob: SyncJobState;
  /** Set the identity to this player and import their history. Resolves with the newest game. */
  startSync: (player: string, platform: Platform) => Promise<CoachAnalysis | null>;
  analyses: CoachAnalysis[];
  activeGameId: string;
  loading: boolean;
  status: string;
  error: string;
  feedbackStatus: string;
  monitoringRefresh: number;
  openGame: (gameId: string) => void;
  runAnalysis: () => Promise<CoachAnalysis | null>;
  syncAllGames: () => Promise<CoachAnalysis | null>;
  recordFeedback: (moment: CriticalMoment, rating: 'helpful' | 'not_helpful') => Promise<void>;
  clearFeedbackStatus: () => void;
  restoreAnalyses: (items: CoachAnalysis[]) => void;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function loadStoredWorkspace(): StoredWorkspace | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as StoredWorkspace;
    const identity = localStorage.getItem(PLAYER_STORAGE_KEY);
    return identity ? { analyses: [], activeGameId: '', pgn: '', ...JSON.parse(identity) } as StoredWorkspace : null;
  } catch {
    return null;
  }
}

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const stored = useMemo(loadStoredWorkspace, []);
  const [pgn, setPgn] = useState(stored?.pgn || '');
  const [player, setPlayer] = useState(stored?.player || '');
  const [platform, setPlatform] = useState<Platform>(stored?.platform || 'chess.com');
  const [analyses, setAnalyses] = useState<CoachAnalysis[]>(stored?.analyses || []);
  const [activeGameId, setActiveGameId] = useState(stored?.activeGameId || stored?.analyses?.[0]?.game.game_id || '');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(stored?.analyses?.length ? `${stored.analyses.length} games ready` : 'Ready');
  const [error, setError] = useState('');
  const [feedbackStatus, setFeedbackStatus] = useState('');
  const [monitoringRefresh, setMonitoringRefresh] = useState(0);
  const [syncJob, setSyncJob] = useState<SyncJobState>(IDLE_SYNC);
  const hasIdentity = player.trim().length > 0;
  // Shared with the Today page (same key), so the count is one request, not one per consumer.
  const today = useQuery({
    queryKey: todayKey(platform, player),
    queryFn: () => getToday(player, platform),
    enabled: hasIdentity,
    staleTime: 60_000
  });

  useEffect(() => {
    // Resume a sync that was still running when the page was reloaded.
    const pending = readStoredSync();
    if (pending) void runSync(pending.player, pending.platform, pending.id);
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        analyses: analyses.slice(0, 25), activeGameId, player, pgn, platform
      }));
    } catch {
      // Server persistence remains authoritative when browser storage is full or unavailable.
    }
  }, [activeGameId, analyses, pgn, platform, player]);

  useEffect(() => {
    try {
      if (player.trim()) localStorage.setItem(PLAYER_STORAGE_KEY, JSON.stringify({ player, platform }));
      else localStorage.removeItem(PLAYER_STORAGE_KEY);
    } catch {
      // Optional convenience only.
    }
  }, [platform, player]);

  async function refreshLibrary(name: string, source: Platform) {
    const key = analyzedGamesKey(source, name);
    await queryClient.invalidateQueries({ queryKey: key });
    const result = await queryClient.fetchQuery({
      queryKey: key,
      queryFn: () => getAnalyzedGames(name, source)
    });
    return result.analyses;
  }

  function openGame(gameId: string) {
    setActiveGameId(gameId);
    setFeedbackStatus('');
  }

  async function runAnalysis() {
    setLoading(true);
    setError('');
    setStatus('Analyzing pasted PGN...');
    try {
      // Store pasted games with the player's platform so the library, review, coach and
      // training routes (which all look games up by platform + player) can find them.
      const result = await analyzeGames(pgn, player, 20, platform);
      setAnalyses((current) => mergeAnalyses(result.analyses, current));
      const first = result.analyses[0] || null;
      if (first) openGame(first.game.game_id);
      const moments = result.analyses.reduce((sum, item) => sum + item.moments.length, 0);
      setStatus(`Analyzed ${result.analyses.length} games with ${moments} coachable moments`);
      void queryClient.invalidateQueries({ queryKey: analyzedGamesKey(platform, player) });
      setMonitoringRefresh((value) => value + 1);
      return first;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Analysis failed');
      setStatus('Could not analyze PGN');
      return null;
    } finally {
      setLoading(false);
    }
  }

  function syncAllGames() {
    return startSync(player, platform);
  }

  function startSync(name: string, source: Platform) {
    const trimmed = name.trim();
    if (!trimmed) return Promise.resolve(null);
    setPlatform(source);
    setPlayer(trimmed);
    return runSync(trimmed, source);
  }

  async function runSync(name: string, source: Platform, resumeId?: string) {
    setLoading(true);
    setError('');
    setStatus(`Starting ${source} history sync for ${name}...`);
    setSyncJob({ ...IDLE_SYNC, status: 'queued', player: name, platform: source });
    let earlyRefresh = false;
    try {
      let job = resumeId ? await getGameSync(resumeId) : await startGameSync(name, source);
      writeStoredSync({ id: job.id, player: name, platform: source });
      let pollFailures = 0;
      while (!['complete', 'failed'].includes(job.status)) {
        const completed = job.analyzed_games + job.skipped_games;
        setSyncJob(syncState(job, name, source));
        setStatus(
          job.status === 'analyzing' && job.total_games > 0
            ? `Checking game ${Math.min(completed + 1, job.total_games)} of ${job.total_games} · ${job.analyzed_games} new analyzed`
            : job.status === 'queued'
              ? `Queued ${source} history sync...`
              : `Fetching complete ${source} history...`
        );
        if (!earlyRefresh && job.analyzed_games >= 10) {
          // Enough games to be useful: let Today offer the latest one before the sync ends.
          earlyRefresh = true;
          void queryClient.invalidateQueries({ queryKey: todayKey(source, name) });
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        try {
          job = await getGameSync(job.id);
          pollFailures = 0;
        } catch (caught) {
          // The job keeps running server-side; ride out brief network or server hiccups.
          pollFailures += 1;
          if (pollFailures > POLL_RETRIES) throw caught;
        }
      }
      writeStoredSync(null);
      setSyncJob(syncState(job, name, source));
      if (job.status === 'failed') throw new Error(job.error || 'Game sync failed');
      void queryClient.invalidateQueries({ queryKey: todayKey(source, name) });
      const synced = await refreshLibrary(name, source);
      setAnalyses(synced);
      const first = synced[0] || null;
      if (first) openGame(first.game.game_id);
      setStatus(
        `Synced ${job.total_games} games · analyzed ${job.analyzed_games} new · skipped ${job.skipped_games} existing`
        + (job.error ? ` · ${job.error}` : '')
      );
      setMonitoringRefresh((value) => value + 1);
      return first;
    } catch (caught) {
      writeStoredSync(null);
      const message = caught instanceof Error ? caught.message : `Could not sync games from ${source}`;
      setError(message);
      setStatus('Game sync failed');
      setSyncJob((current) => ({ ...current, status: 'failed', error: message }));
      return null;
    } finally {
      setLoading(false);
    }
  }

  async function recordFeedback(moment: CriticalMoment, rating: 'helpful' | 'not_helpful') {
    setFeedbackStatus('Saving feedback...');
    try {
      await sendMomentFeedback(moment, rating);
      setFeedbackStatus(rating === 'helpful' ? 'Marked helpful' : 'Marked for review');
      setMonitoringRefresh((value) => value + 1);
    } catch {
      setFeedbackStatus('Feedback could not be saved');
    }
  }

  return (
    <WorkspaceContext.Provider value={{
      pgn, setPgn, player, setPlayer, platform, setPlatform,
      hasIdentity, totalGames: hasIdentity ? today.data?.total_games ?? null : null,
      syncJob, startSync,
      analyses, activeGameId, loading, status, error,
      feedbackStatus, monitoringRefresh, openGame, runAnalysis, syncAllGames,
      recordFeedback, clearFeedbackStatus: () => setFeedbackStatus('')
      , restoreAnalyses: (items) => {
        setAnalyses(items);
        if (items.length && !items.some((item) => item.game.game_id === activeGameId)) {
          setActiveGameId(items[0].game.game_id);
        }
      }
    }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error('useWorkspace must be used inside WorkspaceProvider');
  return context;
}
