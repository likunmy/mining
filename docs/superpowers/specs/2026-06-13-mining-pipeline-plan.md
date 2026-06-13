# Implementation Plan: Mining Aggregation Pipeline

**Based on**: `2026-06-13-mining-pipeline-design.md`  
**Timeline**: 24 hours, single developer  
**Environment**: Windows local, Python 3.11+

## Dependencies

```txt
# requirements.txt
feedparser>=6.0
httpx>=0.27
beautifulsoup4>=4.12
trafilatura>=1.6
lxml>=5.0
chromadb>=0.4
sentence-transformers>=2.2
fastapi>=0.109
uvicorn>=0.27
pydantic>=2.0
tenacity>=8.0
tqdm>=4.60
charset-normalizer>=3.0
```

## Implementation order

### Phase 1: Scaffold (30 min)
- Create directory structure
- requirements.txt
- pipeline/config.py (DATA_DIR, CHROMA_DIR, MODEL, URLs, intervals)
- data/ dirs

### Phase 2: Crawlers (6-8h)
- **P2a**: `base.py` BaseCrawler ABC + `dedup.py` content_hash logic
- **P2b**: `news_crawler.py` — mining.com RSS + full text via trafilatura
- **P2c**: `policy_crawler.py` — 稀土官网 + DISR
- **P2d**: `price_crawler.py` — LME + SHFE + DCE

### Phase 3: Processing (2h)
- `processor.py` — normalize, dedup, chunk
- `embedder.py` — sentence-transformers embedding + ChromaDB upsert
- `run.py` — orchestrator

### Phase 4: API (2h)
- `serve/app.py` — FastAPI /query
- `serve/retriever.py` — ChromaDB query wrapper

### Phase 5: Eval (1h)
- `eval/ground_truth.json` — 20 Q&A
- `eval/evaluate.py` — recall@5 + faithfulness

### Phase 6: Docs + Final (30 min)
- `DATA_NOTES.md`
- Run full pipeline, verify 600+ entries
- Test /query endpoint

## Execution

I'll implement in this order. Each component is testable independently:
new_crawler → save JSONL → processor reads JSONL → embedder reads JSONL → serve reads ChromaDB

This allows verifying each phase before moving to the next.
