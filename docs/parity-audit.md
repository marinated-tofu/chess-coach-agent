# Competitor parity audit

Audit date: 31 October 2026. This rechecks every row of the feature matrix in
[competitive-analysis.md](competitive-analysis.md) against the code on `feature/parity-integration`. That
matrix's "Us" column was written before the parity work and is out of date; this file replaces it.

"Shipped" means the code exists in the listed files. It does not mean each feature was tested
against the competitor side by side.

## Result

27 of 28 matrix rows are shipped. The other, "free without daily caps", ended on purpose: the coach
now has a daily limit so the product can be sold.

The first three rows below closed matrix gaps, and the other 24 shipped matrix rows were already
in place. The rest were not in the matrix. They came from competitor research or from what selling
the product needs.

| Former gap | Status | Where |
| --- | --- | --- |
| Puzzle library by theme | Shipped | `/puzzles`, 5,000 puzzles by theme and rating |
| Stats by time of day | Shipped | `insights.py`. Older games need a re-sync. |
| Time trainer | Shipped | `time_trainer.py`, `/practice?mode=time` |
| Weekly study plan | Shipped | `study_plan.py`, on Today |
| Endgame trainer | Shipped | `endgames.py`, `/endgames` |
| Accounts with private data | Shipped | `accounts.py`, `/account`. Lichess sign-in only, for now. |
| Per-user AI limits | Shipped | Coach: anonymous 5, free 20, paid 200 a day. Practice, plan notes and vision have their own limits. |
| Durable sync queue, health checks | Shipped | `sync_queue.py`, `/api/health/ready` |
| Tactics found and missed | Shipped | `tactics.py`, on Insights. Forks, pins, skewers, mate threats and mates, from stored engine data. Covers fewer chances than Chess.com may on purpose: each one must be proved. |

## Still open

| Gap | Note |
| --- | --- |
| Peer benchmarks | Partial, on purpose. Lichess players get a live percentile. Comparisons between users stay hidden until a band has 30 other players. Chess.com percentiles have no public source. See [peer-benchmarks.md](peer-benchmarks.md). |
| Live checks | Lichess sign-in, a successful Chess.com link and the real coach model were not run in the combined walkthrough. |
| Row locking on Postgres | CI runs the migrations and tests on Postgres; the concurrent queue claim has only been run on SQLite. |
| Payments | Not built. Needs your choice of provider. `plan` exists, but nothing can change it yet. |
| Google Cloud | Written in `infra/gcp`, not applied. Billing is closed. |

Competitor columns were rechecked against primary sources on 31 October 2026. Chess.com, Chessy and
Chessvision.ai prices stayed unconfirmed.

## What stays unique

Engine-verified coach answers, published quality metrics, and drills drawn from the player's own
full history. None of the parity work replaced these.
