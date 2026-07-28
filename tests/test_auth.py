"""Tests for CLI onboarding and login flows."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim.auth.onboarding import AuthError, authenticate
from world_sim.auth.password_utils import hash_password, verify_password
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.server.session_server import run_session
from world_sim.utils.logger import reset_logging_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    setup_logging("INFO")
    yield
    reset_logging_for_tests()


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    db = SqliteManager(tmp_path / "world_sim.sqlite3")
    db.initialize_schema()
    return UserStore(db.connection)


def test_signup_then_login_persists_identity(store: UserStore) -> None:
    passwords = iter(["s3cret", "s3cret"])
    outputs: list[str] = []

    created = authenticate(
        store,
        admin_password="admin-secret",
        input_fn=lambda _: "morgan",
        output_fn=outputs.append,
        getpass_fn=lambda _: next(passwords),
    )
    assert created.user.username == "morgan"
    assert created.user.role == "player"
    assert created.user.password_hash is not None
    assert "s3cret" not in created.user.password_hash
    assert verify_password("s3cret", created.user.password_hash)
    assert created.player_character.user_id == created.user.id

    login_passwords = iter(["s3cret"])
    logged_in = authenticate(
        store,
        admin_password="admin-secret",
        input_fn=lambda _: "morgan",
        output_fn=outputs.append,
        getpass_fn=lambda _: next(login_passwords),
    )
    assert logged_in.user.id == created.user.id
    assert logged_in.player_character.id == created.player_character.id
    assert logged_in.session.id != created.session.id


def test_admin_auth_uses_env_password_not_hash(store: UserStore) -> None:
    outputs: list[str] = []
    auth = authenticate(
        store,
        admin_password="from-env",
        input_fn=lambda _: "admin",
        output_fn=outputs.append,
        getpass_fn=lambda _: "from-env",
    )
    assert auth.is_admin
    assert auth.user.password_hash is None
    assert auth.player_character.name == "admin"


def test_admin_auth_rejects_wrong_password(store: UserStore) -> None:
    with pytest.raises(AuthError, match="Invalid admin password"):
        authenticate(
            store,
            admin_password="from-env",
            input_fn=lambda _: "admin",
            output_fn=lambda _: None,
            getpass_fn=lambda _: "nope",
        )


def test_admin_auth_requires_admin_password_config(store: UserStore) -> None:
    with pytest.raises(AuthError, match="ADMIN_PASSWORD"):
        authenticate(
            store,
            admin_password=None,
            input_fn=lambda _: "admin",
            output_fn=lambda _: None,
            getpass_fn=lambda _: "anything",
        )


def test_login_rejects_bad_password(store: UserStore) -> None:
    store.create_player_user("ripley", hash_password("right"))
    with pytest.raises(AuthError, match="Invalid username or password"):
        authenticate(
            store,
            admin_password="admin-secret",
            input_fn=lambda _: "ripley",
            output_fn=lambda _: None,
            getpass_fn=lambda _: "wrong",
        )


def test_authenticated_session_records_transcript(store: UserStore) -> None:
    user = store.create_player_user("sam", hash_password("pw"))
    player = store.require_player_character_for_user(user.id)
    session = store.create_session(user.id, player.id)
    from world_sim.models import AuthContext

    auth = AuthContext(user=user, player_character=player, session=session)
    outputs: list[str] = []
    inputs = iter(["whoami", "quit"])

    code = run_session(
        auth=auth,
        store=store,
        input_fn=lambda _: next(inputs),
        output_fn=outputs.append,
    )
    assert code == 0
    assert any("sam" in line for line in outputs)

    entries = store.list_transcripts(session.id)
    assert any(entry.content == "whoami" for entry in entries)
    ended = store.connection.execute(
        "SELECT status, ended_at FROM sessions WHERE id = ?",
        (session.id,),
    ).fetchone()
    assert ended["status"] == "ended"
    assert ended["ended_at"] is not None
