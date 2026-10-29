import { Loader2, MessageCircle, RotateCcw, Target, ThumbsDown, ThumbsUp } from 'lucide-react';
import type { CoachAnalysis, CriticalMoment } from '../lib/types';
import { MOVE_LABELS, MoveBadge, momentLabel } from './moveLabels';

/** Ply 1 is White's first move; even plies are Black's ("12..."). */
function movePrefix(moment: CriticalMoment): string {
  return moment.ply % 2 === 1 ? `${moment.move_number}.` : `${moment.move_number}...`;
}

const PHASE: Record<CriticalMoment['phase'], string> = {
  opening: 'Opening',
  middlegame: 'Middlegame',
  endgame: 'Endgame'
};

/** Key moments: chips to pick one, then the moment card with its actions and the coach's notes. */
export function AnalysisPanel({
  analysis,
  selectedMoment,
  onSelectMoment,
  onRetry,
  onPractice,
  practicePending,
  practiceError,
  onAskCoach,
  onFeedback,
  feedbackStatus
}: {
  analysis: CoachAnalysis;
  selectedMoment: CriticalMoment | null;
  onSelectMoment: (moment: CriticalMoment) => void;
  onRetry: (moment: CriticalMoment) => void;
  onPractice: (moment: CriticalMoment) => void;
  practicePending: boolean;
  practiceError: string;
  onAskCoach: (moment: CriticalMoment) => void;
  onFeedback: (moment: CriticalMoment, rating: 'helpful' | 'not_helpful') => void;
  feedbackStatus: string;
}) {
  if (!analysis.moments.length) {
    return (
      <section className="analysis-panel rv-moments" aria-labelledby="rv-moments-title">
        <h2 id="rv-moments-title" className="rv-section-title">Key moments</h2>
        <p className="rv-quiet">No critical moments in this game. Step through the moves to review it.</p>
      </section>
    );
  }

  const selectedLabel = selectedMoment ? momentLabel(analysis.moves, selectedMoment) : null;

  return (
    <section className="analysis-panel rv-moments" aria-labelledby="rv-moments-title">
      <h2 id="rv-moments-title" className="rv-section-title">Key moments</h2>
      <div className="moment-tabs">
        {analysis.moments.map((moment, index) => {
          const label = momentLabel(analysis.moves, moment);
          return (
            <button
              className={selectedMoment?.id === moment.id ? 'active' : ''}
              aria-pressed={selectedMoment?.id === moment.id}
              key={moment.id}
              type="button"
              onClick={() => onSelectMoment(moment)}
              aria-label={`Moment ${index + 1}: ${movePrefix(moment)} ${moment.played_san}, ${MOVE_LABELS[label].name}`}
            >
              <MoveBadge label={label} />
              <span className="tnum">{movePrefix(moment)} {moment.played_san}</span>
            </button>
          );
        })}
      </div>

      {selectedMoment && selectedLabel && (
        <>
          <article className="card critical-card" aria-labelledby="rv-moment-title">
            <div className="card-heading rv-moment-head">
              <h3 id="rv-moment-title">
                <MoveBadge label={selectedLabel} size="md" />
                <span className="tnum">{movePrefix(selectedMoment)} {selectedMoment.played_san}</span>
                <span className="rv-moment-label">{MOVE_LABELS[selectedLabel].name}</span>
              </h3>
              <span className="badge">{PHASE[selectedMoment.phase] ?? selectedMoment.phase}</span>
              <span className="score-badge tnum">−{Math.round(selectedMoment.win_probability_loss)}% win chance</span>
            </div>
            <div className="move-comparison">
              <div className="move-box bad">
                <span>You played</span>
                <strong className="tnum">{movePrefix(selectedMoment)} {selectedMoment.played_san}</strong>
              </div>
              <div className="move-box good">
                <span>Better was</span>
                <strong className="tnum">{selectedMoment.best_san ? `${movePrefix(selectedMoment)} ${selectedMoment.best_san}` : 'No engine move stored'}</strong>
              </div>
            </div>
            <p className="moment-metric tnum">Move accuracy {Math.round(selectedMoment.move_accuracy)}%</p>
            <div className="rv-moment-actions">
              <button type="button" className="rv-button rv-button-primary" onClick={() => onRetry(selectedMoment)}>
                <RotateCcw size={15} aria-hidden="true" /> Retry this move
              </button>
              <button type="button" className="rv-button" onClick={() => onPractice(selectedMoment)} disabled={practicePending}>
                {practicePending ? <Loader2 className="spin" size={15} aria-hidden="true" /> : <Target size={15} aria-hidden="true" />}
                Practice this theme
              </button>
              <button type="button" className="rv-button" onClick={() => onAskCoach(selectedMoment)}>
                <MessageCircle size={15} aria-hidden="true" /> Ask coach
              </button>
            </div>
            {practiceError && <p className="rv-inline-error" role="alert">{practiceError}</p>}
          </article>

          <div className="card prose-card">
            <div className="analysis-block">
              <h3>What happened</h3>
              <p>{selectedMoment.what_happened}</p>
            </div>
            <div className="analysis-block">
              <h3>Better plan</h3>
              <p>{selectedMoment.better_plan}</p>
            </div>
            <div className="analysis-block">
              <h3>Principle</h3>
              <p>{selectedMoment.principle}</p>
            </div>
            <div className="analysis-block">
              <h3>Daily challenge</h3>
              <p>{selectedMoment.drill_prompt}</p>
            </div>
            <div className="moment-feedback">
              <span>{feedbackStatus || 'Was this useful?'}</span>
              <button type="button" aria-label="Mark coaching helpful" title="Helpful" onClick={() => onFeedback(selectedMoment, 'helpful')}>
                <ThumbsUp size={17} />
              </button>
              <button type="button" aria-label="Mark coaching not helpful" title="Not helpful" onClick={() => onFeedback(selectedMoment, 'not_helpful')}>
                <ThumbsDown size={17} />
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
