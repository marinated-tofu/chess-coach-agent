import os
import tempfile
from pathlib import Path


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="chess-coach-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATA_DIR / 'test.db'}"
os.environ.setdefault("MONITORING_LOG_PATH", str(TEST_DATA_DIR / "events.jsonl"))

from chess_coach_agent.db import init_db  # noqa: E402

init_db()
