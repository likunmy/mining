"""Embedding + ChromaDB 入库。"""

import hashlib
import json
import logging
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from pipeline.config import (
    CLEAN_DIR,
    CHROMA_DIR,
    CHROMA_COLLECTION,
    CHROMA_BATCH_SIZE,
    EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)


def embed_all() -> None:
    """读取清洗后 JSONL，embedding 后 upsert 到 ChromaDB。"""
    logger.info("处理所有数据")
    clean_files = sorted(CLEAN_DIR.glob("*.jsonl"))
    if not clean_files:
        logger.warning("无清洗数据需要入库")
        return

    logger.info("加载 embedding 模型: %s", EMBEDDING_MODEL)
    model = SentenceTransformer(EMBEDDING_MODEL)
    logger.info("连接 ChromaDB: %s", CHROMA_DIR)
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    records: list[dict[str, Any]] = []
    for fpath in clean_files:
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    if not records:
        logger.warning("无记录需要 embedding")
        return

    logger.info("开始 embedding %d 条记录...", len(records))

    for i in tqdm(range(0, len(records), CHROMA_BATCH_SIZE)):
        batch = records[i : i + CHROMA_BATCH_SIZE]
        texts = [r.get("document", r.get("full_text", "")) for r in batch]
        embeddings: list[list[float]] = model.encode(texts, show_progress_bar=False).tolist()

        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []
        documents: list[str] = []

        for idx, r in enumerate(batch):
            rid = r.get("id")
            if not rid:
                raw = f"{r.get('content_hash', '')}_{r.get('chunk_index', 0)}"
                rid = hashlib.sha256(raw.encode()).hexdigest()[:32]
            ids.append(rid)

            meta: dict[str, Any] = {
                k: v for k, v in r.items()
                if k in {
                    "source_type", "url", "title", "published_at", "crawled_at",
                    "language", "author", "summary", "jurisdiction", "policy_type",
                    "commodity", "price_open", "price_high", "price_low",
                    "price_close", "price_settle", "volume", "unit", "currency",
                    "exchange", "date", "content_hash", "chunk_index", "chunk_total",
                    "source_name",
                } and v is not None
            }
            # ChromaDB 元数据限制: 只能是 str/int/float/bool
            for k, v in meta.items():
                if isinstance(v, str) and len(v) > 1000:
                    meta[k] = v[:1000]
            metadatas.append(meta)
            documents.append(texts[idx])

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    count = collection.count()
    logger.info("ChromaDB 集合现有 %d 条记录", count)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    embed_all()