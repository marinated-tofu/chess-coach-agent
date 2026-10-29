from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .agent import ChessCoachAgent
from .openrouter_client import complete_with_openrouter


JudgeCall = Callable[[str, str], Awaitable[tuple[str, bool]]]


def _candidate_text(response: Any, variant: str) -> str:
    analysis = response.analyses[0]
    if not analysis.moments:
        if variant == "concise":
            return "No move crossed the calibrated winning-chance-loss threshold."
        return (
            "Theme: no engine-significant error\n"
            "Played move: unavailable\n"
            "Recommended move: unavailable\n"
            "What happened: no move crossed the calibrated threshold\n"
            "Principle: do not manufacture a mistake from a quiet position\n"
            "Drill: none; send this fixture for human review"
        )
    moment = analysis.moments[0]
    if variant == "concise":
        return f"Theme: {moment.theme}. {moment.summary}"
    return (
        f"Theme: {moment.theme}\n"
        f"Played move: {moment.played_san}\n"
        f"Recommended move: {moment.best_san or 'candidate move unavailable'}\n"
        f"What happened: {moment.what_happened}\n"
        f"Principle: {moment.principle}\n"
        f"Drill: {moment.drill_prompt}"
    )


def _parse_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Judge did not return a JSON object")
    return json.loads(text[start : end + 1])


async def _default_judge(system: str, prompt: str) -> tuple[str, bool]:
    return await complete_with_openrouter(system, prompt, temperature=0.0)


async def run_llm_judge(
    dataset: Path,
    variants: tuple[str, ...] = ("grounded",),
    judge: JudgeCall = _default_judge,
) -> dict[str, Any]:
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    agent = ChessCoachAgent()
    variant_results: dict[str, Any] = {}
    for variant in variants:
        details = []
        total_score = 0
        for row in rows:
            response = agent.import_pgn_text(row["pgn"], player=row["player"], max_games=1)
            candidate = _candidate_text(response, variant)
            system = (
                "You are an impartial chess-coaching evaluator. Compare the candidate with the "
                "human-written ground truth. Return JSON only with integer fields theme_score, "
                "grounding_score, coaching_score (each 0, 1, or 2), plus a short reason."
            )
            prompt = (
                f"Expected theme: {row['expected_theme']}\n"
                f"Human reviewer notes: {row['reviewer_notes']}\n\n"
                f"Candidate coaching output:\n{candidate}"
            )
            raw, used_llm = await judge(system, prompt)
            if not used_llm:
                raise RuntimeError("OPENROUTER_API_KEY is required for LLM judge evaluation")
            scores = _parse_json(raw)
            score = sum(int(scores.get(name, 0)) for name in ("theme_score", "grounding_score", "coaching_score"))
            total_score += score
            details.append(
                {
                    "id": row["id"],
                    "score": score,
                    "max_score": 6,
                    "reason": scores.get("reason", ""),
                    "candidate": candidate,
                }
            )
        variant_results[variant] = {
            "average_score": round(total_score / max(1, len(rows)), 3),
            "pass_rate": round(sum(item["score"] >= 4 for item in details) / max(1, len(details)), 3),
            "details": details,
        }
    winner = max(variant_results, key=lambda name: variant_results[name]["average_score"])
    return {"dataset_size": len(rows), "winner": winner, "variants": variant_results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/critical_moments.jsonl"))
    parser.add_argument("--tune", action="store_true", help="Compare concise and grounded answer formats")
    args = parser.parse_args()
    variants = ("concise", "grounded") if args.tune else ("grounded",)
    print(json.dumps(asyncio.run(run_llm_judge(args.dataset, variants=variants)), indent=2))


if __name__ == "__main__":
    main()
