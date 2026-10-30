import os
import tempfile
from pathlib import Path


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="chess-coach-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATA_DIR / 'test.db'}"
os.environ.setdefault("MONITORING_LOG_PATH", str(TEST_DATA_DIR / "events.jsonl"))
# Every test shares the TestClient address, so a low limit would make them fail in sequence.
for feature in ("COACH", "PRACTICE", "STUDY_PLAN", "VISION"):
    os.environ[f"{feature}_DAILY_LIMIT_ANONYMOUS"] = "100000"

from chess_coach_agent.db import init_db  # noqa: E402

init_db()
