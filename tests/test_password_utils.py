"""Tests for password hashing helpers."""

from __future__ import annotations

import pytest

from world_sim.auth.password_utils import hash_password, verify_password


def test_hash_password_is_not_raw_and_verifies() -> None:
    password = "correct horse battery"
    password_hash = hash_password(password)

    assert password not in password_hash
    assert password_hash.startswith("pbkdf2_sha256$")
    assert verify_password(password, password_hash) is True
    assert verify_password("wrong password", password_hash) is False


def test_hash_password_uses_unique_salts() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second


def test_empty_password_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("")
