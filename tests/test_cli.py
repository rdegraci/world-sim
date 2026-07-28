"""Tests for CLI startup wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from world_sim import cli
from world_sim import config as config_mod
from world_sim.auth.password_utils import hash_password
from world_sim.config import bootstrap_directories, resolve_paths
from world_sim.db.sqlite_manager import SqliteManager
from world_sim.db.user_store import UserStore
from world_sim.models import AuthContext
from world_sim.utils.logger import reset_logging_for_tests


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    yield
    reset_logging_for_tests()


def test_main_exits_with_config_error_when_grok_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = resolve_paths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    bootstrap_directories(paths)

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: config_mod.load_settings(paths=paths),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "configuration error" in err.lower()
    assert "GROK_API_KEY" in err


def test_main_starts_authenticated_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = resolve_paths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    bootstrap_directories(paths)
    paths.env_path.write_text(
        "GROK_API_KEY=test-key\nADMIN_PASSWORD=admin-secret\n",
        encoding="utf-8",
    )

    settings = config_mod.load_settings(paths=paths)
    db = SqliteManager(settings.paths.sqlite_path)
    db.initialize_schema()
    store = UserStore(db.connection)
    user = store.create_player_user("cli-user", hash_password("pw"))
    player = store.require_player_character_for_user(user.id)
    session = store.create_session(user.id, player.id)
    auth = AuthContext(user=user, player_character=player, session=session)
    db.close()

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: config_mod.load_settings(paths=paths),
    )
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: auth)
    monkeypatch.setattr(cli, "run_session", lambda **kwargs: 0)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0


def test_run_app_returns_auth_error_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = resolve_paths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    bootstrap_directories(paths)
    paths.env_path.write_text("GROK_API_KEY=test-key\n", encoding="utf-8")
    settings = config_mod.load_settings(paths=paths)

    def _fail_auth(*args: object, **kwargs: object) -> AuthContext:
        raise cli.AuthError("nope")

    monkeypatch.setattr(cli, "authenticate", _fail_auth)
    code = cli.run_app(settings)
    assert code == 1
    assert "authentication error" in capsys.readouterr().err.lower()
