# Competitive analysis and feature gaps

Research date: October 2026. Sources are official product pages, help-center articles, and
app-store listings where available, plus third-party reviews where the vendor publishes nothing.
Sources are listed at the end. A ✗ in the matrix means we found no evidence of the feature in
public material. It does not prove the feature is absent.

## What we compared against

| Product | What it is |
| --- | --- |
| Chess.com Game Review, Coach and Insights | The market default. Per-game review with move labels, accuracy, an eval graph, a scripted "Coach" voice, Retry, Explore variations, and an Insights stats page. One full review per day on the free tier. |
| Lichess | Free and open source. Server Stockfish analysis, accuracy, eval graph, "Learn from your mistakes", opening explorer, puzzle themes, Insights. |
| Aimchess | Analytics app (Play Magnus / Chess.com family). Skill metrics, benchmarks against peers, Training Room (Retry Mistakes, Opening Improver, Time Trainer, Endgames). 15 free exercises a day. |
| DecodeChess | Turns engine output into prose: threats, plans, piece roles, motifs. Explains your own moves since a later update. One free decode a day. |
| Noctie.ai | Human-like bots (20 to 25 levels), opening repertoire drilling, exercises from your mistakes with spaced repetition. |
| Chessable | Course platform built on MoveTrainer, a spaced-repetition system where you play the move on the board. |
| Chessly | GothamChess opening courses with video plus drill mode. Not verified in this research pass; cells come from product knowledge. |
| Dr. Wolf | Chess.com's in-game coach app. Voiced, explains while you play, 3 free coached games. |
| Chessigma | Free Stockfish 17 reviewer with a 9-tier move grade, eval graph, position editor. Ad-supported. "AI supercoach" announced but not shipped. |
| Chessvision.ai | Browser extension and site that turns a board in an image, book or video into a FEN and hands it to Lichess. |
| Chessy (chessvia.ai) | LLM coach the user clipped. Voice in and out, 6 voices, personalities (Hustler, Roasty, GM Chessy), image upload, account sync, play against it, training plans. |
| Chessiro Coach | LLM coach (page updated March 2026). Chat with arrows and highlighted squares, voice in 24 languages, Replay Mistakes puzzles, Smart Shuffle review, Maia bots from 250 to 3000. |

ChessKid's coach is a kid-oriented version of Chess.com Game Review and adds nothing that changes
this analysis, so it is left out of the matrix.

## Feature matrix

Column key: C.com = Chess.com, Li = Lichess, Aim = Aimchess, Dec = DecodeChess, Noc = Noctie,
Cbl = Chessable, Cly = Chessly, Wolf = Dr. Wolf, Sig = Chessigma, CV = Chessvision.ai,
Chy = Chessy, Cro = Chessiro, Us = Chess Coach Agent.

