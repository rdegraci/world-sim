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
ALL_COLLECTIONS = (COLLECTION_SYSTEM, COLLECTION_ROOM, COLLECTION_ITEM)


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

    def list_keys(self, collection_name: str) -> list[str]:
        if collection_name not in self._collections:
            raise ValueError(f"Unknown lore collection: {collection_name}")
        result = self._collections[collection_name].get(include=[])
        return list(result.get("ids") or [])

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
