from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from .openrouter_client import complete_with_openrouter


JudgeCall = Callable[[str, str], Awaitable[tuple[str, bool]]]


class JudgeCriterion(BaseModel):
    """Evaluation of a single test requirement or behavioral rule."""

    criterion_description: str = Field(
        description="The specific requirement or rule that the agent is being evaluated against."
    )
    passed: bool = Field(
        description="Whether the agent's response and actions satisfied this requirement."
    )
    judgement: str = Field(
        description="Why the agent passed or failed, referencing evidence from output or tool calls."
    )


class JudgeFeedback(BaseModel):
    """Complete evaluation report from the judge agent."""

    criteria: list[JudgeCriterion] = Field(
        description="Individual evaluations for each performance requirement."
    )
    feedback: str = Field(description="Holistic summary of the agent's performance.")


def assert_criteria(feedback: JudgeFeedback, required_passes: list[str]) -> None:
    for description in required_passes:
        match = next(
            (item for item in feedback.criteria if item.criterion_description == description),
            None,
        )
        if match is None or not match.passed:
            raise AssertionError(f"Criterion failed: {description}")


def _parse_feedback(raw: str) -> JudgeFeedback:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Judge did not return a JSON object")
    payload = json.loads(raw[start : end + 1])
    return JudgeFeedback.model_validate(payload)


async def evaluate_agent_run(
    question: str,
    answer: str,
    tools_used: list[str],
    criteria: list[str],
    reviewer_notes: str = "",
    judge: JudgeCall | None = None,
) -> JudgeFeedback:
    judge_fn = judge or _default_judge
    system = (
        "You are an expert judge evaluating a chess coaching agent. "
        "Return JSON only matching this schema: "
        '{"criteria":[{"criterion_description":"...","passed":true,"judgement":"..."}],'
        '"feedback":"..."}. '
        "Each criterion_description must exactly match one provided criterion."
    )
    prompt = (
        f"User question:\n{question}\n\n"
        f"Agent answer:\n{answer}\n\n"
        f"Tools used: {', '.join(tools_used) or 'none'}\n\n"
        f"Reviewer notes:\n{reviewer_notes}\n\n"
        f"Criteria:\n" + "\n".join(f"- {item}" for item in criteria)
    )
    raw, used = await judge_fn(system, prompt)
    if not used:
        raise RuntimeError("OPENROUTER_API_KEY is required for agent judge evaluation")
    return _parse_feedback(raw)


async def _default_judge(system: str, prompt: str) -> tuple[str, bool]:
    return await complete_with_openrouter(system, prompt, temperature=0.0)
