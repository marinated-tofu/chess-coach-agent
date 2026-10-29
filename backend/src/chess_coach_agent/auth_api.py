from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from .auth import (
    LICHESS_HOST,
    OAUTH_COOKIE,
    OAUTH_MAX_AGE,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    code_challenge,
    new_code_verifier,
    safe_next,
    sign,
    unsign,
)
from .importers import lichess_user_agent

router = APIRouter(prefix="/api/auth", tags=["auth"])

CALLBACK_PATH = "/api/auth/lichess/callback"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _client_id() -> str:
    return os.getenv("LICHESS_CLIENT_ID", "").strip() or "chess-coach-agent"


def _public_base() -> str:
    # Render sets RENDER_EXTERNAL_URL automatically, so PUBLIC_BASE_URL is optional there.
    value = os.getenv("PUBLIC_BASE_URL", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip()
    return value.rstrip("/")


def _redirect_uri(request: Request) -> str:
    base = _public_base()
    if base:
        return base + CALLBACK_PATH
    # The Vite dev proxy forwards the browser's host; trust it only for local hosts.
    forwarded = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    if forwarded and urlsplit(f"//{forwarded}").hostname in LOCAL_HOSTS:
        return f"http://{forwarded}{CALLBACK_PATH}"
    return str(request.base_url).rstrip("/") + CALLBACK_PATH


def _secure(request: Request) -> bool:
    base = _public_base()
    if base:
        return base.startswith("https://")
    forwarded = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded.split(",")[0].strip() == "https"


@router.get("/lichess/login")
def lichess_login(request: Request, next: str = "/") -> RedirectResponse:
    verifier = new_code_verifier()
    state = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri(request)
    params = {
        "response_type": "code",
        "client_id": _client_id(),
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge(verifier),
        "scope": "",
        "state": state,
    }
    response = RedirectResponse(f"{LICHESS_HOST}/oauth?{urlencode(params)}", status_code=302)
    response.set_cookie(
        OAUTH_COOKIE,
        sign(
            {"verifier": verifier, "state": state, "next": safe_next(next), "redirect_uri": redirect_uri},
            "oauth",
        ),
        max_age=OAUTH_MAX_AGE,
        httponly=True,
        secure=_secure(request),
        samesite="lax",
        path="/api/auth",
    )
    return response


async def _exchange_code(code: str, verifier: str, redirect_uri: str) -> str:
    """Trade the code for a token, read the username, and revoke the token straight away."""
    headers = {"User-Agent": lichess_user_agent()}
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        token_response = await client.post(
            f"{LICHESS_HOST}/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "client_id": _client_id(),
            },
        )
        if token_response.status_code != 200:
            raise HTTPException(400, "Lichess did not accept the sign-in code.")
        token = token_response.json().get("access_token")
        if not token:
            raise HTTPException(400, "Lichess did not return an access token.")
        auth = {"Authorization": f"Bearer {token}"}
        try:
            account = await client.get(f"{LICHESS_HOST}/api/account", headers=auth)
        finally:
            try:
                await client.delete(f"{LICHESS_HOST}/api/token", headers=auth)
            except httpx.HTTPError:
                pass  # The token expires on its own; nothing is stored either way.
        if account.status_code != 200:
            raise HTTPException(502, "Could not read the Lichess account.")
        username = account.json().get("username") or account.json().get("id")
        if not username:
            raise HTTPException(502, "Lichess account has no username.")
        return str(username)


@router.get("/lichess/callback")
async def lichess_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    pending = unsign(request.cookies.get(OAUTH_COOKIE), "oauth", OAUTH_MAX_AGE)
    if not pending:
        raise HTTPException(400, "Sign-in expired or was started in another browser. Try again.")
    target = safe_next(pending.get("next"))
    if error:
        response = RedirectResponse(target, status_code=302)
        response.delete_cookie(OAUTH_COOKIE, path="/api/auth")
        return response
    if not code or not state or not secrets.compare_digest(state, str(pending.get("state", ""))):
        raise HTTPException(400, "Sign-in state did not match. Try again.")
    try:
        username = await _exchange_code(code, pending["verifier"], pending["redirect_uri"])
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not reach Lichess to finish sign-in.") from exc
    response = RedirectResponse(target, status_code=302)
    response.delete_cookie(OAUTH_COOKIE, path="/api/auth")
    response.set_cookie(
        SESSION_COOKIE,
        sign({"lichess_username": username}, "session"),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_secure(request),
        samesite="lax",
        path="/",
    )
    return response


def current_lichess_username(request: Request) -> str | None:
    session = unsign(request.cookies.get(SESSION_COOKIE), "session", SESSION_MAX_AGE)
    return session.get("lichess_username") if session else None


@router.get("/me")
def me(request: Request) -> dict:
    username = current_lichess_username(request)
    return {"signed_in": bool(username), "lichess_username": username}


@router.post("/logout")
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
