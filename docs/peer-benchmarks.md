# Peer benchmarks: data sources

What public data exists for comparing a player with similar players, checked by calling each
endpoint on 2026-10-31. Rule for this feature: a figure needs a real, citable source and a stated
sample size. If there is none, the metric is left out.

## Used

| Source | What it gives | Notes |
| --- | --- | --- |
| [`GET lichess.org/api/user/{user}/perf/{perf}`](https://github.com/lichess-org/api/blob/master/doc/specs/tags/users/api-user-username-perf-perf.yaml) | Current rating and `percentile` | Documented API, no token. `percentile` is missing while a rating is provisional, and the app then shows nothing. |
| [`lichess.org/stat/rating/distribution/{perf}`](https://lichess.org/stat/rating/distribution/blitz) | Weekly histogram, used for the sample size | Read once, stored as a dated snapshot (`LICHESS_WEEKLY_PLAYERS`). Not fetched at runtime, see below. The numbers sit in the `page-init-data` JSON: `freq`, 25-point buckets from rating 400. The page says "734,567 Blitz players this week" and `freq` sums to the same. Exists for ultraBullet, bullet, blitz, rapid, classical. `correspondence` returns 404. |
| This database | Accuracy, blunders per game, accuracy by phase | Compared within one site, time control and 200-point band, only with at least 30 other players who have the metric. |

The two Lichess sources agree. Summing `freq` below the rating rounded to the nearest 25
reproduced the API's `percentile` for the accounts tried, for example 74.6 at 1744 blitz, 86.4 at
1837 rapid and 23.4 at 1160 blitz. The app shows the API's figure.

Weekly distributions cover players active that week, not all accounts. The Insights footnote
says so.

### Why the sample size is a snapshot

The API gives a percentile but no population size, and the
[API spec](https://github.com/lichess-org/api/tree/master/doc/specs) has no distribution endpoint.
The distribution page is the only source, and Cloudflare answers some automated clients with a
403 "Just a moment..." challenge: `httpx`, which this backend uses, gets it, Python's `urllib`
did not. Picking a client to get past a bot check is not something to build on, so the app makes
no request to that page. The percentile stays live and the count is shown with its date.

Snapshot taken 2026-10-31: ultraBullet 11,906, bullet 373,087, blitz 734,567, rapid 543,607,
classical 42,771. Refresh by hand from the page; asking Lichess for an API endpoint would remove
the need.

## Checked and not used

| Source | Result | Why not |
| --- | --- | --- |
| `lichess.org/api/stats/rating/...` and similar paths | 404 | No such endpoint. The data is on the `/stat/` page above. |
| [`api.chess.com/pub/leaderboards`](https://api.chess.com/pub/leaderboards) | Top 50 per category | Says nothing about a typical player. |
| [`api.chess.com/pub/player/{user}/stats`](https://www.chess.com/news/view/published-data-api) | Rating, best, record | No percentile. |
| `chess.com/callback/member/stats/{user}`, `chess.com/stats/live/{perf}/{user}` | Respond, but no percentile in the logged-out response | Undocumented, and robots.txt disallows `/callback/` and `/stats/`. |
| `chess.com/stats/ratings/blitz` | 404 | |
| [`explorer.lichess.ovh/lichess`](https://lichess.org/api#tag/Opening-Explorer) | 401 without a token | Real data by rating group and speed, so it could give opening results for Lichess peers. Not built: it needs `LICHESS_API_TOKEN` and isn't what was asked for first. |
| [database.lichess.org](https://database.lichess.org/) | Monthly game dumps | Raw games, tens of GB a month. No published per-band stats, and only some games carry evals. Too big to process here. |
| Accuracy or blunders by rating | Forum and blog posts only | No authoritative table. Chess.com and Lichess also define accuracy differently, and neither matches this app's engine settings. |

## Left out

- **Percentile for Chess.com players.** No public distribution exists. Their rating is not placed
  on the Lichess curve, because the scales differ and the result would look exact while meaning
  little. Chess.com players get only the comparisons within this database.
- **External accuracy and blunder benchmarks.** Nothing citable.
- **Correspondence percentile.** Lichess has no weekly distribution for it.

## Privacy

Benchmarks read `GameRow` and `CriticalMomentRow` only, so they are public-game stats and the same
for every viewer. Claimed players' games count in other players' cohorts in aggregate, which
matches `accounts.py`: game data is public, practice data is not.
