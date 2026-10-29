#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000/api}"

echo "=== 1. Health ==="
curl -s "$BASE/health"
echo

echo "=== 2. Analyze sample game ==="
SAMPLE_JSON=$(curl -s "$BASE/sample")
PGN=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["pgn"])' "$SAMPLE_JSON")
ANALYZE=$(curl -s -X POST "$BASE/analyze" -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"pgn": sys.argv[1], "player": "kfctofu", "platform": "chess.com", "max_games": 1}))' "$PGN")")
python3 -c '
import json,sys
d=json.loads(sys.argv[1])
m=d["analyses"][0]["moments"][0]
print("moments:", len(d["analyses"][0]["moments"]), "theme:", m["theme"], "id:", m["id"])
' "$ANALYZE"

echo "=== 3. Training session (fallback path) ==="
SESSION=$(curl -s -X POST "$BASE/training/sessions" -H 'Content-Type: application/json' \
  -d '{"platform":"chess.com","username":"kfctofu","position_count":3}')
python3 -c '
import json,sys
d=json.loads(sys.argv[1])
pos=d["positions"][0]
print("session:", d["id"])
print("positions:", len(d["positions"]))
print("prompt:", pos.get("prompt","MISSING")[:100])
print("hint:", pos.get("hint"))
print("choices:", len(pos["choices"]))
' "$SESSION"

echo "=== 4. Exact moment session ==="
MOMENT_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["analyses"][0]["moments"][0]["id"])' "$ANALYZE")
THEME=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["analyses"][0]["moments"][0]["theme"])' "$ANALYZE")
EXACT_BODY=$(python3 - <<PY
import json
print(json.dumps({"platform":"chess.com","username":"kfctofu","theme":"$THEME","moment_id":"$MOMENT_ID","position_count":1}))
PY
)
EXACT=$(curl -s -X POST "$BASE/training/sessions" -H 'Content-Type: application/json' -d "$EXACT_BODY")
python3 -c '
import json,sys
d=json.loads(sys.argv[1])
print("count:", len(d["positions"]), "prompt:", d["positions"][0].get("prompt","")[:60])
' "$EXACT"

echo "=== 5. Theme-filtered session ==="
THEME_BODY=$(python3 - <<PY
import json
print(json.dumps({"platform":"chess.com","username":"kfctofu","theme":"$THEME","position_count":2}))
PY
)
THEME_SESSION=$(curl -s -X POST "$BASE/training/sessions" -H 'Content-Type: application/json' -d "$THEME_BODY")
python3 -c '
import json,sys
d=json.loads(sys.argv[1])
print("themes:", [p["theme"] for p in d["positions"]])
' "$THEME_SESSION"

echo "=== 6. Empty player (no games) ==="
EMPTY=$(curl -s -X POST "$BASE/training/sessions" -H 'Content-Type: application/json' \
  -d '{"platform":"chess.com","username":"brand_new_player_xyz","position_count":3}')
python3 -c '
import json,sys
d=json.loads(sys.argv[1])
print("positions:", len(d.get("positions",[])))
' "$EMPTY"

echo "=== 7. Quiz attempt (legal move) ==="
SID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$SESSION")
PID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["positions"][0]["id"])' "$SESSION")
MOVE=$(python3 -c 'import json,sys; p=json.loads(sys.argv[1])["positions"][0]; print(p["choices"][0] if p["choices"] else "e2e4")' "$SESSION")
ATTEMPT_BODY=$(python3 - <<PY
import json
print(json.dumps({"position_id":"$PID","move":"$MOVE","elapsed_ms":500}))
PY
)
ATTEMPT=$(curl -s -X POST "$BASE/training/sessions/$SID/attempts" -H 'Content-Type: application/json' -d "$ATTEMPT_BODY")
python3 -c '
import json,sys
d=json.loads(sys.argv[1])
print("legal:", d["legal"], "correct:", d["correct"])
' "$ATTEMPT"

echo "=== 8. Illegal move ==="
BAD_BODY=$(python3 - <<PY
import json
print(json.dumps({"position_id":"$PID","move":"Qh9#","elapsed_ms":100}))
PY
)
BAD=$(curl -s -X POST "$BASE/training/sessions/$SID/attempts" -H 'Content-Type: application/json' -d "$BAD_BODY")
python3 -c '
import json,sys
d=json.loads(sys.argv[1])
print("legal:", d["legal"], "correct:", d["correct"])
' "$BAD"

echo "=== 9. Hint attempt ==="
HINT_BODY=$(python3 - <<PY
import json
print(json.dumps({"position_id":"$PID","move":"$MOVE","hints_used":1,"elapsed_ms":400}))
PY
)
HINTED=$(curl -s -X POST "$BASE/training/sessions/$SID/attempts" -H 'Content-Type: application/json' -d "$HINT_BODY")
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print("correct:", d["correct"])' "$HINTED"

echo "=== 10. Monitoring ==="
curl -s "$BASE/monitoring" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("practice_agent_runs:", d.get("practice_agent_runs"))
print("practice_agent_fallback_rate:", d.get("practice_agent_fallback_rate"))
print("practice_agent_completed events:", d.get("event_counts",{}).get("practice_agent_completed",0))
print("training_session_created:", d.get("event_counts",{}).get("training_session_created",0))
'

echo "=== Done ==="
