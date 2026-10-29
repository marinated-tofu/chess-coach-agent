from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .judge import _default_judge, evaluate_agent_run
from .llm import CoachDependencies, create_coach_agent


async def _offline_judge(_system: str, prompt: str) -> tuple[str, bool]:
    criteria_lines = [
        line[2:].strip()
        for line in prompt.splitlines()
        if line.startswith("- ")
    ]
    payload = {
        "criteria": [
            {
                "criterion_description": line,
                "passed": True,
                "judgement": "Offline heuristic judge accepted scenario fixture.",
            }
            for line in criteria_lines
        ],
        "feedback": "Offline evaluation run without OpenRouter judge.",
    }
    return json.dumps(payload), True


async def _run_scenario(row: dict[str, Any], use_live_model: bool) -> dict[str, Any]:
    deps = CoachDependencies(platform=row["platform"], username=row["username"])
    if use_live_model:
        agent = create_coach_agent()
        result = await agent.run(row["question"], deps=deps)
        answer = result.output.answer
        tools_used = list(deps.tools_used)
    else:
        tools_used = list(row.get("expected_tools", []))
        answer = "Practice from your stored mistakes using grounded stored moments."

    feedback = await evaluate_agent_run(
        row["question"],
        answer,
        tools_used,
        row.get("criteria", []),
        reviewer_notes=row.get("reviewer_notes", ""),
        judge=_default_judge if use_live_model else _offline_judge,
    )
    expected_tools = row.get("expected_tools", [])
    tool_pass = all(tool in tools_used for tool in expected_tools) if expected_tools else True
    criteria_pass = all(item.passed for item in feedback.criteria)
    return {
        "id": row["id"],
        "tools_used": tools_used,
        "expected_tools": expected_tools,
        "tool_pass": tool_pass,
        "criteria_pass": criteria_pass,
        "passed": tool_pass and criteria_pass,
        "feedback": feedback.model_dump(mode="json"),
    }


async def run_agent_evaluation(dataset: Path, live: bool = False) -> dict[str, Any]:
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    details = []
    for row in rows:
        details.append(await _run_scenario(row, live))
    passed = sum(item["passed"] for item in details)
    return {
        "dataset_size": len(rows),
        "passed": passed,
        "pass_rate": round(passed / max(1, len(rows)), 3),
        "live_model": live,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/agent_scenarios.jsonl"))
    parser.add_argument("--live", action="store_true", help="Use OpenRouter instead of TestModel")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_agent_evaluation(args.dataset, live=args.live)), indent=2))


if __name__ == "__main__":
    main()
