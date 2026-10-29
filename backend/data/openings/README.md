# Opening names

`a.tsv` to `e.tsv` come from [lichess-org/chess-openings](https://github.com/lichess-org/chess-openings)
(`master` branch, fetched 2026-10-29). The dataset is released under CC0 1.0 (public domain).

Each row has an ECO code, an opening name and the PGN moves that define it.
`chess_coach_agent/openings.py` replays every line once, keys the final position by EPD and names a
game by the deepest of those positions it reaches.

To update, download the five files again from
`https://raw.githubusercontent.com/lichess-org/chess-openings/master/{a,b,c,d,e}.tsv`.