| Feature | C.com | Li | Aim | Dec | Noc | Cbl | Cly | Wolf | Sig | CV | Chy | Cro | Us |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Import Chess.com / Lichess games | ✓ native | ✓ native | ✓ | partial | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ |
| Analyze full history in bulk | partial | partial | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | ✓ |
| PGN paste / upload | ✓ | ✓ | partial | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ |
| Inaccuracy / mistake / blunder labels | ✓ | ✓ | partial | ✓ | partial | ✗ | ✗ | partial | ✓ | ✗ | partial | ✓ | ✓ |
| Positive labels (Best, Great, Brilliant, Book) | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | partial | ✗ |
| Game accuracy % per side | ✓ | ✓ | partial | ✗ | ✗ | ✗ | ✗ | ✗ | partial | ✗ | ✗ | ✗ | partial |
| Eval bar | ✓ | ✓ | ✗ | partial | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Eval graph, click to jump | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Plain-language explanation of each mistake | ✓ | partial | partial | ✓ | partial | ✗ | ✗ | ✓ | partial | ✗ | ✓ | ✓ | ✓ |
| Free-form chat about your game | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |
| Chat answers checked by engine tool calls | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | ✓ |
| Coach draws arrows / highlights on board | ✓ | partial | ✗ | partial | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Voice (spoken answers, speech input) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | ✗ |
| Drag-and-drop interactive board | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | partial | ✓ | ✓ | ✗ |
| Retry the mistake inside the review | ✓ | ✓ | ✓ | ✗ | partial | ✗ | ✗ | partial | ✗ | ✗ | ✗ | ✓ | partial |
| Explore variations with live engine | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | partial | partial | partial | ✗ |
| Drills built from your own mistakes | partial | partial | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| Spaced repetition scheduling | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | partial | ✗ | ✗ | ✗ | ✗ | partial | ✓ |
| Tactics puzzle library by theme | ✓ | ✓ | ✓ | ✗ | partial | partial | partial | ✗ | partial | ✗ | ✗ | ✓ | ✗ |
| Weakness profile that persists across games | partial | partial | ✓ | ✗ | partial | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | ✓ |
| Stats by phase, opening, time of day, opponent | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | ✗ | partial | ✗ | partial |
| Opening names, explorer, repertoire drill | ✓ | ✓ | partial | ✗ | ✓ | ✓ | ✓ | ✗ | partial | ✗ | partial | ✗ | ✗ |
| Clock / time-management analysis | partial | partial | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Play a bot (adaptive or human-like) | ✓ | partial | ✗ | partial | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ | ✗ |
| Board from photo / screenshot | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✗ | ✗ |
| Documented, inspectable eval method | partial | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | ✗ | ✗ | ✗ | ✓ |
| Published quality metrics for the coach | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| Free without daily caps | ✗ | ✓ | ✗ | ✗ | partial | ✗ | ✗ | ✗ | ✓ | partial | ✗ | partial | ✓ |

Notes on our own column:

- "Game accuracy % per side" is partial because `move_accuracy` exists only on critical moments
  (`analysis.py`). There is no per-game number.
- "Retry inside review" is partial because "Train this position" leaves the review page and opens a
  practice session.
- "Stats" is partial: the Progress page shows rating history, theme frequency, quiz attempts and a
  transfer score, but nothing by phase, opening, or time.
- The board is Unicode glyphs in a CSS grid (`ChessBoard.tsx`). Practice asks the player to type
  SAN or UCI, or pick from buttons.
- ECO is parsed from PGN headers into `GameMetadata.eco` but never shown or aggregated.
- Lichess and Chess.com PGNs include `%clk` comments, and the Lichess importer even asks for them
  (`clocks=true`), but `pgn.py` walks `mainline_moves()` and drops them.

## What we do that competitors don't

These are the parts of the product that no single competitor combines, and every item in the gap
list below is designed to keep them intact.

1. A weakness memory built from the full history. Sync pulls up to 5,000 games in the background,
   skips games already analyzed, and recomputes per-theme counts, quiz accuracy, mastery and due
   counts deterministically. Aimchess has history-wide metrics, but its coach does not answer
   questions with them. Chess.com and Lichess review one game at a time; their "learn from
   mistakes" features stay inside that game, and Lichess users have asked for a cross-game version
   in its forum.

2. A chat coach whose chess claims come from tools. The PydanticAI agent has nine tools
   (`inspect_position`, `compare_moves`, `inspect_game` and others) that call Stockfish and
   python-chess. The prompt carries verified context, the output is a validated `CoachingOutput`,
   and an offline answer built from engine data takes over if the LLM fails. Chessy and Chessiro
   offer chat, but neither documents how answers are grounded. Chessiro says it uses Stockfish 19
   for analysis; it does not say the chat model is checked per claim.

3. Spaced repetition of the player's own mistakes. Chessable and Noctie schedule reviews, but of
   course lines or repertoire. Chess.com Retry and Lichess "Learn from your mistakes" replay your
   mistakes once. We store the position, grade the attempt with Stockfish, and bring it back after
   1, 3 or 7 days, doubling up to 30.

