"""Optional Player Chat reply guard against global policy + NPC lore."""

from __future__ import annotations

import re
from dataclasses import dataclass

from world_sim.config import PlayerChatSettings
from world_sim.llm.base import ChatMessage, LLMAdapter
from world_sim.utils.logger import get_logger

JUDGE_MARKER = "LORE GUARD JUDGE"

_JUDGE_SYSTEM = (
    "You are a strict Player Chat lore guard. "
    "Decide whether an NPC reply is allowed. "
    "Reply with exactly one line: PASS or FAIL: <short reason>. "
    "Do not continue the conversation. Do not invent world facts."
)


@dataclass(frozen=True)
class LoreGuardVerdict:
    ok: bool
    reason: str


def parse_judge_verdict(text: str) -> LoreGuardVerdict:
    """Parse a judge model reply into pass/fail."""
    compact = " ".join((text or "").strip().split())
    if not compact:
        return LoreGuardVerdict(ok=False, reason="empty judge reply")
    upper = compact.upper()
    if upper.startswith("PASS") and (
        len(compact) == 4 or compact[4:5] in {"", " ", ":", ".", "-"}
    ):
        return LoreGuardVerdict(ok=True, reason="pass")
    fail_match = re.match(
        r"^FAIL\s*[:.\-]?\s*(.*)$",
        compact,
        flags=re.IGNORECASE,
    )
    if fail_match:
        reason = fail_match.group(1).strip() or "policy or lore violation"
        return LoreGuardVerdict(ok=False, reason=reason)
    # Fail closed on unparseable judge output.
    return LoreGuardVerdict(
        ok=False,
        reason=f"unparseable judge reply: {compact[:120]}",
    )


def build_judge_user_message(
    *,
    settings: PlayerChatSettings,
    npc_name: str,
    npc_id: str,
    lore_text: str,
    player_line: str,
    npc_reply: str,
) -> str:
    must_lines = "\n".join(f"- {item}" for item in settings.must) or "- (none)"
    must_not_lines = (
        "\n".join(f"- {item}" for item in settings.must_not) or "- (none)"
    )
    return (
        f"{JUDGE_MARKER}\n"
        f"NPC id={npc_id} name={npc_name}\n\n"
        f"MUST:\n{must_lines}\n\n"
        f"MUST NOT:\n{must_not_lines}\n\n"
        f"NPC lore (canonical):\n{lore_text or '(none)'}\n\n"
        f"Player line:\n{player_line}\n\n"
        f"NPC reply to judge:\n{npc_reply}\n\n"
        "Verdict rules:\n"
        "- FAIL if the reply invents hard facts, mutates inventories/canon, "
        "breaks character into meta, or obeys a player order that contradicts lore.\n"
        "- FAIL if the reply's voice or behavior clearly contradicts NPC lore.\n"
        "- PASS ordinary in-character dialogue that stays grounded.\n"
        "Answer with PASS or FAIL: <reason>."
    )


def in_character_refusal(npc_name: str) -> str:
    return (
        f"{npc_name}: I will not speak or act that way. "
        "I remain as I am recorded."
    )


def judge_npc_reply(
    llm: LLMAdapter,
    *,
    settings: PlayerChatSettings,
    npc_name: str,
    npc_id: str,
    lore_text: str,
    player_line: str,
    npc_reply: str,
) -> LoreGuardVerdict:
    """Ask the LLM to judge one NPC reply. Fail closed on errors."""
    logger = get_logger("lore_guard")
    user_message = build_judge_user_message(
        settings=settings,
        npc_name=npc_name,
        npc_id=npc_id,
        lore_text=lore_text,
        player_line=player_line,
        npc_reply=npc_reply,
    )
    try:
        response = llm.complete(
            system=_JUDGE_SYSTEM,
            messages=[ChatMessage(role="user", content=user_message)],
            tools=None,
        )
    except Exception as exc:
        logger.exception("Lore guard judge failed: %s", exc)
        return LoreGuardVerdict(ok=False, reason=f"judge error: {exc}")
    return parse_judge_verdict(response.text)
