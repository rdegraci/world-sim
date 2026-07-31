"""Optional semantic retrieval assist (Phase 4b2) — augmentation only."""

from __future__ import annotations

from dataclasses import dataclass

from world_sim.config import RetrievalSettings
from world_sim.lore.chroma_manager import ALL_COLLECTIONS, ChromaManager


@dataclass(frozen=True)
class RetrievalHit:
    """One similarity hit after explicit lore-key grounding check."""

    collection: str
    lore_key: str
    grounded: bool
    preview: str
    distance: float | None = None
    text: str | None = None


class RetrievalAssist:
    """Semantic search helper that never replaces lore-key lookups.

    Hits are re-validated with :meth:`ChromaManager.get_lore`. Ungrounded keys
    are marked and excluded from proposal/context suggestion lists (fail closed).
    """

    def __init__(
        self,
        lore: ChromaManager,
        settings: RetrievalSettings | None = None,
    ) -> None:
        self.lore = lore
        self.settings = settings or RetrievalSettings()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def search(
        self,
        query: str,
        *,
        collections: tuple[str, ...] | None = None,
        top_k: int | None = None,
        include_ungrounded: bool = True,
    ) -> list[RetrievalHit]:
        """Query collections; re-ground every id via get_lore (authoritative)."""
        if not self.settings.enabled:
            return []
        cleaned = " ".join(str(query).split()).strip()
        if not cleaned:
            return []
        names = collections or ALL_COLLECTIONS
        n = top_k if top_k is not None else self.settings.top_k
        hits: list[RetrievalHit] = []
        for collection in names:
            if collection not in ALL_COLLECTIONS:
                continue
            raw = self.lore.query_similar(collection, cleaned, n_results=n)
            for key, _doc, distance in raw:
                grounded_text = self.lore.get_lore(collection, key)
                grounded = grounded_text is not None
                if not grounded and not include_ungrounded:
                    continue
                preview_src = grounded_text or ""
                preview = " ".join(preview_src.split())[:120]
                hits.append(
                    RetrievalHit(
                        collection=collection,
                        lore_key=key,
                        grounded=grounded,
                        preview=preview,
                        distance=distance,
                        text=grounded_text,
                    )
                )
        # Prefer grounded, then closer distances.
        hits.sort(
            key=lambda h: (
                0 if h.grounded else 1,
                h.distance if h.distance is not None else 999.0,
                h.lore_key,
            )
        )
        return hits[: max(1, n) * len(names)]

    def grounded_keys(
        self,
        query: str,
        *,
        collections: tuple[str, ...] | None = None,
        top_k: int | None = None,
    ) -> list[str]:
        """Fail-closed key list suitable for Builder propose_* inputs."""
        return [
            hit.lore_key
            for hit in self.search(
                query,
                collections=collections,
                top_k=top_k,
                include_ungrounded=False,
            )
            if hit.grounded
        ]

    def format_assist_block(
        self,
        query: str,
        *,
        collections: tuple[str, ...] | None = None,
        top_k: int | None = None,
        exclude_keys: set[str] | None = None,
        max_chars_per_hit: int = 160,
    ) -> str:
        """LLM-facing assist text. Empty when disabled or no grounded hits."""
        if not self.settings.enabled:
            return ""
        exclude = exclude_keys or set()
        hits = self.search(
            query,
            collections=collections,
            top_k=top_k,
            include_ungrounded=True,
        )
        grounded_lines: list[str] = []
        dropped = 0
        for hit in hits:
            if hit.lore_key in exclude:
                continue
            if not hit.grounded:
                dropped += 1
                continue
            body = " ".join((hit.text or "").split())[:max_chars_per_hit]
            grounded_lines.append(
                f"- [ASSIST grounded] {hit.collection} / {hit.lore_key}: {body}"
            )
        if not grounded_lines and dropped == 0:
            return ""
        header = (
            "SEMANTIC RETRIEVAL ASSIST (non-authoritative; suggestions only)\n"
            "Do not treat these as world facts unless the same lore_key appears in "
            "AUTHORITATIVE RUNTIME CONTEXT above (SQLite + explicit lore-keys).\n"
            f"Query: {query!r}\n"
        )
        if dropped:
            header += (
                f"Dropped {dropped} ungrounded hit(s) (fail closed — no get_lore).\n"
            )
        if not grounded_lines:
            return header + "(no grounded suggestions)\n"
        return header + "\n".join(grounded_lines)

    def format_builder_discovery(self, query: str) -> str:
        """Human-readable Builder discovery listing."""
        if not self.settings.enabled:
            return (
                "Semantic retrieval is off. Set retrieval.enabled: true in config.yaml."
            )
        if not self.settings.builder_discover:
            return "Builder discovery assist is disabled (retrieval.builder_discover)."
        hits = self.search(query, include_ungrounded=True)
        if not hits:
            return f"No retrieval hits for {query!r}."
        lines = [
            f"Retrieval assist for {query!r} "
            "(grounded = get_lore ok; ungrounded dropped for propose):",
        ]
        for hit in hits:
            status = "grounded" if hit.grounded else "UNGROUNDED (fail closed)"
            dist = (
                f" dist={hit.distance:.4f}" if hit.distance is not None else ""
            )
            preview = hit.preview or "(empty)"
            lines.append(
                f"- [{status}] {hit.collection} / {hit.lore_key}{dist}: {preview}"
            )
        grounded = [h.lore_key for h in hits if h.grounded]
        if grounded:
            lines.append(
                "Grounded keys only (safe to pass to propose_*): "
                + " ".join(grounded)
            )
        else:
            lines.append("No grounded keys — propose nothing from this query.")
        return "\n".join(lines)
