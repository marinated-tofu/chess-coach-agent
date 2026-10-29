# PydanticAI coach: code map

Where PydanticAI (the agent framework) and Pydantic (data models) are used, and how a coach
question flows through the code.

| Library | Used for | Main files |
| --- | --- | --- |
| PydanticAI (`pydantic_ai`) | The coach agent, its tools, structured output, OpenRouter model, message history | `llm.py`, `coach_tools.py` |
| Pydantic (`pydantic`) | API request and response schemas, agent output schema | `models.py` |

All paths below are under `backend/src/chess_coach_agent/`.

## Request flow

```text
CoachPanel.tsx (game review or practice page)
    |  question, platform, username, game_id?, fen?, message_history
    v
POST /api/coach/ask                                   adaptive_api.py
    |  load player weakness memory and the player's analyses
    |  pick the analysis whose game ID matches game_id
    v
ask_coach(question, analysis, fen=..., memory_context=..., message_history=...)   llm.py
    |
    +-- no OPENROUTER_API_KEY --> deterministic fallback answer (used_llm = false)
    |
    +-- create_coach_agent().run(prompt, deps, message_history)
           |  prompt = question + selected game's critical moments + board FEN + player memory
           |  model calls 0..n of the 9 tools
           v
        CoachingOutput (validated)  --> CoachAskResponse
    |
    +-- exception or timeout (COACH_TIMEOUT_SECONDS, default 60) --> fallback answer
    v
log_event("coach_answered", {player, game_id, used_llm, tools_used})              monitoring.py
```

## Model

The model is an `OpenAIChatModel` pointed at OpenRouter (`https://openrouter.ai/api/v1`), with the
model name from `OPENROUTER_MODEL`. The project uses MiniMax (`minimax/minimax-m3` in
`.env.example` and `render.yaml`). If the variable is unset the code defaults to
`openai/gpt-4o-mini`.

## Agent

`create_coach_agent(model=None)` in `llm.py` builds:

```python
Agent(
    model,
    deps_type=CoachDependencies,
    output_type=CoachingOutput,
    instructions=COACH_INSTRUCTIONS,
    tools=[...nine tools...],
    retries=1,
)
```

Passing `model` lets tests swap in PydanticAI's `TestModel`.

The instructions tell the model to treat engine evaluations, legal moves, and supplied game facts
as evidence, never invent variations, separate what the player did from the reusable lesson, give
one drill, and use tools only when the verified context does not already answer the question.

## Dependencies

`CoachDependencies` is the per-run context the tools read through `ctx.deps`:

| Field | Purpose |
| --- | --- |
| `analysis` | The selected game's analysis (critical moments, moves), or `None` |
| `platform`, `username` | Identify the player for database-backed tools |
| `tools_used` | Each tool appends its name; returned to the UI and logged |
| `retrieved_titles` | Lesson titles returned by `search_chess_principles` |
| `panel` | The last quiz or grading panel a training tool produced |

## Tools

| Tool | File | Data source | Purpose |
| --- | --- | --- | --- |
| `search_chess_principles(query)` | `llm.py` | Lesson files, BM25 | Top 3 lesson snippets |
| `inspect_critical_moments()` | `llm.py` | Selected analysis | Up to 4 moments with theme, played and engine moves, eval swing |
| `inspect_position(fen)` | `llm.py` | Stockfish, python-chess | Best move, evaluation, checks, captures |
| `build_training_drill(theme="")` | `llm.py` | Selected analysis | A drill for the main weakness |
| `inspect_game(game_id)` | `coach_tools.py` | Database | Any stored game with its moments by severity |
| `compare_moves(fen, candidate_moves)` | `coach_tools.py` | Stockfish | Legality and evaluation of up to 6 candidates |
| `generate_position_quiz(theme="", difficulty="intermediate")` | `coach_tools.py` | Database | Quiz from the player's own moments |
| `evaluate_candidate_move(position_id, move)` | `coach_tools.py` | Database, Stockfish | Grade a move in a saved training position |
| `build_training_session()` | `coach_tools.py` | Database | Next adaptive quiz plus player profile |

When data is missing (unknown game, no player profile, invalid FEN for `inspect_position`), the
tools return an `{"error": ...}` result the model can read.

## Output

`CoachingOutput` in `models.py`:

| Field | Type | Meaning |
| --- | --- | --- |
| `answer` | str | Markdown answer shown in the panel |
| `evidence` | list[str] | Engine, move, or lesson facts behind the answer |
| `recommended_move` | str or None | A SAN move when the analysis supports one |
| `principle` | str | The reusable chess principle |
| `drill` | str | One practice exercise |
| `confidence` | float, 0 to 1 | Model's confidence |

`CoachAskResponse` wraps it with `answer`, `used_llm`, `tools_used`, `retrieved_notes`, and
`message_history` (PydanticAI messages serialized to JSON). The browser sends the history back on
the next question, so the server keeps no conversation state.

## Fallback

When there is no API key, or the run raises or times out, the endpoint still returns a
`CoachingOutput`. With a selected game it describes the top engine-verified moment (played move,
engine move, theme, principle, drill) at confidence 0.5. Without one it returns the best-matching
lesson and a generic forcing-moves drill at confidence 0.3. The UI labels these answers as offline.

## Observability

`llm.py` configures Logfire with `service_name="chess-coach-agent"` and
`send_to_logfire="if-token-present"`, then calls `logfire.instrument_pydantic_ai()`. Each question
runs inside a `coach_ask` span. See [`monitoring.md`](monitoring.md).

## Tests

| Test | What it checks |
| --- | --- |
| `tests/test_tools.py` | All nine tools are registered; `TestModel` calls two tools, they are recorded in `tools_used`, and the output validates as `CoachingOutput` |
| `tests/test_api.py` | `/api/coach/ask` with `TestModel` and a selected game returns the model's answer, the tool list, and message history; without a model it returns `used_llm: false` |

No test needs an API key.

## Not PydanticAI

The LLM judge (`judge_evaluation.py`) calls OpenRouter's chat completions endpoint directly and
parses JSON scores. It evaluates analysis explanations against the ground truth dataset, not the
coach agent. See [`evaluation_results.md`](evaluation_results.md).
