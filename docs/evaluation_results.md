# Evaluation Results

Evaluation was run on 2026-06-20 with the hand-written datasets in `backend/data/eval/`.

The deterministic critical-moment suite was expanded on 2026-06-21 from two manually scored
coaching cases to 11 regression positions. It currently detects the expected theme in **11/11**
positions, including loose queens, rooks, bishops, and knights; repeated opening queen moves;
king-safety neglect for both colors; and immediate tactical collapses. The original two cases remain
the manually reviewed subset used for the published coaching-quality result below.

## Retrieval Selection

The retrieval benchmark now contains 20 hand-authored queries. It also measures source correctness
and median local latency. Exact machine timings vary, so the checked-in JSON is the authoritative
run artifact.

| Strategy | Hit rate at 3 | MRR | Source correctness | Median latency |
| --- | ---: | ---: | ---: | ---: |
| Title-only | 0.35 | 0.35 | 0.65 | 0.084 ms |
| BM25 | 0.95 | 0.858 | 0.95 | 0.124 ms |
| Vector | 0.95 | 0.725 | 0.95 | 0.338 ms |
| Hybrid RRF | 1.00 | 0.850 | 1.00 | 0.671 ms |

Hybrid did not qualify because it missed BM25 on MRR and exceeded twice BM25's median latency.
BM25 therefore remains the measured production default. This decision is made by code, not a
hard-coded claim: hybrid becomes the default only when it equals or exceeds BM25 on hit rate and
MRR while remaining below the two-times latency guardrail. See
`backend/data/eval/retrieval_results.json` for all per-query ranks.

## MiniMax Judge and Prompt Tuning

For each row in `critical_moments.jsonl`, the pipeline analyzes the PGN, formats the top critical
moment's explanation, and sends it with the human reviewer notes to the judge model through
OpenRouter. The judge scored theme correctness, factual grounding, and coaching quality from 0 to 2
each; a score of 4/6 or more counts as a pass. With `--tune` it runs two answer formats: concise
(theme plus summary) and grounded (theme, played move, engine move, what happened, principle,
drill). The judge evaluates these analysis explanations; answers from the live PydanticAI coach are
scored separately in the next section. The tests replace the judge with a fake so CI needs no key.

| Format | Average score | Pass rate |
| --- | ---: | ---: |
| Concise | 3.0/6 | 50% |
| Grounded, before tuning | 5.0/6 | 100% |
| Grounded, after tuning | 5.5/6 | 100% |

MiniMax identified that the opening-drift answer did not explicitly connect repeated queen moves to
lost development tempi and delayed king safety. The explanation and drill were rewritten around that
feedback. On the next judge run, opening drift improved from `4/6` to `6/6`.

## Live coach evaluation

The sections above score fixed analysis text. This one scores answers from the live PydanticAI
coach, the same `ask_coach` call that serves `/api/coach/ask`, with its nine Stockfish-backed tools.
Run on 2026-10-29.

The dataset is `backend/data/eval/coach_questions.jsonl`: 15 hand-written questions. Thirteen are
about critical moments in the sample games (`kfctofu_sample.pgn`), phrased the way a player would
ask them ("Why did I lose my queen on move 13 after Qe2?"). Two use the loose-piece FENs from
`critical_moments.jsonl` with no game attached. Each row has the acceptable best moves, moves the
answer must not recommend, theme keywords, key points, statements the answer must not make, and a
reference line. Every move and evaluation in the rows was checked with Stockfish at depth 20
through python-chess. The game context is built with the same parse and analyze path as
`/api/analyze`, and the FEN is passed the way the UI passes the board position.

Each answer gets two kinds of score:

- Deterministic checks: the coach used the LLM (no fallback), called at least one tool, recommended
  a legal move in the position, recommended one of the expected moves, avoided the forbidden moves,
  and mentioned a theme keyword.
- An LLM judge that scores grounding, correctness against the key points, the drill, and invented
  variations, 0 to 2 each (8 max, pass at 6). The judge model is pinned for the whole run so coach
  models are compared on the same scale. It is told that the coach's engine runs at depth 9, so
  evaluations within about 0.7 pawns of the depth-20 reference count as matching.

