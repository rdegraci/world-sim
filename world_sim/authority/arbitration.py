"""Serial mutation queue and short claim locks (Phase 4a)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

T = TypeVar("T")

DEFAULT_CLAIM_TTL_SEC = 5.0


class MutationConflict(Exception):
    """Structured runtime refusal when a contested mutation loses."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        resource: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.resource = resource

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "resource": self.resource,
        }


@dataclass
class ClaimRecord:
    holder: str
    resource: str
    expires_at: float
    meta: dict[str, Any] = field(default_factory=dict)


class MutationGate:
    """Single-writer critical section plus short resource claims.

    All contested world mutations must run inside :meth:`run_serial`. Claim locks
    mark hot resources (item, exit, NPC chat) for first-valid-wins semantics.
    """

    def __init__(self, *, default_ttl_sec: float = DEFAULT_CLAIM_TTL_SEC) -> None:
        self._mutex = threading.RLock()
        self._claims: dict[str, ClaimRecord] = {}
        self._default_ttl = default_ttl_sec

    def run_serial(self, fn: Callable[[], T]) -> T:
        """Run ``fn`` as the sole world mutator (serial mutation queue)."""
        with self._mutex:
            self._expire_claims()
            return fn()

    def try_claim(
        self,
        resource: str,
        holder: str,
        *,
        ttl_sec: float | None = None,
        meta: dict[str, Any] | None = None,
    ) -> bool:
        """Claim ``resource`` for ``holder``. Caller must hold the serial lock."""
        self._expire_claims()
        existing = self._claims.get(resource)
        now = time.monotonic()
        if existing is not None and existing.holder != holder and existing.expires_at > now:
            return False
        self._claims[resource] = ClaimRecord(
            holder=holder,
            resource=resource,
            expires_at=now + (ttl_sec if ttl_sec is not None else self._default_ttl),
            meta=dict(meta or {}),
        )
        return True

    def release_claim(self, resource: str, holder: str) -> None:
        existing = self._claims.get(resource)
        if existing is not None and existing.holder == holder:
            del self._claims[resource]

    def get_claim(self, resource: str) -> ClaimRecord | None:
        self._expire_claims()
        return self._claims.get(resource)

    def list_claims_with_prefix(self, prefix: str) -> list[ClaimRecord]:
        self._expire_claims()
        return [c for key, c in self._claims.items() if key.startswith(prefix)]

    def _expire_claims(self) -> None:
        now = time.monotonic()
        expired = [key for key, claim in self._claims.items() if claim.expires_at <= now]
        for key in expired:
            del self._claims[key]


def item_resource(item_instance_id: int) -> str:
    return f"item:{int(item_instance_id)}"


def exit_resource(from_room_id: str, direction: str) -> str:
    return f"exit:{from_room_id}:{direction.strip().lower()}"


def chat_resource(npc_id: str) -> str:
    return f"chat:{npc_id}"


def stub_resource(stub_id: str) -> str:
    return f"stub:{stub_id}"


def holder_for_player(player_character_id: int) -> str:
    return f"pc:{int(player_character_id)}"
