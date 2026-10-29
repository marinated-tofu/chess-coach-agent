from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


LOG_PATH = Path(
    os.getenv(
        "MONITORING_LOG_PATH",
        str(Path(__file__).resolve().parents[2] / "data" / "logs" / "events.jsonl"),
    )
)


def log_event(event_type: str, payload: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        **payload,
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")


def read_events() -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    events = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _used_llm(event: dict[str, Any]) -> bool:
    if event.get("used_llm"):
        return True
    usage = event.get("usage") or {}
    return bool(usage.get("input_tokens") or usage.get("output_tokens"))


def monitoring_summary() -> dict[str, Any]:
    events = read_events()
    event_counts = Counter(event.get("event_type", "unknown") for event in events)
    feedback = [
        event for event in events if event.get("event_type") in {"moment_feedback", "coach_feedback"}
    ]
    chats = [
        event for event in events if event.get("event_type") in {"chat_completed", "coach_answered"}
    ]
    # Every model-backed event counts, not only chat answers: coach turns, practice agent runs
    # and board-image reads (vision_fen) call the model too and log their own usage.
    llm_events = [event for event in events if _used_llm(event)]
    usages = [event.get("usage") or {} for event in llm_events]
    helpful = sum(event.get("rating") == "helpful" for event in feedback)
    themes = Counter(event.get("theme") for event in feedback if event.get("theme"))
    practice_agent_runs = [
        event for event in events if event.get("event_type") == "practice_agent_completed"
    ]
    practice_fallbacks = sum(bool(event.get("fallback")) for event in practice_agent_runs)
    practice_tools = Counter(
        tool for event in practice_agent_runs for tool in event.get("tools_used", [])
    )
    tool_usage = Counter(tool for event in chats for tool in event.get("tools_used", []))
    tool_usage.update(practice_tools)
    input_tokens = sum((event.get("usage") or {}).get("input_tokens", 0) for event in chats)
    output_tokens = sum((event.get("usage") or {}).get("output_tokens", 0) for event in chats)
    estimated_cost = sum((event.get("usage") or {}).get("estimated_cost_usd", 0) for event in chats)
    input_tokens = sum(int(usage.get("input_tokens") or 0) for usage in usages)
    output_tokens = sum(int(usage.get("output_tokens") or 0) for usage in usages)
    estimated_cost = sum(float(usage.get("estimated_cost_usd") or 0) for usage in usages)
    # Older events (and some code paths) recorded that the model ran but not what it used.
    untracked = sum(
        not (usage.get("input_tokens") or usage.get("output_tokens")) for usage in usages
    )
    chat_latency = [event.get("duration_ms", 0) for event in chats if event.get("duration_ms") is not None]
    attempts = [event for event in events if event.get("event_type") == "quiz_attempted"]
    training_sessions = [
        event for event in events if event.get("event_type") == "training_session_created"
    ]
    stream_failures = event_counts["stream_failed"]
    correct_attempts = sum(bool(event.get("correct")) for event in attempts)
    hinted_attempts = sum(int(event.get("hints_used", 0)) > 0 for event in attempts)
    retrieval_methods = Counter(
        event.get("method", "unknown")
        for event in events
        if event.get("event_type") == "retrieval_completed"
    )
    memory_retrievals = [
        event for event in events if event.get("event_type") == "memory_retrieved"
    ]
    return {
        "total_events": len(events),
        "event_counts": dict(event_counts),
        "feedback_count": len(feedback),
        "helpful_rate": round(helpful / len(feedback), 3) if feedback else None,
        "feedback_themes": dict(themes),
        # A run can make several model requests (tool calls); usage.requests counts them.
        "llm_calls": sum(int(usage.get("requests") or 1) for usage in usages),
        "llm_runs": len(llm_events),
        "llm_runs_without_usage": untracked,
        "llm_runs_by_event": dict(Counter(event.get("event_type", "unknown") for event in llm_events)),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(estimated_cost, 8),
        "average_chat_latency_ms": round(sum(chat_latency) / len(chat_latency), 2) if chat_latency else None,
        "tool_usage": dict(tool_usage),
        "stream_failures": stream_failures,
        "training_sessions": len(training_sessions),
        "quiz_attempts": len(attempts),
        "quiz_accuracy": round(correct_attempts / len(attempts), 3) if attempts else None,
        "hint_use_rate": round(hinted_attempts / len(attempts), 3) if attempts else None,
        "retrieval_methods": dict(retrieval_methods),
        "memory_retrievals": len(memory_retrievals),
        "practice_agent_runs": len(practice_agent_runs),
        "practice_agent_fallback_rate": round(
            practice_fallbacks / len(practice_agent_runs), 3
        )
        if practice_agent_runs
        else None,
        "recent_events": list(reversed(events[-8:])),
    }


def export_feedback_candidates(output: Path) -> int:
    candidates = []
    for event in read_events():
        if event.get("event_type") == "coach_feedback" and event.get("rating") == "not_helpful":
            candidates.append(
                {
                    "id": f"coach-feedback-{event.get('timestamp', 'unknown')}",
                    "question": event.get("question", ""),
                    "fen": event.get("fen"),
                    "game_id": event.get("game_id"),
                    "rejected_answer": event.get("answer", ""),
                    "source": "coach_feedback",
                    "review_status": "candidate",
                }
            )
            continue
        if event.get("event_type") != "moment_feedback" or not event.get("fen"):
            continue
        candidates.append(
            {
                "id": f"feedback-{event.get('moment_id', 'unknown')}",
                "fen": event["fen"],
                "expected_theme": event.get("theme", "unknown"),
                "rating": event.get("rating"),
                "reviewer_notes": event.get("comment", ""),
                "source": "monitoring_feedback",
                "review_status": "candidate",
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row) + "\n" for row in candidates), encoding="utf-8")
    return len(candidates)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--export-candidates", type=Path)
    args = parser.parse_args()
    if args.export_candidates:
        count = export_feedback_candidates(args.export_candidates)
        print(json.dumps({"exported": count, "path": str(args.export_candidates)}, indent=2))
    else:
        print(json.dumps(monitoring_summary(), indent=2))


if __name__ == "__main__":
    main()
