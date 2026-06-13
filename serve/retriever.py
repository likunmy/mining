import logging
import time

import chromadb
from sentence_transformers import SentenceTransformer

from serve.config import CHROMA_DIR, CHROMA_COLLECTION, EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class Retriever:
    def __init__(self):
        logger.info("loading embedding model: %s", EMBEDDING_MODEL)
        self.model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("connecting to chroma: %s", CHROMA_DIR)
        self.client = chromadb.PersistentClient(path=CHROMA_DIR)
        self.collection = self.client.get_collection(CHROMA_COLLECTION)

    def query(self, question: str, k: int = 10, where: dict | None = None):
        t0 = time.time()
        q_emb = self.model.encode([question]).tolist()

        kwargs = dict(
            query_embeddings=q_emb,
            n_results=k,
        )
        if where:
            kwargs["where"] = where

        result = self.collection.query(**kwargs)
        elapsed = time.time() - t0

        formatted = []
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        documents = result.get("documents", [[]])[0]

        for i in range(len(ids)):
            meta = metadatas[i] if i < len(metadatas) else {}
            formatted.append({
                "id": ids[i],
                "title": meta.get("title", ""),
                "source_type": meta.get("source_type", ""),
                "url": meta.get("url", ""),
                "published_at": meta.get("published_at", ""),
                "language": meta.get("language", ""),
                "jurisdiction": meta.get("jurisdiction"),
                "commodity": meta.get("commodity"),
                "score": 1.0 - distances[i] if i < len(distances) else 0.0,
                "snippet": (documents[i] or "")[:300],
            })

        return {
            "results": formatted,
            "total": len(formatted),
            "query_time_ms": round(elapsed * 1000, 1),
        }
