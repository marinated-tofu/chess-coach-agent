"""Offline evaluation of live coach answers.

Each row in ``coach_questions.jsonl`` pairs a player question with a sample game and/or a FEN and
Stockfish-verified expected facts. The coach agent answers the question, then every answer is scored
twice: deterministic checks (legal recommended move, expected move, theme, tool use) and an LLM judge
rubric. Running more than one ``--prompt-variant`` compares system prompts on the same rows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

import chess
import httpx
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from .agent import ChessCoachAgent, sample_pgn
from .llm import OPENROUTER_BASE_URL, OPENROUTER_URL, _model_name, ask_coach
from .models import CoachAnalysis, CoachAskResponse


JudgeCall = Callable[[str, str], Awaitable[tuple[str, bool]]]

# The coach prompt before evaluation-driven tuning. Kept verbatim so the comparison is reproducible.
BASELINE_INSTRUCTIONS = dedent(
    """
    You are a precise chess improvement coach. Relevant player memory and game positions may
    already be included in the verified context. Use tools only when the question needs evidence
    not already present; do not call tools merely to satisfy a quota.
    Treat engine evaluations, legal moves, and supplied game facts as evidence; never invent a
    variation or claim a move is forced without support. Separate what the player did from the
    reusable lesson. Give one manageable drill. When the user asks to practice, create a position
    quiz or training session from their stored games. Use saved-game tools instead of inventing
    positions. Return the requested structured coaching object.
    """
).strip()

EVIDENCE_FIRST_INSTRUCTIONS = dedent(
    """
    You are a precise chess improvement coach talking to a club player about their own games.
    Ground every claim before you answer:
    - When the question is about a specific position or move, call inspect_position on that FEN,
      or compare_moves with the moves in question, before answering. Set recommended_move to a
      legal SAN move in the position under discussion, normally the engine's best move from the
      tool output. Leave it empty when you have no engine evidence for a move.
    - Quote the engine numbers you received (for example "+1.6") and name the concrete reason:
      which piece was attacked, undefended, pinned, or forked.
    - Only write move sequences that appear in tool output or the supplied critical moments.
      Never invent a variation or claim a move is forced without support.
    - Put each fact you relied on in evidence, one per item.
    Separate what the player did from the reusable lesson in principle. Give one drill the player
    can do today, tied to this position or theme, with a concrete count (for example five
    positions). When the user asks to practice, create a position quiz or training session from
    their stored games instead of inventing positions. Return the requested structured coaching
    object.
    """
).strip()

PROMPT_VARIANTS: dict[str, str] = {
    "baseline": BASELINE_INSTRUCTIONS,
    "evidence_first": EVIDENCE_FIRST_INSTRUCTIONS,
}

JUDGE_FIELDS = ("grounded_score", "correctness_score", "drill_score", "no_invention_score")
JUDGE_MAX = 2 * len(JUDGE_FIELDS)
JUDGE_PASS = 6

JUDGE_SYSTEM = dedent(
    """
    You are an impartial chess-coaching evaluator. You receive a player's question, a
    Stockfish-verified reference, human-written key points, statements the answer must not make,
    and the coach's structured answer. The coach's engine tool runs at a lower depth than the
    reference, so evaluations within about 0.7 pawns of the reference count as matching; judge the
    moves, the direction of the evaluation, and the reason, not exact numbers.
    Score four criteria with 0, 1, or 2:
    - grounded_score: 2 if the claims rest on concrete facts (engine numbers, named pieces and
      squares, the supplied game) that match the reference; 1 if partly; 0 if generic or unsupported.
    - correctness_score: 2 if the answer agrees with the key points; 1 if partly right or it misses
      the main point; 0 if it makes any statement listed under "must not".
    - drill_score: 2 if the drill is specific to this position or theme and doable today; 1 if
      generic; 0 if missing or unrelated.
    - no_invention_score: 2 if every move sequence quoted is in the reference or is a single legal
      move; 1 if it adds unverified but plausible moves; 0 if it states a variation or tactic that
      contradicts the reference.
    Return JSON only: {"grounded_score": int, "correctness_score": int, "drill_score": int,
    "no_invention_score": int, "reason": "one or two sentences"}.
    """
).strip()


def load_rows(dataset: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def load_game_contexts(rows: list[dict[str, Any]], pgn_text: str | None = None) -> dict[str, CoachAnalysis]:
    """Analyze the sample PGN the same way /api/analyze does and index analyses by game id."""
    needed = {row["game_id"] for row in rows if row.get("game_id")}
    if not needed:
        return {}
    players = {row["player"] for row in rows if row.get("game_id")}
    agent = ChessCoachAgent()
    contexts: dict[str, CoachAnalysis] = {}
    for player in players:
        response = agent.import_pgn_text(pgn_text or sample_pgn(), player=player, max_games=100)
        for analysis in response.analyses:
            if analysis.game.game_id in needed:
                contexts[analysis.game.game_id] = analysis
    missing = needed - contexts.keys()
    if missing:
        raise ValueError(f"Games not found in the sample PGN: {sorted(missing)}")
    return contexts


def _clean_san(move: str) -> str:
    move = re.sub(r"^\d+\.(\.\.)?\s*", "", move.strip())
    return move.rstrip("!?").strip()


def normalize_move(fen: str | None, move: str | None) -> str | None:
    """Return the SAN of ``move`` in ``fen`` or None when it is missing or illegal."""
    if not fen or not move:
        return None
    board = chess.Board(fen)
    text = _clean_san(move)
    try:
        return board.san(board.parse_san(text))
    except ValueError:
        try:
            parsed = chess.Move.from_uci(text)
        except ValueError:
            return None
        return board.san(parsed) if parsed in board.legal_moves else None


def deterministic_checks(row: dict[str, Any], response: CoachAskResponse) -> dict[str, Any]:
    coaching = response.coaching
    checks: dict[str, bool | None] = {
        "used_llm": response.used_llm,
        "used_tool": bool(response.tools_used),
    }
    fen = row.get("fen")
    recommended = normalize_move(fen, coaching.recommended_move)
    expected = {normalize_move(fen, move) for move in row.get("expected_moves", [])}
    forbidden = {normalize_move(fen, move) for move in row.get("forbidden_moves", [])}
    if fen and coaching.recommended_move:
        checks["move_legal"] = recommended is not None
    elif fen and expected:
        checks["move_legal"] = False
    else:
        checks["move_legal"] = None
    checks["expected_move"] = (recommended in expected) if expected else None
    checks["avoids_forbidden_move"] = (recommended not in forbidden) if forbidden and recommended else None
    text = " ".join([coaching.answer, coaching.principle, coaching.drill, *coaching.evidence]).lower()
    checks["theme_mentioned"] = any(word.lower() in text for word in row.get("theme_keywords", []))
    applicable = [value for value in checks.values() if value is not None]
    return {
        "checks": checks,
        "recommended_move": coaching.recommended_move,
        "passed": sum(applicable),
        "applicable": len(applicable),
        "score": round(sum(applicable) / max(1, len(applicable)), 3),
    }


def _parse_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Judge did not return a JSON object")
    return json.loads(text[start : end + 1])


def judge_prompt(row: dict[str, Any], response: CoachAskResponse) -> str:
    coaching = response.coaching
    key_points = "\n".join(f"- {point}" for point in row.get("key_points", []))
    must_not = "\n".join(f"- {point}" for point in row.get("must_not", [])) or "- none"
    evidence = "\n".join(f"- {item}" for item in coaching.evidence) or "- none"
    return (
        f"Player question: {row['question']}\n"
        f"Position (FEN): {row.get('fen') or 'whole game, no single position'}\n"
        f"Acceptable best moves: {', '.join(row.get('expected_moves', [])) or 'not applicable'}\n"
        f"Reference: {row.get('reference_line', '')}\n"
        f"Key points:\n{key_points}\n"
        f"Must not:\n{must_not}\n\n"
        f"Coach answer:\n{coaching.answer}\n\n"
        f"Coach evidence:\n{evidence}\n"
        f"Recommended move: {coaching.recommended_move or 'none'}\n"
        f"Principle: {coaching.principle}\n"
        f"Drill: {coaching.drill}\n"
        f"Tools used: {', '.join(response.tools_used) or 'none'}"
    )


def openrouter_model(name: str) -> OpenAIChatModel | None:
    """Build the coach model for ``name`` with the same provider settings as llm.py."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    provider = OpenAIProvider(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    settings = OpenAIChatModelSettings(
        timeout=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30")),
        extra_body={"provider": {"sort": "throughput"}},
    )
    return OpenAIChatModel(name, provider=provider, settings=settings)  # type: ignore[arg-type]


