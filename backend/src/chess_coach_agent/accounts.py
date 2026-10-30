"""Users, the players they own, and who may see a player's personal data.

Game data is public, so nothing here touches it. Personal data (practice sessions and
attempts, review schedules, repertoires, coach memory) hangs off a player. The rules:

- A claimed player's personal data is open only to the user who owns it.
- An unclaimed player stays open to everyone, which is what lets the demo work with just
  a username. Whoever later proves they own that player takes the data with them.

A claim needs proof (Lichess sign-in, or a code on the Chess.com profile) so nobody can
lock a player out of their own name.

New sign-in providers plug into `sign_in_user`: it only needs a stable provider and subject.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import SESSION_COOKIE, session_user_id
from .db_models import AuthIdentityRow, PlayerRow, UserPlayerRow, UserRow
from .models import PlayerProfile
from .repositories import get_or_create_player, normalize_username


def viewer_id(request: Request) -> str | None:
    """The signed-in user id, or None for an anonymous visitor."""
    return session_user_id(request.cookies.get(SESSION_COOKIE))


Viewer = Annotated[str | None, Depends(viewer_id)]


def sign_in_user(
    session: Session,
    provider: str,
    subject: str,
    display_name: str,
    email: str | None = None,
    current_user_id: str | None = None,
) -> UserRow:
    """Find the user behind an identity, or attach it to whoever is signed in, or create one."""
    identity = session.scalar(
        select(AuthIdentityRow).where(
            AuthIdentityRow.provider == provider, AuthIdentityRow.subject == subject
        )
    )
    if identity is not None:
        return session.get_one(UserRow, identity.user_id)
    user = session.get(UserRow, current_user_id) if current_user_id else None
    if user is None:
        user = UserRow(display_name=display_name[:100], email=email)
        session.add(user)
        session.flush()
    session.add(AuthIdentityRow(user_id=user.id, provider=provider, subject=subject))
    session.flush()
    return user


def link_player(
    session: Session, user_id: str, platform: str, username: str, verified_by: str
) -> UserPlayerRow:
    """Record the claim. An existing claim is returned as is; callers check who holds it."""
    player = get_or_create_player(session, platform, username)
    link = session.get(UserPlayerRow, player.id)
    if link is None:
        link = UserPlayerRow(player_id=player.id, user_id=user_id, verified_by=verified_by)
        session.add(link)
        session.flush()
    return link


def linked_players(session: Session, user_id: str) -> list[PlayerRow]:
    return list(
        session.scalars(
            select(PlayerRow)
            .join(UserPlayerRow, UserPlayerRow.player_id == PlayerRow.id)
            .where(UserPlayerRow.user_id == user_id)
            .order_by(PlayerRow.platform, PlayerRow.username_normalized)
        )
    )


def _denial(user_id: str | None) -> HTTPException:
    if user_id is None:
        return HTTPException(401, "This player's practice data is private. Sign in to open it.")
    return HTTPException(403, "This player is linked to another account.")


def _player_id(session: Session, platform: str, username: str) -> str | None:
    return session.scalar(
        select(PlayerRow.id).where(
            PlayerRow.platform == platform,
            PlayerRow.username_normalized == normalize_username(username),
        )
    )


def can_access_player(session: Session, player_id: str | None, user_id: str | None) -> bool:
    if player_id is None:
        return True
    owner = session.scalar(select(UserPlayerRow.user_id).where(UserPlayerRow.player_id == player_id))
    return owner is None or owner == user_id


def can_access(session: Session, platform: str, username: str, user_id: str | None) -> bool:
    return can_access_player(session, _player_id(session, platform, username), user_id)


def require_player(session: Session, player_id: str, user_id: str | None) -> None:
    if not can_access_player(session, player_id, user_id):
        raise _denial(user_id)


def require_access(session: Session, platform: str, username: str, user_id: str | None) -> None:
    if not can_access(session, platform, username, user_id):
        raise _denial(user_id)


def public_profile(profile: PlayerProfile) -> PlayerProfile:
    """Keep what comes from public games; drop what comes from the player's practice."""
    return profile.model_copy(
        update={"quiz_accuracy": {}, "mastered_positions": 0, "due_positions": 0}
    )


@dataclass(frozen=True)
class SignedInUser:
    id: str
    display_name: str
    plan: str
    players: list[dict[str, str]]


def signed_in_user(session: Session, user_id: str | None) -> SignedInUser | None:
    """Load the viewer. A cookie for a user who no longer exists counts as signed out."""
    user = session.get(UserRow, user_id) if user_id else None
    if user is None:
        return None
    return SignedInUser(
        id=user.id,
        display_name=user.display_name,
        plan=user.plan,
        players=[
            {"platform": player.platform, "username": player.username}
            for player in linked_players(session, user.id)
        ],
    )
