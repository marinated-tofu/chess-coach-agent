import { useCallback, useState } from 'react';
import { ARROW_COLORS, type BoardArrow as BoardArrowMark } from '../components/ChessBoard';
import type { BoardArrow, SquareHighlight } from './coachApi';

const ARROW_KIND_COLORS: Record<BoardArrow['kind'], string> = {
  best: ARROW_COLORS.best,
  played: ARROW_COLORS.mistake,
  threat: 'rgba(196, 98, 16, 0.85)',
  idea: ARROW_COLORS.idea
};

const HIGHLIGHT_KIND_COLORS: Record<SquareHighlight['kind'], string> = {
  focus: 'rgba(32, 98, 196, 0.38)',
  weakness: 'rgba(180, 38, 46, 0.32)',
  threat: 'rgba(196, 98, 16, 0.36)',
  idea: 'rgba(21, 120, 75, 0.3)'
};

export type CoachMarks = {
  fen: string;
  arrows: BoardArrowMark[];
  highlights: Array<{ square: string; color: string }>;
};

/**
 * Board marks from the coach's last answer. They were validated against one FEN, so callers
 * pass the current FEN and get nothing back once the board has moved on.
 */
export function useCoachMarks(fen: string) {
  const [marks, setMarks] = useState<CoachMarks | null>(null);
  const onAnnotations = useCallback(
    (arrows: BoardArrow[], highlights: SquareHighlight[]) =>
      setMarks({
        fen,
        arrows: arrows.map((arrow) => ({
          from: arrow.from_square,
          to: arrow.to_square,
          color: ARROW_KIND_COLORS[arrow.kind]
        })),
        highlights: highlights.map((item) => ({ square: item.square, color: HIGHLIGHT_KIND_COLORS[item.kind] }))
      }),
    [fen]
  );
  const current = marks && marks.fen === fen ? marks : null;
  return { arrows: current?.arrows ?? [], highlights: current?.highlights ?? [], onAnnotations };
}
