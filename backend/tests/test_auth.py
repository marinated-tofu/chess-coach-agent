import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from chess_coach_agent import auth_api
from chess_coach_agent.api import app
from chess_coach_agent.auth import OAUTH_COOKIE, SESSION_COOKIE, safe_next, sign, unsign


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.delenv("LICHESS_CLIENT_ID", raising=False)


def _mock_lichess(monkeypatch, *, username="DrNykterstein", token_status=200):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST" and request.url.path == "/api/token":
            if token_status != 200:
                return httpx.Response(token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "lio_test", "token_type": "Bearer"})
        if request.method == "GET" and request.url.path == "/api/account":
            assert request.headers["Authorization"] == "Bearer lio_test"
            return httpx.Response(200, json={"id": username.lower(), "username": username})
        if request.method == "DELETE" and request.url.path == "/api/token":
            return httpx.Response(204)
        return httpx.Response(404)

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(auth_api.httpx, "AsyncClient", factory)
    return calls


def _login(client, next_path="/games"):
    response = client.get(
        "/api/auth/lichess/login", params={"next": next_path}, follow_redirects=False
    )
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    return response, location, {k: v[0] for k, v in parse_qs(location.query, keep_blank_values=True).items()}


def test_login_redirect_params_and_pkce():
    with TestClient(app) as client:
        response, location, params = _login(client)
        assert f"{location.scheme}://{location.netloc}{location.path}" == "https://lichess.org/oauth"
        assert params["response_type"] == "code"
        assert params["client_id"] == "chess-coach-agent"
        assert params["redirect_uri"] == "http://testserver/api/auth/lichess/callback"
        assert params["code_challenge_method"] == "S256"
        assert params["scope"] == ""
        set_cookie = response.headers["set-cookie"]
        assert "HttpOnly" in set_cookie and "samesite=lax" in set_cookie.lower()
        pending = unsign(client.cookies.get(OAUTH_COOKIE), "oauth", 600)
        assert pending["state"] == params["state"]
        assert pending["next"] == "/games"
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(pending["verifier"].encode()).digest()
        ).rstrip(b"=").decode()
        assert params["code_challenge"] == expected


def test_login_uses_public_base_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://coach.example.com/")
    monkeypatch.setenv("LICHESS_CLIENT_ID", "my-coach")
    with TestClient(app) as client:
        response, _, params = _login(client)
        assert params["redirect_uri"] == "https://coach.example.com/api/auth/lichess/callback"
        assert params["client_id"] == "my-coach"
        assert "Secure" in response.headers["set-cookie"]


def test_callback_success_sets_session_and_revokes_token(monkeypatch):
    calls = _mock_lichess(monkeypatch)
    with TestClient(app) as client:
        _, _, params = _login(client, "/progress?tab=1")
        response = client.get(
            "/api/auth/lichess/callback",
            params={"code": "abc", "state": params["state"]},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/progress?tab=1"
        session = unsign(client.cookies.get(SESSION_COOKIE), "session", 3600)
        assert session["uid"]
        assert "access_token" not in session and "lio_test" not in client.cookies.get(SESSION_COOKIE)

        token_request = calls[0]
        form = parse_qs(token_request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["abc"]
        assert form["redirect_uri"] == ["http://testserver/api/auth/lichess/callback"]
        assert form["client_id"] == ["chess-coach-agent"]
        assert form["code_verifier"][0]
        assert [(c.method, c.url.path) for c in calls] == [
            ("POST", "/api/token"),
            ("GET", "/api/account"),
            ("DELETE", "/api/token"),
        ]

        me = client.get("/api/auth/me").json()
        assert me["signed_in"] is True
        assert me["lichess_username"] == "DrNykterstein"
        assert me["plan"] == "free"
        assert me["players"] == [{"platform": "lichess", "username": "DrNykterstein"}]

        assert client.post("/api/auth/logout").status_code == 204
        me = client.get("/api/auth/me").json()
        assert me["signed_in"] is False
        assert me["lichess_username"] is None
        assert me["players"] == []


def test_state_mismatch_rejected(monkeypatch):
    calls = _mock_lichess(monkeypatch)
    with TestClient(app) as client:
        _login(client)
        response = client.get(
            "/api/auth/lichess/callback",
            params={"code": "abc", "state": "forged"},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert calls == []
        assert SESSION_COOKIE not in client.cookies


def test_callback_without_pending_cookie_rejected(monkeypatch):
    _mock_lichess(monkeypatch)
    with TestClient(app) as client:
        response = client.get(
            "/api/auth/lichess/callback", params={"code": "abc", "state": "x"}, follow_redirects=False
        )
        assert response.status_code == 400


def test_token_exchange_failure(monkeypatch):
    _mock_lichess(monkeypatch, token_status=400)
    with TestClient(app) as client:
        _, _, params = _login(client)
        response = client.get(
            "/api/auth/lichess/callback",
            params={"code": "bad", "state": params["state"]},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert SESSION_COOKIE not in client.cookies


@pytest.mark.parametrize(
    "target",
    ["https://evil.example", "//evil.example/x", "/\\evil.example", "javascript:alert(1)", "", "games"],
)
def test_open_redirect_blocked(target):
    assert safe_next(target) == "/"
    with TestClient(app) as client:
        _login(client, target)
        assert unsign(client.cookies.get(OAUTH_COOKIE), "oauth", 600)["next"] == "/"


def test_tampered_session_ignored():
    token = sign({"uid": "someone"}, "session")
    body, _, _ = token.rpartition(".")
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, body + ".bad")
        assert client.get("/api/auth/me").json()["signed_in"] is False
        # A valid OAuth-purpose token must not work as a session.
        client.cookies.set(SESSION_COOKIE, sign({"uid": "x"}, "oauth"))
        assert client.get("/api/auth/me").json()["signed_in"] is False


def test_dev_proxy_forwarded_host_only_trusted_for_localhost():
    with TestClient(app) as client:
        response = client.get(
            "/api/auth/lichess/login",
            headers={"X-Forwarded-Host": "127.0.0.1:5193"},
            follow_redirects=False,
        )
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert query["redirect_uri"] == ["http://127.0.0.1:5193/api/auth/lichess/callback"]
        response = client.get(
            "/api/auth/lichess/login",
            headers={"X-Forwarded-Host": "evil.example"},
            follow_redirects=False,
        )
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert query["redirect_uri"] == ["http://testserver/api/auth/lichess/callback"]
