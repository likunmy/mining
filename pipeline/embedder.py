import hashlib
import json
import logging

import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from pipeline.config import CLEAN_DIR, CHROMA_DIR, CHROMA_COLLECTION, CHROMA_BATCH_SIZE, EMBEDDING_MODEL

logger = logging.getLogger(__name__)


def embed_all():
    """Read clean JSONL, embed, upsert to ChromaDB."""
    clean_files = sorted(CLEAN_DIR.glob("*.jsonl"))
    if not clean_files:
        logger.warning("no clean files to embed")
        return

    logger.info("loading embedding model: %s", EMBEDDING_MODEL)
    model = SentenceTransformer(EMBEDDING_MODEL)
    logger.info("connecting to chroma: %s", CHROMA_DIR)
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    records = []
    for fpath in clean_files:
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    if not records:
        logger.warning("no records to embed")
        return

    logger.info("embedding %d records...", len(records))

    for i in tqdm(range(0, len(records), CHROMA_BATCH_SIZE)):
        batch = records[i : i + CHROMA_BATCH_SIZE]
        texts = [r.get("document", r.get("full_text", "")) for r in batch]
        embeddings = model.encode(texts, show_progress_bar=False).tolist()

        ids = []
        metadatas = []
        documents = []

        for r in batch:
            rid = r.get("id")
            if not rid:
                raw = f"{r.get('source_type', 'unknown')}_{r.get('url', '')}"
                rid = hashlib.sha256(raw.encode()).hexdigest()[:32]
            ids.append(rid)
            meta = {k: v for k, v in r.items() if k in (
                "source_type", "url", "title", "published_at", "crawled_at",
                "language", "author", "summary", "jurisdiction", "policy_type",
                "commodity", "price_open", "price_high", "price_low",
                "price_close", "price_settle", "volume", "unit", "currency",
                "exchange", "date", "content_hash", "chunk_index", "chunk_total",
                "source_name",
            ) and v is not None}
            # Chroma metadata must be str/int/float/bool
            for k, v in meta.items():
                if isinstance(v, str) and len(v) > 1000:
                    meta[k] = v[:1000]
            metadatas.append(meta)
            documents.append(texts[-1])

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    count = collection.count()
    logger.info("chroma collection now has %d entries", count)