4. An open, documented method. Moment selection uses the published Lichess win-chance curve and
   thresholds (`docs/moment_selection.md`). Retrieval strategies were benchmarked and the winner is
   chosen by a gate (`docs/evaluation_results.md`). The `/quality` page tracks LLM use, tool calls,
   and helpful / not-helpful feedback. No competitor publishes coach quality numbers.

5. No paywall on review count. Chess.com, Aimchess, DecodeChess and Dr. Wolf all cap free use.

The weak spots behind this pitch: explanations on the review page are deterministic templates (five
themes), Stockfish runs at depth 9 by default, and only the player's own moves are evaluated.

## Prioritized gap list

Ordering is by user value per unit of effort, adjusted for what unblocks other work. Effort: S is
up to 2 days, M is 3 to 7 days, L is more than a week, for one engineer familiar with the repo.

### Shared files and how to avoid conflicts

Several files are touched by almost every feature: `backend/.../models.py`,
`frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/router.tsx` and
`frontend/src/styles.css`. Four rules keep parallel work mergeable:

- Do one small prep change before wave 1: move `GameReviewPage` (and `gameStats`, `boardFen`) out
  of `router.tsx` into `frontend/src/pages/GameReviewPage.tsx`. `router.tsx` then only holds route
  definitions, and each new page adds one route entry.
- New backend features go in new modules with their own `APIRouter`, registered with one
  `include_router` line in `api.py`. Do not grow `adaptive_api.py`.
- New TypeScript types and fetch functions go in new files (`lib/evalTypes.ts`,
  `lib/openingsApi.ts`) instead of growing `types.ts` and `api.ts`. New CSS goes in a stylesheet
  imported by the component that needs it.
- Additions to `models.py` must be optional fields with defaults, so stored analyses
  (`games.metadata_json`) still load. No migration is needed for anything stored in that JSON.

### Wave 1: five items with no shared files

| # | Item | Owner files | Effort |
| --- | --- | --- | --- |
| 1 | Full-game evals, accuracy, extended labels | `analysis.py`, `engine.py`, `pgn.py`, `models.py` (MoveRecord, CoachAnalysis), new `classification.py`, `tests/test_analysis.py` | M |
| 2 | Interactive board | `ChessBoard.tsx`, `PracticePage.tsx`, `package.json`, new `lib/chessRules.ts`, new `board.css` | M |
| 3 | Opening names and opening stats | new `openings.py`, new `openings_api.py`, new `data/openings/*.tsv`, new `lib/openingsApi.ts`, new `components/OpeningsPanel.tsx`, one line in `ProgressPage.tsx` | M |
| 4 | Coach voice and board annotations | `llm.py`, new `annotations.py`, `CoachPanel.tsx`, new `lib/useSpeech.ts` | M |
| 5 | Theme puzzle library (backend) | new `puzzles.py`, new `scripts/ingest_puzzles.py`, `db_models.py` (new table), new Alembic revision, `training.py` | M |

### Wave 2: after items 1 and 2 land

| # | Item | Depends on | Owner files | Effort |
| --- | --- | --- | --- | --- |
| 6 | Eval bar, eval graph, move badges, accuracy display | 1, 2 | new `EvalGraph.tsx`, new `EvalBar.tsx`, `GamePanel.tsx`, `AnalysisPanel.tsx` | M |
| 7 | Retry the mistake inside the review | 2 | new `RetryMistake.tsx`, new `grading_api.py`, `pages/GameReviewPage.tsx` | S |
| 8 | Analysis board with variations and live engine | 2 | new `pages/AnalysisBoardPage.tsx`, new `lib/stockfishWorker.ts`, one route in `router.tsx` | M |
| 9 | Insights: stats by phase, opening, time, opponent | 1, 3 | new `insights.py`, new `insights_api.py`, new `pages/InsightsPage.tsx`, one route + nav link | M |
| 10 | Time-management analysis | 1 | `analysis.py` (theme detector), `pgn.py` already done in 1 | S |
| 11 | Play out positions against a bot | 2 | new `play_api.py`, new `pages/PlayPage.tsx`, one route | M |

