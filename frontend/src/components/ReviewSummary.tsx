import { BookOpen, RefreshCw } from 'lucide-react';
import { countClassifications, hasEngineData, useGameOpening } from '../lib/reviewApi';
import type { CoachAnalysis, Platform } from '../lib/types';
import { LABEL_ORDER, MOVE_LABELS, MoveBadge } from './moveLabels';

function formatAccuracy(value: number | null | undefined): string {
  return value == null ? '–' : value.toFixed(1);
}

/** Game Review header: accuracy per side, label counts per side, and the opening name. */
export function ReviewSummary({
  analysis,
  username,
  platform
}: {
  analysis: CoachAnalysis;
  username: string;
  platform: Platform | 'pgn';
}) {
  const opening = useGameOpening(username, platform, analysis.game.game_id);
  const engine = hasEngineData(analysis);
  const counts = countClassifications(analysis);
  const you = analysis.game.player_color;
  const openingName = opening.data?.name || (analysis.game.eco ? `ECO ${analysis.game.eco}` : null);
  const sides = [
    { color: 'white' as const, name: analysis.game.white },
    { color: 'black' as const, name: analysis.game.black }
  ];

  return (
    <section className="review-summary" aria-label="Game review summary">
      <div className="rs-opening">
        <BookOpen size={15} aria-hidden="true" />
        {openingName ? (
          <span>
            <strong>{openingName}</strong>
            {opening.data?.eco && opening.data.name ? <small className="tnum">{opening.data.eco}</small> : null}
          </span>
        ) : (
          <span className="rs-muted">{opening.isPending && opening.fetchStatus !== 'idle' ? 'Finding the opening…' : 'Opening not identified'}</span>
        )}
      </div>

      {engine ? (
        <div className="rs-body">
          <div className="rs-accuracy">
            {sides.map((side) => (
              <div className="rs-player" key={side.color} data-color={side.color}>
                <span className="rs-player-name">
                  <i aria-hidden="true" />
                  <span className="rs-name-text">{side.name}</span>
                  {you === side.color && <small>You</small>}
                </span>
                <strong className="tnum">
                  {formatAccuracy(analysis.accuracy?.[side.color])}
                </strong>
                <span className="rs-caption">Accuracy</span>
              </div>
            ))}
          </div>
          <table className="rs-counts">
            <caption className="rv-sr-only">Moves per label for each player</caption>
            <thead>
              <tr>
                <th scope="col"><span className="rv-sr-only">Label</span></th>
                <th scope="col">White</th>
                <th scope="col">Black</th>
              </tr>
            </thead>
            <tbody>
              {LABEL_ORDER.map((label) => {
                const white = counts.white[label] ?? 0;
                const black = counts.black[label] ?? 0;
                return (
                  <tr key={label} data-empty={white + black === 0 || undefined}>
                    <th scope="row">
                      <MoveBadge label={label} />
                      <span>{MOVE_LABELS[label].name}</span>
                    </th>
                    <td className="tnum">{white}</td>
                    <td className="tnum">{black}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="rs-note">
          <RefreshCw size={14} aria-hidden="true" />
          This game was analyzed before move labels existed. Re-sync to get move labels and accuracy.
        </p>
      )}
    </section>
  );
}
