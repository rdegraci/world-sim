"""Orchestration for World Builder workflows."""

from __future__ import annotations

from pathlib import Path

from world_sim.builder.apply import ApplyError, apply_seed_plan
from world_sim.builder.plans import (
    SeedPlan,
    create_empty_plan,
    list_plan_ids,
    load_plan,
    save_plan,
)
from world_sim.builder.preview import format_seed_plan_preview
from world_sim.builder.proposals import (
    attach_lore,
    connect_rooms,
    place_item,
    place_npc,
    propose_from_brief,
    propose_items_from_lore,
    propose_npcs_from_lore,
    propose_rooms_from_lore,
)
from world_sim.builder.validation import ValidationResult, validate_world
from world_sim.db.world_store import WorldStore
from world_sim.builder.linking import collection_for_lore_key
from world_sim.config import RetrievalSettings
from world_sim.lore.chroma_manager import (
    ALL_COLLECTIONS,
    COLLECTION_ITEM,
    COLLECTION_NPC,
    COLLECTION_ROOM,
    COLLECTION_SYSTEM,
    ChromaManager,
)
from world_sim.lore.retrieval import RetrievalAssist
from world_sim.lore.seed import seed_starter_world

_COLLECTION_ALIASES = {
    "system": COLLECTION_SYSTEM,
    "room": COLLECTION_ROOM,
    "item": COLLECTION_ITEM,
    "npc": COLLECTION_NPC,
    COLLECTION_SYSTEM: COLLECTION_SYSTEM,
    COLLECTION_ROOM: COLLECTION_ROOM,
    COLLECTION_ITEM: COLLECTION_ITEM,
    COLLECTION_NPC: COLLECTION_NPC,
}