def openrouter_judge(model_name: str) -> JudgeCall:
    """Same request shape as llm.complete_with_openrouter, with the judge model pinned.

    The judge stays fixed while coach models change, so scores are comparable across models.
    """

    async def call(system: str, prompt: str) -> tuple[str, bool]:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return "", False
        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "Chess Coach Agent",
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(OPENROUTER_URL, headers=headers, json=body)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"].strip(), True
        except Exception:
            return "", False

    return call


async def judge_answer(row: dict[str, Any], response: CoachAskResponse, judge: JudgeCall) -> dict[str, Any]:
    prompt = judge_prompt(row, response)
    last_error = "judge unavailable"
    for _attempt in range(2):
        raw, used_llm = await judge(JUDGE_SYSTEM, prompt)
        if not used_llm:
            continue
        try:
            scores = _parse_json(raw)
            values = {name: max(0, min(2, int(scores.get(name, 0)))) for name in JUDGE_FIELDS}
        except (ValueError, TypeError) as exc:
            last_error = str(exc)
            continue
        total = sum(values.values())
        return {**values, "total": total, "max": JUDGE_MAX, "pass": total >= JUDGE_PASS,
                "reason": str(scores.get("reason", ""))}
    return {**{name: 0 for name in JUDGE_FIELDS}, "total": 0, "max": JUDGE_MAX, "pass": False,
            "reason": f"Judge failed: {last_error}", "judge_error": True}


