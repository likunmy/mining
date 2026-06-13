"""ChromaDB retrieval — vector search for news/policy, metadata lookup for price."""

import logging
import re
import time
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

from serve.config import CHROMA_DIR, CHROMA_COLLECTION, EMBEDDING_MODEL
from serve.router import SearchPlan

logger = logging.getLogger(__name__)

COMMODITY_ALIASES: dict[str, list[str]] = {
    "copper": ["copper", "铜", "cu"],
    "zinc": ["zinc", "锌"],
    "nickel": ["nickel", "镍"],
    "lithium": ["lithium", "锂"],
    "iron_ore": ["iron ore", "iron_ore", "铁矿石"],
}


class Retriever:
    def __init__(self) -> None:
        logger.info("loading embedding model: %s", EMBEDDING_MODEL)
        try:
            self.model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
        except Exception:
            logger.warning("embedding model not cached, downloading (one-time)...")
            self.model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("connecting to chroma: %s", CHROMA_DIR)
        self.client = chromadb.PersistentClient(path=CHROMA_DIR)
        self.collection = self.client.get_collection(CHROMA_COLLECTION)

    def query(self, question: str, k: int = 10, where: dict | None = None) -> dict[str, Any]:
        t0 = time.time()

        # 价格查询：通过品种+时间精确检索
        is_price_explicit = where and where.get("source_type") == "price"
        commodity_in_where = where and where.get("commodity")
        commodity_from_q = self._detect_commodity(question)

        if is_price_explicit or commodity_in_where or (commodity_from_q and not where):
            commodity = commodity_in_where or commodity_from_q
            if commodity:
                return self._search_price(commodity, k, t0)
            # 未指定品种时返回所有品种最新价格
            return self._search_all_prices(k, t0)

        # 常规向量检索（news / policy / mixed）
        q_emb = self.model.encode([question]).tolist()
        kwargs: dict[str, Any] = dict(query_embeddings=q_emb, n_results=k)
        if where:
            kwargs["where"] = where

        result = self.collection.query(**kwargs)
        return self._format_results(result, t0)

    def multi_query(self, plans: list[SearchPlan]) -> list[dict]:
        """Execute multiple search plans, deduplicate, return merged results."""
        all_results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        t0 = time.time()

        for plan in plans:
            if "price" in plan.source_types:
                result = self._search_price(
                    plan.where.get("commodity", ""),
                    k=10,
                    t0=t0,
                )
            else:
                q_text = plan.query or ""
                q_emb = self.model.encode([q_text]).tolist()
                where: dict[str, Any] = {"source_type": {"$in": plan.source_types}}
                if plan.where:
                    where.update(plan.where)
                try:
                    raw = self.collection.query(
                        query_embeddings=q_emb,
                        n_results=10,
                        where=where,
                    )
                    result = self._format_results(raw, t0)
                except Exception as e:
                    logger.warning("multi_query plan failed: %s", e)
                    continue

            for r in result["results"]:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    all_results.append(r)

        return all_results

    def _search_price(self, commodity: str, k: int, t0: float) -> dict[str, Any]:
        """按品种+日期降序获取价格数据，不经过向量检索。"""
        result = self.collection.get(
            where={"$and": [{"source_type": "price"}, {"commodity": commodity}]}
        )

        items: list[dict[str, Any]] = []
        for i in range(len(result["ids"])):
            meta = result["metadatas"][i] or {}
            items.append({
                "date": meta.get("date", ""),
                "id": result["ids"][i],
                "meta": meta,
                "doc": result["documents"][i] or "",
            })

        # 按日期降序排列
        items.sort(key=lambda x: x["date"], reverse=True)

        formatted: list[dict[str, Any]] = []
        for item in items[:k]:
            meta = item["meta"]
            formatted.append({
                "id": item["id"],
                "title": meta.get("title", ""),
                "source_type": "price",
                "url": meta.get("url", ""),
                "published_at": meta.get("date", ""),
                "language": meta.get("language", ""),
                "commodity": meta.get("commodity"),
                "score": 1.0,
                "snippet": item["doc"][:300],
            })

        elapsed = time.time() - t0
        return {
            "results": formatted,
            "total": len(formatted),
            "query_time_ms": round(elapsed * 1000, 1),
        }

    def _search_all_prices(self, k: int, t0: float) -> dict[str, Any]:
        """按日期降序获取所有品种最新价格，不经过向量检索。"""
        result = self.collection.get(where={"source_type": "price"})

        items: list[dict[str, Any]] = []
        for i in range(len(result["ids"])):
            meta = result["metadatas"][i] or {}
            items.append({
                "date": meta.get("date", ""),
                "id": result["ids"][i],
                "meta": meta,
                "doc": result["documents"][i] or "",
            })

        items.sort(key=lambda x: x["date"], reverse=True)

        # 去重：每种品种只保留最新一条
        seen_commodities: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for item in items:
            c = item["meta"].get("commodity", "")
            if c not in seen_commodities:
                seen_commodities.add(c)
                deduped.append(item)
            if len(deduped) >= k:
                break

        formatted: list[dict[str, Any]] = []
        for item in deduped:
            meta = item["meta"]
            formatted.append({
                "id": item["id"],
                "title": meta.get("title", ""),
                "source_type": "price",
                "url": meta.get("url", ""),
                "published_at": meta.get("date", ""),
                "language": meta.get("language", ""),
                "commodity": meta.get("commodity"),
                "score": 1.0,
                "snippet": item["doc"][:300],
            })

        elapsed = time.time() - t0
        return {
            "results": formatted,
            "total": len(formatted),
            "query_time_ms": round(elapsed * 1000, 1),
        }

    def _format_results(self, result: dict[str, Any], t0: float) -> dict[str, Any]:
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        documents = result.get("documents", [[]])[0]

        formatted: list[dict[str, Any]] = []
        for i in range(len(ids)):
            meta: dict = metadatas[i] if i < len(metadatas) else {}
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

        elapsed = time.time() - t0
        return {
            "results": formatted,
            "total": len(formatted),
            "query_time_ms": round(elapsed * 1000, 1),
        }

    @staticmethod
    def _detect_commodity(question: str) -> str | None:
        q = question.lower()
        for commodity, aliases in COMMODITY_ALIASES.items():
            if any(alias in q for alias in aliases):
                return commodity
        return None
