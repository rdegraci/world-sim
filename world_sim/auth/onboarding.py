"""Username onboarding and login for the local CLI session."""

from __future__ import annotations

import getpass
from collections.abc import Callable

from world_sim.auth.password_utils import hash_password, verify_password
from world_sim.db.user_store import AuthStoreError, UserStore
from world_sim.models import AuthContext
from world_sim.utils.logger import get_logger

ADMIN_USERNAME = "admin"

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]
GetPassFn = Callable[[str], str]


class AuthError(Exception):
    """Raised when authentication or onboarding fails."""


def _prompt_nonempty(
    prompt: str,
    *,
    input_fn: InputFn,
    output_fn: OutputFn,
) -> str:
    while True:
        value = input_fn(prompt).strip()
        if value:
            return value
        output_fn("Please enter a non-empty value.")


def _prompt_password(
    prompt: str,
    *,
    getpass_fn: GetPassFn,
    output_fn: OutputFn,
) -> str:
    while True:
        value = getpass_fn(prompt)
        if value:
            return value
        output_fn("Password must not be empty.")


def _authenticate_admin(
    store: UserStore,
    *,
    admin_password: str | None,
    input_fn: InputFn,
    output_fn: OutputFn,
    getpass_fn: GetPassFn,
) -> AuthContext:
    del input_fn  # Username already collected by caller.
    logger = get_logger("auth")
    if not admin_password:
        raise AuthError(
            "Admin login requires ADMIN_PASSWORD in the app .env file. "
            "Set ADMIN_PASSWORD to a non-empty value and restart."
        )

    password = _prompt_password(
        "Admin password: ",
        getpass_fn=getpass_fn,
        output_fn=output_fn,
    )
    if password != admin_password:
        raise AuthError("Invalid admin password.")

    user = store.ensure_admin_user(ADMIN_USERNAME)
    player = store.require_player_character_for_user(user.id)
    session = store.create_session(user.id, player.id)
    logger.info("Admin user authenticated; session_id=%s", session.id)
    return AuthContext(user=user, player_character=player, session=session)


def _signup_player(
    store: UserStore,
    username: str,
    *,
    output_fn: OutputFn,
    getpass_fn: GetPassFn,
) -> AuthContext:
    logger = get_logger("auth")
    output_fn(f"Creating new account for '{username}'.")
    password = _prompt_password(
        "Create password: ",
        getpass_fn=getpass_fn,
        output_fn=output_fn,
    )
    confirm = _prompt_password(
        "Confirm password: ",
        getpass_fn=getpass_fn,
        output_fn=output_fn,
    )
    if password != confirm:
        raise AuthError("Passwords do not match.")

    password_hash = hash_password(password)
    try:
        user = store.create_player_user(username, password_hash)
    except AuthStoreError as exc:
        raise AuthError(str(exc)) from exc

    player = store.require_player_character_for_user(user.id)
    session = store.create_session(user.id, player.id)
    logger.info("Created player user id=%s session_id=%s", user.id, session.id)
    return AuthContext(user=user, player_character=player, session=session)


def _login_player(
    store: UserStore,
    username: str,
    password_hash: str,
    *,
    output_fn: OutputFn,
    getpass_fn: GetPassFn,
) -> AuthContext:
    logger = get_logger("auth")
    password = _prompt_password(
        "Password: ",
        getpass_fn=getpass_fn,
        output_fn=output_fn,
    )
    if not verify_password(password, password_hash):
        raise AuthError("Invalid username or password.")

    user = store.get_user_by_username(username)
    if user is None:
        raise AuthError("Invalid username or password.")
    player = store.require_player_character_for_user(user.id)
    session = store.create_session(user.id, player.id)
    logger.info("Player login user_id=%s session_id=%s", user.id, session.id)
    return AuthContext(user=user, player_character=player, session=session)


def authenticate(
    store: UserStore,
    *,
    admin_password: str | None,
    input_fn: InputFn = input,
    output_fn: OutputFn = print,
    getpass_fn: GetPassFn = getpass.getpass,
) -> AuthContext:
    """Run CLI onboarding/login and return an authenticated session context."""
    output_fn("Sign in to World-Sim.")
    output_fn("Enter a username. Use 'admin' for the local admin account.")
    username = _prompt_nonempty(
        "Username: ",
        input_fn=input_fn,
        output_fn=output_fn,
    )

    if username.lower() == ADMIN_USERNAME:
        return _authenticate_admin(
            store,
            admin_password=admin_password,
            input_fn=input_fn,
            output_fn=output_fn,
            getpass_fn=getpass_fn,
        )

    existing = store.get_user_by_username(username)
    if existing is None:
        return _signup_player(
            store,
            username,
            output_fn=output_fn,
            getpass_fn=getpass_fn,
        )

    if existing.role != "player" or not existing.password_hash:
        raise AuthError(
            f"Account '{existing.username}' cannot use normal password login."
        )

    return _login_player(
        store,
        existing.username,
        existing.password_hash,
        output_fn=output_fn,
        getpass_fn=getpass_fn,
    )
