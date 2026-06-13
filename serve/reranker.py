"""Cross-encoder reranker — re-scores news/policy results, skips price data."""

import logging
from typing import Any

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


class Reranker:
    """Cross-encoder reranker for news/policy results.

    Price data passes through untouched (already sorted by date descending).
    """

    def __init__(self, model_name: str = RERANKER_MODEL) -> None:
        logger.info("loading reranker model: %s", model_name)
        try:
            self.model = CrossEncoder(model_name, local_files_only=True)
        except Exception:
            logger.info("reranker model not cached, trying download (one-time)...")
            try:
                self.model = CrossEncoder(model_name)
            except Exception as e:
                logger.warning("failed to load reranker model: %s", e)
                self.model = None

    def rerank(self, question: str, results: list[dict]) -> list[dict]:
        """Rerank news/policy results; price results pass through unchanged."""
        if self.model is None:
            return results

        news_policy = [r for r in results if r.get("source_type") != "price"]
        price = [r for r in results if r.get("source_type") == "price"]

        if not news_policy:
            return results

        pairs = [(question, r.get("snippet", "")) for r in news_policy]
        try:
            scores = self.model.predict(pairs, show_progress_bar=False)
            for r, s in zip(news_policy, scores):
                r["score"] = float(s)
            news_policy.sort(key=lambda x: x["score"], reverse=True)
        except Exception as e:
            logger.warning("reranking failed: %s", e)

        return news_policy + price
