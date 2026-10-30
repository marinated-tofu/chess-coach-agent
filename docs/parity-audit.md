# Competitor parity audit

Audit date: 31 October 2026. This rechecks every row of the feature matrix in
[competitive-analysis.md](competitive-analysis.md) against the code on `main` (2eb40a3). That
matrix's "Us" column was written before the parity work and is out of date; this file replaces it.

"Shipped" means the code exists in the listed files. It does not mean each feature was tested
against the competitor side by side. Competitor columns come from the October 2026 research and
were not re-verified here, and competitors' prices could not be confirmed from their own pages.

## Result

24 of 28 matrix rows are shipped, 3 are partial, and 1 is true today but ends once we charge.

| Feature | Status | Where |
| --- | --- | --- |
| Import Chess.com / Lichess games | Shipped | `importers.py` |
| Analyze full history in bulk | Shipped | `adaptive_api.py` |
| PGN paste | Shipped | `GamesPage.tsx` |
| Mistake and blunder labels | Shipped | `classification.py` |
| Positive labels | Shipped | `classification.py` |
| Game accuracy | Shipped | `analysis.py` |
| Eval bar | Shipped | `EvalBar.tsx` |
| Eval graph, click to jump | Shipped | `EvalGraph.tsx` |
| Plain-language explanations | Shipped | `analysis.py` |
| Free-form chat about your game | Shipped | `llm.py`, `CoachPanel.tsx` |
| Chat answers checked by engine tools | Shipped | `coach_tools.py` |
| Coach draws arrows and highlights | Shipped | `annotations.py` |
| Voice in and out | Shipped | `useSpeech.ts` (browser speech) |
| Drag-and-drop board | Shipped | `ChessBoard.tsx` |
| Retry the mistake in review | Shipped | `RetryMistake.tsx` |
| Explore variations with live engine | Shipped | `AnalysisBoardPage.tsx` |
| Drills from your own mistakes | Shipped | `training.py` |
| Spaced repetition | Shipped | `training.py`, `repertoire.py` |
| Puzzle library by theme | Partial | `puzzles.py`: 1,250 puzzles, used inside practice sessions |
| Weakness profile across games | Shipped | `insights.py` |
| Stats by phase, opening, time, opponent | Partial | `insights.py`: no time-of-day breakdown |
| Openings, explorer, repertoire drill | Shipped | `explorer.py`, `repertoire.py` |
| Clock and time analysis | Partial | `insights.py`: analysis only, no time trainer |
| Bots | Shipped | `bots.py` |
| Board from image | Shipped | `vision.py` |
| Documented eval method | Shipped | `evaluation_results.md` |
| Published coach quality metrics | Shipped | `/quality` |
| Free without daily caps | Ends with paid plans | Current state only |

## Gaps outside the matrix

| Gap | Who has it | Note |
| --- | --- | --- |
| Accounts with private data | All paid competitors | Only optional Lichess sign-in exists. No users table. Required before charging. |
| Peer benchmarks | Aimchess | Needs enough users to compare against, so it can't be honest yet. |
| Weekly study plan | Aimchess | Today gives a daily view only. |
| Endgame trainer | Aimchess | Endgames appear as a theme, not a dedicated trainer. |
| Larger puzzle library | Chess.com, Lichess | 1,250 is small next to theirs. |

## Production gaps

Not competitor features, but they block selling it: per-user rate limits (none in the code), a
job queue for syncs, alerts, and the Google Cloud move, which is written in `infra/gcp` but not
applied because the billing account is closed.

## What stays unique

Engine-verified coach answers, published quality metrics, and drills drawn from the player's own
full history. None of the parity work replaced these.
