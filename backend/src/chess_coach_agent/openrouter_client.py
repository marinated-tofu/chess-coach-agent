from __future__ import annotations

import os

import httpx
from .env_bootstrap import load_project_env  # noqa: F401

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_URL = f"{OPENROUTER_BASE_URL}/chat/completions"


# Fastest model in our tool-calling latency check that still grounds answers in tool calls.
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"


def model_name() -> str:
    return os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)


def request_timeout() -> float:
    raw = os.getenv("OPENROUTER_TIMEOUT_SECONDS", "12")
    try:
        return float(raw)
    except ValueError:
        return 12.0


async def complete_with_openrouter(
    system: str,
    prompt: str,
    temperature: float = 0.0,
) -> tuple[str, bool]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "", False
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "Chess Coach Agent",
    }
    body = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    try:
        async with httpx.AsyncClient(timeout=request_timeout()) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip(), True
    except Exception:
        return "", False


def complete_with_openrouter_sync(
    system: str,
    prompt: str,
    temperature: float = 0.0,
) -> tuple[str, bool]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "", False
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "Chess Coach Agent",
    }
    body = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    try:
        with httpx.Client(timeout=request_timeout()) as client:
            response = client.post(OPENROUTER_URL, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip(), True
    except Exception:
        return "", False
