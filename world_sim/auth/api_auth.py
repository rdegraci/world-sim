"""Programmatic login/signup for HTTP and WebSocket clients."""

from __future__ import annotations

from world_sim.auth.onboarding import ADMIN_USERNAME, AuthError
from world_sim.auth.password_utils import hash_password, verify_password
from world_sim.db.user_store import AuthStoreError, UserStore
from world_sim.models import AuthContext
from world_sim.utils.logger import get_logger


def authenticate_credentials(
    store: UserStore,
    *,
    username: str,
    password: str,
    admin_password: str | None,
    allow_signup: bool = True,
) -> AuthContext:
    """Authenticate or optionally sign up a player; return AuthContext with new session."""
    logger = get_logger("auth.api")
    name = username.strip()
    if not name:
        raise AuthError("Username is required.")
    if not password:
        raise AuthError("Password is required.")

    if name.lower() == ADMIN_USERNAME:
        if not admin_password:
            raise AuthError(
                "Admin login requires ADMIN_PASSWORD in the app .env file."
            )
        if password != admin_password:
            raise AuthError("Invalid admin password.")
        user = store.ensure_admin_user(ADMIN_USERNAME)
        player = store.require_player_character_for_user(user.id)
        session = store.create_session(user.id, player.id)
        logger.info("Admin API auth session_id=%s", session.id)
        return AuthContext(user=user, player_character=player, session=session)

    existing = store.get_user_by_username(name)
    if existing is None:
        if not allow_signup:
            raise AuthError("Invalid username or password.")
        try:
            user = store.create_player_user(name, hash_password(password))
        except AuthStoreError as exc:
            raise AuthError(str(exc)) from exc
        player = store.require_player_character_for_user(user.id)
        session = store.create_session(user.id, player.id)
        logger.info("API signup user_id=%s session_id=%s", user.id, session.id)
        return AuthContext(user=user, player_character=player, session=session)

    if existing.role != "player" or not existing.password_hash:
        raise AuthError(
            f"Account '{existing.username}' cannot use normal password login."
        )
    if not verify_password(password, existing.password_hash):
        raise AuthError("Invalid username or password.")

    player = store.require_player_character_for_user(existing.id)
    session = store.create_session(existing.id, player.id)
    logger.info("API login user_id=%s session_id=%s", existing.id, session.id)
    return AuthContext(user=existing, player_character=player, session=session)
