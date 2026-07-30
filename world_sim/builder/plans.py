"""Seed plan models and JSON persistence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


PLAN_STATUS_DRAFT = "draft"
PLAN_STATUS_APPLIED = "applied"


@dataclass
class SeedPlan:
    """Reviewable structural draft. Never authoritative until applied."""

    plan_id: str
    status: str = PLAN_STATUS_DRAFT
    created_at: str = ""
    updated_at: str = ""
    brief_path: str | None = None
    brief: dict[str, Any] | None = None
    rooms: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    npcs: list[dict[str, Any]] = field(default_factory=list)
    exits: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeedPlan:
        return cls(
            plan_id=str(data["plan_id"]),
            status=str(data.get("status", PLAN_STATUS_DRAFT)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            brief_path=data.get("brief_path"),
            brief=data.get("brief"),
            rooms=list(data.get("rooms") or []),
            items=list(data.get("items") or []),
            npcs=list(data.get("npcs") or []),
            exits=list(data.get("exits") or []),
            attachments=list(data.get("attachments") or []),
            notes=list(data.get("notes") or []),
            gaps=list(data.get("gaps") or []),
        )


def new_plan_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"plan_{stamp}_{uuid4().hex[:6]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def plans_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / "builder" / "plans"
    path.mkdir(parents=True, exist_ok=True)
    return path


def plan_path(data_dir: Path, plan_id: str) -> Path:
    return plans_dir(data_dir) / f"{plan_id}.json"


def save_plan(data_dir: Path, plan: SeedPlan) -> Path:
    plan.updated_at = utc_now_iso()
    if not plan.created_at:
        plan.created_at = plan.updated_at
    path = plan_path(data_dir, plan.plan_id)
    path.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_plan(data_dir: Path, plan_id: str) -> SeedPlan:
    path = plan_path(data_dir, plan_id)
    if not path.exists():
        raise FileNotFoundError(f"Seed plan not found: {plan_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid seed plan file: {path}")
    return SeedPlan.from_dict(data)


def list_plan_ids(data_dir: Path) -> list[str]:
    directory = plans_dir(data_dir)
    ids = [path.stem for path in directory.glob("plan_*.json")]
    return sorted(ids)


def create_empty_plan(*, brief_path: str | None = None, brief: dict[str, Any] | None = None) -> SeedPlan:
    now = utc_now_iso()
    return SeedPlan(
        plan_id=new_plan_id(),
        status=PLAN_STATUS_DRAFT,
        created_at=now,
        updated_at=now,
        brief_path=brief_path,
        brief=brief,
    )
