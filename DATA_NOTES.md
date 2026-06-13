# DATA_NOTES — Mining Aggregation Pipeline

## Schema

All data stored in ChromaDB collection `mining_aggregator`, single collection with rich metadata.

### Core fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | str (hash) | Primary key: `sha256(source_type + url)` truncated to 32 chars |
| `document` | str | Embedded text content (paragraph-level chunks) |
| `metadata.source_type` | str | `news`, `policy`, or `price` |
| `metadata.url` | str | Source URL |
| `metadata.title` | str | Article/document title |
| `metadata.published_at` | str | ISO 8601 datetime or date string |
| `metadata.language` | str | `zh` or `en` |
| `metadata.content_hash` | str | `sha256(normalized_text)` for cross-URL dedup |

### Source-type specific metadata

**news**: `author`, `summary`

**policy**: `jurisdiction` (CN/AU), `policy_type` (regulation/strategy/law/announcement), `source_name`

**price**: `commodity`, `price_open`, `price_high`, `price_low`, `price_close`, `price_settle`, `volume`, `unit`, `currency`, `exchange`, `date`

### Chunking metadata

`chunk_index`, `chunk_total` — which segment of a multi-chunk document

## Primary Key

`sha256(source_type + url)` → ChromaDB `id`

Used with `upsert()` for idempotent re-crawl: re-crawling the same URL overwrites the existing entry.

## Dedup Strategy

### Layer 1: URL dedup
- Same URL → same `id` → ChromaDB upsert overwrites silently

### Layer 2: Content dedup
- After normalization (strip whitespace, unify whitespace sequence), compute `sha256(text)`
- `DedupChecker` loads all prior `content_hash` values from existing clean JSONL
- Before insert, check if `content_hash` already exists → skip if yes
- Catches syndicated articles (same content, different URLs across mining.com and S&P)

### Layer 3: In-run dedup
- `DedupChecker` tracks hashes seen during current run to avoid intra-batch duplicates

## Data Storage

### Raw (`data/raw/*.jsonl`)
- One JSONL per crawler run: `{source_type}_{timestamp}.jsonl`
- Fields vary by source, always includes `full_text`

### Clean (`data/clean/*.jsonl`)
- One JSONL per processor run: `all_{timestamp}.jsonl`
- Normalized schema, chunked, deduplicated
- Each record has `document` field ready for embedding
- ChromaDB metadata-compatible (no nested dicts, no None values in metadata)

### ChromaDB (`chroma_data/`)
- Persistent ChromaDB at project root
- Collection: `mining_aggregator`
- Distance: cosine
- Batch upsert: 100 records/batch

## Constraints

- Metadata values must be `str`, `int`, `float`, or `bool` (ChromaDB constraint)
- String metadata values truncated to 1000 chars
- Minimum document length: 20 chars (shorter records are dropped)
- ChromaDB `where` filter supports `$gte`/`$lte` on string dates
