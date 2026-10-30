"""The readiness route and structured logging of unhandled exceptions."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from chess_coach_agent import health
from chess_coach_agent.api import app
from chess_coach_agent.monitoring import JsonFormatter

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_cached_result(monkeypatch):
    monkeypatch.setattr(health, "_stockfish_result", None)


def test_ready_passes_when_both_checks_pass(monkeypatch):
    monkeypatch.setattr(health, "_start_stockfish", lambda: True)
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "stockfish": "ok"},
    }


def test_ready_fails_without_stockfish(monkeypatch):
    monkeypatch.setattr(health, "stockfish_path", lambda: None)
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "stockfish": "failed"}


def test_ready_fails_when_the_engine_will_not_start(monkeypatch):
    monkeypatch.setattr(health, "stockfish_path", lambda: "/nonexistent/stockfish")
    assert client.get("/api/health/ready").status_code == 503


def test_ready_fails_without_the_database_and_hides_why(monkeypatch):
    def down():
        raise RuntimeError("postgresql://user:hunter2@db/secret is unreachable")

    monkeypatch.setattr(health, "_start_stockfish", lambda: True)
    monkeypatch.setattr(health, "check_database", down)
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "failed"
    assert "hunter2" not in response.text


def test_stockfish_check_is_cached(monkeypatch):
    starts = []
    monkeypatch.setattr(health, "_start_stockfish", lambda: starts.append(1) or True)
    assert health.check_stockfish() and health.check_stockfish()
    assert len(starts) == 1


def test_formatter_writes_one_json_line_with_severity_and_stack():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "app", logging.ERROR, __file__, 1, "Unhandled %s", ("exception",), sys.exc_info()
        )
    record.fields = {"path": "/api/x"}
    line = JsonFormatter().format(record)
    assert "\n" not in line
    entry = json.loads(line)
    assert entry["severity"] == "ERROR"
    assert entry["message"] == "Unhandled exception"
    assert entry["path"] == "/api/x"
    assert entry["error_type"] == "ValueError"
    assert "boom" in entry["stack_trace"]


def test_unhandled_exception_is_logged_and_returns_a_plain_500(monkeypatch, caplog):
    def explode():
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr("chess_coach_agent.api.monitoring_summary", explode)
    quiet = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="chess_coach_agent.api"):
        response = quiet.get("/api/monitoring?secret=abc")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert "hunter2" not in response.text

    record = next(item for item in caplog.records if item.message == "Unhandled exception")
    assert record.fields == {"method": "GET", "path": "/api/monitoring"}
    assert record.exc_info[0] is RuntimeError
