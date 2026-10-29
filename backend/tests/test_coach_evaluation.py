import asyncio
import json
from pathlib import Path

from pydantic_ai.models.test import TestModel

from chess_coach_agent import coach_evaluation
from chess_coach_agent.coach_evaluation import (
    PROMPT_VARIANTS,
    deterministic_checks,
    format_summary,
    judge_answer,
    load_rows,
    normalize_move,
    run_coach_eval,
)
from chess_coach_agent.llm import COACH_INSTRUCTIONS, create_coach_agent
from chess_coach_agent.models import CoachAskResponse, CoachingOutput


DATASET = Path("data/eval/coach_questions.jsonl")


def _response(recommended: str | None, *, tools: list[str] | None = None) -> CoachAskResponse:
    coaching = CoachingOutput(
        answer="Qe2 walked into Nxe2+ from the knight on d4. Qh5+ was the engine move.",
        evidence=["inspect_position: best move Qh5+ (+0.6)"],
        recommended_move=recommended,
        principle="Check which enemy pieces attack the destination square.",
        drill="Set up five positions from this game and list every knight attack first.",
        confidence=0.8,
    )
    return CoachAskResponse(
        answer=coaching.answer,
        coaching=coaching,
        used_llm=True,
        tools_used=tools if tools is not None else ["inspect_position"],
    )


def _row(row_id: str) -> dict:
    return next(row for row in load_rows(DATASET) if row["id"] == row_id)


def test_dataset_rows_are_well_formed_and_moves_legal():
    rows = load_rows(DATASET)
    assert 12 <= len(rows) <= 20
    assert len({row["id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["question"] and row["key_points"] and row["theme_keywords"]
        for move in row["expected_moves"] + row["forbidden_moves"]:
            assert normalize_move(row["fen"], move) is not None, (row["id"], move)


def test_normalize_move_accepts_annotations_numbers_and_uci():
    fen = _row("g0_m13_queen_loss")["fen"]
    assert normalize_move(fen, "13.Qh5+") == "Qh5+"
    assert normalize_move(fen, "Qh5!") == "Qh5+"
    assert normalize_move(fen, "d1h5") == "Qh5+"
    assert normalize_move(fen, "Qh7") is None
    assert normalize_move(None, "Qh5+") is None


def test_deterministic_checks_reward_expected_move_and_flag_forbidden_move():
    row = _row("g0_m13_queen_loss")
    good = deterministic_checks(row, _response("Qh5+"))
    assert good["checks"]["expected_move"] is True
    assert good["checks"]["avoids_forbidden_move"] is True
    assert good["score"] == 1.0

    bad = deterministic_checks(row, _response("Qe2", tools=[]))
    assert bad["checks"]["expected_move"] is False
    assert bad["checks"]["avoids_forbidden_move"] is False
    assert bad["checks"]["used_tool"] is False
    assert bad["score"] < 1.0

    missing = deterministic_checks(row, _response(None))
    assert missing["checks"]["move_legal"] is False


def test_judge_answer_clamps_scores_and_retries_bad_json():
    calls = []

    async def flaky_judge(_system: str, _prompt: str) -> tuple[str, bool]:
        calls.append(1)
        if len(calls) == 1:
            return "not json", True
        return json.dumps(
            {"grounded_score": 5, "correctness_score": 2, "drill_score": 1, "no_invention_score": -1}
        ), True

    result = asyncio.run(judge_answer(_row("g0_m13_queen_loss"), _response("Qh5+"), flaky_judge))
    assert len(calls) == 2
    assert result["grounded_score"] == 2 and result["no_invention_score"] == 0
    assert result["total"] == 5 and result["pass"] is False


def test_create_coach_agent_accepts_custom_instructions():
    default_agent = create_coach_agent(TestModel())
    custom_agent = create_coach_agent(TestModel(), instructions="Be brief.")
    assert COACH_INSTRUCTIONS in default_agent._instructions  # noqa: SLF001
    assert "Be brief." in custom_agent._instructions  # noqa: SLF001


def test_run_coach_eval_with_test_model_and_fake_judge(monkeypatch):
    seen_prompts: list[str] = []

    async def fake_judge(_system: str, prompt: str) -> tuple[str, bool]:
        seen_prompts.append(prompt)
        good = "Recommended move: Qh5+" in prompt
        score = 2 if good else 1
        payload = {name: score for name in coach_evaluation.JUDGE_FIELDS}
        return json.dumps({**payload, "reason": "fixture"}), True

    captured: list[str | None] = []
    original_ask = coach_evaluation.ask_coach

    async def spy_ask(*args, **kwargs):
        captured.append(kwargs.get("instructions"))
        return await original_ask(*args, **kwargs)

    monkeypatch.setattr(coach_evaluation, "ask_coach", spy_ask)
    model = TestModel(
        call_tools=["inspect_critical_moments", "search_chess_principles"],
        custom_output_args={
            "answer": "Qe2 let the d4 knight take with check. Play Qh5+ instead.",
            "evidence": ["Critical moment: move 13 Qe2, engine candidate Qh5+"],
            "recommended_move": "Qh5+",
            "principle": "Before a queen move, list every enemy piece that attacks the square.",
            "drill": "Replay moves 10-13 and name each knight attack before moving.",
            "confidence": 0.7,
        },
    )
    result = asyncio.run(
        run_coach_eval(
            DATASET,
            ("baseline", "evidence_first"),
            limit=2,
            judge=fake_judge,
            model=model,
            concurrency=2,
        )
    )

    assert result["dataset_size"] == 2
    assert set(captured) == {PROMPT_VARIANTS["baseline"], PROMPT_VARIANTS["evidence_first"]}
    assert len(result["runs"]) == 2
    for run in result["runs"].values():
        first = run["details"][0]
        assert sorted(first["tools_used"]) == ["inspect_critical_moments", "search_chess_principles"]
        assert first["deterministic"]["checks"]["used_llm"] is True
        assert first["deterministic"]["checks"]["expected_move"] is True
        assert first["judge"]["total"] == 8
        # Row 2 expects Qh5+ too, so the fixed answer passes there as well.
        assert run["summary"]["judge_pass_rate"] == 1.0
    assert len(seen_prompts) == 4
    assert "Key points:" in seen_prompts[0]
    assert "Winner:" in format_summary(result)
