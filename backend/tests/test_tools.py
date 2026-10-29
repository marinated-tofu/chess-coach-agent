import pytest
from pydantic_ai.models.test import TestModel

from chess_coach_agent.llm import CoachDependencies, create_coach_agent
from chess_coach_agent.models import CoachingOutput


@pytest.mark.asyncio
async def test_agent_executes_registered_tools_and_returns_structured_output():
    deps = CoachDependencies()
    model = TestModel(
        call_tools=["search_chess_principles", "inspect_critical_moments"],
        custom_output_args={
            "answer": "Scan forcing moves first.",
            "evidence": ["The tactical-vision note prioritizes checks and captures."],
            "recommended_move": None,
            "principle": "Checks, captures, threats.",
            "drill": "List all forcing moves in five positions.",
            "confidence": 0.8,
        },
    )

    result = await create_coach_agent(model).run("How should I find tactics?", deps=deps)

    assert isinstance(result.output, CoachingOutput)
    assert result.output.confidence == 0.8
    assert set(deps.tools_used) == {"search_chess_principles", "inspect_critical_moments"}


def test_agent_exposes_all_chess_coaching_tools():
    model = TestModel(call_tools=[])
    agent = create_coach_agent(model)
    tool_names = set(agent._function_toolset.tools)
    assert tool_names == {
        "search_chess_principles",
        "inspect_critical_moments",
        "inspect_player_moments",
        "inspect_position",
        "build_training_drill",
        "inspect_game",
        "compare_moves",
        "rank_practice_moments",
        "generate_position_quiz",
        "evaluate_candidate_move",
        "build_training_session",
        "write_quiz_copy",
    }
