.PHONY: install test eval eval-llm eval-coach retrieval-eval feedback-export score dev backend frontend build migrate seed

install:
	cd backend && uv sync --extra dev
	cd frontend && npm install

test:
	cd backend && uv run pytest -q
	cd frontend && npm run build

eval:
	cd backend && uv run python -m chess_coach_agent.evaluation --dataset data/eval/critical_moments.jsonl

retrieval-eval:
	cd backend && uv run python -m chess_coach_agent.retrieval_evaluation --dataset data/eval/retrieval.jsonl --output data/eval/retrieval_results.json

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m chess_coach_agent.ingest_knowledge

eval-llm:
	cd backend && uv run python -m chess_coach_agent.judge_evaluation --dataset data/eval/critical_moments.jsonl --tune

eval-coach:
	cd backend && uv run python -m chess_coach_agent.coach_evaluation --dataset data/eval/coach_questions.jsonl --output data/eval/coach_results.json

feedback-export:
	cd backend && uv run python -m chess_coach_agent.monitoring --export-candidates data/eval/feedback_candidates.jsonl

score:
	python3 scripts/score_project.py

backend:
	cd backend && uv run uvicorn chess_coach_agent.api:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

dev:
	@echo "Run in two terminals: make backend and make frontend"

build:
	cd frontend && npm run build
