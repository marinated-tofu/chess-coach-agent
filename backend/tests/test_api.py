from fastapi.testclient import TestClient

from chess_coach_agent.api import app


def test_health_and_sample_endpoints():
    client = TestClient(app)
    assert client.get("/api/health").json()["status"] == "ok"
    sample = client.get("/api/sample").json()
    assert "pgn" in sample
    assert sample["player"] == "kfctofu"


def test_analyze_endpoint_with_sample():
    client = TestClient(app)
    sample = client.get("/api/sample").json()
    response = client.post("/api/analyze", json={"pgn": sample["pgn"], "player": "kfctofu", "max_games": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["analyses"][0]["moments"]


def test_coach_ask_runs_agent_with_selected_game(monkeypatch):
    from pydantic_ai.models.test import TestModel

    from chess_coach_agent import llm

    model = TestModel(
        call_tools=["inspect_critical_moments"],
        custom_output_args={
            "answer": "Check forcing moves first.",
            "evidence": ["Move 12 lost material."],
            "recommended_move": None,
            "principle": "Checks, captures, threats.",
            "drill": "List forcing moves in five positions.",
            "confidence": 0.7,
        },
    )
    monkeypatch.setattr(llm, "_openrouter_model", lambda: model)
    with TestClient(app) as client:
        _ask_about_sample_game(client)


def _ask_about_sample_game(client):
    sample = client.get("/api/sample").json()
    analyzed = client.post(
        "/api/analyze",
        json={"pgn": sample["pgn"], "player": "kfctofu", "max_games": 1, "platform": "pgn"},
    ).json()
    game_id = analyzed["analyses"][0]["game"]["game_id"]

    response = client.post(
        "/api/coach/ask",
        json={"question": "What went wrong?", "platform": "pgn", "username": "kfctofu", "game_id": game_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["used_llm"] is True
    assert payload["answer"] == "Check forcing moves first."
    assert payload["tools_used"] == ["inspect_critical_moments"]
    assert payload["message_history"]
    assert payload["arrows"] == [] and payload["highlights"] == []


def test_coach_ask_falls_back_without_model(monkeypatch):
    from chess_coach_agent import llm

    monkeypatch.setattr(llm, "_openrouter_model", lambda: None)
    with TestClient(app) as client:
        response = client.post("/api/coach/ask", json={"question": "How do I improve?"})
        assert response.status_code == 200
        assert response.json()["used_llm"] is False
        assert response.json()["arrows"] == []
        assert response.json()["highlights"] == []
        assert response.json()["annotations_dropped"] == 0
        feedback = client.post(
            "/api/coach/feedback",
            json={"question": "How do I improve?", "answer": "Scan checks.", "rating": "not_helpful"},
        )
        assert feedback.json() == {"status": "recorded"}
