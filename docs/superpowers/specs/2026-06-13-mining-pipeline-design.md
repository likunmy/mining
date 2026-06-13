# Mining News + Policy + Price Aggregation Pipeline

## Overview

A 3-source aggregation pipeline that collects mining news, critical mineral policy documents, and commodity pricing data (600+ entries from the past 30 days), stores them in a ChromaDB vector database, and exposes a FastAPI `/query` endpoint for natural-language retrieval.

**Design date**: 2026-06-13  
**Target**: 24-hour delivery

---

## Architecture

```
pipeline/run.py (orchestrator)
    │
    ├── news_crawler.py    (mining.com RSS → full text)
    ├── policy_crawler.py  (CN稀土官网 + AU DISR)
    └── price_crawler.py   (LME + SHFE + DCE public prices)
            │
            ▼
    processor.py (clean + dedup + chunk) → data/clean/*.jsonl
            │
            ▼
    embedder.py (embed + ChromaDB upsert)
            │
            ▼
    ChromaDB (chroma_data/, collection: "mining_aggregator")
            │
            ▼
    FastAPI serve/app.py → POST /query { question, filters } → top-k results
```

**Key design decisions**:
- Python full-stack (httpx + trafilatura + ChromaDB + FastAPI)
- Intermediate JSONL storage decouples crawling from embedding
- Single ChromaDB collection with rich metadata for cross-source queries
- No LLM generation — `/query` returns pure retrieval results

---

## Data Schema

### ChromaDB document

```python
id:       "<source_type>_<sha256_of_url>"
document: "Normalized text content (paragraph-level chunks)"
metadata: {
    # Universal
    "source_type":  "news | policy | price",
    "url":          str,
    "title":        str,
    "published_at": "ISO 8601 datetime",
    "crawled_at":   "ISO 8601 datetime",
    "content_hash": "sha256 of normalized text",
    "language":     "zh | en",

    # News-specific
    "author":  str | None,
    "summary": str | None,

    # Policy-specific
    "jurisdiction": "CN | AU | ...",
    "policy_type":  "regulation | strategy | law | announcement",

    # Price-specific
    "commodity":     "copper | zinc | nickel | lithium | iron_ore",
    "price_open":    float,
    "price_high":    float,
    "price_low":     float,
    "price_close":   float,
    "price_settle":  float | None,
    "volume":        float | None,
    "unit":          "USD/t | CNY/t",
    "currency":      "USD | CNY",
    "date":          "YYYY-MM-DD",

    # Chunking metadata
    "chunk_index":  int,
    "chunk_total":  int,
}
```

### Primary key
- `sha256(url)` → ChromaDB `id` — natural dedup on same URL

### Dedup strategy
1. **URL dedup**: ChromaDB `upsert()` — same `id` overwrites silently (idempotent)
2. **Content dedup**: normalize text (strip whitespace, unify punctuation) → `sha256` → before insert, query ChromaDB for existing `content_hash` → skip if found
3. **Edge case**: same article syndicated across mining.com and S&P → different URLs, same content_hash → skipped by content dedup

### Chunking strategy
- **News**: paragraph-level chunks (200–500 tokens each), preserve paragraph boundaries
- **Policy**: section-level chunks by heading hierarchy (h1/h2 boundaries)
- **Price**: single record per row (one commodity × one date), document field is a human-readable string like `"copper LME 2024-01-15 O:9234 H:9280 L:9210 C:9250 USD/t"`

---

## Pipeline Components

### `pipeline/crawlers/base.py`
`BaseCrawler` ABC with interface:
- `crawl(max_count=200) → list[dict]` — raw records
- `save_raw(records, path)` — save to `data/raw/{name}_{ts}.jsonl`

### `pipeline/crawlers/news_crawler.py`
- Bootstrap: fetch RSS feed from mining.com (and S&P Global Mining if available)
- Extract URL + title + pub_date + summary from feed
- For each URL: `httpx.get()` → `trafilatura.extract()` for full text
- Rate limit: 2s between requests
- Output: raw JSONL with url, title, author, published_at, full_text

### `pipeline/crawlers/policy_crawler.py`
- China稀土官网: `httpx` with `charset_normalizer` for encoding detection, `lxml` parser
- Australia DISR: RSS/sitemap discovery, same extraction pattern
- Anti-crawl: random UA rotation, 3–5s interval between requests
- Output: raw JSONL with url, title, published_at, jurisdiction, full_text

### `pipeline/crawlers/price_crawler.py`
- LME: scrape public daily settlement price tables from lme.com
- SHFE: scrape shfe.com.cn daily settlement data
- DCE: scrape iron ore futures data from dce.com.cn
- Fallback: IndexMundi / TradingEconomics if primary source blocks
- Output: raw JSONL with commodity, date, O/H/L/C/Settle, volume

