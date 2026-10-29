#!/usr/bin/env python3
"""Verify OpenRouter wiring for the chess coach practice agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from chess_coach_agent.env_bootstrap import load_project_env
from chess_coach_agent.llm import _openrouter_model
from chess_coach_agent.openrouter_client import complete_with_openrouter_sync, model_name, request_timeout


def _status() -> dict[str, object]:
    configured = bool(os.getenv("OPENROUTER_API_KEY"))
    return {
        "configured": configured,
        "model": model_name() if configured else None,
        "timeout_seconds": request_timeout(),
        "pydantic_agent_ready": _openrouter_model() is not None if configured else False,
    }


def _ping_completion() -> tuple[bool, str]:
    system = "Reply with exactly OK."
    prompt = "Health check."
    raw, used = complete_with_openrouter_sync(system, prompt, temperature=0.0)
    if not used:
        return False, "OpenRouter request failed (no API key or HTTP error)"
    if not raw:
        return False, "OpenRouter returned an empty response"
    return True, raw[:120]


async def _ping_agent() -> tuple[bool, str]:
    from pydantic_ai.models.test import TestModel

    from chess_coach_agent.llm import CoachDependencies, create_coach_agent
    from chess_coach_agent.models import CoachingOutput

    deps = CoachDependencies(platform="lichess", username="verify_llm_user")
    model = TestModel(
        call_tools=["search_chess_principles", "inspect_critical_moments"],
        custom_output_args={
            "answer": "Practice from stored mistakes.",
            "evidence": ["Use grounded moments from sync."],
            "recommended_move": None,
            "principle": "Scan forcing moves first.",
            "drill": "Solve five stored positions.",
            "confidence": 0.8,
        },
    )
    result = await create_coach_agent(model).run("How should I practice from stored mistakes?", deps=deps)
    if not isinstance(result.output, CoachingOutput):
        return False, "Agent did not return CoachingOutput"
    return True, f"tools={deps.tools_used}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    parser.add_argument("--live", action="store_true", help="Also ping OpenRouter with a tiny completion")
    parser.add_argument("--agent", action="store_true", help="Also run the offline TestModel agent smoke check")
    args = parser.parse_args()

    load_project_env()
    report: dict[str, object] = {"status": _status()}

    if args.live:
        ok, detail = _ping_completion()
        report["live_completion"] = {"ok": ok, "detail": detail}

    if args.agent:
        ok, detail = asyncio.run(_ping_agent())
        report["agent_smoke"] = {"ok": ok, "detail": detail}

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = report["status"]
        assert isinstance(status, dict)
        print("LLM status")
        print(f"  configured: {status.get('configured')}")
        print(f"  model: {status.get('model')}")
        print(f"  timeout_seconds: {status.get('timeout_seconds')}")
        print(f"  pydantic_agent_ready: {status.get('pydantic_agent_ready')}")
        if "live_completion" in report:
            live = report["live_completion"]
            assert isinstance(live, dict)
            print(f"  live_completion: {'ok' if live.get('ok') else 'FAILED'} ({live.get('detail')})")
        if "agent_smoke" in report:
            smoke = report["agent_smoke"]
            assert isinstance(smoke, dict)
            print(f"  agent_smoke: {'ok' if smoke.get('ok') else 'FAILED'} ({smoke.get('detail')})")

    failures = []
    status = report["status"]
    assert isinstance(status, dict)
    if not status.get("configured"):
        failures.append("OPENROUTER_API_KEY missing (set backend/.env)")
    if args.live and report.get("live_completion", {}).get("ok") is not True:
        failures.append("live OpenRouter completion failed")
    if args.agent and report.get("agent_smoke", {}).get("ok") is not True:
        failures.append("agent smoke check failed")

    if failures:
        if not args.json:
            print("\nFix:")
            for item in failures:
                print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
