import { BookOpen } from 'lucide-react';
import type { MoveClassification } from '../lib/types';

type LabelMeta = { name: string; glyph: string; color: string };

/** One glyph and one color per label, used by the move list, graph markers and summary. */
export const MOVE_LABELS: Record<MoveClassification, LabelMeta> = {
  brilliant: { name: 'Brilliant', glyph: '!!', color: '#12817c' },
  great: { name: 'Great', glyph: '!', color: '#2b66a3' },
  best: { name: 'Best', glyph: '★', color: '#3b7f2b' },
  excellent: { name: 'Excellent', glyph: '✓', color: '#557a2e' },
  good: { name: 'Good', glyph: '✓', color: '#5f6e66' },
  book: { name: 'Book', glyph: 'B', color: '#86643d' },
  inaccuracy: { name: 'Inaccuracy', glyph: '?!', color: '#94650a' },
  mistake: { name: 'Mistake', glyph: '?', color: '#b4520f' },
  miss: { name: 'Miss', glyph: '✕', color: '#b2375a' },
  blunder: { name: 'Blunder', glyph: '??', color: '#a8202b' }
};

/** Display order for the summary table, best to worst. */
export const LABEL_ORDER: MoveClassification[] = [
  'brilliant', 'great', 'best', 'excellent', 'good', 'book', 'inaccuracy', 'mistake', 'miss', 'blunder'
];

/** Labels worth a dot on the eval graph. */
export const GRAPH_MARKED: ReadonlySet<MoveClassification> = new Set(['brilliant', 'great', 'inaccuracy', 'mistake', 'miss', 'blunder']);

/** Labels the move list shows a badge for; excellent/good stay quiet to keep the list readable. */
export const LIST_BADGED: ReadonlySet<MoveClassification> = new Set([
  'brilliant', 'great', 'best', 'book', 'inaccuracy', 'mistake', 'miss', 'blunder'
]);

export const RETRY_LABELS: ReadonlySet<MoveClassification> = new Set(['mistake', 'blunder', 'miss']);

export function MoveBadge({ label, size = 'sm' }: { label: MoveClassification; size?: 'sm' | 'md' }) {
  const meta = MOVE_LABELS[label];
  return (
    <span className={`mv-badge mv-badge-${size}`} style={{ backgroundColor: meta.color }} aria-hidden="true">
      {label === 'book' ? <BookOpen size={size === 'md' ? 12 : 10} strokeWidth={2.6} /> : meta.glyph}
    </span>
  );
}
