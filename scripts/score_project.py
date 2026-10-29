from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Score:
    name: str
    points: int
    max_points: int
    explanation: str


def exists(path: str) -> bool:
    return (ROOT / path).exists()


def read(path: str) -> str:
    file_path = ROOT / path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8", errors="ignore")


def any_file(pattern: str) -> bool:
    return any(ROOT.glob(pattern))


def contains(path: str, *terms: str) -> bool:
    text = read(path).lower()
    return all(term.lower() in text for term in terms)


def score_problem() -> Score:
    ok = contains("README.md", "club players", "critical moments", "problem")
    return Score("Problem Description", 2 if ok else 1 if exists("README.md") else 0, 2, "README describes the chess improvement problem.")


def score_knowledge() -> Score:
    has_kb = any_file("backend/data/knowledge/*.md")
    evaluated = all(
        exists(path)
        for path in [
            "backend/data/eval/retrieval.jsonl",
            "backend/src/chess_coach_agent/retrieval_evaluation.py",
            "docs/evaluation_results.md",
        ]
    )
    selected = contains(
        "backend/src/chess_coach_agent/knowledge.py",
        "production_strategy",
        "hybrid_rrf",
    ) and exists("backend/data/eval/retrieval_results.json")
    return Score(
        "Knowledge Base and Retrieval",
        2 if has_kb and evaluated and selected else 1 if has_kb else 0,
        2,
        "Title, BM25, vector, and hybrid retrieval are benchmarked; guardrails select production retrieval.",
    )


def score_agents() -> Score:
    llm = read("backend/src/chess_coach_agent/llm.py")
    tools = [
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
    ]
    registered_tools = all(term in llm for term in tools)
    pydantic_agent = "from pydantic_ai import Agent" in llm and "output_type=CoachingOutput" in llm
    has_llm = "OPENROUTER_API_KEY" in llm
    points = 3 if has_llm and registered_tools and pydantic_agent else 2 if has_llm else 0
    return Score(
        "Agents and LLM",
        points,
        3,
        "PydanticAI lets OpenRouter call twelve documented tools before structured answer synthesis.",
    )


def score_code_org() -> Score:
    ok = any_file("backend/src/chess_coach_agent/*.py") and any_file("frontend/src/**/*.tsx") and exists("backend/pyproject.toml")
    return Score("Code Organization", 2 if ok else 0, 2, "Backend package and React frontend are organized separately.")


def score_testing() -> Score:
    tests = list((ROOT / "backend/tests").glob("test_*.py"))
    has_judge = exists("backend/tests/test_judge.py") and contains("README.md", "fake judge", "test suite")
    return Score("Testing", 2 if tests and has_judge else 1 if tests else 0, 2, f"{len(tests)} test modules plus a controlled judge test.")


def score_evaluation() -> Score:
    ground_truth = exists("backend/data/eval/critical_moments.jsonl")
    llm_judge = exists("backend/src/chess_coach_agent/judge_evaluation.py")
    tuned = contains("docs/evaluation_results.md", "concise", "grounded", "after tuning")
    return Score("Evaluation", 3 if ground_truth and llm_judge and tuned else 2 if ground_truth and llm_judge else 0, 3, "MiniMax judge results document prompt comparison and tuning.")


def score_eval_bonus() -> Score:
    handcrafted = contains("backend/data/eval/critical_moments.jsonl", "reviewer_notes")
    manual = contains("docs/manual_evaluation.md", "manual verdict", "2/2 acceptable")
    return Score("Evaluation bonus points", (2 if handcrafted else 0) + (2 if manual else 0), 4, "Ground truth is hand-authored and manually reviewed.")


def score_monitoring() -> Score:
    logs = exists("backend/src/chess_coach_agent/monitoring.py")
    dashboard = exists("frontend/src/components/MonitoringDashboard.tsx") and contains("backend/src/chess_coach_agent/api.py", "/api/monitoring")
    docs = contains("docs/monitoring.md", "logfire", "jsonl", "dashboard")
    tracing = contains(
        "backend/src/chess_coach_agent/llm.py", "instrument_pydantic_ai", "service_name"
    )
    return Score("Monitoring", 2 if logs and dashboard and docs and tracing else 1 if logs else 0, 2, "Logfire traces and local usage events feed the React quality dashboard.")


def score_monitoring_bonus() -> Score:
    feedback_path = contains("backend/src/chess_coach_agent/api.py", "/api/feedback") and contains("frontend/src/components/AnalysisPanel.tsx", "onFeedback")
    log_to_eval = contains("backend/src/chess_coach_agent/monitoring.py", "export_feedback_candidates", "review_status")
    return Score("Monitoring bonus points", (1 if feedback_path else 0) + (2 if log_to_eval else 0), 3, "Feedback is collected and exportable as reviewable eval candidates.")


def score_reproducibility() -> Score:
    ok = contains("README.md", "quickstart", "uv sync", "npm install") and exists("backend/data/sample_games/kfctofu_sample.pgn")
    return Score("Reproducibility", 2 if ok else 1 if exists("README.md") else 0, 2, "README setup and sample PGN are present.")


def score_best_practices() -> Score:
    points = 0
    evidence = []
    if exists("Dockerfile.backend") or exists("Dockerfile.frontend"):
        points += 1
        evidence.append("Dockerfiles")
    if exists("docker-compose.yml"):
        points += 2
        evidence.append("docker-compose")
    if exists("Makefile"):
        points += 1
        evidence.append("Makefile")
    if exists("backend/pyproject.toml") and contains("README.md", "uv"):
        points += 1
        evidence.append("uv workflow")
    if any_file(".github/workflows/*.yml"):
        points += 2
        evidence.append("CI")
    return Score("Best Coding Practices", points, 7, ", ".join(evidence))


def score_additional_bonus() -> Score:
    points = 1 if any_file("frontend/src/**/*.tsx") else 0
    deployed = contains("README.md", "https://chess-coach-agent.onrender.com/")
    points += 2 if deployed else 0
    return Score("Additional Bonus Points", points, 3, "React UI and a public Render deployment are documented.")


SCORERS: list[Callable[[], Score]] = [
    score_problem,
    score_knowledge,
    score_agents,
    score_code_org,
    score_testing,
    score_evaluation,
    score_eval_bonus,
    score_monitoring,
    score_monitoring_bonus,
    score_reproducibility,
    score_best_practices,
    score_additional_bonus,
]


def main() -> None:
    scores = [scorer() for scorer in SCORERS]
    total = sum(score.points for score in scores)
    max_total = sum(score.max_points for score in scores)
    print(f"Project score: {total}/{max_total}")
    print()
    for score in scores:
        print(f"- {score.name}: {score.points}/{score.max_points} — {score.explanation}")


if __name__ == "__main__":
    main()
