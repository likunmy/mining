"""FastAPI /query endpoint."""

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from serve.retriever import Retriever

logger = logging.getLogger(__name__)

app = FastAPI(title="Mining Aggregator", version="0.1.0")
retriever: Retriever | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    k: int = Field(default=10, ge=1, le=50)
    source_type: str | None = None
    language: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    commodity: str | None = None
    jurisdiction: str | None = None


class QueryResponse(BaseModel):
    question: str
    results: list
    total: int
    query_time_ms: float


@app.on_event("startup")
def startup():
    global retriever
    try:
        retriever = Retriever()
        logger.info("retriever ready")
    except Exception as e:
        logger.error("failed to init retriever: %s", e, exc_info=True)


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    if not retriever:
        raise HTTPException(503, "retriever not initialized")

    where = {}
    if req.source_type:
        where["source_type"] = req.source_type
    if req.language:
        where["language"] = req.language
    if req.commodity:
        where["commodity"] = req.commodity
    if req.jurisdiction:
        where["jurisdiction"] = req.jurisdiction
    if req.date_from:
        where["published_at"] = {"$gte": req.date_from}
    if req.date_to:
        where["published_at"] = {"$lte": req.date_to}

    result = retriever.query(req.question, k=req.k, where=where or None)
    result["question"] = req.question
    return result


@app.get("/health")
def health():
    return {"status": "ok", "retriever": retriever is not None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve.app:app", host="0.0.0.0", port=8000, reload=False)