Items 6, 7, 8, 9 and 11 can run at the same time in wave 2. Item 10 belongs to whoever owned item
1, because it edits `analysis.py`.

### Later, lower priority

| # | Item | Effort |
| --- | --- | --- |
| 12 | Sign in with Lichess (OAuth PKCE) so a profile belongs to a person | M |
| 13 | Annotated PGN export of a reviewed game | S |
| 14 | Board from screenshot (Chessvision-style) | L |

---

### 1. Full-game evals, game accuracy and extended move labels

User value: every competitor's review starts with an accuracy number and a label on every move.
Ours only labels the bad moves, so a clean game shows almost nothing, and there is no positive
feedback. This item also produces the data that items 6, 9 and 10 render.

Who has it: Chess.com (Best, Excellent, Good, Book, Great, Brilliant, Inaccuracy, Mistake, Miss,
Blunder, plus CAPS accuracy and a per-phase game rating), Lichess (accuracy and ACPL), Chessigma
(9 tiers), DecodeChess, Chessiro (good and best).

Implementation sketch (backend only):

- In `analyze_parsed_game`, evaluate every position once, for both sides. The "after" eval of ply
  n is the "before" eval of ply n+1, so this takes N+1 engine calls for N plies. The current code
  makes two calls per player move, which is about the same total.
- Add optional fields to `MoveRecord`: `eval_cp`, `mate`, `best_uci`, `best_san`,
  `win_chance_loss`, `accuracy`, `classification`, `clock_seconds`. Add
  `accuracy: dict[str, float]` (white, black) and `phase_accuracy` to `CoachAnalysis`. All stored
  in `metadata_json`, so no migration.
- New `classification.py`. Keep our Lichess win-chance thresholds for inaccuracy, mistake and
  blunder so `moment_selection.md` stays true. Below 0.10 loss: Best (engine move or under 0.005),
  Excellent (under 0.02), Good (under 0.10). Great: the played move is best and the second
  MultiPV line loses at least 0.20, which needs `multipv=2` in `engine.py`. Brilliant: Great plus
  a material sacrifice (python-chess SEE or a piece left en prise) and the player was not already
  above 0.9 win chance. Miss: the opponent's previous move was a mistake or blunder and this move
  gives back at least 0.10. Book: position is in the item 3 opening table; until item 3 lands,
  treat the first plies matching the PGN `ECO` as Book or skip the label.
- Game accuracy: Lichess formula (mean of the volatility-weighted mean and harmonic mean of
  per-move accuracy). `move_accuracy()` already exists.
- In `pgn.py`, iterate `game.mainline()` nodes instead of `mainline_moves()` and read
  `node.clock()` into `clock_seconds`.
- Bump `ANALYSIS_VERSION` and add a re-analysis path: sync currently skips games that have an
  analysis, so stored games need a backfill job that re-runs games with an older version string.
- Make depth configurable per call. Reviews should use more than depth 9 (or a node limit) while
  the bulk sync stays cheap. Measure CPU time on the Render instance first.

Effort: M. Independent: yes. Owns `analysis.py`, `engine.py`, `pgn.py` and the `MoveRecord` /
`CoachAnalysis` part of `models.py`. Publish the new field names on day one so items 6 and 9 can
build against fixtures.

### 2. Interactive board

User value: every competitor lets you move pieces. Typing "Nf3" into a text box is the most
visible gap in the product, and items 6, 7, 8 and 11 need a board that accepts moves and draws
arrows.

Who has it: all of them except Chessvision.ai, which hands off to Lichess.

Implementation sketch (frontend only):

