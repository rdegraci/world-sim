"""ChromaDB storage for canonical lore text keyed by stable IDs."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from world_sim.utils.logger import get_logger

COLLECTION_SYSTEM = "system_lore"
COLLECTION_ROOM = "room_lore"
COLLECTION_ITEM = "item_lore"
COLLECTION_NPC = "npc_lore"
ALL_COLLECTIONS = (
    COLLECTION_SYSTEM,
    COLLECTION_ROOM,
    COLLECTION_ITEM,
    COLLECTION_NPC,
)


class DeterministicEmbeddingFunction(EmbeddingFunction[Documents]):
    """Tiny deterministic embeddings so lore can be stored/fetched by key offline."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def name() -> str:
        return "deterministic_hash_v1"

    def __call__(self, input: Documents) -> Embeddings:
        vectors: list[list[float]] = []
        for doc in input:
            base = sum(ord(ch) for ch in doc) % 97
            vectors.append([((base + i) % 97) / 97.0 for i in range(8)])
        return vectors


class ChromaManager:
    """Persistent ChromaDB manager for canonical lore collections."""

    def __init__(self, persist_dir: Path) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._embedding = DeterministicEmbeddingFunction()
        self._collections = {
            name: self._client.get_or_create_collection(
                name=name,
                embedding_function=self._embedding,
                metadata={"hnsw:space": "cosine"},
            )
            for name in ALL_COLLECTIONS
        }
        get_logger("lore").info(
            "ChromaDB ready at %s collections=%s",
            self.persist_dir,
            ", ".join(ALL_COLLECTIONS),
        )

    def upsert_lore(self, collection_name: str, key: str, text: str) -> None:
        if collection_name not in self._collections:
            raise ValueError(f"Unknown lore collection: {collection_name}")
        collection = self._collections[collection_name]
        collection.upsert(
            ids=[key],
            documents=[text],
            metadatas=[{"lore_key": key}],
        )

    def get_lore(self, collection_name: str, key: str) -> str | None:
        if collection_name not in self._collections:
            raise ValueError(f"Unknown lore collection: {collection_name}")
        collection = self._collections[collection_name]
        result = collection.get(ids=[key], include=["documents"])
        documents = result.get("documents") or []
        if not documents or documents[0] is None:
            return None
        return str(documents[0])

    def delete_lore(self, collection_name: str, key: str) -> bool:
        """Delete a lore entry by key. Returns True if it existed."""
        if collection_name not in self._collections:
            raise ValueError(f"Unknown lore collection: {collection_name}")
        if self.get_lore(collection_name, key) is None:
            return False
        self._collections[collection_name].delete(ids=[key])
        return True

    def list_keys(self, collection_name: str) -> list[str]:
        return [key for key, _text in self.list_entries(collection_name)]

    def list_entries(
        self,
        collection_name: str,
        *,
        search: str | None = None,
    ) -> list[tuple[str, str]]:
        """Return (key, text) pairs, optionally filtered by simple substring search."""
        if collection_name not in self._collections:
            raise ValueError(f"Unknown lore collection: {collection_name}")
        collection = self._collections[collection_name]
        result = collection.get(include=["documents"])
        ids = list(result.get("ids") or [])
        documents = list(result.get("documents") or [])
        entries: list[tuple[str, str]] = []
        needle = search.strip().lower() if search else None
        for key, document in zip(ids, documents, strict=False):
            text = "" if document is None else str(document)
            if needle and needle not in key.lower() and needle not in text.lower():
                continue
            entries.append((str(key), text))
        entries.sort(key=lambda item: item[0])
        return entries

    def get_many(
        self,
        collection_name: str,
        keys: Sequence[str],
    ) -> dict[str, str]:
        found: dict[str, str] = {}
        for key in keys:
            text = self.get_lore(collection_name, key)
            if text is not None:
                found[key] = text
        return found

    def query_similar(
        self,
        collection_name: str,
        query_text: str,
        *,
        n_results: int = 5,
    ) -> list[tuple[str, str | None, float | None]]:
        """Raw Chroma similarity hits: (id, document_or_none, distance_or_none).

        Assist-only. Callers must re-ground via :meth:`get_lore` before treating
        a hit as authoritative canon.
        """
        if collection_name not in self._collections:
            raise ValueError(f"Unknown lore collection: {collection_name}")
        cleaned = " ".join(str(query_text).split()).strip()
        if not cleaned:
            return []
        n = max(1, int(n_results))
        collection = self._collections[collection_name]
        # Cap n_results to collection size so Chroma does not error on empty/small sets.
        try:
            total = int(collection.count())
        except Exception:  # noqa: BLE001 — count is best-effort
            total = n
        if total <= 0:
            return []
        n = min(n, total)
        result = collection.query(
            query_texts=[cleaned],
            n_results=n,
            include=["documents", "distances"],
        )
        ids_nested = result.get("ids") or [[]]
        docs_nested = result.get("documents") or [[]]
        dist_nested = result.get("distances") or [[]]
        ids = list(ids_nested[0] if ids_nested else [])
        docs = list(docs_nested[0] if docs_nested else [])
        dists = list(dist_nested[0] if dist_nested else [])
        hits: list[tuple[str, str | None, float | None]] = []
        for index, key in enumerate(ids):
            doc = docs[index] if index < len(docs) else None
            dist = dists[index] if index < len(dists) else None
            text = None if doc is None else str(doc)
            distance = float(dist) if dist is not None else None
            hits.append((str(key), text, distance))
        return hits