def _token_usage(response: CoachAskResponse) -> dict[str, int]:
    usage = {"input_tokens": 0, "output_tokens": 0}
    for message in response.message_history:
        stats = message.get("usage") or {}
        usage["input_tokens"] += int(stats.get("input_tokens") or 0)
        usage["output_tokens"] += int(stats.get("output_tokens") or 0)
    return usage


async def _evaluate_row(
    row: dict[str, Any],
    analysis: CoachAnalysis | None,
    instructions: str,
    judge: JudgeCall,
    model: Any,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = await ask_coach(
        row["question"],
        analysis,
        fen=row.get("fen"),
        # No platform/username: quiz tools stay read-only and the demo database is never written.
        platform=None,
        username=None,
        model=model,
        instructions=instructions,
    )
    coach_seconds = round(time.perf_counter() - started, 2)
    checks = deterministic_checks(row, response)
    judged = await judge_answer(row, response, judge)
    return {
        "id": row["id"],
        "question": row["question"],
        "coach_seconds": coach_seconds,
        "tools_used": response.tools_used,
        "usage": _token_usage(response),
        "deterministic": checks,
        "judge": judged,
        "answer": response.answer,
        "coaching": response.coaching.model_dump(mode="json"),
    }


def _variant_summary(details: list[dict[str, Any]]) -> dict[str, Any]:
    count = max(1, len(details))
    check_names = {name for item in details for name in item["deterministic"]["checks"]}
    check_rates = {}
    for name in sorted(check_names):
        values = [item["deterministic"]["checks"][name] for item in details]
        applicable = [value for value in values if value is not None]
        if applicable:
            check_rates[name] = round(sum(applicable) / len(applicable), 3)
    return {
        "judge_average": round(sum(item["judge"]["total"] for item in details) / count, 3),
        "judge_pass_rate": round(sum(item["judge"]["pass"] for item in details) / count, 3),
        "criteria_average": {
            name: round(sum(item["judge"][name] for item in details) / count, 3) for name in JUDGE_FIELDS
        },
        "deterministic_average": round(sum(item["deterministic"]["score"] for item in details) / count, 3),
        "check_rates": check_rates,
        "average_coach_seconds": round(sum(item["coach_seconds"] for item in details) / count, 2),
        "input_tokens": sum(item["usage"]["input_tokens"] for item in details),
        "output_tokens": sum(item["usage"]["output_tokens"] for item in details),
    }


async def run_coach_eval(
    dataset: Path,
    variants: tuple[str, ...] = ("baseline",),
    *,
    models: tuple[str, ...] = (),
    limit: int | None = None,
    judge: JudgeCall | None = None,
    judge_model: str | None = None,
    model: Any = None,
    concurrency: int = 4,
    pgn_text: str | None = None,
) -> dict[str, Any]:
    """Evaluate every (coach model, prompt variant) pair on the dataset.

    ``model`` injects a ready model object (tests use pydantic_ai TestModel) and overrides
    ``models``. Without either, the configured OPENROUTER_MODEL is used.
    """
    unknown = [name for name in variants if name not in PROMPT_VARIANTS]
    if unknown:
        raise ValueError(f"Unknown prompt variant(s): {unknown}; choose from {sorted(PROMPT_VARIANTS)}")
    rows = load_rows(dataset, limit)
    contexts = load_game_contexts(rows, pgn_text)
    judge_name = judge_model or _model_name()
    judge_call = judge or openrouter_judge(judge_name)
    if model is not None:
        coach_models: dict[str, Any] = {str(getattr(model, "model_name", "injected")): model}
    else:
        names = models or (_model_name(),)
        coach_models = {name: openrouter_model(name) for name in names}
    semaphore = asyncio.Semaphore(max(1, concurrency))
    started = time.perf_counter()

    async def bounded(row: dict[str, Any], instructions: str, coach_model: Any) -> dict[str, Any]:
        async with semaphore:
            analysis = contexts.get(row["game_id"]) if row.get("game_id") else None
            return await _evaluate_row(row, analysis, instructions, judge_call, coach_model)

    runs: dict[str, Any] = {}
    for model_name, coach_model in coach_models.items():
        for variant in variants:
            details = await asyncio.gather(
                *(bounded(row, PROMPT_VARIANTS[variant], coach_model) for row in rows)
            )
            runs[f"{model_name} | {variant}"] = {
                "model": model_name,
                "variant": variant,
                "summary": _variant_summary(list(details)),
                "details": list(details),
            }

    def rank(label: str) -> tuple[float, float]:
        summary = runs[label]["summary"]
        return summary["judge_average"], summary["deterministic_average"]

    winners_by_model = {
        name: max((label for label in runs if runs[label]["model"] == name), key=rank)
        for name in coach_models
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "judge_model": judge_name if judge is None else "injected",
        "dataset": str(dataset),
        "dataset_size": len(rows),
        "judge_pass_threshold": f"{JUDGE_PASS}/{JUDGE_MAX}",
        "elapsed_seconds": round(time.perf_counter() - started, 1),
        "winner": max(runs, key=rank),
        "best_variant_by_model": {name: runs[label]["variant"] for name, label in winners_by_model.items()},
        "runs": runs,
    }


def format_summary(result: dict[str, Any]) -> str:
    header = (
        f"{'model | variant':<44}{'judge avg':>10}{'judge pass':>12}{'checks':>8}{'move ok':>9}"
        f"{'theme':>7}{'tool':>6}{'sec/q':>7}"
    )
    lines = [
        f"Coach evaluation: {result['dataset_size']} questions, judge {result['judge_model']}",
        header,
    ]
    for name, payload in result["runs"].items():
        summary = payload["summary"]
        rates = summary["check_rates"]
        lines.append(
            f"{name:<44}{summary['judge_average']:>7.2f}/{JUDGE_MAX}{summary['judge_pass_rate']:>12.0%}"
            f"{summary['deterministic_average']:>8.0%}{rates.get('expected_move', 0):>9.0%}"
            f"{rates.get('theme_mentioned', 0):>7.0%}{rates.get('used_tool', 0):>6.0%}"
            f"{summary['average_coach_seconds']:>7.1f}"
        )
    lines.append(f"Winner: {result['winner']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/coach_questions.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/eval/coach_results.json"))
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N questions")
    parser.add_argument(
        "--prompt-variant",
        action="append",
        choices=sorted(PROMPT_VARIANTS),
        help="System prompt to evaluate; repeat to compare (default: all variants)",
    )
    parser.add_argument(
        "--model",
        action="append",
        help="OpenRouter coach model to evaluate; repeat to compare (default: OPENROUTER_MODEL)",
    )
    parser.add_argument("--judge-model", default=None, help="Judge model (default: OPENROUTER_MODEL)")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    variants = tuple(args.prompt_variant or PROMPT_VARIANTS)
    result = asyncio.run(
        run_coach_eval(
            args.dataset,
            variants,
            models=tuple(args.model or ()),
            limit=args.limit,
            judge_model=args.judge_model,
            concurrency=args.concurrency,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(format_summary(result))
    print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