- Add `chess.js` (move legality, SAN) and `react-chessboard` (MIT, React 19 compatible).
  Chessground looks closer to Lichess but is GPL-3.0, so check the repo license before choosing it.
- Rewrite `ChessBoard.tsx` around react-chessboard and keep its current props so `GamePanel.tsx`
  does not change. Add optional props: `onMove(uci)`, `arrows`, `lastMove`, `highlightSquares`,
  `interactive`. Render the square-control heatmap through `customSquareStyles` using the existing
  `lib/squareControl.ts` output.
- `PracticePage.tsx`: replace the SAN input with drag-to-move. Keep the choice buttons for
  beginner difficulty and the text input as a keyboard fallback for accessibility.
- `lib/chessRules.ts`: thin wrappers (legal moves, SAN from UCI, side to move).

Effort: M. Independent: yes. Owns `ChessBoard.tsx`, `PracticePage.tsx`, `package.json`. The
heatmap is the main regression risk; keep a Playwright check in `frontend/e2e`.

### 3. Opening names and opening stats

User value: players think in openings ("I lose with the Caro-Kann"). Today the app knows the ECO
code and never shows it. Opening names also give item 1 its Book label and item 9 its main
grouping.

Who has it: Chess.com (Explore tab, Insights openings), Lichess (opening explorer, including your
own games), Aimchess (Opening Improver), Noctie, Chessable and Chessly (repertoires).

Implementation sketch (backend and frontend):

- Vendor the `lichess-org/chess-openings` TSV files (CC0) into `backend/data/openings/`. New
  `openings.py` builds a dict keyed by EPD and returns the deepest match for a move list.
- New `openings_api.py` with `GET /api/openings/{platform}/{username}`: replay each stored game's
  moves from `metadata_json`, name the opening, and aggregate games, score, and critical moments
  per opening and color. Computing names at read time avoids touching `analysis.py` or `pgn.py`,
  which item 1 owns. After both land, item 1's owner can store `opening_name` on `GameMetadata`.
- New `OpeningsPanel.tsx` (a table and a Recharts bar) mounted on the Progress page with one
  import line in `ProgressPage.tsx`.

Effort: M. Independent: yes. A full repertoire trainer (Chessable-style) is out of scope; the
existing spaced-repetition tables could hold repertoire lines later.

### 4. Coach voice and board annotations

User value: the newer LLM coaches (Chessy, Chessiro) and Chess.com's coach all talk and point at
squares. Our answers are text only, and a sentence like "the knight on f6 is loose" is easier to
follow with the square lit up.

Who has it: Chess.com (ElevenLabs coach voices, visual explanations on hover), Dr. Wolf, Chessy
(voice in and out, 6 voices), Chessiro (voice in 24 languages, arrows and highlighted squares).

Implementation sketch:

- Backend: new `annotations.py` with a `BoardAnnotation` model (`kind: arrow | square`, `from`,
  `to`, `color`) and a validator that drops any square or move not legal in the current FEN, using
  python-chess. Add an optional `annotations: list[BoardAnnotation]` to `CoachingOutput` (one
  optional field in `models.py`, separate from item 1's region). In `llm.py`, tell the agent it
  may return annotations and run the validator before responding. This keeps the "every claim is
  checked" rule for drawings too.
- Frontend: new `lib/useSpeech.ts` using the browser Web Speech API (`speechSynthesis` to read
  answers, `SpeechRecognition` for a mic button where supported). No paid TTS needed for a first
  version. `CoachPanel.tsx` adds a speaker toggle, a mic button, and an `onAnnotations` callback.
- Wiring annotations to the board is one prop in `GamePanel.tsx` and `PracticePage.tsx` after
  item 2 lands. Until then, list annotations as text under the answer.

Effort: M. Independent: yes in wave 1. The final hookup touches files owned by items 2 and 6, so
do it as a short follow-up.

### 5. Theme puzzle library to back up own-mistake drills

User value: a new user, or one who has cleared the due queue, sees "No positions due". Every
major competitor has a themed puzzle stream. Mapping puzzles to our five themes gives extra
volume on the player's weakest theme while their own positions remain first in the queue.

Who has it: Chess.com, Lichess (puzzle themes dashboard), Aimchess (adaptive tactics), Chessiro
(Replay Mistakes plus puzzles), Chessigma (puzzles blog and trainer).

Implementation sketch (backend only in wave 1):

- `scripts/ingest_puzzles.py` loads a filtered slice of the Lichess puzzle CSV (CC0), for example
  50k puzzles rated 800 to 2200, into a new `puzzles` table (`db_models.py` plus an Alembic
  revision).
- `puzzles.py` maps Lichess tags to our themes: `hangingPiece` to loose_piece; `fork`, `pin`,
  `skewer`, `discoveredAttack` to missed_tactic; `kingsideAttack`, `backRankMate`, `exposedKing`
  to king_safety; `endgame` tags to endgame_conversion. opening_drift has no clean match.
- `training.py`: when fewer than five own positions are due, fill the session with puzzles for
  the top weakness theme, served through the existing `TrainingSessionView` shape with a
  `source: "puzzle"` flag. Lichess puzzles start one ply before the solution: apply the first move
  to get the FEN and use the second move as `correct_move`. Grade only the first solution move
  until item 2 lands. Puzzle attempts should not count toward the transfer score.

Effort: M. Independent: yes. Owns `training.py` and `db_models.py`. The Postgres size of 50k rows
is small; the full 5M-row file is not needed.

### 6. Eval bar, eval graph, move badges and accuracy display

User value: this is the first screen of a Chess.com or Lichess review. A player can see where the
game turned without reading anything.

Who has it: Chess.com, Lichess, Chessigma; DecodeChess partially.

Implementation sketch (frontend only):

- New `EvalGraph.tsx` with Recharts (already a dependency): an area chart of win chance by ply,
  dots on critical moments colored by judgment, click to set `currentPly`.
- New `EvalBar.tsx` next to the board, driven by `moves[ply].eval_cp`.
- `GamePanel.tsx`: classification glyph next to each SAN in the move list; show the best move for
  the current ply as an arrow (item 2 board prop).
- `AnalysisPanel.tsx`: accuracy per side and per phase in the summary box.
- Types go in new `lib/evalTypes.ts`.

Effort: M. Depends on 1 (data) and 2 (arrows). Owns `GamePanel.tsx` and `AnalysisPanel.tsx`.

### 7. Retry the mistake inside the review

User value: Chess.com Retry and Lichess "Learn from your mistakes" let you try again on the spot.
Our "Train this position" leaves the page and starts a session, which is a heavier step than most
players want right after a loss.

Who has it: Chess.com, Lichess, Aimchess (Retry Mistakes), Chessiro (Replay Mistakes).

Implementation sketch:

- Backend: new `grading_api.py` with a stateless `POST /api/moves/grade` (fen, move) that reuses
  the Stockfish grading from `training.evaluate_attempt` without writing an attempt. Move the
  grading core into a pure function in a new module rather than editing `training.py`, which
  item 5 owns.
- Frontend: new `RetryMistake.tsx`. On a selected critical moment, set the board to `fen_before`,
  accept one move, show the result, and offer "Add to practice", which calls the existing
  `createTrainingSession` so the position joins the spaced-repetition queue. This keeps the UVP
  link between review and long-term practice.
- Mount it in `pages/GameReviewPage.tsx` (after the prep refactor).

Effort: S. Depends on 2.

### 8. Analysis board with variations and live engine

User value: players want to ask "what if I had played Bxf7?" and see the answer move by move.
Today the only way is to type a question to the coach.

Who has it: Chess.com (Explore variations in Game Review), Lichess, DecodeChess, Chessigma
(position editor).

Implementation sketch (frontend only):

- Add the `stockfish` npm package (WASM build, GPL-3.0; it runs in a separate worker file, but
  check the license as in item 2) and wrap it in `lib/stockfishWorker.ts` with MultiPV 3.
  Running in the browser keeps load off the Render backend.
- New `pages/AnalysisBoardPage.tsx` at `/analysis?fen=...`: interactive board, variation tree
  held in chess.js, top three engine lines, and the `CoachPanel` with the current FEN so the
  existing tools answer about the explored position.
- Link to it from the review page ("Open in analysis board").

Effort: M. Depends on 2.

### 9. Insights: stats by phase, opening, time and opponent

User value: Chess.com and Lichess Insights and Aimchess metrics answer "where do I lose points?"
Our Progress page shows theme counts and a rating line. The data for a much richer page is
already in the database after items 1 and 3.

Who has it: Chess.com Insights (accuracy by phase and move number, results by opponent rating,
time of day), Lichess Insights, Aimchess (benchmarks against similar ratings).

Implementation sketch:

- Backend: new `insights.py` and `insights_api.py`, `GET /api/insights/{platform}/{username}`
  with filters (time control, color, date range). Aggregate from `games` and `critical_moments`
  rows plus the per-move fields from item 1: accuracy by phase, results by opening (item 3),
  blunder rate by move number, results by opponent rating band and by hour.
- Frontend: new `pages/InsightsPage.tsx` with Recharts, a route and a sidebar link. Leave
  `ProgressPage.tsx` for practice outcomes.
- Feed the top two findings into the coach's verified context (`_player_memory_context` in
  `adaptive_api.py`) so the chat can cite them. That is a small edit to a file nobody else owns in
  wave 2.

