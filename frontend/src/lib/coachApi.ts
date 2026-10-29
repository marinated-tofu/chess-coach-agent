// Coach-specific API calls and types. Kept out of api.ts/types.ts so the coach
// panel can change without touching shared files.

export type ArrowKind = 'best' | 'played' | 'threat' | 'idea';
export type HighlightKind = 'focus' | 'weakness' | 'threat' | 'idea';

/** A board arrow the server has checked with python-chess against the FEN that was sent. */
export interface BoardArrow {
  from_square: string;
  to_square: string;
  kind: ArrowKind;
}

export interface SquareHighlight {
  square: string;
  kind: HighlightKind;
}

/** Extra fields /api/coach/ask returns on top of the CoachAskResponse in types.ts. */
export interface CoachAnnotations {
  arrows?: BoardArrow[];
  highlights?: SquareHighlight[];
  annotations_dropped?: number;
}

export type CoachRating = 'helpful' | 'not_helpful';

export async function sendCoachFeedback(request: {
  question: string;
  answer: string;
  rating: CoachRating;
  gameId?: string;
  fen?: string;
  toolsUsed: string[];
}): Promise<void> {
  const response = await fetch('/api/coach/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: request.question.slice(0, 2000),
      answer: request.answer.slice(0, 8000),
      rating: request.rating,
      game_id: request.gameId || null,
      fen: request.fen || null,
      tools_used: request.toolsUsed
    })
  });
  if (!response.ok) throw new Error('Could not send feedback.');
}