### `pipeline/processor.py`
- Read all `data/raw/*.jsonl`
- Normalize fields to schema
- Content dedup (content_hash)
- Chunk documents
- Write `data/clean/all_{ts}.jsonl`

### `pipeline/embedder.py`
- Embedding model: `jina-embeddings-v3` (free, 512-dim) or OpenAI `text-embedding-3-small`
- Init ChromaDB client at `chroma_data/`
- Upsert in batches of 100
- Progress bar via `tqdm`

### `pipeline/run.py`
```python
def run():
    for crawler in [NewsCrawler, PolicyCrawler, PriceCrawler]:
        records = crawler().crawl()
        crawler.save_raw(records)
    processor.process_all()
    embedder.embed_all()
```

Error handling: per-source try/except, logs error, continues to next source.

### `pipeline/config.py`
- DATA_DIR, CHROMA_DIR, MODEL_NAME
- Per-source URLs, rate limits, UA strings
- Checkpoint file for incremental crawl

---

## Serving Layer

### `serve/app.py`
- FastAPI app with CORS enabled
- `POST /query` endpoint

### `serve/retriever.py`
```python
class Retriever:
    def __init__(self, chroma_dir, model_name):
        self.client = chromadb.PersistentClient(chroma_dir)
        self.collection = self.client.get_collection("mining_aggregator")
        self.embedder = ...  # same model as pipeline

    def query(self, question: str, k=10, where=None):
        q_emb = self.embedder.encode([question])
        return self.collection.query(
            query_embeddings=q_emb,
            n_results=k,
            where=where,
        )
```

### Request / Response

```
POST /query
{
    "question": "近7天澳洲锂出口政策有何变化？",
    "k": 10,
    "filters": {
        "source_type": null,     # news | policy | price
        "language": null,        # zh | en
        "date_from": null,       # "2024-01-01"
        "date_to": null,
        "commodity": null,       # price filter
        "jurisdiction": null     # policy filter
    }
}

Response 200:
{
    "question": "...",
    "results": [
        {
            "id": "policy_abc",
            "title": "标题",
            "source_type": "policy",
            "url": "https://...",
            "published_at": "2024-01-10",
            "language": "zh",
            "score": 0.89,
            "snippet": "..."
        }
    ],
    "total": 5,
    "query_time_ms": 42
}
```

---

## Evaluation

### Structure
```
eval/
├── ground_truth.json     # 20 Q&A pairs with relevant_ids and expected_answer
├── evaluate.py           # Automatic evaluation runner
├── config.py
└── results/
    └── eval_report.json  # Output
```

### Ground truth distribution
- 7 news questions ("最近关于铜的报道")
- 7 policy questions ("中国稀土出口管制最新政策")
- 6 price questions ("LME镍价本周走势")

### Metrics
1. **Recall@5**: proportion of relevant documents in top-5 results
2. **Answer faithfulness**: entity/number overlap between retrieved snippets and expected answer (via simple token-overlap or STS)

### Run
```bash
cd eval && python evaluate.py
# Outputs recall@5, faithfulness score, per-item breakdown
```

---

## Error Handling

| Scenario | Handling |
|----------|----------|
| Single crawler fails | Log error, skip source, continue pipeline |
| Content extraction fails on one page | Skip record, log to `data/errors.jsonl` |
| ChromaDB connection fails | Retry 3× with 1s backoff, then abort |
| Embedding API rate limit | Exponential backoff (`tenacity`) |
| Incremental run | Load checkpoint from `data/checkpoint.json` |
| Duplicate content | `content_hash` skip |

---

## Directory Structure

```
D:\code\mining\
├── pipeline/
│   ├── run.py
│   ├── config.py
│   ├── processor.py
│   ├── embedder.py
│   ├── dedup.py
│   └── crawlers/
│       ├── __init__.py
│       ├── base.py
│       ├── news_crawler.py
│       ├── policy_crawler.py
│       └── price_crawler.py
├── serve/
│   ├── app.py
│   ├── retriever.py
│   └── config.py
├── eval/
│   ├── ground_truth.json
│   ├── evaluate.py
│   ├── config.py
│   └── results/
├── data/
│   ├── raw/
│   ├── clean/
│   ├── errors.jsonl
│   └── checkpoint.json
├── chroma_data/
├── DATA_NOTES.md
└── requirements.txt
```

---

## Post-MVP / Future

- Add LLM-based RAG answer generation (ollama + qwen2.5 for local)
- CI eval gate (PR check recall@5 threshold)
- Scheduled daily incremental crawl (Task Scheduler / cron)
- Web frontend for browsing
