import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { Compass, Loader2, Target } from 'lucide-react';
import { createTrainingSession } from '../lib/api';
import { getOpeningPosition } from '../lib/libraryApi';
import { getOpenings, type OpeningColor, type OpeningStat } from '../lib/openingsApi';
import type { Platform } from '../lib/types';
import './OpeningsPanel.css';

const INITIAL_ROWS = 10;

function themeLabel(theme: string): string {
  const text = theme.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function ResultBar({ stat }: { stat: OpeningStat }) {
  const total = stat.wins + stat.draws + stat.losses;
  const label = `${stat.wins.toLocaleString()} wins, ${stat.draws.toLocaleString()} draws, ${stat.losses.toLocaleString()} losses`;
  if (!total) return <span className="openings-muted">No results</span>;
  return (
    <div className="openings-result">
      <div className="openings-bar" role="img" aria-label={label} title={label}>
        {[
          ['win', stat.wins],
          ['draw', stat.draws],
          ['loss', stat.losses]
        ].map(([kind, count]) =>
          Number(count) > 0 ? (
            <span key={kind} className={`openings-bar-${kind}`} style={{ flexGrow: Number(count) }} />
          ) : null
        )}
      </div>
      <span className="openings-wdl" aria-hidden="true">
        {stat.wins.toLocaleString()}/{stat.draws.toLocaleString()}/{stat.losses.toLocaleString()}
      </span>
    </div>
  );
}

function Weakness({ stat }: { stat: OpeningStat }) {
  if (!stat.top_theme) return <span className="openings-muted">No mistakes logged</span>;
  return (
    <>
      <span>{themeLabel(stat.top_theme)}</span>
      {stat.common_first_mistake_ply != null && (
        <span className="openings-sub">
          First slip most often on move {Math.ceil(stat.common_first_mistake_ply / 2)}
        </span>
      )}
    </>
  );
}

export function OpeningsPanel({ username, platform }: { username: string; platform: Platform }) {
  const navigate = useNavigate();
  const [color, setColor] = useState<OpeningColor>('white');
  const [showAll, setShowAll] = useState(false);
  const [pending, setPending] = useState('');
  const [actionError, setActionError] = useState('');

  async function explore(stat: OpeningStat) {
    setPending(`explore-${stat.name}`);
    setActionError('');
    try {
      const position = await getOpeningPosition(stat.name);
      await navigate({ to: '/analysis', search: { fen: position.fen } });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not open the explorer');
    } finally {
      setPending('');
    }
  }

  async function practice(stat: OpeningStat) {
    if (!stat.top_theme) return;
    setPending(`practice-${stat.name}`);
    setActionError('');
    try {
      const session = await createTrainingSession(username, platform, stat.top_theme);
      await navigate({ to: '/practice/$sessionId', params: { sessionId: session.id } });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not start practice');
    } finally {
      setPending('');
    }
  }
  const openings = useQuery({
    queryKey: ['openings', platform, username],
    queryFn: () => getOpenings(username, platform)
  });

  const rows = openings.data?.[color] ?? [];
  const visible = showAll ? rows : rows.slice(0, INITIAL_ROWS);
  const hasAccuracy = rows.some((row) => row.avg_accuracy != null);
  const isEmpty = openings.isSuccess && !openings.data.white.length && !openings.data.black.length;

  return (
    <section className="openings-panel" aria-labelledby="openings-title">
      <header className="openings-header">
        <div>
          <h2 id="openings-title">Your openings</h2>
          {openings.data && !isEmpty && (
            <p>
              {openings.data.classified_games.toLocaleString()} of{' '}
              {openings.data.total_games.toLocaleString()} games matched a named opening.
            </p>
          )}
        </div>
        {!isEmpty && (
          <div className="openings-toggle" role="group" aria-label="Show openings by color">
            {(['white', 'black'] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={color === value}
                onClick={() => {
                  setColor(value);
                  setShowAll(false);
                }}
              >
                As {value === 'white' ? 'White' : 'Black'}
                {openings.data && <span>{openings.data[value].length.toLocaleString()}</span>}
              </button>
            ))}
          </div>
        )}
      </header>

      {openings.isPending && (
        <div className="openings-skeleton" aria-busy="true" aria-label="Loading openings">
          {Array.from({ length: 5 }, (_, index) => <div key={index} />)}
        </div>
      )}

      {openings.isError && (
        <p className="openings-error" role="alert">
          Opening stats didn't load.{' '}
          <button type="button" className="openings-link" onClick={() => void openings.refetch()}>
            Try again
          </button>
        </p>
      )}

      {isEmpty && (
        <div className="openings-empty">
          <p>Import a few games and this table will show which openings you score best and worst in.</p>
          <button
            type="button"
            className="primary"
            onClick={() => void navigate({ to: '/games', search: { import: true } })}
          >
            Import games
          </button>
        </div>
      )}

      {openings.isSuccess && !isEmpty && (
        rows.length ? (
          <>
            <table className="openings-table">
              <caption className="openings-visually-hidden">
                Openings played as {color}, sorted by number of games
              </caption>
              <thead>
                <tr>
                  <th scope="col">Opening</th>
                  <th scope="col" className="openings-num">Games</th>
                  <th scope="col" className="openings-num">Score</th>
                  {hasAccuracy && <th scope="col" className="openings-num">Accuracy</th>}
                  <th scope="col">Won / drawn / lost</th>
                  <th scope="col">Most common mistake</th>
                  <th scope="col"><span className="openings-visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((stat) => (
                  <tr key={`${stat.color}-${stat.name}`}>
                    <th scope="row" className="openings-name">
                      <span className="openings-eco">{stat.eco}</span>
                      <span className="openings-title" title={stat.name}>{stat.name}</span>
                      {stat.top_variation && (
                        <span className="openings-sub" title={stat.top_variation}>
                          Mostly {stat.top_variation.replace(`${stat.name}: `, '')}
                        </span>
                      )}
                    </th>
                    <td className="openings-num" data-label="games">{stat.games.toLocaleString()}</td>
                    <td className="openings-num" data-label="score">{Math.round(stat.score_pct)}%</td>
                    {hasAccuracy && (
                      <td className="openings-num" data-label="accuracy">
                        {stat.avg_accuracy == null ? '–' : `${Math.round(stat.avg_accuracy)}%`}
                      </td>
                    )}
                    <td className="openings-results-cell"><ResultBar stat={stat} /></td>
                    <td className="openings-weakness"><Weakness stat={stat} /></td>
                    <td className="openings-actions">
                      <button
                        type="button"
                        className="ghost"
                        disabled={Boolean(pending)}
                        onClick={() => void explore(stat)}
                        aria-label={`Explore ${stat.name} on the analysis board`}
                      >
                        {pending === `explore-${stat.name}` ? <Loader2 className="spin" size={14} /> : <Compass size={14} />}
                        Explore
                      </button>
                      {stat.top_theme && (
                        <button
                          type="button"
                          className="ghost"
                          disabled={Boolean(pending)}
                          onClick={() => void practice(stat)}
                          aria-label={`Practice ${themeLabel(stat.top_theme).toLowerCase()} positions`}
                        >
                          {pending === `practice-${stat.name}` ? <Loader2 className="spin" size={14} /> : <Target size={14} />}
                          Practice
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {actionError && <p className="openings-error" role="alert">{actionError}</p>}
            {rows.length > INITIAL_ROWS && (
              <button type="button" className="openings-link openings-more" onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Show top 10' : `Show all ${rows.length.toLocaleString()} openings`}
              </button>
            )}
          </>
        ) : (
          <p className="openings-muted openings-none">
            No games as {color === 'white' ? 'White' : 'Black'} yet.
          </p>
        )
      )}
    </section>
  );
}
