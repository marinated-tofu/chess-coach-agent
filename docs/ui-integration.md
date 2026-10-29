# UI integration guide

What the React app calls, shows, and logs. Offline evaluation (`evaluation.py`,
`retrieval_evaluation.py`, `judge_evaluation.py`) is covered in
[`evaluation_results.md`](evaluation_results.md).

Local app: <http://127.0.0.1:5173>
Production: <https://chess-coach-agent.onrender.com>

## Routes

| Route | Page | In sidebar | Backend calls |
| --- | --- | --- | --- |
| `/` | Home | yes | `GET /api/progress/...`, `POST /api/training/sessions` |
| `/games` | Game library and import | yes | `GET /api/games/...`, `POST /api/games/sync`, sync polling, `POST /api/analyze` |
| `/games/$gameId` | Game review with Coach panel | no | `POST /api/feedback`, `POST /api/coach/ask`, `POST /api/training/sessions` |
| `/practice`, `/practice/$sessionId` | Practice with Coach panel | yes | training session endpoints, `POST /api/coach/ask` |
| `/progress` | Progress charts | yes | `GET /api/progress/...` |
| `/quality` | Monitoring dashboard | no | `GET /api/monitoring` |
| `/analyze` | Redirect to `/games?import=true` | no | none |

## Home (`/`)

File: `frontend/src/pages/HomePage.tsx`

| Control | API | Backend behavior |
| --- | --- | --- |
| Page load | `GET /api/progress/{platform}/{username}` | Player profile, due positions, mastery, recent attempts |
| Continue training / Start practice | `POST /api/training/sessions` | Builds a session from stored mistakes |
| Import games | none | Navigates to `/games?import=true` |

## Games (`/games`)

File: `frontend/src/router.tsx` (GamesPage, GameIntake)

| Control | API | Backend behavior |
| --- | --- | --- |
| Page load | `GET /api/games/{platform}/{username}` | Restores persisted analyses |
| Sync full history | `POST /api/games/sync`, then `GET /api/games/sync/{id}` | Fetches up to 5,000 games, analyzes new ones with Stockfish, stores them |
| Analyze PGN (prefilled with the sample game) | `POST /api/analyze` | Parses and analyzes pasted PGN |
| Game row | none | Navigates to `/games/{gameId}` |

## Game review (`/games/$gameId`)

Files: `frontend/src/router.tsx` (GameReviewPage), `AnalysisPanel.tsx`, `GamePanel.tsx`,
`CoachPanel.tsx`

| Control | API | Backend behavior |
| --- | --- | --- |
| Page data | none | Reads the analysis from the browser workspace cache |
| Moment tabs | none | Updates `?moment=` and moves the board to that ply |
| Helpful / not helpful | `POST /api/feedback` | Writes a `moment_feedback` event |
| Train this position | `POST /api/training/sessions` with the moment ID and theme | Opens a one-position drill |
| Board controls, move list | none | Changes the displayed ply |
| Heatmap: You / Opponent / Both / Off | none | Recolors squares by attacker count |
| Flip board | none | Swaps orientation for this game |
| Coach panel question or suggestion chip | `POST /api/coach/ask` with `game_id` and the board FEN at the current ply | Runs the PydanticAI coach |

The analysis text (what happened, principle, training plan) comes from the deterministic analyzer,
not the LLM. Opening `/games/{id}` directly in a fresh browser shows "Review unavailable", because
this page reads the cache and does not fetch the game from the server.

### Square-control heatmap

`frontend/src/lib/squareControl.ts` parses the FEN and counts, for each square, how many white and
black pieces attack it (pawn diagonals, knight and king steps, sliding pieces stopped by blockers).

- You / Opponent shade each square by that side's attacker count. Both colors each square for the
  side with more attackers, with a neutral color for ties.
- The bar shows the strongest square (most attackers, ties broken toward the center) and the
  weakest piece: the piece of that side defended by the fewest of its own pieces. In Both mode
  both callouts are for your side.
- Off hides the overlay. The flip button turns the board around; it resets when you open another
  game.

### Coach panel

`frontend/src/components/CoachPanel.tsx` keeps the conversation in component state. After each
answer it stores the returned `message_history` and sends it with the next question. Each answer
shows the Markdown text, the suggested move if any, the principle, the drill, a collapsible
evidence list, the confidence, and the tools the agent called. Fallback answers are labeled
"Offline answer from engine analysis". The reset button clears the conversation.

## Practice (`/practice` and `/practice/$sessionId`)

File: `frontend/src/pages/PracticePage.tsx`

| Control | API | Backend behavior |
| --- | --- | --- |
| Start practice | `POST /api/training/sessions` | Builds a session from stored mistakes |
| Session load | `GET /api/training/sessions/{id}` | Positions, FENs, prompts, choices |
| Submit move | `POST /api/training/sessions/{id}/attempts` | Stockfish grading, spaced-repetition schedule |
| Show hint (beginner positions) | none | Reveals the hint; counts as a hint on submit |
| Next position / View progress | none | Moves on or opens `/progress` |
| Try again | none | Clears the result |
| Coach panel | `POST /api/coach/ask` with the position FEN | Hints and explanations for the current position |

## Progress (`/progress`)

File: `frontend/src/pages/ProgressPage.tsx`. One call, `GET /api/progress/{platform}/{username}`:
rating history, results, theme frequency, quiz accuracy by theme, transfer score.

## Quality (`/quality`)

Files: `frontend/src/router.tsx` (QualityPage), `MonitoringDashboard.tsx`. Loads
`GET /api/monitoring` on open, after sync or feedback, and on Refresh. See
[`monitoring.md`](monitoring.md) for the metrics. Evaluation and retrieval benchmark results are
not shown here; they are in [`evaluation_results.md`](evaluation_results.md).

## Client-side state

`WorkspaceContext` (`frontend/src/workspace/WorkspaceContext.tsx`) holds the player and platform,
the PGN box, up to 25 analyses in `sessionStorage`, the active game, sync status, the last
feedback message, and a counter that refreshes `/quality`. The server (Postgres or SQLite) is the
source of truth for games, moments, training plans, and progress.

## What UI actions log

| User action | Event |
| --- | --- |
| Paste and analyze PGN | `analysis_requested`, `analysis_completed`, `analysis_timing` |
| Sync finishes | `analysis_completed` per game, `games_sync_completed` or `games_sync_failed` |
| Helpful / not helpful | `moment_feedback` |
| Start practice, Train this position | `training_session_created` |
| Submit move | `quiz_attempted` |
| Ask the coach | `coach_answered` |

## Where the LLM is used

| UI surface | LLM? |
| --- | --- |
| Coach panel (game review, practice) | Yes, when `OPENROUTER_API_KEY` is set; otherwise the deterministic fallback |
| Analysis panel, feedback, heatmap | No |
| Practice session creation and move grading | No (database and Stockfish) |
| Progress, Quality | No |