class BuilderSession:
    """Stateful builder working against shared World-Sim stores."""

    def __init__(
        self,
        world: WorldStore,
        lore: ChromaManager,
        data_dir: Path,
        *,
        seed_starter: bool = True,
        retrieval: RetrievalSettings | None = None,
    ) -> None:
        self.world = world
        self.lore = lore
        self.data_dir = Path(data_dir)
        self.current_plan_id: str | None = None
        self.retrieval = RetrievalAssist(lore, retrieval or RetrievalSettings())
        if seed_starter:
            seed_starter_world(world, lore)

    def ensure_plan(self) -> SeedPlan:
        if self.current_plan_id:
            return self.load_current_plan()
        plan = create_empty_plan()
        plan.notes.append("New draft seed plan.")
        self._persist(plan)
        return plan

    def load_current_plan(self) -> SeedPlan:
        if not self.current_plan_id:
            raise FileNotFoundError("No current seed plan. Create one with propose_* first.")
        return load_plan(self.data_dir, self.current_plan_id)

    def _persist(self, plan: SeedPlan) -> SeedPlan:
        save_plan(self.data_dir, plan)
        self.current_plan_id = plan.plan_id
        return plan

    def list_plans(self) -> list[str]:
        return list_plan_ids(self.data_dir)

    def upsert_lore(self, lore_key: str, text: str, *, collection: str | None = None) -> str:
        """Write approved canon text into Chroma (lore-first step before propose).

        Does not create SQLite structure. Structure still requires propose → apply.
        """
        key = lore_key.strip()
        body = text.strip()
        if not key:
            raise ValueError("lore_key is required.")
        if not body:
            raise ValueError("lore text is required.")

        if collection:
            resolved = _COLLECTION_ALIASES.get(collection.strip().lower())
            if resolved is None:
                raise ValueError(
                    f"Unknown collection '{collection}'. "
                    "Use system, room, item, or npc."
                )
        else:
            resolved = collection_for_lore_key(key)
            if resolved is None:
                raise ValueError(
                    f"Cannot infer collection from lore key '{key}'. "
                    "Pass collection explicitly (system|room|item|npc)."
                )

        expected = collection_for_lore_key(key)
        if expected is not None and expected != resolved:
            raise ValueError(
                f"Lore key '{key}' belongs in '{expected}', not '{resolved}'."
            )

        self.lore.upsert_lore(resolved, key, body)
        return f"Approved lore upserted: {resolved} / {key}"

    def open_plan(self, plan_id: str) -> SeedPlan:
        plan = load_plan(self.data_dir, plan_id)
        self.current_plan_id = plan.plan_id
        return plan

    def propose_rooms(self, lore_keys: list[str]) -> SeedPlan:
        plan = self.ensure_plan()
        propose_rooms_from_lore(plan, self.lore, self.world, lore_keys)
        return self._persist(plan)

    def propose_items(self, lore_keys: list[str], *, place_in: str | None = None) -> SeedPlan:
        plan = self.ensure_plan()
        propose_items_from_lore(
            plan, self.lore, self.world, lore_keys, place_in=place_in
        )
        return self._persist(plan)

    def propose_npcs(
        self,
        lore_keys: list[str],
        *,
        npc_id: str | None = None,
        name: str | None = None,
        current_room_id: str | None = None,
    ) -> SeedPlan:
        plan = self.ensure_plan()
        propose_npcs_from_lore(
            plan,
            self.lore,
            self.world,
            lore_keys,
            npc_id=npc_id,
            name=name,
            current_room_id=current_room_id,
        )
        return self._persist(plan)

    def propose_from_brief(self, brief_path: str | Path) -> SeedPlan:
        plan = propose_from_brief(self.lore, self.world, str(brief_path))
        self._annotate_retrieval_suggestions(plan)
        return self._persist(plan)

    def discover_lore(self, query: str) -> str:
        """Semantic discovery assist — grounded keys only for propose_*."""
        return self.retrieval.format_builder_discovery(query)

    def propose_discovered(
        self,
        query: str,
        *,
        kind: str,
        place_in: str | None = None,
    ) -> SeedPlan:
        """Propose only from grounded retrieval hits (fail closed on ungrounded)."""
        if not self.retrieval.enabled:
            raise ValueError(
                "Semantic retrieval is off. Set retrieval.enabled: true first."
            )
        kind_n = kind.strip().lower()
        collection_map = {
            "rooms": COLLECTION_ROOM,
            "room": COLLECTION_ROOM,
            "items": COLLECTION_ITEM,
            "item": COLLECTION_ITEM,
            "npcs": COLLECTION_NPC,
            "npc": COLLECTION_NPC,
        }
        collection = collection_map.get(kind_n)
        if collection is None:
            raise ValueError("kind must be rooms, items, or npcs.")
        keys = self.retrieval.grounded_keys(
            query,
            collections=(collection,),
        )
        if not keys:
            plan = self.ensure_plan()
            plan.gaps.append(
                f"Retrieval found no grounded {kind_n} lore for {query!r} "
                "(fail closed — nothing proposed)."
            )
            return self._persist(plan)
        if collection == COLLECTION_ROOM:
            return self.propose_rooms(keys)
        if collection == COLLECTION_ITEM:
            return self.propose_items(keys, place_in=place_in)
        return self.propose_npcs(keys, current_room_id=place_in)

    def _annotate_retrieval_suggestions(self, plan: SeedPlan) -> None:
        if not self.retrieval.enabled or not self.retrieval.settings.builder_discover:
            return
        query_bits: list[str] = []
        if plan.brief and isinstance(plan.brief, dict):
            for field in ("goal", "tone", "title"):
                value = plan.brief.get(field)
                if value:
                    query_bits.append(str(value))
        query_bits.extend(
            note for note in plan.notes if note.startswith("Goal:")
        )
        query = " ".join(query_bits).strip()
        if not query:
            return
        keys = self.retrieval.grounded_keys(query)
        already: set[str] = set()
        for att in plan.attachments:
            if isinstance(att, dict) and att.get("lore_key"):
                already.add(str(att["lore_key"]))
        for room in plan.rooms:
            if isinstance(room, dict) and room.get("lore_key"):
                already.add(str(room["lore_key"]))
        for item in plan.items:
            if isinstance(item, dict) and item.get("lore_key"):
                already.add(str(item["lore_key"]))
        for npc in plan.npcs:
            if not isinstance(npc, dict):
                continue
            for key in npc.get("npc_lore") or []:
                already.add(str(key))
        suggestions = [
            k for k in keys if k not in already
        ][: self.retrieval.settings.top_k]
        if suggestions:
            plan.notes.append(
                "[retrieval assist] related grounded lore keys (not auto-applied): "
                + ", ".join(suggestions)
            )

    def connect_rooms(self, from_room: str, direction: str, to_room: str) -> SeedPlan:
        plan = self.ensure_plan()
        connect_rooms(
            plan,
            from_room_id=from_room,
            direction=direction,
            to_room_id=to_room,
        )
        return self._persist(plan)

    def place_item(self, item_id: str, room_id: str) -> SeedPlan:
        plan = self.ensure_plan()
        place_item(plan, item_id, room_id)
        return self._persist(plan)

    def place_npc(self, npc_id: str, room_id: str) -> SeedPlan:
        plan = self.ensure_plan()
        place_npc(plan, npc_id, room_id)
        return self._persist(plan)

    def attach_room_lore(self, room_id: str, lore_key: str) -> SeedPlan:
        plan = self.ensure_plan()
        attach_lore(plan, entity_kind="room", entity_id=room_id, lore_key=lore_key)
        return self._persist(plan)

    def attach_item_lore(self, item_id: str, lore_key: str) -> SeedPlan:
        plan = self.ensure_plan()
        attach_lore(
            plan, entity_kind="item_definition", entity_id=item_id, lore_key=lore_key
        )
        return self._persist(plan)

    def attach_npc_lore(self, npc_id: str, lore_key: str) -> SeedPlan:
        plan = self.ensure_plan()
        attach_lore(plan, entity_kind="npc", entity_id=npc_id, lore_key=lore_key)
        return self._persist(plan)

    def preview(self, plan_id: str | None = None) -> str:
        plan = load_plan(self.data_dir, plan_id) if plan_id else self.load_current_plan()
        return format_seed_plan_preview(plan)

    def validate(self, plan_id: str | None = None, *, include_plan: bool = True) -> ValidationResult:
        plan: SeedPlan | None = None
        if include_plan:
            target = plan_id or self.current_plan_id
            if target:
                plan = load_plan(self.data_dir, target)
        return validate_world(self.world, self.lore, plan=plan)

    def apply(self, plan_id: str | None = None) -> SeedPlan:
        target = plan_id or self.current_plan_id
        if not target:
            raise ApplyError("No plan specified to apply.")
        plan = load_plan(self.data_dir, target)
        applied = apply_seed_plan(self.world, self.lore, plan)
        return self._persist(applied)

    def list_lore(self, collection: str | None = None) -> list[tuple[str, str, str]]:
        """Return (collection, key, text_preview) for approved lore."""
        names = [collection] if collection else list(ALL_COLLECTIONS)
        rows: list[tuple[str, str, str]] = []
        for name in names:
            resolved = _COLLECTION_ALIASES.get(name, name)
            if resolved not in ALL_COLLECTIONS:
                raise ValueError(f"Unknown lore collection: {name}")
            for key, text in self.lore.list_entries(resolved):
                preview = " ".join(text.split())[:80]
                rows.append((resolved, key, preview))
        return rows

    def add_frontier_stub(
        self,
        *,
        from_room_id: str,
        direction: str,
        target_room_id: str,
        lore_key: str,
        target_name: str | None = None,
        return_direction: str | None = None,
        stub_id: str | None = None,
    ) -> str:
        """Register a prepared unrealized exit (does not create the room yet)."""
        from world_sim.builder.linking import display_name_from_id, lore_exists

        if self.world.get_room(from_room_id) is None:
            raise ValueError(f"From-room '{from_room_id}' does not exist.")
        if not lore_exists(self.lore, lore_key):
            raise ValueError(
                f"Approved lore '{lore_key}' missing. upsert_lore first "
                "(fail closed — stubs must bind to existing canon)."
            )
        resolved_id = stub_id or f"stub_{from_room_id}_{direction}_{target_room_id}"
        name = target_name or display_name_from_id(target_room_id)
        stub = self.world.upsert_frontier_stub(
            stub_id=resolved_id,
            from_room_id=from_room_id,
            direction=direction,
            target_room_id=target_room_id,
            target_name=name,
            lore_key=lore_key,
            return_direction=return_direction,
        )
        return (
            f"Frontier stub pending: {stub.stub_id} "
            f"({stub.from_room_id} --{stub.direction}--> {stub.target_room_id}, "
            f"lore={stub.lore_key}). "
            "Enable world.dynamic_expansion to realize on cross."
        )

    def list_frontier_stubs(self, *, status: str | None = None) -> str:
        stubs = self.world.list_frontier_stubs(status=status)
        if not stubs:
            return "(no frontier stubs)"
        lines = ["Frontier stubs:"]
        for stub in stubs:
            ret = f", return={stub.return_direction}" if stub.return_direction else ""
            lines.append(
                f"- [{stub.status}] {stub.stub_id}: "
                f"{stub.from_room_id} --{stub.direction}--> {stub.target_room_id} "
                f"({stub.target_name}) lore={stub.lore_key}{ret}"
            )
        return "\n".join(lines)