Effort: M. Depends on 1 and 3.

### 10. Time-management analysis

User value: a large share of club-level losses are clock losses or blunders under time pressure.
Aimchess sells a Time Trainer for this reason. The data is already in every imported PGN.

Who has it: Aimchess (Time Trainer); Chess.com and Lichess partially (clock times in analysis,
Lichess Insights move-time dimension).

Implementation sketch (backend): with `clock_seconds` from item 1, add a `time_pressure` theme in
`analysis.py` when a mistake is made with under 10% of the starting time left, and record time
spent per move. Add a principle and lesson snippet for it in `backend/data/knowledge/`. Insights
(item 9) charts mistakes by remaining clock.

Effort: S. Depends on 1, same owner.

### 11. Play out positions against a bot

User value: Noctie, Chessiro, Chessy and Dr. Wolf all let you play the coach. For us the useful
version is narrower: play on from one of your own critical moments, or a few games in the opening
you score worst with, and have the result analyzed like any other game.

Who has it: Chess.com (bots), Dr. Wolf, Noctie (human-like), Chessiro (Maia, 250 to 3000), Chessy,
Lichess (Stockfish levels).

Implementation sketch:

- Backend: new `play_api.py`, `POST /api/play/move` (fen, level) using Stockfish with
  `UCI_LimitStrength` and `UCI_Elo` through `engine.py`'s existing path. Maia (lc0 with Maia
  weights) plays more like a human but needs another binary on Render; leave it for later.
- Finished games go through the existing PGN analysis path with `platform: "pgn"`, so they appear
  in the library and feed weakness memory.
- Frontend: new `pages/PlayPage.tsx` using the item 2 board, with a "Play from here" button on
  critical moments.

Effort: M. Depends on 2.

### 12 to 14. Later items

12. Sign in with Lichess (OAuth 2 PKCE, no client secret needed). Today anyone can open any
    username's data, and Chessy and Chess.com tie data to an account. M effort; touches
    `WorkspaceContext.tsx` and every player-scoped route, so it should not run alongside wave 2.
13. Annotated PGN export: write classifications and critical-moment comments as PGN comments with
    python-chess. S effort, new endpoint, no conflicts.
