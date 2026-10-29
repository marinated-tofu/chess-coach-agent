# Critical Moment Selection

The coach uses Stockfish to evaluate every move made by the selected player. It does not target a
fixed number of moments. A game can have zero, one, or many review moments.

## Move classification

Engine centipawn scores are converted to Lichess-style winning chances:

```text
winning_chances = 2 / (1 + exp(-0.00368208 * clamp(cp, -1000, 1000))) - 1
loss = winning_chances_before - winning_chances_after
```

Only a decrease for the moving player is considered:

| Winning-chance loss | Label | Review behavior |
| --- | --- | --- |
| Less than 0.10 | No error | Not shown as a critical moment |
| 0.10 to 0.19 | Inaccuracy | Shown in review; used as drill fallback |
| 0.20 to 0.29 | Mistake | Shown and preferred for training |
| 0.30 or more | Blunder | Shown and preferred for training |

On the UI, the loss is displayed in Win% percentage points, so the boundaries appear as 5, 10,
and 15 percentage points. A move that Stockfish itself selected as best is not labeled, which avoids
horizon-noise positions where separate searches disagree slightly.

The move-accuracy percentage uses Lichess's exponential mapping from lost Win% to a 0-100 score.
Stockfish establishes move quality; thematic detectors only explain the likely human pattern after
an engine-significant error has already been established.

## Theme assignment

Themes do not independently create critical moments:

- `loose_piece`: the move newly leaves a minor or major piece attacked and undefended.
- `opening_drift`: an engine-significant repeated early queen move.
- `king_safety`: king-zone danger increases while the king remains uncastled.
- `endgame_conversion`: an engine-significant error in a simplified position.
- `time_pressure`: a mistake or blunder played with under 10% of the base clock left (from PGN
  `%clk` comments). Checked first, because the clock is the likelier cause.
- `missed_tactic`: the default when the loss is significant but the narrower detectors do not fit.

Training sessions prefer mistakes and blunders. Inaccuracies are retained for complete game review
and are used only when no stronger training position is available.

## Full-game labels and accuracy

Since analysis version `lichess-win-chance-v2`, every ply of both sides is evaluated (Stockfish
MultiPV 2) and gets a label: Brilliant, Great, Best, Excellent, Good, Book, Inaccuracy, Mistake,
Miss or Blunder, plus Lichess game accuracy per side. The error labels use the same thresholds as
the table above. The rules for the other labels and the accuracy formula are documented in
`backend/src/chess_coach_agent/classification.py`.

## References

- Lichess move judgments use 0.10/0.20/0.30 winning-chance-loss thresholds:
  <https://github.com/lichess-org/lila/blob/c7a16d8bc3f3e4091edb123f43d9783560305d83/modules/tree/src/main/Advice.scala>
- Lichess's centipawn-to-winning-chances formula and 1000-cp clamp:
  <https://github.com/lichess-org/scalachess/blob/f62751e06f0b13c00a0d4d665462544119ea56cf/core/src/main/scala/eval.scala>
- Lichess's published Win% and move-accuracy explanation:
  <https://lichess.org/page/accuracy>
- Chess.com also describes its current classifier as expected-points based, rather than raw
  centipawn-loss based:
  <https://support.chess.com/en/articles/8708970-how-is-accuracy-in-analysis-determined>

