import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from chess_coach_agent.agent_evaluation import _offline_judge, run_agent_evaluation
from chess_coach_agent.judge import JudgeFeedback, assert_criteria, evaluate_agent_run
from chess_coach_agent.llm import CoachDependencies, create_coach_agent
from chess_coach_agent.models import CoachingOutput


async def fake_judge(_system: str, prompt: str) -> tuple[str, bool]:
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
                "judgement": "Structured judge fixture",
            }
            for line in criteria_lines
        ],
        "feedback": "Fixture judge completed.",
    }
    return json.dumps(payload), True


@pytest.mark.asyncio
async def test_judge_feedback_parses_structured_output():
    feedback = await evaluate_agent_run(
        "Give me practice.",
        "Let's drill your stored mistakes.",
        ["inspect_player_moments", "build_training_session"],
        ["Creates a training session from stored games rather than inventing positions"],
        judge=fake_judge,
    )
    assert isinstance(feedback, JudgeFeedback)
    assert feedback.criteria
    assert_criteria(
        feedback,
        ["Creates a training session from stored games rather than inventing positions"],
    )


@pytest.mark.asyncio
async def test_agent_executes_practice_tools_with_test_model():
    deps = CoachDependencies(platform="chess.com", username="kfctofu")
    model = TestModel(
        call_tools=["inspect_player_moments", "build_training_session"],
        custom_output_args={
            "answer": "Practice from your stored mistakes.",
            "evidence": ["Stored critical moments were inspected."],
            "recommended_move": None,
            "principle": "Scan forcing moves first.",
            "drill": "Replay the selected positions.",
            "confidence": 0.8,
        },
    )
    result = await create_coach_agent(model).run("Build my next practice session.", deps=deps)
    assert isinstance(result.output, CoachingOutput)
    assert deps.tools_used == ["inspect_player_moments", "build_training_session"]


def test_agent_evaluation_offline_fixture_passes():
    result = asyncio.run(
        run_agent_evaluation(Path("data/eval/agent_scenarios.jsonl"), live=False)
    )
    assert result["dataset_size"] >= 10
    assert result["pass_rate"] == 1.0


def test_offline_judge_returns_json():
    raw, used = asyncio.run(
        _offline_judge("system", "Criteria:\n- Uses build_training_session when the user asks to practice")
    )
    assert used is True
    payload = json.loads(raw)
    assert payload["criteria"][0]["passed"] is True
