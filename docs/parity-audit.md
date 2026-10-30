# Competitor parity audit

Audit date: 31 October 2026. This rechecks every row of the feature matrix in
[competitive-analysis.md](competitive-analysis.md) against the code on `feature/parity-integration`. That
matrix's "Us" column was written before the parity work and is out of date; this file replaces it.

"Shipped" means the code exists in the listed files. It does not mean each feature was tested
against the competitor side by side. Competitor columns come from the October 2026 research and
were not re-verified here, and competitors' prices could not be confirmed from their own pages.

## Result

27 of 28 matrix rows are shipped. The other, "free without daily caps", ended on purpose: the coach
now has a daily limit so the product can be sold.

| Former gap | Status | Where |
| --- | --- | --- |
| Puzzle library by theme | Shipped | `/puzzles`, 5,000 puzzles by theme and rating |
| Stats by time of day | Shipped | `insights.py`. Older games need a re-sync. |
| Time trainer | Shipped | `time_trainer.py`, `/practice?mode=time` |
| Weekly study plan | Shipped | `study_plan.py`, on Today |
| Endgame trainer | Shipped | `endgames.py`, `/endgames` |
| Accounts with private data | Shipped | `accounts.py`, `/account`. Lichess sign-in only, for now. |
| Per-user coach limit | Shipped | Anonymous 5, free 20, paid 200 a day |

The other 24 shipped rows were already in place before this work.

## Still open

| Gap | Note |
| --- | --- |
| Peer benchmarks (Aimchess) | Partly built, see `docs/peer-benchmarks.md`. Lichess rating percentile is live. Comparisons within this database stay hidden until a rating band has 30 other analyzed players. Nothing external exists for accuracy or blunders, or for Chess.com percentiles. |
| Live checks | Lichess sign-in and a successful Chess.com link haven't run against the real services. The account migration and quota path haven't run on Postgres. |
| Limits on other AI routes | The practice agent, study plan note and vision routes have no per-user limit. |
| Job queue, alerts | Not built. |
| Payments | Not built. `plan` exists, but nothing can change it yet. |
| Google Cloud | Written in `infra/gcp`, not applied. Billing is closed. |

## What stays unique

Engine-verified coach answers, published quality metrics, and drills drawn from the player's own
full history. None of the parity work replaced these.
