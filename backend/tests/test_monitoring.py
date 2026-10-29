from pathlib import Path

from fastapi.testclient import TestClient

from chess_coach_agent import monitoring
from chess_coach_agent.api import app


def test_feedback_is_visible_in_dashboard_and_exportable(tmp_path: Path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(monitoring, "LOG_PATH", log_path)
    client = TestClient(app)
    response = client.post(
        "/api/feedback",
        json={
            "moment_id": "game-12",
            "game_id": "game",
            "rating": "helpful",
            "theme": "loose_piece",
            "fen": "8/8/8/8/8/8/8/K6k w - - 0 1",
            "comment": "Correctly identified the hanging rook.",
        },
    )
    assert response.status_code == 200
    summary = client.get("/api/monitoring").json()
    assert summary["feedback_count"] == 1
    assert summary["helpful_rate"] == 1.0

    output = tmp_path / "feedback_candidates.jsonl"
    assert monitoring.export_feedback_candidates(output) == 1
    assert '"review_status": "candidate"' in output.read_text(encoding="utf-8")


def test_llm_usage_counts_every_model_backed_event(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitoring, "LOG_PATH", tmp_path / "events.jsonl")
    usage = {"input_tokens": 100, "output_tokens": 20, "estimated_cost_usd": 0.001}
    monitoring.log_event("chat_completed", {"used_llm": True, "usage": {**usage, "requests": 3}})
    monitoring.log_event("coach_answered", {"used_llm": True, "usage": usage})
    monitoring.log_event("coach_answered", {"used_llm": False, "usage": {"input_tokens": 0}})
    # Logged before usage was recorded: counts as a run, but its tokens are unknown.
    monitoring.log_event("coach_answered", {"used_llm": True})
    monitoring.log_event("practice_agent_completed", {"used_llm": True})
    monitoring.log_event("vision_fen", {"usage": usage})
    summary = monitoring.monitoring_summary()
    assert summary["llm_runs"] == 5
    assert summary["llm_calls"] == 3 + 1 + 1 + 1 + 1
    assert summary["llm_runs_without_usage"] == 2
    assert summary["input_tokens"] == 300
    assert summary["output_tokens"] == 60
    assert summary["llm_runs_by_event"]["coach_answered"] == 2