Two system prompts were compared. `baseline` is the current `COACH_INSTRUCTIONS`. `evidence_first`
tells the coach to call `inspect_position` or `compare_moves` before answering a position question,
to take `recommended_move` from tool output, to quote the engine numbers, and to give a drill with a
concrete count. The prompts ran on three coach models, with `anthropic/claude-haiku-5.5` as judge.

| Coach model | Prompt | Judge avg | Judge pass | Expected move | Used a tool | Seconds per answer |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| claude-haiku-5.5 | baseline | 6.20/8 | 60% | 83% | 93% | 7.8 |
| claude-haiku-5.5 | evidence_first | 6.20/8 | 80% | 92% | 87% | 8.9 |
| gemini-3.8-flash | baseline | 6.20/8 | 67% | 92% | 100% | 24.8 |
| gemini-3.8-flash | evidence_first | 5.73/8 | 53% | 92% | 100% | 26.4 |
| minimax-m3.1-flash | baseline | 4.13/8 | 33% | 58% | 73% | 5.2 |
| minimax-m3.1-flash | evidence_first | 4.87/8 | 33% | 58% | 93% | 16.0 |

Model choice. Haiku and Gemini Flash reach the same judge average, but Haiku answers in about a
third of the time. MiniMax M3.1 Flash is the fastest, yet it skipped tools on several questions,
left `recommended_move` empty on five of them, and scored lowest on grounding and invented
variations. This supports switching the default coach model to Haiku. The judge is also Haiku, so a
self-preference bias is possible; Gemini matching it on the same scale suggests the gap to MiniMax
is not an artifact of that.

Prompt choice. No variant won clearly, so `baseline` stays the default. On Haiku, `evidence_first`
raised the pass rate from 60% to 80% and the expected-move rate from 83% to 92%, with the same
judge average. On Gemini it scored lower, mainly on drills (1.2/2 against 1.87/2). On MiniMax it
raised tool use from 73% to 93% and the judge average from 4.13 to 4.87, but answers took three
times longer. With 15 questions and one run each, a 0.5-point difference is within run-to-run
noise. The script reports `gemini-3.8-flash | baseline` as the overall winner only through a
tie-break on the deterministic score.

What the failures show:

- On `g7_m13_knight_fork` every model recommended a queen move other than the depth-20 best
  (`Qh4`, about +2.1). The coach's depth-9 engine prefers `Qf6` (about +0.7 at depth 20), and the
  coach repeats it. The answers are not wrong about the blunder, but the engine depth caps how
  good the recommended move can be.
- Haiku fell back to the non-LLM answer on 1 of 15 questions with `baseline` and 2 of 15 with
  `evidence_first`, each after about 10 seconds. The same questions succeeded 12 times out of 12 on
  a rerun, so this looks like an intermittent provider error. The fallback names the first critical
  moment of the game rather than the one asked about, which the judge correctly scores low.
  `ask_coach` does not record the exception, so the cause is not in the results file.
- No answer from any model recommended a forbidden move.

Cost and time: 90 coach answers plus 90 judge calls took 8.5 minutes with 4 concurrent requests.
The coach calls used 655k input and 87k output tokens. The OpenRouter balance dropped by $0.38 over
the run; other work shared the key at the time, so that figure is an upper bound.

Per-question answers, checks, and judge reasons are in `backend/data/eval/coach_results.json`.
The unit tests (`test_coach_evaluation.py`) run the same pipeline with PydanticAI `TestModel` and a
fake judge, so they need no network.

Commands:

```bash
cd backend
uv run python -m chess_coach_agent.retrieval_evaluation --dataset data/eval/retrieval.jsonl --output data/eval/retrieval_results.json
uv run python -m chess_coach_agent.judge_evaluation --dataset data/eval/critical_moments.jsonl --tune
uv run python -m chess_coach_agent.coach_evaluation \
  --model anthropic/claude-haiku-5.5 --model google/gemini-3.8-flash --model minimax/minimax-m3.1-flash
```

The dataset is intentionally small. Scores establish that the workflow functions; they are not a
claim of general chess-coaching accuracy.
