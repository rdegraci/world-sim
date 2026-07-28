"""Authentication package for World-Sim."""

from world_sim.auth.onboarding import AuthError, authenticate
from world_sim.auth.password_utils import hash_password, verify_password

__all__ = [
    "AuthError",
    "authenticate",
    "hash_password",
    "verify_password",
]
