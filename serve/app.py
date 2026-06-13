"""FastAPI /query endpoint — RAG with LLM routing + cross-encoder reranking."""

import logging
import sys
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from serve.generator import generate_answer
from serve.reranker import Reranker
from serve.retriever import Retriever
from serve.router import plan as plan_search

logger = logging.getLogger(__name__)

app = FastAPI(title="Mining Aggregator", version="0.2.0")
_retriever: Retriever | None = None
_reranker: Reranker | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class QueryResponse(BaseModel):
    question: str
    results: list
    generated_answer: str | None = None
    total: int
    query_time_ms: float


def _ensure_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def _ensure_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker


@app.on_event("startup")
def startup() -> None:
    logger.info("server started (models load lazily on first query)")


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> dict[str, Any]:
    retriever = _ensure_retriever()
    reranker = _ensure_reranker()

    t0 = time.time()

    # 1. LLM routing — question → search plan
    plan = plan_search(req.question)

    # 2. Multi-query retrieval
    all_results = retriever.multi_query(plan.searches)

    # 3. Rerank (cross-encoder skips price data)
    all_results = reranker.rerank(req.question, all_results)

    # 4. Price data goes directly into LLM context (not reranked)
    news_policy = [r for r in all_results if r.get("source_type") != "price"]
    price = [r for r in all_results if r.get("source_type") == "price"]
    context_docs = news_policy[:5] + price

    # 5. LLM answer generation
    answer = generate_answer(req.question, context_docs)

    elapsed = time.time() - t0
    return {
        "question": req.question,
        "results": all_results,
        "generated_answer": answer,
        "total": len(all_results),
        "query_time_ms": round(elapsed * 1000, 1),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "retriever": _retriever is not None,
        "reranker": _reranker is not None,
    }


def main() -> None:
    """CLI entry point for pyproject.toml scripts."""
    import uvicorn
    uvicorn.run("serve.app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    main()
