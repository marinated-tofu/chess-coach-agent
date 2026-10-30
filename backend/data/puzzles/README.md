# Themed puzzle subset

`puzzles.jsonl` holds 5,000 tactics puzzles: 1,000 for each coaching theme, spread across
rating bands from 600 to 2200 (125 per 200-point band). The practice session uses them only
after the player's own game positions run out, or in the "puzzles" mode. The `/puzzles` page
browses all of them.

## Source and license

- Source: the Lichess puzzle database, <https://database.lichess.org/#puzzles>
- License: Creative Commons CC0 (public domain). No attribution is required, but we credit
  Lichess anyway.
- Each `id` is the Lichess puzzle id. The original is at `https://lichess.org/training/<id>`.

## How it was built

The full dump is about 300 MB compressed, so it is streamed and never written to disk:

```sh
cd backend
curl -sL https://database.lichess.org/lichess_db_puzzle.csv.zst \
  | zstd -dc | head -n 500000 \
  | uv run python scripts/build_puzzle_subset.py --per-theme 1000
```

Filters: popularity at least 80, at least 200 plays, rating deviation at most 90. The script
stops reading once every theme has its puzzles (about 309,000 rows in the October 2026 dump).

## Format

One JSON object per line:

| field | meaning |
| --- | --- |
| `id` | Lichess puzzle id |
| `fen` | Position the player solves. This is the Lichess FEN **after** the opponent's first move has been played. |
| `solution` | Remaining UCI moves, starting with the player's move. The Lichess opponent move is dropped. |
| `solution_san` | `solution[0]` in SAN. Practice grades this move only; the puzzle page grades the whole line. |
| `rating` | Lichess puzzle rating |
| `theme` | Our coaching theme (see the mapping below) |
| `tags` | The original Lichess theme tags |

## Theme mapping

Each puzzle gets one primary theme. The first match in this order wins, so specific themes
beat generic ones (a hanging piece in the opening counts as `loose_piece`):

| our theme | Lichess tags |
| --- | --- |
| `loose_piece` | hangingPiece |
| `endgame_conversion` | endgame, rookEndgame, pawnEndgame, queenEndgame, bishopEndgame, knightEndgame, queenRookEndgame |
| `opening_drift` | opening |
| `king_safety` | kingsideAttack, queensideAttack, attackingF2F7, exposedKing, backRankMate, smotheredMate, mateIn1, mateIn2, mateIn3 |
| `missed_tactic` | fork, pin, skewer, discoveredAttack, doubleCheck, deflection, attraction, interference, clearance, xRayAttack, intermezzo, capturingDefender, trappedPiece, sacrifice |

Caveats:

- `opening_drift` in our analysis means drifting from opening principles. Lichess has no tag
  for that, so we use puzzles that occur in the opening phase. It is the loosest match.
- `king_safety` puzzles are attacking puzzles: the player hunts an exposed king rather than
  defends one. Spotting the pattern from the attacker's side is the closest available drill.
- Time pressure has no puzzle equivalent, since puzzles are untimed. Themes outside the five
  above (`time_pressure`, `candidate_move_discipline`) draw a mixed pool across all themes.