14. Board from screenshot, as in Chessvision.ai and Chessy. L effort (a vision model or a
    dedicated board-recognition model). Low value for a coach built on imported games.

## Summary of ownership

| Engineer | Wave 1 | Wave 2 |
| --- | --- | --- |
| A (analysis backend) | 1. Full-game evals and labels | 10. Time management, then 13. PGN export |
| B (board frontend) | 2. Interactive board | 8. Analysis board |
| C (openings, data) | 3. Openings | 9. Insights |
| D (coach) | 4. Voice and annotations | 7. Retry in review, plus hooking annotations to the board |
| E (practice backend) | 5. Puzzle library | 11. Play against a bot |
| F (optional sixth) | | 6. Eval bar, graph, badges |

If only five engineers are available, B takes item 6 after item 8, since both are board-heavy.

## Sources

- Chess.com, [Game Review glossary](https://www.chess.com/terms/game-review)
- Chess.com, [How are moves classified](https://support.chess.com/en/articles/8572705-how-are-moves-classified-what-is-a-blunder-or-brilliant-move)
- Chess.com, [Game Review v2](https://www.chess.com/news/view/chesscom-launches-game-review-v2),
  [More in-depth line explanation](https://www.chess.com/announcements/view/update-game-reviews-coach-now-with-more-in-depth-line-explanation),
  [Explore variations](https://www.chess.com/announcements/view/update-explore-variations-in-game-review),
  [Game Review now more human](https://www.chess.com/announcements/view/update-game-review-now-more-human)
- Chess.com, [What is Insights](https://support.chess.com/en/articles/8708925-what-is-insights-on-chess-com)
- GamesBeat, [Chess.com AI coach voices](https://gamesbeat.com/chess-com-will-let-you-choose-your-ai-coach-based-on-celebrity-voices/);
  ElevenLabs, [Learning chess aloud](https://elevenlabs.io/blog/chess-dot-com)
- Lichess, [Learn from your mistakes](https://lichess.org/blog/WFvLpiQAACMA8e9D/learn-from-your-mistakes),
  [forum request for cross-game version](https://lichess.org/forum/lichess-feedback/create-learn-from-your-mistakes-across-all-games),
  [Chess Insights](https://lichess.org/@/lichess/blog/chess-insights/VmZbaigA)
- Aimchess, [site](https://aimchess.com), [App Store listing](https://apps.apple.com/us/app/aimchess-learn-chess-online/id1524941307),
  [Play Magnus announcement](https://playmagnusgroup.com/chess-training-and-analytics-startup-aimchess-joins-play-magnus-group)
- DecodeChess, [Explaining your moves](https://decodechess.com/new-feature-explaining-your-moves/)
- Noctie, [App Store listing](https://apps.appfollow.io/ios/noctie-chess-trainer/6444289077?country=us),
  [Chessiverse comparison](https://chessiverse.com/compare/chessiverse-vs-noctie)
- Chessable, [App Store listing](https://apps.apple.com/us/app/chessable/id1523279049)
- Dr. Wolf, [Chess.com app page](https://www.chess.com/play/apps/drwolf)
- Chessigma, [site](https://chessigma.com/), [How analysis works](https://www.chessigma.com/blog/how-chessigma-analysis-works)
- Chessvision.ai, [Firefox add-on](https://addons.mozilla.org/addon/chessvision-ai-for-firefox/)
- Chessy, [chessvia.ai](https://www.chessvia.ai/) (also the saved clipping in the user's notes)
- Chessiro, [Best AI chess coach (March 2026)](https://chessiro.com/blog/best-ai-chess-coach)
- AI Engineer, [Building a chess coach talk](https://ai.engineer/talks/building-a-chess-coach)
- Open data for implementation: [lichess-org/chess-openings](https://github.com/lichess-org/chess-openings),
  [Lichess puzzle database](https://database.lichess.org/#puzzles)
