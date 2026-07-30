"""Human-readable preview of draft seed plans."""

from __future__ import annotations

from world_sim.builder.plans import SeedPlan


def format_seed_plan_preview(plan: SeedPlan) -> str:
    lines: list[str] = [
        f"Seed plan: {plan.plan_id}",
        f"Status: {plan.status} (draft until explicit apply)",
    ]
    if plan.brief_path:
        lines.append(f"Guidance brief: {plan.brief_path}")
    if plan.brief and plan.brief.get("goal"):
        lines.append(f"Brief goal: {plan.brief['goal']}")
    lines.append("")

    lines.append(f"Rooms ({len(plan.rooms)}):")
    if not plan.rooms:
        lines.append("  (none)")
    for room in plan.rooms:
        lines.append(
            f"  [{room.get('action', '?')}] {room.get('room_id')} "
            f"— {room.get('name')} (lore={room.get('lore_key')})"
        )

    lines.append(f"Items / definitions ({len(plan.items)}):")
    if not plan.items:
        lines.append("  (none)")
    for item in plan.items:
        place = item.get("place_in")
        place_bit = f", place_in={place}" if place else ""
        lines.append(
            f"  [{item.get('action', '?')}] {item.get('item_id')} "
            f"— {item.get('name')} (lore={item.get('lore_key')}{place_bit})"
        )

    lines.append(f"NPCs ({len(plan.npcs)}):")
    if not plan.npcs:
        lines.append("  (none)")
    for npc in plan.npcs:
        room = npc.get("current_room_id")
        room_bit = f", room={room}" if room else ""
        lore = ",".join(npc.get("npc_lore") or [])
        lines.append(
            f"  [{npc.get('action', '?')}] {npc.get('npc_id')} "
            f"— {npc.get('name')} (npc_lore=[{lore}]{room_bit})"
        )

    lines.append(f"Exits ({len(plan.exits)}):")
    if not plan.exits:
        lines.append("  (none)")
    for exit_op in plan.exits:
        lines.append(
            f"  {exit_op.get('from_room_id')} --{exit_op.get('direction')}--> "
            f"{exit_op.get('to_room_id')}"
        )

    lines.append(f"Lore attachments ({len(plan.attachments)}):")
    if not plan.attachments:
        lines.append("  (none)")
    for attachment in plan.attachments:
        lines.append(
            f"  {attachment.get('entity_kind')}:{attachment.get('entity_id')} "
            f"-> {attachment.get('lore_key')}"
        )

    if plan.notes:
        lines.append("Notes:")
        for note in plan.notes:
            lines.append(f"  - {note}")

    if plan.gaps:
        lines.append("Gaps (approved lore missing — fail closed on validate):")
        for gap in plan.gaps:
            lines.append(f"  ! {gap}")

    lines.append("")
    lines.append("Nothing has been written to SQLite. Use apply_seed_plan after validate.")
    return "\n".join(lines)
