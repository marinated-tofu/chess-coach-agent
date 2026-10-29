# Monitoring

Monitoring has two layers:

1. **JSONL event log.** The API appends one JSON object per event to `MONITORING_LOG_PATH`
   (default `backend/data/logs/events.jsonl`). This works locally with no account or token.
2. **Logfire traces.** `llm.py` calls `logfire.instrument_pydantic_ai()`. When `LOGFIRE_TOKEN` is
   set, every coach question is traced: the `coach_ask` span, each model request, and each tool
   call with its arguments and result. Failed or timed-out runs log a `coach_ask_failed` warning.
   Without a token nothing is sent.

## Events

| Event | Logged when | Main fields |
| --- | --- | --- |
| `analysis_requested`, `analysis_timing` | PGN is pasted and analyzed | player, game count, duration |
| `analysis_completed` | A game finishes analysis | game, moment, and theme counts |
| `games_sync_completed`, `games_sync_failed` | A full-history sync job ends | job ID, counts or error |
| `training_session_created` | A practice session starts | session ID, positions, difficulty |
| `practice_agent_completed` | The practice agent builds a session | `used_llm`, `fallback`, `tools_used`, `duration_ms` |
| `quiz_attempted` | A practice move is graded | correct, legal, hints used |
| `moment_feedback` | A user rates a critical moment | moment ID, game ID, theme, FEN, rating, comment |
| `coach_answered` | The coach answers a question | player, game ID, `used_llm`, tools called |

`used_llm: false` on `coach_answered` means the deterministic fallback answered (no API key,
error, or timeout), so the fallback rate can be read straight from the log.

## Dashboard

The `/quality` page in the React app calls `GET /api/monitoring`, which reads the JSONL log and
returns a summary. It shows total events, completed analyses, feedback count and helpful rate,
training sessions, quiz accuracy, hint use, and a bar chart of every event type, including
`coach_answered`. Older fields from the retired chat prototype (LLM calls, tokens, cost) are still
read from old logs and show 0 for new data.

Print the same summary from the command line:

```bash
cd backend
uv run python -m chess_coach_agent.monitoring --summary
```

To send traces to Logfire, create a project token and set it before starting the API:

```bash
export LOGFIRE_TOKEN=...
uv run uvicorn chess_coach_agent.api:app --host 127.0.0.1 --port 8000
```

## User feedback

Each critical moment on the game review page has helpful and not-helpful buttons.
`POST /api/feedback` records the moment ID, game ID, detected theme, position FEN, rating, and
optional comment. The dashboard shows it on the next refresh.

## Logs to evaluation candidates

Convert feedback events into a review queue:

```bash
cd backend
uv run python -m chess_coach_agent.monitoring \
  --export-candidates data/eval/feedback_candidates.jsonl
```

Each exported row has the FEN, expected theme, rating, and the user's comment as reviewer notes,
the same shape as `critical_moments.jsonl`. Every row is marked `review_status: candidate`. A person
checks it and adds a PGN before it joins the ground truth set; after that, `make eval` and
`make eval-llm` include it. Noisy ratings never become ground truth automatically.

## Deployment note

On Render's free plan the log lives in `/tmp`, so the dashboard resets on restart or redeploy.
Attach a disk and point `MONITORING_LOG_PATH` at it to keep history.
