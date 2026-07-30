"""Guidance brief loading and parsing (intent only; not canon)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class BriefError(ValueError):
    """Raised when a guidance brief cannot be parsed or is invalid."""


def load_guidance_brief(path: Path | str) -> dict[str, Any]:
    """Load a YAML or Markdown-with-YAML-front-matter guidance brief.

    The brief steers proposals. It is never stored as canon.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise BriefError(f"Guidance brief not found: {file_path}")

    text = file_path.read_text(encoding="utf-8")
    raw = _parse_brief_text(text)
    return normalize_brief(raw, source_path=str(file_path))


def _parse_brief_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise BriefError("Guidance brief is empty.")

    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) >= 3:
            front = parts[1]
            body = parts[2].strip()
            loaded = yaml.safe_load(front) or {}
            if not isinstance(loaded, dict):
                raise BriefError("YAML front matter must be a mapping.")
            if body and "goal" not in loaded:
                loaded["goal"] = body.splitlines()[0].lstrip("# ").strip()
            elif body and "notes" not in loaded:
                loaded["body"] = body
            return loaded

    loaded = yaml.safe_load(stripped)
    if loaded is None:
        raise BriefError("Guidance brief parsed to empty content.")
    if not isinstance(loaded, dict):
        raise BriefError("Guidance brief must be a YAML mapping (or Markdown front matter).")
    return loaded


def normalize_brief(raw: dict[str, Any], *, source_path: str | None = None) -> dict[str, Any]:
    """Normalize brief fields into a stable shape for propose/validate."""
    constraints_raw = raw.get("constraints") or {}
    if constraints_raw is None:
        constraints_raw = {}
    if not isinstance(constraints_raw, dict):
        raise BriefError("'constraints' must be a mapping.")

    propose_raw = raw.get("propose") or {}
    if propose_raw is None:
        propose_raw = {}
    if not isinstance(propose_raw, dict):
        raise BriefError("'propose' must be a mapping.")

    must_link = _normalize_links(raw.get("must_link") or [])
    must_place = _normalize_placements(raw.get("must_place") or [])
    do_not = [str(item).strip() for item in (raw.get("do_not") or []) if str(item).strip()]

    brief: dict[str, Any] = {
        "goal": str(raw.get("goal") or "").strip(),
        "tone": str(raw.get("tone") or "").strip() or None,
        "constraints": {
            "max_rooms": _optional_int(constraints_raw.get("max_rooms")),
            "max_items": _optional_int(constraints_raw.get("max_items")),
            "max_npcs": _optional_int(constraints_raw.get("max_npcs")),
        },
        "propose": {
            "rooms": _normalize_entity_list(propose_raw.get("rooms") or [], kind="room"),
            "items": _normalize_entity_list(propose_raw.get("items") or [], kind="item"),
            "npcs": _normalize_npc_list(propose_raw.get("npcs") or []),
        },
        "must_link": must_link,
        "must_place": must_place,
        "do_not": do_not,
    }
    if source_path:
        brief["source_path"] = source_path
    if raw.get("body"):
        brief["body"] = str(raw["body"])
    return brief


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BriefError(f"Expected integer constraint, got {value!r}") from exc


def _normalize_entity_list(entries: Any, *, kind: str) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise BriefError(f"'propose.{kind}s' must be a list.")
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            lore_key = entry.strip()
            entity: dict[str, Any] = {"lore_key": lore_key}
        elif isinstance(entry, dict):
            entity = dict(entry)
            if "lore_key" not in entity:
                raise BriefError(f"Each propose.{kind} entry needs 'lore_key'.")
            entity["lore_key"] = str(entity["lore_key"]).strip()
        else:
            raise BriefError(f"Invalid propose.{kind} entry: {entry!r}")
        if not entity["lore_key"]:
            raise BriefError(f"Empty lore_key in propose.{kind}.")
        if kind == "item" and entity.get("place_in"):
            entity["place_in"] = str(entity["place_in"]).strip()
        if entity.get("room_id"):
            entity["room_id"] = str(entity["room_id"]).strip()
        if entity.get("item_id"):
            entity["item_id"] = str(entity["item_id"]).strip()
        if entity.get("name"):
            entity["name"] = str(entity["name"]).strip()
        normalized.append(entity)
    return normalized


def _normalize_npc_list(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise BriefError("'propose.npcs' must be a list.")
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            entity = {"npc_id": _npc_id_from_key(entry), "npc_lore": [entry.strip()]}
        elif isinstance(entry, dict):
            entity = dict(entry)
            lore_keys = entity.get("npc_lore") or entity.get("lore_keys") or []
            if isinstance(lore_keys, str):
                lore_keys = [lore_keys]
            if not lore_keys and entity.get("lore_key"):
                lore_keys = [entity["lore_key"]]
            lore_keys = [str(key).strip() for key in lore_keys if str(key).strip()]
            if not lore_keys:
                raise BriefError("Each propose.npc entry needs npc_lore or lore_key.")
            npc_id = str(entity.get("npc_id") or _npc_id_from_key(lore_keys[0])).strip()
            entity = {
                "npc_id": npc_id,
                "name": str(entity.get("name") or "").strip() or None,
                "npc_lore": lore_keys,
                "current_room_id": (
                    str(entity["current_room_id"]).strip()
                    if entity.get("current_room_id")
                    else None
                ),
            }
        else:
            raise BriefError(f"Invalid propose.npc entry: {entry!r}")
        normalized.append(entity)
    return normalized


def _normalize_links(entries: Any) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        raise BriefError("'must_link' must be a list.")
    links: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise BriefError(f"Invalid must_link entry: {entry!r}")
        try:
            links.append(
                {
                    "from": str(entry["from"]).strip(),
                    "direction": str(entry["direction"]).strip().lower(),
                    "to": str(entry["to"]).strip(),
                }
            )
        except KeyError as exc:
            raise BriefError("must_link entries need from, direction, and to.") from exc
    return links


def _normalize_placements(entries: Any) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        raise BriefError("'must_place' must be a list.")
    placements: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise BriefError(f"Invalid must_place entry: {entry!r}")
        kind = str(entry.get("kind") or entry.get("type") or "").strip().lower()
        entity_id = str(entry.get("id") or entry.get("entity_id") or "").strip()
        room_id = str(entry.get("room") or entry.get("room_id") or "").strip()
        if kind not in {"item", "npc"} or not entity_id or not room_id:
            raise BriefError(
                "must_place entries need kind (item|npc), id, and room."
            )
        placements.append({"kind": kind, "id": entity_id, "room": room_id})
    return placements


def _npc_id_from_key(lore_key: str) -> str:
    key = lore_key.strip()
    parts = key.split(":")
    if len(parts) >= 2 and parts[0] == "npc":
        return parts[1]
    return key.replace(":", "_")
